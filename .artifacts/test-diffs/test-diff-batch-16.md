# Test diff: batch-16 (T8S.3 M2 §8 acceptance E2E test code)

8 new `@pytest.mark.e2e` tests in `tests/e2e/test_m2_acceptance.py`; pyproject.toml marker registration + `addopts` to exclude from default.

## 修改文件

- `tests/e2e/test_m2_acceptance.py` — NEW (380 lines, 8 tests)
- `pyproject.toml` — registered `e2e` marker + `addopts = "-m 'not e2e'"` to exclude from default run

## 覆盖的场景

Each test encodes one spec §8 acceptance step:

| Test | Spec §8 step | Skip gate |
|------|-------------|-----------|
| `test_step_1_wizard_creates_tenant_and_publishes` | 1 (wizard + publish) | needs master uvicorn at :8000 |
| `test_step_2_fork_creator_extracts_and_writes_config` | 2 (fork creator) | `@requires_gh` (gh auth status) |
| `test_step_3_fork_make_setup_and_run_web` | 3 (fork boot) | needs fork uvicorn at :8001 (ConnectionError → skip) |
| `test_step_4_browser_chat_endpoint_responds` | 4 (browser /chat) | needs fork uvicorn |
| `test_step_5_magic_link_login_and_session_mode` | 5 (magic-link) | needs fork uvicorn |
| `test_step_6_dream_agent_run_after_idle` | 6 (dream agent) | `@requires_anthropic` |
| `test_step_7_master_admin_chat_routes_to_master` | 7 (_master dream) | `@requires_anthropic` |
| `test_step_8_proposal_approve_reject_persists` | 8 (approve/reject) | endpoint may not exist → pytest.skip |

## 已修 regression bug

None. New M2 surface.

## 验证

- `python -m pytest tests/e2e/test_m2_acceptance.py` → 8 deselected (excluded by default)
- `python -m pytest -m e2e tests/e2e/test_m2_acceptance.py --collect-only` → 8 tests collected
- `python -m pytest tests/bootstrap/` → 19 pass, 0 regression (default addopts doesn't break other suites)

## 关联 artifact

- eval-doc-021 (batch-16 E2E test code design)

## Manual run instructions

```bash
# Prerequisites
export ANTHROPIC_API_KEY=sk-ant-...
gh auth login
# Start master uvicorn (port 8000) and a fork uvicorn (port 8001) in separate terminals

# Run the 8 acceptance steps
pytest -m e2e tests/e2e/test_m2_acceptance.py -v

# Evidence is collected in:
ls e2e-evidence/m2-acceptance/<ts>-step-*/
```
