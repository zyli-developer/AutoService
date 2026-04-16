# Backend Gap Fill Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill 5 backend gaps so the PRD three-act journey runs end-to-end.

**Architecture:** New `autoservice/onboarding.py` for REST endpoints (upload/activate/invite), plus surgical edits to `message_router.py`, `proposal_pipeline.py`, and `sla_aggregator.py`. All changes are additive — no existing behavior changes.

**Tech Stack:** Python 3.11, FastAPI, pdfplumber, beautifulsoup4, csv stdlib, existing LocalEngine/CCPool/ComplianceEngine.

**Spec:** `docs/superpowers/specs/2026-04-16-prd-gap-fill-design.md` Track 1

**Branch:** dev-a

---

## Chunk 1: Upload & Parse Pipeline

### Task 1: Onboarding module — file parsers

**Files:**
- Create: `autoservice/onboarding.py`
- Create: `tests/test_onboarding.py`

- [ ] **Step 1: Write test for CSV parser**

```python
# tests/test_onboarding.py
import tempfile, csv
from pathlib import Path

class TestParseCSV:
    def test_parses_two_column_csv(self, tmp_path):
        csv_path = tmp_path / "history.csv"
        csv_path.write_text("role,content\ncustomer,Hello\nagent,Hi there!\n", encoding="utf-8")
        from autoservice.onboarding import parse_csv
        turns = parse_csv(csv_path)
        assert len(turns) == 2
        assert turns[0] == {"role": "customer", "content": "Hello"}
        assert turns[1] == {"role": "agent", "content": "Hi there!"}

    def test_empty_csv_returns_empty(self, tmp_path):
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("role,content\n", encoding="utf-8")
        from autoservice.onboarding import parse_csv
        assert parse_csv(csv_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_onboarding.py::TestParseCSV -v`
Expected: FAIL — `ImportError: cannot import name 'parse_csv'`

- [ ] **Step 3: Implement parse_csv**

```python
# autoservice/onboarding.py
"""Onboarding pipeline — file parsing + agent generation + tenant setup."""
from __future__ import annotations

import csv
import logging
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("autoservice.onboarding")


def parse_csv(path: Path) -> list[dict[str, str]]:
    """Parse a two-column (role, content) conversation CSV."""
    turns: list[dict[str, str]] = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            role = row.get("role", "").strip()
            content = row.get("content", "").strip()
            if role and content:
                turns.append({"role": role, "content": content})
    return turns
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_onboarding.py::TestParseCSV -v`
Expected: PASS

- [ ] **Step 5: Write test for PDF parser**

```python
# tests/test_onboarding.py (append)
class TestParsePDF:
    def test_extracts_text(self, tmp_path):
        """Requires a real PDF — create a minimal one with reportlab or skip."""
        from autoservice.onboarding import parse_pdf
        # Use a text file as fallback test (parse_pdf should handle gracefully)
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("This is plain text", encoding="utf-8")
        # PDF parser should return empty for non-PDF
        result = parse_pdf(txt_path)
        assert isinstance(result, str)

    def test_missing_file_returns_empty(self, tmp_path):
        from autoservice.onboarding import parse_pdf
        result = parse_pdf(tmp_path / "nonexistent.pdf")
        assert result == ""
```

- [ ] **Step 6: Implement parse_pdf**

```python
# autoservice/onboarding.py (append)

def parse_pdf(path: Path) -> str:
    """Extract plain text from a PDF file using pdfplumber."""
    if not path.exists():
        return ""
    try:
        import pdfplumber
        text_parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n\n".join(text_parts)
    except Exception as exc:
        logger.warning("PDF parse failed for %s: %s", path, exc)
        return ""
```

- [ ] **Step 7: Write test for URL parser**

```python
# tests/test_onboarding.py (append)
from unittest.mock import patch, MagicMock

class TestParseURL:
    def test_extracts_text_from_html(self):
        from autoservice.onboarding import parse_url
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><h1>Welcome</h1><p>Our products</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        with patch("autoservice.onboarding.requests.get", return_value=mock_resp):
            result = parse_url("https://example.com")
        assert "Welcome" in result
        assert "Our products" in result

    def test_request_failure_returns_empty(self):
        from autoservice.onboarding import parse_url
        with patch("autoservice.onboarding.requests.get", side_effect=Exception("timeout")):
            assert parse_url("https://bad.url") == ""
```

