---
title: M3 Epic E4 · Compliance Country Filter
status: draft
date: 2026-04-21
prd_refs: [docs/prd/AutoService-M3-PRD.md §2 E4]
stories: [E4.1, E4.2]
---

# M3 Epic E4 · Compliance Country Filter — Design

> Closes PRD gap A-④: filter the 16 compliance templates by `tenant.countries`
> (today one-size-fits-all). ISO 3166-1 alpha-2 per CON-05; rulesets hardcoded
> in repo per CON-06 (hot-reload deferred to M4+).

---

## 1. Context & Problem Statement

### 1.1 What's wrong with "one-size-fits-all"

Today `ComplianceEngine.scan()` runs **all 16 rules** (EU 6 + US 4 + CN 6) against every
tenant regardless of operating region. Consequences:

- **Signal noise** — a US-only retailer sees 6 EU GDPR failures (e.g., `eu-03 Consent mechanism`)
  it isn't obligated to satisfy. Risk report conflates real gaps with irrelevant ones.
- **Compliance drift risk** — because everyone fails at least a few rules, operators learn to
  triage by hand. Real blockers hide under noise, and `BlockingDecision.production_blocked`
  loses signal when the blocker comes from a rule outside the tenant's regulatory reach.
- **Scale block** — adding JP/SG/AU (E4.2) today would multiply the noise 2x+. Need the
  filter first, then expand coverage.

### 1.2 PRD mapping

