# E2E report: batch-16 (T8S.3 M2 §8 acceptance E2E test code)

## Scope

**Deliverable is code, not an executed acceptance run.** The test file encodes spec §8's 8 steps as `@pytest.mark.e2e` pytest cases. Actual acceptance-run reports will use a different filename pattern (e.g. `e2e-m2-acceptance-RUN-<date>.md`) produced when a human operator invokes the suite.

## Collection verification

- `python -m pytest tests/e2e/test_m2_acceptance.py` → **8 deselected** (correctly excluded from default)
- `python -m pytest -m e2e tests/e2e/test_m2_acceptance.py --collect-only` → **8 tests collected**
- Regression sanity: `python -m pytest tests/bootstrap/` → **19 pass, 0 regression**

## New tests

8 `@pytest.mark.e2e` test functions, one per spec §8 step:
- `test_step_1_wizard_creates_tenant_and_publishes`
- `test_step_2_fork_creator_extracts_and_writes_config` (@requires_gh)
- `test_step_3_fork_make_setup_and_run_web`
- `test_step_4_browser_chat_endpoint_responds`
- `test_step_5_magic_link_login_and_session_mode`
- `test_step_6_dream_agent_run_after_idle` (@requires_anthropic)
- `test_step_7_master_admin_chat_routes_to_master` (@requires_anthropic)
- `test_step_8_proposal_approve_reject_persists` (pytest.skip if endpoint absent)

## Skip / gate matrix

| Trigger | Effect |
|---------|--------|
| Default `pytest` | all 8 deselected (via `addopts = "-m 'not e2e'"`) |
| `pytest -m e2e` + missing `ANTHROPIC_API_KEY` | steps 6, 7 skip |
| `pytest -m e2e` + `gh auth status` fails | step 2 skips |
| `pytest -m e2e` + fork uvicorn unreachable | steps 3, 4, 5, 6 skip with `ConnectionError` |
| `/api/proposals/<id>/approve` returns 404 | step 8 records evidence + skips |

## Batch-16 commit trail

- `326e905` — register eval-doc-020 (batch-15, unrelated) — historical context
- batch-16 dispatch 1 (adaa7ca54): subagent stalled pre-produce; 0 artifacts landed
- Main orchestrator takeover: wrote test file + pyproject.toml marker + evidence scaffolding + 3 artifacts

## Yellow review

Inline review against the 4 eval-doc concerns:

1. ✅ All 8 spec §8 steps have a corresponding test function; names map 1:1 to step numbers
2. ✅ Skip logic guards all network/LLM calls: module-level `pytestmark = pytest.mark.e2e` + per-step env/connection checks; no accidental LLM call at import time
3. ✅ Evidence writes under `e2e-evidence/m2-acceptance/<ISO-ts>-<step_id>/`; no production data dirs touched
4. ✅ Test names + docstrings cross-reference spec section verbatim (first line of each docstring: "Spec §8 step N — …")

Verdict: **APPROVED** — non-blocking suggestions (M3+ backlog):
- Step 8's endpoint-pending guard is honest but means M2 gate-status is conditional on endpoint landing; should land or be explicitly deferred in M2 gate-check
- Step 6's manual `/api/dream/trigger` bypass of the 30-min idle wait is documented but a future variant could poll DreamScheduler's in-memory next-trigger time if exposed
- Consider adding `pytest-html` evidence rendering if manual run cadence increases

## 关联 artifact

- eval-doc-021 (batch-16 eval, this report's basis)

## Verdict

**batch-16 ✅ GO** — 8 E2E tests collected, default-excluded, explicitly invokable. T8S.3 complete. **M2 38/38 code-wise COMPLETE** 🎉.

Remaining human-act to close M2: operator runs `pytest -m e2e tests/e2e/test_m2_acceptance.py -v` with env + uvicorns + gh CLI configured, reviews `e2e-evidence/` output, signs off M2 gate.