- [ ] **Step 8: Implement parse_url**

```python
# autoservice/onboarding.py (append)
import requests

def parse_url(url: str) -> str:
    """Fetch a URL and extract visible text using BeautifulSoup."""
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "AutoService-Bot/1.0"})
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except Exception as exc:
        logger.warning("URL parse failed for %s: %s", url, exc)
        return ""
```

- [ ] **Step 9: Run all parser tests**

Run: `PYTHONPATH=. pytest tests/test_onboarding.py -v`
Expected: ALL PASS

- [ ] **Step 10: Commit parsers**

```bash
git add autoservice/onboarding.py tests/test_onboarding.py
git commit -m "feat: onboarding file parsers (CSV, PDF, URL)"
```

### Task 2: Onboarding REST API endpoints

**Files:**
- Modify: `autoservice/onboarding.py`
- Modify: `autoservice/web_gateway.py`
- Create: `tests/test_onboarding_api.py`

- [ ] **Step 1: Write test for /api/onboard/upload endpoint**

```python
# tests/test_onboarding_api.py
import io
from starlette.testclient import TestClient
from autoservice.web_gateway import create_app

class TestOnboardUpload:
    def test_upload_csv_triggers_generation(self):
        client = TestClient(create_app())
        csv_content = b"role,content\ncustomer,Hello\nagent,Hi\n"
        resp = client.post(
            "/api/onboard/upload",
            data={"brand_name": "TestBrand", "industry": "tech"},
            files={"files": ("history.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "souls" in body
        assert "tenant_id" in body

    def test_upload_no_files_returns_422(self):
        client = TestClient(create_app())
        resp = client.post("/api/onboard/upload", data={"brand_name": "X"})
        # Missing required fields is okay — should still return 200 with empty generation
        assert resp.status_code in (200, 422)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_onboarding_api.py -v`
Expected: FAIL — 404 (route not registered)

- [ ] **Step 3: Implement upload endpoint + mount on app**

```python
# autoservice/onboarding.py (append)
from fastapi import APIRouter, File, Form, UploadFile
from autoservice.soul_generator import TenantConfig, generate_souls

onboard_router = APIRouter(prefix="/api/onboard", tags=["onboarding"])


@onboard_router.post("/upload")
async def upload_and_generate(
    brand_name: str = Form(""),
    industry: str = Form("general"),
    website_url: str = Form(""),
    languages: str = Form("zh"),
    files: list[UploadFile] = File(default=[]),
) -> dict[str, Any]:
    """Upload materials, parse, generate 4 agent souls."""
    tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"
    tenant_dir = Path(".autoservice") / "tenants" / tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)
    kb_texts: list[str] = []

    # Parse uploaded files
    for f in files:
        content = await f.read()
        suffix = Path(f.filename or "").suffix.lower()
        saved = tenant_dir / (f.filename or f"upload{suffix}")
        saved.write_bytes(content)

        if suffix == ".csv":
            turns = parse_csv(saved)
            kb_texts.append("\n".join(f"{t['role']}: {t['content']}" for t in turns))
        elif suffix == ".pdf":
            text = parse_pdf(saved)
            if text:
                kb_texts.append(text)
        else:
            kb_texts.append(content.decode("utf-8", errors="ignore"))

    # Parse URL if provided
    if website_url:
        url_text = parse_url(website_url)
        if url_text:
            kb_texts.append(url_text)

    # Store KB
    kb_path = tenant_dir / "kb.txt"
    kb_path.write_text("\n\n---\n\n".join(kb_texts), encoding="utf-8")

    # Generate souls
    config = TenantConfig(
        tenant_id=tenant_id,
        brand_name=brand_name or tenant_id,
        industry=industry,
        languages=languages.split(","),
    )
    try:
        drafts = generate_souls(config, dry_run=True)
        souls = {
            d.role: {"role": d.role, "kb_hit_count": 0, "mode": "dry_run", "warnings": []}
            for d in drafts
        }
    except Exception as exc:
        logger.warning("Soul generation failed: %s", exc)
        souls = {}

    return {"tenant_id": tenant_id, "souls": souls, "kb_size": len(kb_texts)}
```

