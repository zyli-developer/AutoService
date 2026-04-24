# Eval: batch-15 — T8B.1 GitHubApiForkCreator + T8B.2 LocalTarballForkCreator runbook config step

**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §3.4 "fork_creator: github_api 实现"
**Tasks**: T8B.1 (🟡 Yellow · Large) + T8B.2 (🟢 Green · Small) · Phase 8 · batch-15
**Producer**: main orchestrator + inline code-reviewer (T8B.1 Yellow self-review)
**Related**: eval-doc-015 (T7B.1/T7B.2 TenantContext + tenant_root — defines the runtime that fork_mode boots into) · prior publish-pipeline artifacts from M1 (ForkCreator Protocol already lives in `autoservice/publish.py`).

## 预期行为

### T8B.1 — `GitHubApiForkCreator` (new class in `autoservice/publish.py`)

Thin `gh` CLI wrapper that creates a GitHub fork of the platform repo for a given tenant.

Construction (per spec §3.4):
```python
GitHubApiForkCreator(gh_bin="gh", source_repo="ezagent42/AutoService", org=None)
```
- `gh_bin` defaults to `"gh"` but is injectable for tests.
- `source_repo` is the upstream the fork derives from; defaults to `"ezagent42/AutoService"` (the platform repo — matches M1 `write_runbook` hardcode).
- `org` (optional) — if set, fork is created under that GitHub org (e.g. `"h2oslabs"`), else falls back to the user's default namespace.

`available()` probe:
- Runs `gh auth status` via `subprocess.run(..., capture_output=True, text=True, timeout=30)`.
- Returns `True` on exit 0; `False` on `FileNotFoundError` (gh CLI missing) or non-zero exit (not authed).
- Does NOT raise — callers use it for fallback-to-local decisions.

