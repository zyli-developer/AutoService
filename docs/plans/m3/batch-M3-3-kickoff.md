# Batch M3-3 Kickoff · E3/E5/E6 Core 🔒

**Batches**: batch-7, batch-8, batch-9, batch-10 · **Milestone**: M3-3 · **Target**: 2026-04-30 EOD · **Duration**: ~32h

**⚠️ HIGH-RISK BATCH**: batch-8 contains **T4S.1 🔒 CON-04 security-critical**. All 🔒 tasks require mandatory code-reviewer subagent + AST guardrail. Re-read [E5 design spec](../../superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md) §Cross-cutting RED-LINE guardrails before starting.

## Pre-checks (M3-2 gate)
- [ ] batch-6 gate passed
- [ ] M2 regression still green
- [ ] [cc-prompt-templates.md §6](cc-prompt-templates.md) CON-04 checklist understood

---

## batch-7 · Parsers + Compressor (8h, 3 lanes)

**Note**: T4S.7 pulled forward from P4 to unblock T3S.2 in batch-8.

| ID | Name | Owner | Mode | Type |
|---|---|---|---|---|
| T3S.1 | `<handoff>` tag parser (mirror parse_sentiment) | Dev1 | solo + code-reviewer | 🟡 |
| T3S.3 | classify_intent DB + YAML migration | subagent-1 | parallel | 🟢 |
| T4S.7 | history compressor (haiku) | subagent-2 | parallel + code-reviewer | 🟡 |

**Yellow review (T3S.1)**: adversarial tags handled (nested, malformed attrs, injection attempts, truncated close tag)
**Yellow review (T4S.7)**: LLM cost budget enforced; summary quality check (new role gets usable context)

**Gate**: Parser adversarial tests green · DB migration idempotent · compressor stays within budget

---

## batch-8 · 🔒 Role-Switch + apply_proposal (10h, 3 lanes)

| ID | Name | Owner | Mode | Criticality |
|---|---|---|---|---|
| T3S.2 | role-switch orchestrator | Dev1 | solo + code-reviewer | 🟡 |
| T3S.4 | classify_intent CRUD + hot-reload | subagent-1 | parallel | 🟢 |
| **T4S.1** | **apply_proposal module** | **Dev1** | **solo + MANDATORY code-reviewer** | **🔒 CON-04** |
| T4S.2 | proposal_audit + state machine ext | subagent-2 | parallel | 🟢 |

**🔒 T4S.1 Gate (read before coding)**:
1. Module path: `autoservice/proposal_apply.py` (NEW — not in dream_agent.py, not in proposal_pipeline.py)
2. Import cone: `proposal_apply.py` MAY NOT import anything from `autoservice/dream_agent.py` or `autoservice/master_dream_agent.py`
3. Pre-condition: `proposal.status == 'accepted'` strictly (error otherwise)
4. Audit: every call writes to proposal_audit(pid, admin_user_id, action='apply', ts, session_id)
5. Idempotency: apply-on-already-applied = no-op (NOT error)
6. Admin authentication: extract admin_user_id from session; reject if not tier-0 or tenant_admin of proposal's tenant
7. In M3 scope: body of apply = `mark_applied` only (no physical side-effects beyond state + audit)

**Code-reviewer mandatory checklist** (paste in commit body):
- [ ] No imports from dream modules
- [ ] No direct SQL `UPDATE proposals SET status='applied'` except inside apply_proposal
- [ ] update_status state machine rejects accepted→applied unless called from apply_proposal
- [ ] Signature-lock tests intact: `test_emit_proposal_signature_has_no_status_kwarg` + new `test_apply_proposal_requires_admin_user_id` + `test_apply_proposal_rejects_non_accepted_status`

**Gate**: role-switch e2e (`<handoff to='lead'>` → next turn lead role + compressed summary) · apply_proposal code-reviewer APPROVED · CON-04 checklist all ✅

---

## batch-9 · Close: UI + 🔒 AST Guardrail (8h, 4 lanes)

| ID | Name | Owner | Mode | Criticality |
|---|---|---|---|---|
| T3S.5 | keyword editor UI | Dev1 | solo | 🟢 |
| T3S.6 | admin-to-admin invite (E1.6) | subagent-1 | parallel | 🟢 |
| T4S.3 | Apply button + endpoint | subagent-2 | parallel + code-reviewer | 🟡 |
| **T4S.8** | **CON-04 AST guardrail test** | **Dev1** | **solo_after_subagents + code-reviewer** | **🔒** |

**🔒 T4S.8 Gate**: AST-walk test asserts `status='applied'` and `status='accepted'` string literals only appear in `autoservice/proposal_apply.py` and `autoservice/proposal_pipeline.py:update_status`. Any other file containing these strings → FAIL. Test must fail if new code introduces bypass.

**Gate**: All UI/e2e for keyword editor + admin invite + Apply button · AST guardrail CI-gated

---

## batch-10 · P4 Remainders (6h, 3 lanes)

| ID | Name | Owner | Mode | Type |
|---|---|---|---|---|
| T4S.4 | platform dream cross-tenant signals | Dev1 | solo + code-reviewer | 🟡 |
| T4S.5 | sandbox_gc.py TTL job | subagent-1 | parallel | 🟢 |
| T4S.6 | JP/SG/AU rulesets (~11 rules) | subagent-2 | parallel | 🟢 |

**Yellow review (T4S.4)**: cross-tenant data access is read-only; no tenant isolation breach; _master scheduler hits master_dream_agent path only.

**Gate (M3-3 milestone)**:
- [ ] 14 P3+P4 tasks ✅
- [ ] apply_proposal APPROVED + AST guardrail green (in CI)
- [ ] Role-switch e2e with compressor
- [ ] JP tenant sees JP rules only (country filter)
- [ ] sandbox_gc hourly scan with synthetic time control test passes
- [ ] Platform dream produces platform_level draft from cross-tenant signals
- [ ] M2 regression still green
- [ ] Smoke 1: `pytest tests/triage/test_role_switch.py -v`
- [ ] Smoke 2: `pytest tests/dream_agent/test_apply_proposal.py tests/dream_agent/test_con04_guardrail.py -v`
- [ ] Smoke 3: `pytest tests/compliance/test_jp_sg_au_rules.py tests/sandbox_gc/ -v`

## Risks

- **R1 (critical)**: T4S.1 CON-04 bypass — mitigated by mandatory code-reviewer + T4S.8 AST guardrail
- **R4**: T3S.2 depends on T4S.7 (pulled forward in batch-7) — resolved in plan
- **R5**: If T2S.1 RBAC perf still flaky, don't compound with P3 tasks — fix first

## Next

→ `/prd2impl:skill-10-smoke-test M3-3`
→ `/prd2impl:skill-8-batch-dispatch batch-11` (Playwright; may defer M3.5)