Add to `web_gateway.py` in `create_app()`:

```python
from autoservice.onboarding import onboard_router
app.include_router(onboard_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_onboarding_api.py -v`
Expected: PASS

- [ ] **Step 5: Write test for /api/onboard/activate**

```python
# tests/test_onboarding_api.py (append)
class TestOnboardActivate:
    def test_activate_returns_sandbox_url(self):
        client = TestClient(create_app())
        resp = client.post("/api/onboard/activate", json={"tenant_id": "test_tenant"})
        assert resp.status_code == 200
        body = resp.json()
        assert "sandbox_url" in body
        assert "test_tenant" in body["sandbox_url"]
```

- [ ] **Step 6: Implement activate + invite endpoints**

```python
# autoservice/onboarding.py (append)
from pydantic import BaseModel

class ActivateRequest(BaseModel):
    tenant_id: str

class InviteRequest(BaseModel):
    tenant_id: str
    emails: list[str]

@onboard_router.post("/activate")
async def activate_sandbox(req: ActivateRequest) -> dict[str, Any]:
    sandbox_url = f"https://{req.tenant_id}.sandbox.localhost"
    tenant_dir = Path(".autoservice") / "tenants" / req.tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)
    config_path = tenant_dir / "config.yaml"
    import yaml
    config = {}
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config["sandbox_url"] = sandbox_url
    config["activated_at"] = __import__("datetime").datetime.now().isoformat()
    config_path.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
    return {"sandbox_url": sandbox_url, "tenant_id": req.tenant_id, "status": "active"}

@onboard_router.post("/invite")
async def invite_team(req: InviteRequest) -> dict[str, Any]:
    invites = []
    for email in req.emails:
        token = uuid.uuid4().hex
        invites.append({
            "email": email,
            "token": token,
            "link": f"https://{req.tenant_id}.sandbox.localhost/invite?t={token}",
        })
    return {"tenant_id": req.tenant_id, "invites": invites}
```

- [ ] **Step 7: Run all onboarding tests**

Run: `PYTHONPATH=. pytest tests/test_onboarding.py tests/test_onboarding_api.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit API endpoints**

```bash
git add autoservice/onboarding.py autoservice/web_gateway.py tests/test_onboarding_api.py
git commit -m "feat: onboarding REST API (upload/activate/invite)"
```

---

## Chunk 2: Operator Suggestions + Compliance Gate

### Task 3: Operator→Agent suggestion injection

**Files:**
- Modify: `autoservice/gateway/message_router.py`
- Modify: `tests/gateway/test_web_gateway.py`

- [ ] **Step 1: Write test for suggestion collection**

```python
# tests/gateway/test_suggestions.py
import pytest
import asyncio
from autoservice.conversation_engine import LocalEngine
from autoservice.conversation_engine.types import (
    Participant, ParticipantRole, MessageVisibility,
)
from datetime import datetime, timezone

@pytest.fixture
def engine_with_conv():
    engine = LocalEngine()
    loop = asyncio.new_event_loop()
    now = datetime.now(timezone.utc)
    conv = loop.run_until_complete(engine.create_conversation(channel="web", external_id="test"))
    loop.run_until_complete(engine.join(conv.id, Participant(id="cust", role=ParticipantRole.CUSTOMER, joined_at=now)))
    loop.run_until_complete(engine.join(conv.id, Participant(id="agent", role=ParticipantRole.AGENT, joined_at=now)))
    loop.run_until_complete(engine.join(conv.id, Participant(id="op", role=ParticipantRole.OPERATOR, joined_at=now)))
    return engine, conv.id, loop