`create_fork(tenant_id)` — ONLY the gh-fork creation step (per T8B.1 scope — the tarball-extract/git-commit/push steps are NOT owned by this class in batch-15; full automation lands later or via `LocalTarballForkCreator` + runbook):
- Computes fork name: `f"AutoService-{tenant_id}"`.
- Invokes `subprocess.run(["gh", "repo", "create", <target>, "--source=<source_repo>", ...], capture_output=True, text=True, timeout=60)`.
  - `<target>` is `f"{org}/AutoService-{tenant_id}"` when `org` set, else just `f"AutoService-{tenant_id}"` (user namespace).
  - Uses `gh repo create --source --public/--private` fork-style (spec ref: equivalent to `gh repo fork` but creates a named target — spec §3.4's `gh repo fork --fork-name` is the canonical form; we accept either — implementation uses `gh repo fork` for parity with the runbook).
- On success: returns the fork URL (parsed from stdout; `gh repo fork` emits `https://github.com/<owner>/AutoService-<tid>` on stdout).
- On failure:
  - `FileNotFoundError` (gh not installed) → `raise ForkCreationError(phase="gh-check", fork_name=None, original_error=exc)` with actionable message "gh CLI not found — install from https://cli.github.com or use LocalTarballForkCreator".
  - `subprocess.CalledProcessError` (gh returned non-zero) → `raise ForkCreationError(phase="gh-repo-fork", fork_name=fork_name, original_error=exc)` with stderr captured for diagnostics.
  - `subprocess.TimeoutExpired` → `raise ForkCreationError(phase="gh-repo-fork", fork_name=fork_name, original_error=exc)` with a "timed out after N seconds" message.
- After the gh fork call succeeds but a later step fails (N/A for this class since it only does the fork step — but the invariant is preserved for subclasses / callers): `ForkCreationError.fork_name` is always populated so humans can run `gh repo delete` themselves.

`ForkCreationError` exception class (new, defined alongside `GitHubApiForkCreator`):
- Attributes: `phase: str`, `fork_name: Optional[str]`, `original_error: Optional[Exception]`, `stderr: Optional[str]`.
- `__str__` produces a single-line diagnostic including all four for log grep-ability.
- Purpose: caller (HTTP handler) maps to 500 + renders to admin-portal; admin runs `gh repo delete <fork_name>` manually.

### T8B.2 — `LocalTarballForkCreator` runbook config step (defensive fix per spec §3.4 last paragraph)

Spec §3.4 says: "`LocalTarballForkCreator` 的 runbook 补第 4 步（M1 忘了）：解压后必须额外在 fork 仓 `.autoservice/config.local.yaml` 写 `deployment_mode: tenant` + `tenant_id: <tid>`，否则启动报错。"

Interpretation: the **runbook markdown** produced by `write_runbook()` must include an extra step between the current step 3 "Extract content" and step 4 "Verify" that directs the human operator to create `.autoservice/config.local.yaml` with the two required keys. This is a runbook-content change (no code-flow change in `LocalTarballForkCreator.create`).

New helper `_fork_local_config_yaml_text(tenant_id)` renders:
```yaml
deployment_mode: tenant
tenant_id: <tid>
```
(with trailing newline, stable across platforms — hand-rolled, no pyyaml dep, matching `_plugin_yaml_text` convention).

`write_runbook()` body gains a new "Write config.local.yaml" step emitted inline so the operator can `cat > .autoservice/config.local.yaml <<'EOF'` then copy-paste. The shell snippet is deterministic (no runtime timestamps inside the yaml body).

**Idempotency / safety note**: the runbook instructs the operator to use `cat > ...` which overwrites. If the operator has already customized `.autoservice/config.local.yaml` in their fork, they must merge manually — the runbook explicitly notes this (HTTPS-style cautionary tone). The runbook is human-run markdown; not auto-executed, so no code-level idempotency guard is needed.

**HTTPS warning surfacing**: per spec §9 risk "Magic-link token 开发时 http 嗅探 · 部署 runbook 加 HTTPS 强制警告". Although HTTPS is about the deployed site, the runbook already guides infra deployment (step 6). We add one explicit sentence near the deploy step: "⚠️ Production deployment MUST terminate TLS — magic-link tokens transit over Cookie; HTTP leaks them". This is a documentation-only change inside `write_runbook`.

### Failure-mode surface (T8B.1 Yellow concern — spec §9)

Spec §9 risk row: "`GitHubApiForkCreator` 失败后部分状态残留 · 失败不自动 `gh repo delete`（需人工确认）；返回失败明确指向需清理的 fork 名".

Red lines (enforced in tests + grep-level regression guard):
1. **NEVER call `gh repo delete`** anywhere in the class. A grep across the publish.py source for `"repo delete"` or `"repo-delete"` must return zero hits inside `GitHubApiForkCreator`. Test #5 enforces this.
2. **`ForkCreationError.fork_name` populated on all post-create failures** — since `create_fork` in this batch only does the fork step, any exception it raises that occurs *after* `gh repo fork` has started must include `fork_name=f"AutoService-{tenant_id}"`. Test #4 enforces this.
3. **subprocess `timeout` set** — every `subprocess.run` call passes an explicit `timeout` (30 for auth check, 60 for fork create). Timeouts propagate as `ForkCreationError` with a clear "timed out" message. Test #6 enforces this.
4. **stderr not swallowed** — on any `CalledProcessError`, `.stderr` is attached to the exception via `ForkCreationError.stderr` and logged at WARNING level. Silent swallow is forbidden — test asserts log output contains stderr substring.

## 验收标准

### Tests in `tests/publish/test_github_api_fork_creator.py` (~8 cases, `unittest.mock.patch("subprocess.run")`)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_available_returns_true_when_gh_authed` | `available()` invokes `subprocess.run(["gh","auth","status"], ..., timeout=30)` — exit 0 → True |
| 2 | `test_available_returns_false_when_gh_missing` | `FileNotFoundError` from subprocess → `available()` returns False (no raise) |
| 3 | `test_create_fork_success_returns_url` | `subprocess.run(...)` returns `stdout="https://github.com/user/AutoService-tid\n"`, exit 0 → `create_fork("tid")` returns that URL; verifies expected argv including fork-name and timeout=60 |
| 4 | `test_create_fork_partial_failure_includes_fork_name` | `CalledProcessError(stderr="network down")` → raises `ForkCreationError` with `fork_name="AutoService-tid"`, `phase="gh-repo-fork"`, `stderr="network down"` |
| 5 | `test_create_fork_NEVER_calls_gh_repo_delete` | grep-level regression: `inspect.getsource(GitHubApiForkCreator)` + `inspect.getsource(ForkCreationError)` contain zero occurrences of `"repo delete"` / `"repo-delete"` |
| 6 | `test_create_fork_timeout_raises_with_fork_name` | `TimeoutExpired` → `ForkCreationError(phase="gh-repo-fork", fork_name="AutoService-tid")`, message contains "timed out" |
| 7 | `test_create_fork_with_org_prefix` | `org="h2oslabs"` construction → subprocess argv target is `"h2oslabs/AutoService-tid"` |
| 8 | `test_create_fork_gh_missing_raises_actionable_error` | `FileNotFoundError` from subprocess.run → `ForkCreationError(phase="gh-check", fork_name=None)`, message mentions install URL |
| 9 | `test_create_fork_stderr_logged_not_swallowed` | `caplog` captures WARNING-level line containing stderr content on CalledProcessError |

### Tests in `tests/publish/test_local_tarball_config_step.py` (~4-5 cases)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_runbook_includes_config_local_yaml_step` | `write_runbook("t1", Path("x.tar.gz"))` output contains both `deployment_mode: tenant` and `tenant_id: t1` text |
| 2 | `test_runbook_config_step_ordering` | "Write config.local.yaml" step appears AFTER "Extract content" and BEFORE "Verify" |
| 3 | `test_runbook_https_warning_present` | Runbook body contains an HTTPS warning string per spec §9 |
| 4 | `test_runbook_config_yaml_snippet_matches_fork_local_config_helper` | The yaml snippet in the runbook is exactly what `_fork_local_config_yaml_text(tenant_id)` returns |
| 5 | `test_runbook_overwrite_warning_present` | Runbook warns operator that `cat > ...` overwrites — if they already have a config.local.yaml, merge manually |

### Pre-existing tests preserved

- `tests/publish/test_publish_gate_checks.py`, `tests/publish/test_publish_unfreeze.py` — the gate logic and unfreeze are untouched. Write-runbook is only modified by adding a new step and the HTTPS note; existing assertions that check for "gh repo fork" in the runbook body still pass.
- `tests/bootstrap/`, `tests/fork_runtime/`, `tests/setup/` — no overlap.

## 关键 invariant

- **CON-08 (deployment runbook HTTPS warning — spec §9)**: the runbook text produced by `write_runbook` MUST include an explicit HTTPS warning sentence. Test #3 of T8B.2 pins this.
- **Spec §9 risk row "GitHubApiForkCreator 失败后部分状态残留"**: on ANY exception raised by `create_fork` after the fork-create subprocess has been invoked, `ForkCreationError.fork_name` MUST be populated (so the admin knows which repo to clean up). NEVER `gh repo delete` automatically. Tests #4 + #5 pin this.
- **subprocess safety — timeout + capture**: every `subprocess.run` invocation in `GitHubApiForkCreator` uses `capture_output=True, text=True, timeout=<int>`. Test #1 / #3 / #6 assert timeouts. Test #9 asserts stderr is logged not swallowed.
- **`LocalTarballForkCreator.create` return shape unchanged**: `ForkResult(tenant_id, artifact_path, runbook_path, repo_url=None)` stays as-is. Only the runbook markdown body changes. Existing callers (`publish()`) keep working.
- **Runbook remains human-run**: T8B.2 does NOT introduce code that writes `.autoservice/config.local.yaml` in a remote fork checkout — that's spec §3.4's `GitHubApiForkCreator` scope (and even there, `_write_fork_local_config` is future work beyond T8B.1's stripped-down scope). Keeps T8B.2 green-sized.

## Spec decisions recorded

- **T8B.1 scope restricted to "fork create" only** — spec §3.4 sample code does fork + tar-x + config-write + commit + push in one method. Prompt narrows this to just the gh-CLI fork step; the rest either goes in M3 or remains a runbook step. Rationale: Yellow + Large is already full; adding full automation (tar extract + git push from server) widens the subprocess surface and introduces a credential-management problem (server needs push rights in a fork). Spec allows deferral — `steps_executed=["fork"]` is a valid subset. Documented in class docstring.
- **`ForkCreationError` is a NEW class, not reuse of stdlib**: `CalledProcessError` lacks `fork_name`; wrapping it keeps the clean "what to tell the human" separation.
- **`org` defaults to None (user fork)**: spec says `--fork-name` only, no org. We allow org for future deployments (a platform team may want all forks under `h2oslabs/`), but default is user namespace. Test #7 covers.
- **Runbook step 4 added as human copy-paste**: the runbook is markdown the admin reads. We emit the yaml inline between code fences so copy-paste works. Machine-executable form is out of scope — that's `GitHubApiForkCreator.create` full flow, deferred.
- **HTTPS warning placement**: inside the "Deploy per infra docs" step, as a sentence prefixed with "⚠️". Matches magic-link auth's cookie-transport concern (spec §5.5 + §9).
- **Idempotency of runbook-driven config write**: runbook is human-run, so no code-level guard. But the runbook text explicitly warns that `cat > ...` overwrites — test #5 of T8B.2 pins this copy.

## Yellow review focus (T8B.1)

Reviewer brief points — enforced either by tests or inspected manually by code-reviewer:
1. **Regression guard — NEVER auto-delete**: grep across the new class + ForkCreationError class body for `"repo delete"` / `"repo-delete"` / `"delete"` in any gh argv. Test #5 pins this.
2. **fork_name populated on all post-create failures**: tests #4 + #6 + #8 cover the distinct failure phases (CalledProcessError post-invoke, TimeoutExpired post-invoke, FileNotFoundError pre-invoke). Pre-invoke is the only case where `fork_name=None` is acceptable (gh CLI wasn't found, so no fork was created).
3. **subprocess timeout sane**: 30s for `gh auth status`, 60s for `gh repo fork`. Not unbounded. Not trivially small. Tests assert both.
4. **gh CLI stderr not silently swallowed**: WARNING-level log on any CalledProcessError. stderr attached to ForkCreationError. Test #9 pins this.

Reviewer verdict recorded in commit body per §6.1 Closing.

## Evidence

| Artifact | Location |
|----------|----------|
| `GitHubApiForkCreator` + `ForkCreationError` | `autoservice/publish.py` — new additions below `LocalTarballForkCreator` |
| `LocalTarballForkCreator` runbook step | `autoservice/publish.py` — modified `write_runbook()` body |
| T8B.1 tests | `tests/publish/test_github_api_fork_creator.py` (~9 cases) |
| T8B.2 tests | `tests/publish/test_local_tarball_config_step.py` (~5 cases) |
| Task status row | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 8 — T8B.1 + T8B.2 |

## Future work (flagged, beyond batch-15)

- **Full `GitHubApiForkCreator.create` flow**: tar-extract + `_write_fork_local_config` + git commit + push. Requires server-side git credentials management (SSH agent forwarding or token provisioning) — defer to M3 or T8S.3 smoke-test as applicable.
- **`available()` fallback wiring in `publish()`**: spec §3.4 shows the selector that picks `GitHubApiForkCreator` vs `LocalTarballForkCreator` based on config + availability. This selector wiring is NOT in batch-15 scope (tasks cover the class itself + the runbook step, not the publish() dispatch). Land it in T8S.3 or a dedicated micro-task.
- **gh CLI version probe**: detect outdated `gh` that doesn't support `--fork-name` — not in scope; runbook text suffices as mitigation.
