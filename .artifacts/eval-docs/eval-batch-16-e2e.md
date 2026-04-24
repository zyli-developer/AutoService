# Eval: batch-16 (T8S.3 M2 §8 acceptance E2E test code · yellow L)

## 预期行为

- Encode spec §8's 8 acceptance steps as `@pytest.mark.e2e` pytest tests in `tests/e2e/test_m2_acceptance.py`
- Default `pytest` run excludes these (via `addopts = "-m 'not e2e'"`)
- Explicit `pytest -m e2e tests/e2e/test_m2_acceptance.py` collects all 8
- Steps 6 + 7 skip when `ANTHROPIC_API_KEY` missing; step 2 skips when `gh` unauthenticated; steps 3 + 4 skip when fork uvicorn unreachable (`ConnectionError`)
- Each test writes timestamped evidence to `e2e-evidence/m2-acceptance/<ts>-step-<N>-<name>/`

## 验收标准

1. 8 test functions, each cross-referencing spec §8 step in docstring (spec §8 1-8)
2. `python -m pytest tests/e2e/test_m2_acceptance.py` → "N deselected" (not run)
3. `python -m pytest -m e2e tests/e2e/test_m2_acceptance.py --collect-only` → 8 tests collected
4. Other test suites unaffected (regression verified: tests/bootstrap/ 19 pass)
5. Evidence directory layout auditable (ISO-8601 timestamps + step_id)
6. No credentials in logs; no automatic LLM/network call without env flag

## 关键 invariant

- **NEVER run in CI by default** — `addopts = "-m 'not e2e'"` enforces
- **No silent network dependency** — skips explicit with reason
- **Non-destructive** — evidence writes live under `e2e-evidence/`; no production data mutation
- **Each step traceable** — test function name maps to spec §8 step number

## Spec ambiguities resolved

1. **"5-turn idle + auto-trigger"**: step 6 uses manual `/api/dream/trigger` to bypass the 30-min idle wait (pytest cannot wait 30min); the full idle-wait variant is an additional manual check outside pytest (documented in step 6 docstring)
2. **Two uvicorn instances**: steps assume master on `:8000` + fork on `:8001`; overridable via `M2_MASTER_BASE_URL` / `M2_FORK_BASE_URL` env. Defaults match a local dev setup.
3. **Step 8 approve endpoint**: if `/api/proposals/<id>/approve` doesn't exist yet (M3 scope per batch-11 eval-doc-014 note), step 8 records evidence and `pytest.skip`s — acceptance pass is optional for this endpoint in M2
4. **Evidence format**: JSON for structured data, plain text otherwise; filename `{name}.json|.txt`

## What stays out of scope

- Actually running the E2E (manual act; needs real LLM + gh + uvicorn)
- Wiring CI to run these (they're opt-in only)
- Replacing unit test coverage — these 8 tests complement, don't replace, the module-level test suites

## Yellow review concerns (for code-reviewer subagent)

1. All 8 spec §8 steps have a corresponding test function — traceable via test name `test_step_<N>_<shortname>`
2. Skip logic gates all network/LLM calls behind env checks; no accidental LLM call at collection time
3. Evidence collection paths non-destructive (writes under `e2e-evidence/`, no production data dirs)
4. Test names + docstrings cite spec section verbatim (`Spec §8 step N — …`)