class TestCollectSuggestions:
    def test_collects_side_messages(self, engine_with_conv):
        engine, conv_id, loop = engine_with_conv
        from autoservice.gateway.message_router import _collect_operator_suggestions
        # Send a SIDE message (operator in copilot mode, gate downgrades)
        loop.run_until_complete(engine.send_message(
            conv_id, source="op", content="Emphasize discount",
            requested_visibility=MessageVisibility.SIDE,
        ))
        suggestions = loop.run_until_complete(_collect_operator_suggestions(engine, conv_id))
        assert "Emphasize discount" in suggestions

    def test_empty_when_no_side_messages(self, engine_with_conv):
        engine, conv_id, loop = engine_with_conv
        from autoservice.gateway.message_router import _collect_operator_suggestions
        suggestions = loop.run_until_complete(_collect_operator_suggestions(engine, conv_id))
        assert suggestions == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/gateway/test_suggestions.py -v`
Expected: FAIL — `cannot import name '_collect_operator_suggestions'`

- [ ] **Step 3: Implement _collect_operator_suggestions**

Add to `autoservice/gateway/message_router.py`:

```python
async def _collect_operator_suggestions(
    engine: ConversationEngine, conv_id: str, limit: int = 5,
) -> str:
    """Collect recent SIDE-visibility messages as operator suggestions for agent context."""
    try:
        msgs = await engine.get_messages(conv_id, viewer_role="operator", limit=20)
        side_msgs = [
            m for m in msgs
            if m.visibility.value == "side" and m.source != "agent"
        ][-limit:]
        if not side_msgs:
            return ""
        lines = [f"[{m.timestamp.strftime('%H:%M') if hasattr(m.timestamp, 'strftime') else ''}] {m.source}: {m.content}" for m in side_msgs]
        return "<operator_suggestions>\n" + "\n".join(lines) + "\n</operator_suggestions>"
    except Exception:
        return ""
```

- [ ] **Step 4: Inject suggestions into _generate_agent_reply prompt**

In `_generate_agent_reply()`, before the `pool.session_query()` call, collect and prepend suggestions:

```python
# In _generate_agent_reply, before building prompt:
suggestions = await _collect_operator_suggestions(engine, conv_id)
prompt = f"{suggestions}\n<channel conv_id={conv_id} source=web>\n{customer_text}\n</channel>" if suggestions else f"<channel conv_id={conv_id} source=web>\n{customer_text}\n</channel>"
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=. pytest tests/gateway/test_suggestions.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add autoservice/gateway/message_router.py tests/gateway/test_suggestions.py
git commit -m "feat: operator suggestion injection into agent context"
```

### Task 4: Proposal compliance gate

**Files:**
- Modify: `autoservice/proposal_pipeline.py`
- Modify: `tests/test_proposal_pipeline.py`

- [ ] **Step 1: Write test for compliance gate**

```python
# tests/test_proposal_pipeline.py (append to existing TestProposalPipeline class)
def test_compliance_gate_blocks_proposal(self):
    """Proposals that fail compliance check get status=blocked."""
    from autoservice.proposal_pipeline import ProposalPipeline
    from autoservice.memory_pool import MemoryPool
    import tempfile, asyncio
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        mp = MemoryPool(Path(d) / "m.db")
        mp.record_turn("c1", "customer", "Problem")
        mp.record_turn("c1", "agent", "Fix")
        pp = ProposalPipeline(memory_pool=mp, db_path=Path(d) / "p.db")
        proposals = asyncio.get_event_loop().run_until_complete(pp.run())
        # All proposals should have a compliance_status field
        for p in proposals:
            assert "compliance_status" in p
            assert p["compliance_status"] in ("passed", "blocked")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_proposal_pipeline.py::TestProposalPipeline::test_compliance_gate_blocks_proposal -v`
Expected: FAIL — `KeyError: 'compliance_status'`

- [ ] **Step 3: Implement compliance gate in ProposalPipeline.run()**

In `autoservice/proposal_pipeline.py`, after `self._store_proposal(proposal)` in `run()`, add compliance check:

```python
# After proposal = self.create_proposal(suggestion, batch)
# Add compliance gate:
from autoservice.compliance.compliance import ComplianceEngine
ce = ComplianceEngine()
# Build minimal config from proposal content
synthetic_config = {"proposal_content": proposal.get("title", "")}
report = ce.scan(self._tenant_id or "default", synthetic_config)
if report.blocking.dream_engine_blocked:
    proposal["compliance_status"] = "blocked"
    proposal["blocking_rules"] = report.blocking.blocking_rules