- [M3 PRD §1.2](../../prd/AutoService-M3-PRD.md#l33): "合规适配：按 `tenant.countries`
  过滤合规模板（PRD gap A-④ 收尾）"
- [M3 PRD §2 Epic E4](../../prd/AutoService-M3-PRD.md#l97-l108): two stories
  (E4.1 filter P1, E4.2 new rulesets P2); CON-05 alpha-2 codes, CON-06 rules hardcoded.
- [M3 PRD §6.1](../../prd/AutoService-M3-PRD.md#l247): gate requirement — "US tenant 不看到
  EU-only 规则 (E4.1)".
- [M3 PRD §1.3](../../prd/AutoService-M3-PRD.md#l39): non-goal — "合规规则热更新 M4+".

### 1.3 Gap analysis

- [GAP-E4.1 (partial, P1)](../../plans/m3/2026-04-21-gap-analysis.yaml): 16 rules + single-region
  `region_filter` exist; no `tenant.countries` field; filter does not come from tenant config.
- [GAP-E4.2 (missing, P2)](../../plans/m3/2026-04-21-gap-analysis.yaml): no JP / SG / AU rulesets;
  coverage stops at `cn-06`.

---

## 2. Current State

### 2.1 Rules file

[autoservice/compliance/rules.yaml](../../../autoservice/compliance/rules.yaml) holds 16 rules,
each with a **singular** `region: EU|US|CN` string field:

```yaml
- rule_id: eu-01
  region: EU          # ← string, not list
  regulation: "EU AI Act Art.52(1)"
  severity: critical
  ...
```

Counts: EU 6 (GDPR + EU AI Act), US 4 (CCPA + COPPA), CN 6 (PIPL + 网信办). No rule today
targets multiple regions and there is no "global" tag.

### 2.2 Scan engine

[autoservice/compliance/compliance.py:143-174](../../../autoservice/compliance/compliance.py):

```python
def scan(
    self,
    tenant_id: str,
    config: dict,
    region_filter: Optional[str] = None,   # single region
) -> ComplianceReport:
    for rule in self._rules:
        if region_filter and rule["region"] != region_filter:
            continue                        # skip non-matching
        ...
```

`region_filter` is optional; **when None, all 16 rules run**. Callers today never set it —
confirmed by grep of all in-repo callers:

| Caller | Line | Passes `region_filter`? |
|--------|------|-------------------------|
| [autoservice/api_routes.py:1210](../../../autoservice/api_routes.py) | `engine.scan(tenant_id, config)` | No |
| [autoservice/publish.py:504](../../../autoservice/publish.py) | `engine.scan(tenant_id, nested)` | No |
| [autoservice/proposal_pipeline.py:429](../../../autoservice/proposal_pipeline.py) | `engine.scan(...)` | No |
| [tests/test_proposal_pipeline.py:103,108](../../../tests/test_proposal_pipeline.py) | mock `scan(tenant_id, config)` | No |

**So `region_filter` is dead API surface** — no caller sets it, no test asserts it. This
simplifies the backward-compat story in §3.1.

### 2.3 Tenant config

[autoservice/master_tenant.py:48-74](../../../autoservice/master_tenant.py) writes
`config.json` for internal tenants. Fields today: `tenant_id`, `brand_name`, `industry`,
`tier`, `parent_tenant_id`, `kind`, `status`, `channels`, `compliance`, `soul`, `dream`,
`created_at`. **No `countries` field.** Same for onboarding-produced tenants
([autoservice/onboarding.py](../../../autoservice/onboarding.py) — no `countries`/`region` string).

### 2.4 Compliance endpoint

[autoservice/api_routes.py:1166-1210](../../../autoservice/api_routes.py) loads
`.autoservice/tenants/<tid>/config.json`, builds a nested dict
(`{"tenant": ..., "soul": ...}`), and calls `engine.scan(tenant_id, config)`. Again, no country
extraction.

### 2.5 Reference: unused country detection

[cinnox-demo/scripts/route_query.py:96-98](../../../cinnox-demo/scripts/route_query.py) has a
`detect_country()` utility, but it is **not** wired into compliance. Mentioned here only as a
reference; we are not planning to auto-detect per-request — compliance filters on the tenant's
**configured** operating countries, not on end-user geolocation.

---

## 3. Design

### 3.1 E4.1 — Country filter (P1)

#### 3.1.1 Tenant config schema

Add `countries: list[str]` to tenant `config.json`:

```json
{
  "tenant_id": "acme-eu",
  "brand_name": "Acme EU Retail",
  "countries": ["DE", "FR", "IT"],
  "channels": ["web"],
  "compliance": { ... },
  ...
}
```

**Semantics:**

- ISO 3166-1 alpha-2 codes (CON-05). Upper-case by convention; validator lower-cases
  on read for comparison.
- **Empty list `[]` = fail-closed** — scan runs only rules tagged `GLOBAL` (see §3.1.4);
  risk report shows `warning: tenant has no configured countries`. Rationale: a tenant
  with no declared operating country should not accidentally ship to production.
- **Missing field** (old config, no `countries` key) = **fail-open, all rules** — preserves
  M2 behaviour for unmigrated tenants. Callers bubble a deprecation warning into the report.
  This is the migration escape hatch; new-tenant flows always write the field.

We deliberately distinguish `[]` (explicit empty, fail-closed) from `missing` (legacy,
fail-open) to avoid breaking existing `.autoservice/sandbox/<tid>/config.json` files. Once
all tenants have been migrated, a follow-up PR can harden missing-to-fail-closed behind a
flag.

#### 3.1.2 Country → region mapping

Rules tag region as a **bucket** (`EU`, `US`, `CN`, plus `JP`/`SG`/`AU` in E4.2). A
new registry module `autoservice/compliance/country_registry.py` maps each supported
alpha-2 code to its bucket: all 27 EU member states → `"EU"`; `US`→`US`; `CN`→`CN`;
`JP`→`JP`; `SG`→`SG`; `AU`→`AU`. Exports `COUNTRY_TO_REGION: dict[str, str]`,
`SUPPORTED_COUNTRIES: frozenset[str]`, and `validate_countries()` (§3.1.5).

Rationale for keeping the registry in code (CON-06): avoids runtime config, no
hot-reload path, no admin UI needed in M3. EU is one bucket because GDPR + EU AI
Act apply uniformly across all 27 members. UK is intentionally excluded — post-Brexit
UK-GDPR is close but not identical; a separate bucket is a M4 decision (§6.5).

#### 3.1.3 Scan API change

Extend the signature: add `countries: list[str] | None = None` as positional, keep
`region_filter: str | None = None` keyword-only and **deprecated** (emits
`DeprecationWarning`). Filter precedence: (1) if `countries` is provided — even `[]` —
use it; (2) else if `region_filter` is provided, use legacy single-region path;
(3) else, run all rules.

When `countries` is provided, build `active_regions = {COUNTRY_TO_REGION[c] for c in
validate_countries(countries)}`; a rule applies iff `rule["region"] == "GLOBAL"` or
`rule["region"] in active_regions`.

`region_filter` grep confirms zero in-repo callers (§2.2), so keeping it as deprecated
doesn't block removal — landing in M4 once downstream forks confirm.

#### 3.1.4 "Global" rules — opt-in via explicit tag

Some rules plausibly apply regardless of region (e.g., "AI disclosure" has analogues in
EU AI Act, CCPA, and 网信办). We considered three options:

| Option | Behaviour | Decision |
|--------|-----------|----------|
| (a) Any rule without a region tag is global | Implicit; fragile | Rejected |
| (b) Explicit `region: GLOBAL` sentinel in yaml | Opt-in per rule | **Chosen** |
| (c) Separate `global.yaml` file | Parallel registry | Rejected (adds file ops) |

M3 ships **zero** `GLOBAL` rules — the 16 existing rules keep their region-specific tags.
E4.2 may add 1-2 `GLOBAL` rules (e.g., AI identity disclosure) if the regulators' language
is close enough to reuse. Rule authors decide; reviewer verifies.

A tenant with `countries: []` therefore scans only `GLOBAL` rules — in M3 that's zero rules,
so the scan returns PASS with zero checks. The endpoint adds a `warning: no_countries_configured`
field to make this visible.

#### 3.1.5 Validation

`validate_countries(raw: list[str]) -> list[str]` in `country_registry.py`: upper-cases
each element, rejects non-strings, rejects any code not in `SUPPORTED_COUNTRIES`, raises
`ValueError` with the offending codes + the supported list on failure; returns the
normalised list on success.

**Where to validate:**

1. **Config load (read path)** — `api_routes.compliance_check` calls it after reading
   `config.json`. Failure → HTTP 400 with offending codes.
2. **Onboarding (write path)** — new-tenant writers call it before writing. Rejecting at
   write prevents stored garbage; rejecting at read catches garbage that slipped past M2
   configs or manual edits.

No migration on existing configs — they lack the field and fall through to fail-open
behaviour (§3.1.1).

#### 3.1.6 Endpoint behaviour

[api_routes.py:1166](../../../autoservice/api_routes.py) `POST /api/compliance/check`:
read `raw_config.get("countries")`; if `None` → legacy path (all rules, warning
`no_countries_field_legacy_fallback`); if present → `validate_countries()` (HTTP 400
on failure), then `engine.scan(tenant_id, config, countries=countries)`; empty list
adds warning `no_countries_configured`.

`ComplianceReport` gets a new `warnings: list[str]` field (default empty).
**No UI-supplied country parameter** — the endpoint never accepts a `countries` query
arg. Filter is always derived from the tenant's stored config, so one tenant cannot
ask "show me EU rules" and bypass its own configuration.

Downstream callers ([publish.py:504](../../../autoservice/publish.py),
[proposal_pipeline.py:429](../../../autoservice/proposal_pipeline.py)) get the same
treatment: pass `config.get("countries")` through after validation; on missing,
fall back to all-rules.

#### 3.1.7 Alternatives considered

| # | Alternative | Rejected because |
|---|-------------|------------------|
| A | Keep `region_filter`, make UI pick one region per request | Doesn't close the gap — tenant can still scan against wrong region by request; no declarative source of truth |
| B | Rules carry `regions: list[str]` and drop the `region: str` field | Breaks all 16 existing rules; migration churn for zero M3 benefit. We use country→region mapping instead |
| C | Nested resolution (C inherits B's countries if B is parent) | E2 subtenant is **DEFERRED_M4**; flat model only. See §4.1 |
| D | Auto-detect country from operator locale / request IP | Adds runtime dependency; compliance should reflect tenant's **operating reach**, not request origin |

---

### 3.2 E4.2 — New country rulesets (P2)

#### 3.2.1 Target coverage

PRD lists JP/SG/AU as **examples**, not binding. Chosen scope for M3:

| Country | Regulation | Rule count target | Rationale |
|---------|-----------|-------------------|-----------|
| **JP** | APPI (個人情報保護法) | 4 | Strong internal-beta demand from Japan-based pre-sales |
| **SG** | PDPA | 3 | Small, well-defined regime; fast win |
| **AU** | Privacy Act 1988 + APPs | 4 | High customer interest; APPs 1/5/6/11 cover the core |
| **(GLOBAL)** | — | 0 in M3 | Defer explicit globals until a second regime agrees on wording |

Total add: **~11 rules**, bringing the registry to 27. Matches PRD's "3-5 per country"
density without pushing the yaml past readability.

#### 3.2.2 Candidate rules per country (indicative)

Proposed rule_ids matching the existing yaml schema (rule authors finalise
fields/conditions at implementation; reuse existing fields when regulatory substance
overlaps, add new fields only for genuinely new obligations):

- **JP (APPI, 4):** `jp-01` purpose-of-use disclosure (Art.17/18, critical),
  `jp-02` sensitive-data consent (Art.20, critical), `jp-03` cross-border safeguards
  (Art.28, high), `jp-04` right to disclosure/correction (Art.33-34, high).
- **SG (PDPA, 3):** `sg-01` consent obligation (§13, critical — reuses `eu-03` field),
  `sg-02` DNC check (§37, high — gated on outbound), `sg-03` breach notification
  readiness (§26A, high).
- **AU (Privacy Act / APPs, 4):** `au-01` APP 1 privacy-policy (critical — reuses
  `eu-02` field), `au-02` APP 5 collection notice (critical — reuses `us-01` field),
  `au-03` APP 6 use/disclosure limitation (high), `au-04` APP 11 security/encryption
  (critical).

#### 3.2.3 No schema migration

Every new rule uses the existing yaml shape
([rule-schema.md](../../../docs/compliance/rule-schema.md)): `rule_id`, `name`, `name_zh`,
`region`, `regulation`, `severity`, `trigger.{type,field,condition}`, `blocking`, `description`,
`description_zh`, `remediation_doc`, `tags`. No loader changes. `remediation_doc` paths
(`docs/compliance/jp-01.md`, etc.) are created as stub placeholders (content is follow-up).

#### 3.2.4 Alternatives considered

| # | Alternative | Rejected because |
|---|-------------|------------------|
| E | Full ruleset per country (~6-8 rules each) | Out of scope — PRD targets 3-5; deeper coverage belongs to M4 compliance spec |
| F | Minimal "compliance hook" placeholder (1 rule per country) | Doesn't produce useful reports; defeats the point of E4.2 |
| G | Reuse `region: EU` for near-EU-aligned regimes (UK/JP/AU) | Incorrect — regulatory texts differ; sharing a bucket hides real gaps. Each country gets its own bucket |

---

## 4. Cross-cutting topics

### 4.1 Interaction with Epic E2 (subtenant)

Epic E2 is **DEFERRED_M4** per
[M3 PRD §8.1 Errata](../../prd/AutoService-M3-PRD.md). Consequence for E4:

- No nested `countries` resolution. Each tenant in M3 has its own `config.json` with its
  own `countries`. The flat model holds.
- When E2 returns, a separate spec will decide whether a child tenant inherits the
  parent's `countries` by default, or sets its own. That decision does not bind E4.

### 4.2 Error handling summary

| Scenario | Behaviour | Endpoint status |
|----------|-----------|-----------------|
| `config.json` missing `countries` key | Run all rules; warning `no_countries_field_legacy_fallback` | 200 |
| `countries: []` (empty list) | Run only `GLOBAL` rules (zero in M3); warning `no_countries_configured` | 200 |
| `countries: ["XX"]` (unknown code) | Reject with HTTP 400, error message lists bad codes + supported codes | 400 |
| `countries: ["de", "fr"]` (lowercase) | Normalize to `["DE", "FR"]`, no warning | 200 |
| `countries: "US"` (string, not list) | Reject with HTTP 400 | 400 |
| Legit multi-country tenant `["US", "DE"]` | Rules with `region in {US, EU}` + `GLOBAL` | 200 |

### 4.3 No UI parameter coupling

The existing compliance endpoint has no query params beyond `tenant_id`. We keep it that
way. Any "what-if, scan me against EU instead" debug feature belongs in a separate
internal-only endpoint (not in M3 scope).

---

## 5. Test Strategy

### 5.1 Unit tests (new)

Target file: `tests/compliance/test_country_filter.py`

- `test_validate_countries_accepts_alpha2` — `["US", "DE", "jp"]` → `["US", "DE", "JP"]`.
- `test_validate_countries_rejects_unknown` — `["US", "XX"]` raises with `XX` in message.
- `test_validate_countries_rejects_non_string` — `["US", 123]` raises.
- `test_country_to_region_covers_eu_27` — all 27 EU members map to `"EU"`.
- `test_scan_filters_by_single_country` — tenant `["US"]` returns only the 4 US rules.
- `test_scan_filters_by_multi_country` — tenant `["US", "DE"]` returns 4 + 6 = 10 rules.
- `test_scan_global_rule_always_runs` — inject a synthetic `region: GLOBAL` rule; included for
  any country set including `[]`.
- `test_scan_empty_countries_runs_only_global` — with no `GLOBAL` rule, zero rule results.
- `test_scan_missing_countries_runs_all_rules` — legacy path; 16 rule results.
- `test_scan_rejects_invalid_country_at_call_site` — `scan(countries=["XX"])` raises.

### 5.2 Integration tests

Target file: `tests/compliance/test_endpoint_country_filter.py`

- `test_us_tenant_sees_only_us_rules` — create tenant `{countries: ["US"], ...}` →
  POST `/api/compliance/check` → response rules all start with `us-`.
- `test_multi_region_tenant_eu_plus_us` — tenant `["DE", "US"]` → 10 rules, grouped.
- `test_legacy_tenant_all_rules_warning` — tenant without `countries` field → 16 rules
  + warning in report.
- `test_empty_countries_fail_closed_warning` — tenant with `countries: []` → warning,
  zero applicable rules.
- `test_invalid_country_400` — tenant with `countries: ["XX"]` → HTTP 400 + list of
  valid codes.
- `test_publish_flow_honors_countries` — [publish.py:504](../../../autoservice/publish.py)
  route: `_run_compliance_scan` must pass country filter through so a US-only tenant's
  publish isn't blocked by an EU rule.

### 5.3 Regression tests

- `tests/test_proposal_pipeline.py` — existing mocks use two-arg `scan(tenant_id, config)`;
  must keep working (countries kwarg defaults to None → legacy fallback). Add an assertion
  that legacy path still emits 16 results.
- `tests/compliance/` (existing) — all present tests green after the change;
  add one test asserting `DeprecationWarning` is raised when `region_filter=` is passed.

### 5.4 E4.2 rule tests

Target file: `tests/compliance/test_new_country_rules.py`

- `test_rules_yaml_loads` — YAML parses; total rule count = 27 (16 existing + 11 new).
- `test_every_rule_has_required_fields` — schema lint per
  [rule-schema.md](../../../docs/compliance/rule-schema.md): rule_id, name, region,
  regulation, severity, trigger{type,field,condition}, blocking, description,
  remediation_doc.
- `test_rule_ids_unique` — no duplicate rule_ids.
- `test_rule_region_in_supported_buckets` — every `rule.region` ∈ `{EU, US, CN, JP, SG, AU, GLOBAL}`.
- `test_jp_tenant_sees_jp_rules` — `countries: ["JP"]` → 4 jp- rules.
- `test_sg_tenant_sees_sg_rules` — 3 sg- rules.
- `test_au_tenant_sees_au_rules` — 4 au- rules.
- `test_shared_field_rules_deduplicate` — when `au-01` and `eu-02` share
  `tenant.privacy_policy_url`, a tenant `["AU", "DE"]` gets both rule_ids (two entries,
  same field); that's intentional — each regulation demands its own evidence.

---

## 6. Open Questions

1. **Global rules — implicit or explicit?** Chosen: explicit `region: GLOBAL` tag opt-in
   per rule (§3.1.4). **Q:** Is there any rule among the existing 16 where we want to
   re-tag as `GLOBAL` during E4.1? Default answer: **no** — keep the current region tags.
   Revisit in E4.2 review.
2. **Empty `countries: []` — fail-closed or fail-open?** Chosen: fail-closed with warning
   (§3.1.1). **Q:** Should we additionally surface a visible error in admin-portal's tenant
   view? Proposed: yes, but that's UI scope — out of this spec.
3. **`region_filter` deprecation timeline.** Kept with `DeprecationWarning` in M3. **Q:**
   Remove in M4 or M5? Default: M4 — zero in-repo callers today (§2.2), plenty of time
   for forks to migrate.
4. **Which countries for E4.2 internal beta?** PRD gives JP/SG/AU as examples. This spec
   commits to exactly those three. **Q:** Any customer-driven reason to swap in HK or KR
   instead? None identified at spec-writing time; confirm with pre-sales before task-gen.
5. **UK rules.** Post-Brexit UK GDPR is ~95% aligned with EU GDPR but textually distinct.
   **Q:** Do we add a fourth country in E4.2 (pushing scope to 4 countries + ~14 rules)?
   Default answer: **no** — defer to M4; the "textual overlap" cost isn't worth the added
   surface in M3.
6. **Shared-field rules.** `sg-01` reuses `eu-03`'s `tenant.consent_mechanism_enabled`
   field. **Q:** Is reporting two rule failures ("consent missing — EU" and
   "consent missing — SG") for the same underlying config gap desirable? Yes — each
   regulation's audit trail needs its own evidence row, even if remediation is a single
   config change.

---

## 7. Non-goals

Explicitly out of scope for M3:

- **Hot reload of rules** — CON-06 hardcoded; rule changes ship via normal code PRs. M4+.
- **Admin UI for rule editing** — coupled to hot reload. M4+.
- **Compliance rule versioning / audit trail of rule changes** — rules evolve; tracking
  "tenant X was scanned against rules v1.2" belongs to a compliance-audit epic. M4+.
- **Regional compliance dashboard / cross-tenant reporting** — reporting layer beyond the
  single-tenant `/api/compliance/check` endpoint is a separate epic.
- **Country auto-detection from request / operator geolocation** — compliance filter comes
  from declared operating countries, not end-user origin.
- **Nested resolution (subtenant inherits parent countries)** — Epic E2 is DEFERRED_M4;
  revisit alongside it.
- **UK / KR / HK rulesets** — deferred to M4; see §6.5.
- **Removing `region_filter`** — deprecated in M3, removed later (§6.3).

---

## 8. Implementation order (non-task granularity)

Roughly the order a single-engineer batch would land it; task-gen will split finer:

| Step | Content | Dependency |
|------|---------|-----------|
| S1 | `country_registry.py` (`COUNTRY_TO_REGION`, `SUPPORTED_COUNTRIES`, `validate_countries`) | independent |
| S2 | `ComplianceEngine.scan(countries=...)` + `_rule_applies` + `GLOBAL` handling + `region_filter` deprecation | S1 |
| S3 | `ComplianceReport.warnings` field + serialization | independent |
| S4 | Endpoint + `publish.py` + `proposal_pipeline.py` wiring — read `config.get("countries")`, validate, pass through | S2 + S3 |
| S5 | `master_tenant.py` + onboarding: write `countries: []` default for new internal/onboarded tenants; migration doc | S1 |
| S6 | E4.1 unit + integration + regression tests | S2-S5 |
| S7 | E4.2 new rules yaml additions (JP/SG/AU) + remediation stubs | S2 (filter works) |
| S8 | E4.2 rule schema lint tests + per-country integration tests | S7 |

S1-S6 land E4.1 (P1) as a batch; S7-S8 land E4.2 (P2) behind it.

---

## 9. Red lines & constraints checklist

- [x] ISO 3166-1 alpha-2 (CON-05) — `country_registry.py` enforces at validate time.
- [x] Rules hardcoded in repo (CON-06) — no DB, no admin edit, no hot reload.
- [x] No scope creep into Epic E2 (DEFERRED_M4) — flat tenants only.
- [x] No dream / CON-04 touchpoints — compliance path never writes proposals.
- [x] Backward-compat for legacy configs — missing `countries` key = fail-open with warning.
- [x] `region_filter` kept working through M3 (zero in-repo callers; deprecated).

---

**Next step:** spec review → task-gen splits S1-S8 into ~6-8 tasks across two batches
(E4.1 P1 first, E4.2 P2 behind it).
