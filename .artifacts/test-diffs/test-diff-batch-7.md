# Test diff: batch-7 (P5 auth foundations)

新增 **20 tests** across **4 files** covering T5B.1 / T5B.2 / T5B.3 / T5B.4. Related eval-doc: `eval-doc-009`.

## 新增文件

- `tests/auth/__init__.py` — package marker.
- `tests/auth/test_repository.py` — 7 tests for `autoservice.auth` module API (T5B.1).
- `tests/auth/test_request_login.py` — 5 tests for `POST /api/auth/request-login` (T5B.2).
- `tests/auth/test_verify.py` — 5 tests for `GET /api/auth/verify` (T5B.3).
- `tests/auth/test_logout.py` — 3 tests for `POST /api/auth/logout` (T5B.4).

## 覆盖的场景

Cross-referenced from `eval-doc-009` §验收标准:

**T5B.1 — auth.py repository (7 tests)**
- `test_apply_schema_is_idempotent` — second `apply_schema` call does not raise.
- `test_issue_and_consume_login_token_roundtrip` — emit → consume → second-consume fails → consumed_at populated.
- `test_consume_expired_token_returns_none_and_does_not_burn` — red-line: expired tokens must stay un-burned for debuggability.
- `test_consume_unknown_token_returns_none` — missing token path.
- `test_create_and_lookup_session_roundtrip` — NULL tenant_id is valid (tier-0 _master path).
- `test_revoke_session_makes_lookup_return_none` — revoke + idempotent double-revoke + revoke-nonexistent.
- `test_lookup_expired_session_returns_none` — TTL enforcement.

**T5B.2 — /api/auth/request-login (5 tests)**
- `test_allowlisted_email_persists_token_and_logs_link` — happy path; token row + dev log entry.
- `test_non_allowlisted_email_returns_200_without_persisting` — **anti-enumeration red line**: identical 200 shape; zero side effects.
- `test_missing_email_field_returns_422` — input validation.
- `test_smtp_empty_host_writes_devmail_jsonl` — dev-mode observability (spec §5.6).
- `test_two_rapid_requests_create_two_tokens` — no rate limit in M2 (spec §5.7 defers to M3).

**T5B.3 — /api/auth/verify (5 tests)**
- `test_valid_token_302s_with_set_cookie_and_creates_session` — 302 + HttpOnly + SameSite=Lax cookie + sessions row.
- `test_invalid_token_returns_401_and_no_session_created` — plain-text 401.
- `test_expired_token_returns_401_and_is_not_burned` — red-line: consumed_at stays NULL on expiry.
- `test_already_consumed_token_returns_401` — replay defence.
- `test_missing_token_returns_422` — input validation.

**T5B.4 — /api/auth/logout (3 tests)**
- `test_authenticated_logout_clears_cookie_and_revokes_session` — 204 + Max-Age=0 + revoked_at stamped.
- `test_logout_without_cookie_is_idempotent_204` — idempotency.
- `test_logout_with_already_revoked_session_is_idempotent_204` — idempotency on second logout.

## 已修 regression bug

None. All 168 pre-existing tests across `tests/bootstrap/ tests/cc_pool/ tests/dream_agent/ tests/dream_runs/ tests/dream_scheduler/ tests/api/ tests/soul_generator/` remain green.

10 pre-existing failures in `tests/test_proposal_pipeline.py` + 2 in `tests/contract/` are **test-isolation pollution** unrelated to batch-7 — they pass when run alone (confirmed pre-existence via `git stash`).