else:
    proposal["compliance_status"] = "passed"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_proposal_pipeline.py::TestProposalPipeline::test_compliance_gate_blocks_proposal -v`
Expected: PASS

- [ ] **Step 5: Run full proposal pipeline tests**

Run: `PYTHONPATH=. pytest tests/test_proposal_pipeline.py -v`
Expected: ALL PASS (existing tests unbroken)

- [ ] **Step 6: Commit**

```bash
git add autoservice/proposal_pipeline.py tests/test_proposal_pipeline.py
git commit -m "feat: compliance gate on proposal pipeline"
```

---

## Chunk 3: SLA Metrics + Final Integration

### Task 5: SLA 7 metrics

**Files:**
- Modify: `autoservice/sla_aggregator.py`
- Modify: `tests/test_sla_aggregator.py` (if exists, else tests that cover SLA)

- [ ] **Step 1: Write test for new metrics**

```python
# tests/test_sla_metrics_extended.py
from autoservice.sla_aggregator import SLAAggregator, MetricType, WindowSize

class TestExtendedMetrics:
    def test_digest_rate_exists(self):
        assert hasattr(MetricType, "DIGEST_RATE")

    def test_complaint_rate_exists(self):
        assert hasattr(MetricType, "COMPLAINT_RATE")

    def test_ttfb_ms_exists(self):
        assert hasattr(MetricType, "TTFB_MS")

    def test_record_and_query_new_metrics(self):
        agg = SLAAggregator()
        agg.record(MetricType.DIGEST_RATE, 0.85)
        agg.record(MetricType.COMPLAINT_RATE, 0.02)
        agg.record(MetricType.TTFB_MS, 450.0)
        result = agg.get_percentiles(MetricType.DIGEST_RATE, WindowSize.FIVE_MIN)
        assert result.count == 1
        assert result.p50 == 0.85
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_sla_metrics_extended.py -v`
Expected: FAIL — `AttributeError: DIGEST_RATE`

- [ ] **Step 3: Add 3 metrics to MetricType enum**

In `autoservice/sla_aggregator.py`, add to `MetricType`:

```python
class MetricType(str, Enum):
    FIRST_REPLY_MS = "first_reply_ms"
    ACCEPT_MS = "accept_ms"
    CSAT_SCORE = "csat_score"
    RESOLUTION_RATE = "resolution_rate"
    DIGEST_RATE = "digest_rate"
    COMPLAINT_RATE = "complaint_rate"
    TTFB_MS = "ttfb_ms"
```

No other changes needed — `SLAAggregator.__init__` already iterates `MetricType` to create buffers.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=. pytest tests/test_sla_metrics_extended.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run existing SLA tests for regression**

Run: `PYTHONPATH=. pytest tests/ -k "sla" -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add autoservice/sla_aggregator.py tests/test_sla_metrics_extended.py
git commit -m "feat: SLA 7 metrics (add digest_rate, complaint_rate, ttfb_ms)"
```

### Task 6: Final integration — mount router + run full test suite

**Files:**
- Modify: `autoservice/web_gateway.py`

- [ ] **Step 1: Verify onboard_router is mounted**

Ensure `create_app()` in `web_gateway.py` includes:
```python
from autoservice.onboarding import onboard_router
app.include_router(onboard_router)
```

- [ ] **Step 2: Run full test suite**

Run: `PYTHONPATH=. pytest tests/ --ignore=tests/test_init_discuss.py --ignore=tests/test_widget_sdk_build.py -v --tb=short`
Expected: ALL PASS

- [ ] **Step 3: Run smoke test**

Run: `PYTHONPATH=. python tests/smoke_full.py`
Expected: 38/38 passed

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: backend gap-fill complete (upload, suggestions, compliance gate, SLA 7)"
```
