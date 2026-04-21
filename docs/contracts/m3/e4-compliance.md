# Contract · M3 Epic E4 · Compliance Country Filter

**Version**: v1.0 · **Frozen**: 2026-04-21
**Design spec**: [docs/superpowers/specs/2026-04-21-m3-e4-compliance-country-filter-design.md](../../superpowers/specs/2026-04-21-m3-e4-compliance-country-filter-design.md)
**Stories covered**: E4.1, E4.2

## 1. Country Registry (CON-05)

**Standard**: ISO 3166-1 alpha-2 (two-letter uppercase codes).

New module `autoservice/country_registry.py`:

```python
# Full alpha-2 set (249 codes). Canonical source — no runtime fetch.
ISO_3166_1_ALPHA_2: frozenset[str] = frozenset({
    "AD","AE","AF","AG","AI","AL","AM","AO","AQ","AR","AS","AT","AU","AW","AX","AZ",
    # ... (full set) ...
})

# Special markers
GLOBAL_TAG: str = "*"   # compliance rules tagged region="*" apply to every tenant

def is_valid(code: str) -> bool:
    return code in ISO_3166_1_ALPHA_2

def validate_list(codes: list[str]) -> list[str]:
    """Return invalid codes; empty list = all valid."""
    return [c for c in codes if not is_valid(c)]
```

## 2. Tenant Config Extension

Add to `config.json` tenant schema:

```json
{
  "tenant_id": "...",
  "countries": ["US", "EU"],   // NEW in M3; ISO alpha-2; may include "EU" as a regional alias
  ...
}
```

### 2.1 Semantics

| Value | Meaning |
|---|---|
| `["US", "EU"]` | Tenant operates in these regions; compliance scan applies matching rules |
| `[]` (empty list) | **Fail-closed** (OQ-E4-1 default) — scan blocks; surfaces warning "tenant.countries required for operation" |
| field missing | Treated as empty `[]` (fail-closed; new tenants must set countries during onboarding) |

### 2.2 EU Alias

`"EU"` is accepted as a convenience alias in tenant.countries and rule.region. It is not ISO alpha-2 strict, but the compliance engine recognizes it. Future: may split EU into member-state codes (M4+ scope).

### 2.3 Validation

- On tenant config load: call `country_registry.validate_list(tenant.countries)`; raise if any invalid
- On onboarding wizard step: operator must pick ≥1 country before advancing
- Migration for existing M2 tenants: set `countries: ["*"]` (global permissive) during first M3 boot, emit warning `config: tenant {tid} countries defaulted to global ['*']; update in admin-portal`

## 3. Compliance Scan API (E4.1)

Extend [autoservice/compliance/compliance.py](../../../autoservice/compliance/compliance.py) `scan()`:

### 3.1 New Signature

```python
def scan(
    tenant_config: dict,
    countries: list[str] | None = None,    # NEW preferred param
    region_filter: str | None = None,       # DEPRECATED (retained for M3, removed M4)
) -> list[ScanResult]:
    """Run compliance rules filtered by country set.
    
    Rule matching:
      - rule.region == '*' (GLOBAL_TAG)      → always applies
      - rule.region in countries             → applies
      - rule.region == 'EU' and 'EU' in countries → applies
      - otherwise                             → skipped
    
    If countries is None and region_filter is set:
      behave as M2 (single-region scan), emit DeprecationWarning.
    
    If both countries and region_filter provided: ValueError.
    """
```

### 3.2 Deprecation Timeline (OQ-E4-2)

- **M3**: `region_filter` kwarg marked `@deprecated`; still works; emits `DeprecationWarning` on use
- **M4**: `region_filter` removed. Callers must pass `countries`.

**[FINDING from E4 subagent]**: `region_filter` has zero in-repo callers as of 2026-04-21. Migration cost near zero.

### 3.3 Rule YAML Schema (Unchanged)

Existing rules at [autoservice/compliance/rules.yaml](../../../autoservice/compliance/rules.yaml) keep single `region` field. No schema migration.

```yaml
- id: eu-01
  region: "EU"      # or "US" | "CN" | "JP" | "SG" | "AU" | "*"
  # ... existing fields ...
```

## 4. New Rulesets (E4.2, OQ-E4-3)

Add ~11 rules across three countries (uses existing rule schema):

### 4.1 Japan (JP) — APPI (Act on Protection of Personal Information)

- `jp-01` Purpose limitation (APPI §15-17)
- `jp-02` Data subject access right (APPI §28)
- `jp-03` Cross-border transfer opt-in (APPI §24)
- `jp-04` Breach notification (72h — APPI 2022 amendment)

### 4.2 Singapore (SG) — PDPA

- `sg-01` Consent for collection (PDPA §13)
- `sg-02` DNC (Do Not Call) registry check (PDPA §36-48)
- `sg-03` Data protection officer disclosure (PDPA §11)
- `sg-04` Data breach notification (PDPA §26D — 72h)

### 4.3 Australia (AU) — Privacy Act

- `au-01` Australian Privacy Principles consent (APP 3)
- `au-02` Direct marketing opt-out (APP 7)
- `au-03` Notifiable Data Breach scheme (30 days)

Total: ~11 rules across three countries. Pattern matches existing EU(6) / US(4) / CN(6) density.

### 4.4 Deferred (OQ-E4-3)

UK / KR / HK / BR / IN — deferred to M4+.

## 5. Compliance Endpoint Auto-Apply

Existing endpoint [api_routes.py:1166](../../../autoservice/api_routes.py#L1166) reads `tenant_id` from session. Extend to:

1. Load `tenant.countries` from config
2. Call `scan(tenant_config, countries=tenant.countries)`
3. If countries is empty → return 400 with message "tenant.countries unset — please configure in admin-portal"

No explicit country param from UI. Filter is automatic.

## 6. "Don't Do" List

1. **Don't** remove `region_filter` kwarg in M3 (breaks migration window for external callers if any)
2. **Don't** add hot-reload of rules.yaml — CON-06 defers to M4+
3. **Don't** support nested country sets (e.g., `["EU-DE", "EU-FR"]`) — M3 treats EU as atomic
4. **Don't** allow empty `[]` to pass scan (fail-closed per OQ-E4-1)
5. **Don't** mutate `rules.yaml` schema — `region` stays singular per-rule in M3

## 7. Open Questions (Defaults Applied)

| OQ | Default |
|---|---|
| OQ-E4-1 empty `countries[]` policy | fail-closed + warning |
| OQ-E4-2 `region_filter` deprecation | M3 deprecate; M4 remove |
| OQ-E4-3 M3 new countries | JP / SG / AU (~11 rules) |

## 8. Test Requirements

- `tests/compliance/test_country_registry.py` — alpha-2 validation; invalid code rejection
- `tests/compliance/test_multi_region_filter.py` — US tenant sees US rules; EU+US tenant sees both; global rules always apply
- `tests/compliance/test_jp_sg_au_rules.py` — new rulesets pass lint; JP tenant gets JP rules only
- `tests/compliance/test_empty_countries_fail_closed.py` — empty list → scan blocked
- `tests/compliance/test_region_filter_deprecated.py` — old kwarg emits DeprecationWarning
