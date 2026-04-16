# PRD Gap Fill — Backend + UI Alignment Design

> 2026-04-16 | Two parallel tracks | Based on `docs/prd/autoservice-full-journey.html`

## Context

The PRD HTML defines a three-act product journey (merchant onboarding, daily operations, nightly learning) with high-fidelity interactive prototypes. Backend components are ~87% complete but 5 capabilities are missing. Frontend has 3 SPA skeletons that don't match the PRD's visual/interaction design.

## Decision Log

- **UI scope**: Full alignment (option A) — use PRD's CSS design system directly, not Ant Design theme overrides
- **Backend priority**: Upload pipeline > Operator suggestions > Compliance gate > SLA metrics > Sandbox URL
- **Upload depth**: Lightweight pipeline (option B) — real CSV/PDF/URL parsing, no deep NLP structuring
- **Branch strategy**: dev-a (backend) / dev-b (UI), PR to dev (option B) — same as existing workflow

---

## Track 1: Backend (dev-a) — 5 Gap Items

### 1.1 Upload & Parse Pipeline (P0)

**New file:** `autoservice/onboarding.py`

REST API mounted on the FastAPI app in `web_gateway.py`:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/onboard/upload` | POST | Accept files + form fields, parse, generate agents |
| `/api/onboard/activate` | POST | Generate sandbox URL, write tenant config |
| `/api/onboard/invite` | POST | Generate invite tokens for team members |

**Upload flow:**
1. Receive multipart form: `brand_name`, `industry`, `website_url`, `languages[]`, files (PDF/CSV)
2. Parse each file type:
   - **CSV**: `csv` stdlib → `memory_pool.record_turn()` per row
   - **PDF**: `pdfplumber` → extract plain text → store as KB document
   - **URL**: `requests` + `BeautifulSoup` → extract page text → store as KB document
3. Call `soul_generator.generate_souls(config, dry_run=False)` with KB context
4. Return `GenerationResult` (per-role kb_hit_count, mode, warnings)

**Dependencies:** `pdfplumber`, `beautifulsoup4` (add to requirements)

### 1.2 Operator→Agent Suggestion Channel (P0)

**Modified file:** `autoservice/gateway/message_router.py`

No new frame types needed. Leverage existing mechanisms:

1. Operator sends `operator_message` in copilot mode
2. Gate already downgrades to `visibility=SIDE` (not seen by customer)
3. **New**: When generating next agent reply via CCPool, collect recent SIDE messages for the conversation and inject as context:
   ```
   <operator_suggestions>
   [15:42] operator: 强调 B 档本月优惠
   [15:43] operator: 客户之前买过 X 服务，可以推荐升级
   </operator_suggestions>
   ```
4. Agent's Claude prompt naturally incorporates these suggestions

**Change scope:** ~20 lines in `_generate_agent_reply()` to query recent SIDE messages and prepend to prompt.

### 1.3 Proposal Compliance Gate (P1)

**Modified file:** `autoservice/proposal_pipeline.py`

In `ProposalPipeline.run()`, after proposals are generated and before status is set to `draft`:

1. Build a synthetic tenant config from the proposal content
2. Call `ComplianceEngine().scan(tenant_id, config)`
3. If `blocking.production_blocked` or `blocking.dream_engine_blocked`:
   - Set proposal `status = "blocked"`
   - Attach `blocking_reason` from failed rule IDs
4. Otherwise proceed to `draft` status

**Change scope:** ~15 lines.

### 1.4 SLA 7 Metrics (P1)

**Modified file:** `autoservice/sla_aggregator.py`

Add 3 metrics to the existing ring-buffer architecture:

| New Metric | Source | Description |
|-----------|--------|-------------|
| `digest_rate` | Conversations resolved without takeover / total | Agent self-resolution ratio |
| `complaint_rate` | Complaints flagged / total conversations | From triage urgency signal |
| `ttfb_ms` | Time from customer message to first placeholder | Placeholder stream latency |

Same P50/P95 + 5m/1h/24h window pattern as existing metrics.

### 1.5 Sandbox URL + Team Invite (P2)

**New endpoints in:** `autoservice/onboarding.py`

- `POST /api/onboard/activate`: Generate `{tenant_id}.sandbox.localhost` URL, write to tenant config YAML, return URL
- `POST /api/onboard/invite`: Accept email list, generate UUID invite tokens, return invite links (no real email send)

Lightweight implementation — data stored in `.autoservice/tenants/{tenant_id}/config.yaml`.

---

## Track 2: UI (dev-b) — PRD Full Visual Alignment

### 2.1 Design System Package

**New package:** `frontend/packages/design-system/`

Extract from PRD HTML `autoservice-full-journey.html`:

**`tokens.css`** — CSS custom properties:
```css
--cream: #fff;
--oat: #e0e2e6; --oat-l: #f8fafc;
--silver: #9f9b93; --charcoal: #55534e;
--m300: #dbeafe; --m600: #1b61c9; --m800: #181d26;
--s500: #3bd3fd; --s800: #0089ad;
--l400: #f8cc65; --l500: #fbbd41; --l700: #d08a11; --l800: #9d6a09;
--u300: #c1b0ff; --u500: #8a5cf6; --u800: #43089f; --u900: #32037d;
--p: #fc7981;
```

Color semantics: M=merchant/primary, S=customer, L=warning, U=platform, P=urgent.

**`components.css`** — Reusable classes: `.web-msg`, `.im-card`, `.im-block`, `.cs-card`, `.cs-wiz-step`, `.im-suggest`, `.im-handoff`, `.im-driver`, `.im-sidebar-msg`, `.im-cmd`, etc.

### 2.2 customer-chat Rewrite

Transform from full-screen layout to **floating widget overlay on merchant site**:

- Background: simulated merchant site (hero banner + product cards)
- FAB button: 48px circle, bottom-right, m800 background, pulse animation
- Chat modal: 300×380px, m800 header, white body, pill-shaped input
- Message styles: customer=m800 dark, agent=white+border, system=centered italic
- Remove current Tailwind full-screen layout entirely

### 2.3 operator-console Rewrite

Transform from Ant Design layout to **Feishu-style IM workspace**:

- Titlebar: oat-l background, three-dot indicator, workspace name
- Sidebar (160px): workspace header + channel list (#hash prefix) + DM section + unread badges
- Main area: conversation cards with avatars (colored squares) + im-block info blocks
- Copilot mode: relay lines (客户说/拟回复) + yellow suggestion bar
- Takeover mode: blue driver messages + purple sidebar agent messages
- Toggle controls: pill-shaped a/b switches
- Command input: /hijack /release styled with pink im-cmd badges
- Remove Ant Design dependency

### 2.4 admin-portal Rewrite

Hybrid approach — PRD CSS for layout, keep Ant Design for Table/Form:

- **Wizard**: horizontal stepper (pill steps: done=m300, current=m800, pending=oat-l), 5 steps
- **Step1 Upload**: form card with file upload + agent initialization status grid
- **Step3 Rehearsal**: virtual customer QA cards with pass/edit buttons
- **Step4 Compliance**: GDPR/CCPA/个保法 checklist with progress bar
- **Dashboard**: platform monitor style (SLA metric cards + monospace event stream)
- **Notifications/Dream Engine**: IM conversation style (proposal cards + /approve /edit /reject + canary progress bar)

### 2.5 Component Count

| SPA | Rewrite scope | Components |
|-----|--------------|------------|
| design-system | New shared package | tokens + ~15 component classes |
| customer-chat | Full rewrite (fullscreen → float) | ~8 |
| operator-console | Full rewrite (antd → IM style) | ~12 |
| admin-portal | Partial rewrite (wizard + dashboard + notifications) | ~10 |

---

## Parallel Execution

| Track | Branch | Scope | Files touched |
|-------|--------|-------|---------------|
| Backend | dev-a | 5 Python modules | `autoservice/*.py`, `autoservice/gateway/*.py` |
| UI | dev-b | 3 SPAs + design system | `frontend/**/*.tsx`, `frontend/**/*.css` |

No file overlap — safe for parallel execution. Both PR to `dev` when complete.
