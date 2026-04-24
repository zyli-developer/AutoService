# Test diff: batch-15 — T8B.1 GitHubApiForkCreator + T8B.2 LocalTarballForkCreator runbook config step

**Related**: eval-doc-020 (batch-15 eval)
**Producer**: main orchestrator
**Scope**: Phase 8 · batch-15 · T8B.1 (Yellow+Large) + T8B.2 (Green)

新增 **19 tests** across **2 files** (all green on first integrated run after RED-phase scaffolding).

## 新增文件

| 文件 | Tests | 覆盖任务 |
|------|------|----------|
| `tests/publish/test_github_api_fork_creator.py` | 11 | T8B.1 — `GitHubApiForkCreator` + `ForkCreationError` |
| `tests/publish/test_local_tarball_config_step.py` | 8 | T8B.2 — `_fork_local_config_yaml_text` helper + `write_runbook` runbook step |

## 覆盖的场景 (from eval-doc-020)

### T8B.1 — `GitHubApiForkCreator` (11 tests)

| # | Test | Eval acceptance row |
|---|------|---------------------|
| 1 | `test_available_returns_true_when_gh_authed` | pins `gh auth status` argv + timeout=30 |
| 2 | `test_available_returns_false_when_gh_missing` | FileNotFoundError → False, no raise |
| 3 | `test_available_returns_false_when_not_authed` | CalledProcessError → False, no raise |
| 4 | `test_create_fork_success_returns_url` | Happy path — argv `gh repo fork <src> --fork-name=<target>`, timeout=60, returns parsed URL |
| 5 | `test_create_fork_with_org_prefix` | `org="h2oslabs"` → fork-name prefix applied in argv |
| 6 | `test_create_fork_partial_failure_includes_fork_name` | CalledProcessError → ForkCreationError.fork_name populated + .phase="gh-repo-fork" + .stderr captured |
| 7 | `test_create_fork_NEVER_calls_gh_repo_delete` | **Red-line grep regression**: `inspect.getsource` contains zero `"repo delete"` / `"repo-delete"` / `"delete"` literals |
| 8 | `test_create_fork_timeout_raises_with_fork_name` | TimeoutExpired → ForkCreationError with fork_name + message contains "timed out" |
| 9 | `test_create_fork_gh_missing_raises_actionable_error` | FileNotFoundError → phase="gh-check", fork_name=None, message contains "cli.github.com" / "install" |
| 10 | `test_create_fork_stderr_logged_not_swallowed` | caplog at WARNING — stderr content surfaces in log output |
| 11 | `test_create_fork_empty_tenant_id_rejected` | Empty / whitespace tenant_id → ValueError, subprocess never invoked |

### T8B.2 — runbook config step (8 tests)

| # | Test | Eval acceptance row |
|---|------|---------------------|
| 1 | `test_fork_local_config_yaml_helper_shape` | Helper renders both `deployment_mode: tenant` + `tenant_id: <tid>`, trailing newline |
| 2 | `test_fork_local_config_yaml_rejects_empty_tenant_id` | Empty / whitespace raises ValueError (defensive) |
| 3 | `test_fork_local_config_yaml_rejects_malformed_tenant_id` | Identifiers with whitespace or newlines raise (yaml-injection guard) |
| 4 | `test_runbook_includes_config_local_yaml_step` | Runbook body contains `deployment_mode: tenant`, `tenant_id: <tid>`, `config.local.yaml` |
| 5 | `test_runbook_config_step_ordering` | Order: Extract content → config.local.yaml → Verify (spec-mandated fork boot assertion ordering) |
| 6 | `test_runbook_https_warning_present` | Runbook mentions `https` + one of tls/magic-link/warning/⚠/cookie (CON-08 spec §9) |
| 7 | `test_runbook_config_yaml_snippet_matches_helper` | Every line from `_fork_local_config_yaml_text` output appears verbatim in runbook body — single source of truth |
| 8 | `test_runbook_overwrite_warning_present` | Runbook includes overwrite/existing/merge-manually caution for `cat > ...` pattern |

## 已修 regression bug

无 regression — 所有既有测试 (`tests/publish/test_publish_gate_checks.py`, `test_publish_unfreeze.py`, `tests/bootstrap/*`, `tests/fork_runtime/*`, `tests/setup/*`) 保持通过。

## Implementation touch-points

- `autoservice/publish.py` — added:
  - `ForkCreationError` exception class (~52 LoC)
  - `GitHubApiForkCreator` class (~110 LoC) — `available()` + `create_fork()`
  - `_fork_local_config_yaml_text(tenant_id)` helper (~22 LoC, with regex validation)
  - `_extract_first_url(text)` helper (~6 LoC)
  - `_VALID_TENANT_ID_RE` module-level compiled regex
  - `import re, subprocess, Optional`
  - `write_runbook()` body updated — new step 4 emits config.local.yaml snippet + overwrite warning + HTTPS warning on deploy step

## Spec decisions (recorded in eval-doc-020)

1. **T8B.1 scope narrow** — only the gh-fork creation step (not tar-extract / commit / push) — sized-appropriate for Yellow+Large.
2. **`ForkCreationError` is a NEW exception class** — not reuse of `CalledProcessError`; needed `fork_name` field for spec §9 compliance.
3. **`org` defaults to None** — user fork; optional platform-org override supported for future deployments.
4. **Runbook remains human-run** — T8B.2 is documentation only; no automated write of config.local.yaml in server-side code.
5. **HTTPS warning placement** — inside deploy step, with ⚠ + spec cross-reference (§5.5 / §9).

## Yellow self-review — T8B.1

Inline self-review per template §5 (single-agent batch; no subagent spawn):

| Concern | Verdict |
|---------|---------|
| Never auto-deletes forks | PASS — test #7 grep asserts zero `"repo delete"` in class source |
| `fork_name` populated on all post-create-success failures | PASS — test #6 (CalledProcessError) + test #8 (TimeoutExpired) both assert, test #9 pins the pre-invoke case where `None` is correct |
| subprocess timeout sane | PASS — 30s (`gh auth status`) + 60s (`gh repo fork`), both as class constants, asserted in tests #1 + #4 |
| No silent stderr swallowing | PASS — test #10 caplog fixture asserts WARNING log contains stderr content |

**Verdict: APPROVED** — no BLOCKING concerns; no revision pass needed.
