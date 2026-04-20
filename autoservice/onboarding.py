"""
Onboarding upload pipeline — extracts text from uploaded files.

Supports PDF, HTML, and plain-text files. Extracted text is chunked
for downstream processing (e.g., knowledge-base ingestion, RAG indexing).

Usage:
    from autoservice.onboarding import OnboardingPipeline

    pipeline = OnboardingPipeline(output_dir=".autoservice/onboarding")
    result = pipeline.ingest("path/to/file.pdf")
    # result = {"status": "ok", "file_type": "pdf", "text": "...", "num_chunks": 3, ...}
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import sqlite3
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("onboarding")


# ---------------------------------------------------------------------------
# Sandbox paths & constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SANDBOX_ROOT = PROJECT_ROOT / ".autoservice" / "sandbox"
DREAM_SOUL_TEMPLATE = Path(__file__).resolve().parent / "dream_soul_template.md"


def sandbox_dir(tenant_id: str) -> Path:
    """Return the sandbox root for a given tenant."""
    return SANDBOX_ROOT / tenant_id


# ---------------------------------------------------------------------------
# Sandbox KB helpers (per-tenant SQLite + FTS5)
# ---------------------------------------------------------------------------

def _init_sandbox_kb(db_path: Path) -> sqlite3.Connection:
    """Initialize a per-tenant sandbox KB SQLite DB with FTS5.

    Schema mirrors the minimum fields required by the spec §2.4
    (kb_chunks: id, content, source_name, section, domain) and
    provides an FTS5 virtual table `kb_fts` that mirrors `content`.
    Content-synced FTS keeps writes cheap and search consistent.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_chunks (
            id          TEXT PRIMARY KEY,
            content     TEXT NOT NULL,
            source_name TEXT DEFAULT '',
            section     TEXT DEFAULT '',
            domain      TEXT DEFAULT '',
            created_at  TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
            content,
            source_name,
            section,
            domain,
            content=kb_chunks,
            content_rowid=rowid,
            tokenize="unicode61 remove_diacritics 1"
        )
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS kb_ai AFTER INSERT ON kb_chunks BEGIN
            INSERT INTO kb_fts(rowid, content, source_name, section, domain)
            VALUES (new.rowid, new.content, new.source_name, new.section, new.domain);
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS kb_ad AFTER DELETE ON kb_chunks BEGIN
            INSERT INTO kb_fts(kb_fts, rowid, content, source_name, section, domain)
            VALUES ('delete', old.rowid, old.content, old.source_name, old.section, old.domain);
        END
        """
    )
    conn.commit()
    return conn


def _ingest_chunks_into_sandbox_kb(
    tenant_id: str,
    file_results: Iterable[dict],
    *,
    domain: str = "",
) -> int:
    """Write extracted chunks into `.autoservice/sandbox/<tid>/kb/kb.db`.

    Returns the number of chunks written.
    """
    db_path = sandbox_dir(tenant_id) / "kb" / "kb.db"
    conn = _init_sandbox_kb(db_path)
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    try:
        for r in file_results:
            if r.get("status") != "ok":
                continue
            source_name = r.get("original_name") or r.get("file_name") or ""
            for chunk in r.get("chunks", []) or []:
                text = (chunk or "").strip()
                if not text:
                    continue
                conn.execute(
                    "INSERT INTO kb_chunks (id, content, source_name, section, domain, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (_uuid.uuid4().hex, text, source_name, "", domain, now),
                )
                written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def _write_sandbox_config_skeleton(
    tenant_id: str,
    brand_name: str,
    industry: str,
) -> Path:
    """Write the initial `config.json` skeleton for a sandbox tenant.

    Only the fields owned by Step 0 `/upload` are set here:
    tenant_id, brand_name, industry, status, created_at. Compliance,
    channels, soul, and dream fields are filled by later steps
    (`/activate`, `/dream-config`); see spec §2.2 / §3.2.
    """
    path = sandbox_dir(tenant_id) / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    skeleton = {
        "tenant_id": tenant_id,
        "brand_name": brand_name or "",
        "industry": industry or "general",
        "status": "sandbox",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(skeleton, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _copy_dream_soul_template(tenant_id: str) -> Optional[Path]:
    """Copy the static dream_soul.md template into the sandbox souls/ dir.

    Returns the destination path on success, or None if the template
    is missing (caller should log — we treat it as non-fatal).
    """
    if not DREAM_SOUL_TEMPLATE.exists():
        log.warning("dream_soul_template.md not found at %s", DREAM_SOUL_TEMPLATE)
        return None
    dest = sandbox_dir(tenant_id) / "souls" / "dream_soul.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DREAM_SOUL_TEMPLATE, dest)
    return dest


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class UnsupportedFileType(ValueError):
    """Raised when the uploaded file type is not supported."""
    pass


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------

_EXT_MAP = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".txt": "text",
    ".md": "text",
    ".csv": "text",
    ".log": "text",
    ".yaml": "text",
    ".yml": "text",
    ".json": "text",
    ".xml": "text",
    ".rst": "text",
}


def detect_file_type(filename: str) -> str:
    """Detect file type from extension. Returns 'pdf', 'html', 'text', or 'unsupported'."""
    ext = Path(filename).suffix.lower()
    if ext == "":
        # No extension — treat as plain text (Makefile, Dockerfile, etc.)
        return "text"
    return _EXT_MAP.get(ext, "unsupported")


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    import pdfplumber

    if not pdf_bytes:
        raise ValueError("Empty PDF bytes")

    pages_text: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)

    return "\n\n".join(pages_text)


def extract_text_from_html(html_string: str) -> str:
    """Extract visible text from HTML, stripping tags, scripts, and styles."""
    if not html_string:
        return ""

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_string, "html.parser")

    # Remove script and style elements
    for element in soup(["script", "style", "noscript"]):
        element.decompose()

    text = soup.get_text(separator="\n")
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text_plain(text: str) -> str:
    """Pass-through for plain text — just strip edges."""
    return text.strip()


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    max_chars: int = 4000,
    overlap: int = 200,
) -> list[str]:
    """Split text into chunks of at most max_chars, with optional overlap.

    Tries to split on paragraph boundaries (double newline) first,
    then sentence boundaries, then hard-cuts.
    """
    if not text.strip():
        return []

    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + max_chars

        if end >= len(text):
            chunks.append(text[start:].strip())
            break

        # Try to find a paragraph break
        cut = text.rfind("\n\n", start, end)
        if cut <= start:
            # Try a single newline
            cut = text.rfind("\n", start, end)
        if cut <= start:
            # Try a sentence-ending period
            cut = text.rfind(". ", start, end)
            if cut > start:
                cut += 1  # include the period
        if cut <= start:
            # Hard cut
            cut = end

        chunk = text[start:cut].strip()
        if chunk:
            chunks.append(chunk)

        # Move forward with overlap
        start = max(cut - overlap, start + 1)
        if start >= len(text):
            break

    return chunks


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class OnboardingPipeline:
    """End-to-end upload pipeline: detect -> extract -> chunk -> save.

    Args:
        output_dir: Directory to save extracted chunks. If None, chunks are
                    returned in-memory only (not persisted).
    """

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir) if output_dir else None

    def ingest(self, file_path: str) -> dict:
        """Ingest a file: detect type, extract text, chunk, and optionally save.

        Args:
            file_path: Path to the file to process.

        Returns:
            dict with keys: status, file_type, text, num_chunks, chunks,
            and optionally output_path.

        Raises:
            FileNotFoundError: If file_path does not exist.
            UnsupportedFileType: If file type is not supported.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_type = detect_file_type(path.name)
        if file_type == "unsupported":
            raise UnsupportedFileType(
                f"Unsupported file type: {path.suffix!r}. "
                f"Supported: PDF, HTML, TXT, MD, CSV, YAML, JSON, XML, RST."
            )

        # Extract text
        if file_type == "pdf":
            raw_bytes = path.read_bytes()
            text = extract_text_from_pdf(raw_bytes)
        elif file_type == "html":
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            text = extract_text_from_html(raw_text)
        else:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            text = extract_text_plain(raw_text)

        # Chunk
        chunks = chunk_text(text)

        result: dict = {
            "status": "ok",
            "file_type": file_type,
            "file_name": path.name,
            "text": text,
            "num_chunks": len(chunks),
            "chunks": chunks,
        }

        # Optionally persist chunks
        if self.output_dir is not None:
            out = self.output_dir / path.stem
            out.mkdir(parents=True, exist_ok=True)
            for i, chunk in enumerate(chunks):
                chunk_file = out / f"chunk_{i:04d}.txt"
                chunk_file.write_text(chunk, encoding="utf-8")
            result["output_path"] = str(out)
            log.info("Saved %d chunks to %s", len(chunks), out)

        return result


# ---------------------------------------------------------------------------
# FastAPI REST API
# ---------------------------------------------------------------------------

from fastapi import APIRouter, File, Form, UploadFile
import uuid
import tempfile

onboard_router = APIRouter(prefix="/api/onboard", tags=["onboarding"])


@onboard_router.post("/upload")
async def upload_and_parse(
    brand_name: str = Form(""),
    industry: str = Form("general"),
    website_url: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    """Upload files, parse, return extracted text + trigger soul generation."""
    pipeline = OnboardingPipeline()
    results = []

    for f in files:
        content = await f.read()
        suffix = Path(f.filename or "").suffix or ".txt"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            result = pipeline.ingest(str(tmp_path))
            result["original_name"] = f.filename
            results.append(result)
        except UnsupportedFileType as exc:
            results.append({"status": "skipped", "file_name": f.filename, "reason": str(exc)})
        finally:
            tmp_path.unlink(missing_ok=True)

    # Optionally parse URL
    url_result = None
    if website_url:
        try:
            import requests
            from bs4 import BeautifulSoup
            resp = requests.get(website_url, timeout=15, headers={"User-Agent": "AutoService/1.0"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            url_text = soup.get_text(separator="\n", strip=True)
            url_result = {"status": "ok", "source": website_url, "text_length": len(url_text)}
        except Exception as exc:
            url_result = {"status": "failed", "source": website_url, "error": str(exc)}

    tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"

    # --- Sandbox provisioning (spec §2 / §3.1) ---
    # Step 0 owns three on-disk artifacts:
    #   1. .autoservice/sandbox/<tid>/config.json  (skeleton — tenant metadata only)
    #   2. .autoservice/sandbox/<tid>/kb/kb.db     (FTS5 SQLite with extracted chunks)
    #   3. .autoservice/sandbox/<tid>/souls/       (4 LLM-generated + dream template)
    config_path = None
    try:
        config_path = _write_sandbox_config_skeleton(tenant_id, brand_name, industry)
    except Exception as exc:
        log.warning("Failed to write sandbox config skeleton: %s", exc)

    # --- KB ingest: write extracted chunks into per-tenant sandbox KB ---
    kb_chunks_written = 0
    try:
        kb_chunks_written = _ingest_chunks_into_sandbox_kb(
            tenant_id, results, domain=industry or ""
        )
    except Exception as exc:
        log.warning("Sandbox KB ingest failed (upload still succeeds): %s", exc)

    # --- Soul generation: wire soul_generator after text extraction ---
    souls_output = None
    souls_saved: dict[str, str] = {}
    try:
        from autoservice.soul_generator import TenantConfig, generate_souls, save_drafts

        # Combine extracted text from all successfully parsed files
        combined_text = "\n\n".join(
            r.get("text", "") for r in results if r.get("status") == "ok"
        )

        soul_config = TenantConfig(
            tenant_id=tenant_id,
            brand_name=brand_name or "Unknown Brand",
            industry=industry,
            extra_context=combined_text[:8000] if combined_text else "",
        )

        gen_result = generate_souls(soul_config, dry_run=(not combined_text))

        # --- Persist soul drafts to sandbox (fixes bug #1) ---
        try:
            paths = save_drafts(gen_result)
            souls_saved = {role: str(p) for role, p in paths.items()}
        except Exception as exc:
            log.warning("save_drafts failed: %s", exc)

        souls_output = {
            "mode": gen_result.mode,
            "total_kb_hits": gen_result.total_kb_hits,
            "warnings": gen_result.warnings,
            "saved_to": souls_saved,
            "roles": {
                role: {
                    "content": draft.content,
                    "kb_hit_count": draft.kb_hit_count,
                    "warnings": draft.warnings,
                }
                for role, draft in gen_result.souls.items()
            },
        }
    except Exception as exc:
        log.warning("Soul generation failed (upload still succeeds): %s", exc)
        souls_output = {"error": str(exc)}

    # --- Dream soul placeholder: copy static template (M1 only, see §2.5) ---
    try:
        dream_path = _copy_dream_soul_template(tenant_id)
        if dream_path is not None:
            souls_saved["dream"] = str(dream_path)
            if isinstance(souls_output, dict) and "saved_to" in souls_output:
                souls_output["saved_to"] = souls_saved
    except Exception as exc:
        log.warning("Dream soul template copy failed: %s", exc)

    return {
        "tenant_id": tenant_id,
        "brand_name": brand_name,
        "industry": industry,
        "files_parsed": len([r for r in results if r.get("status") == "ok"]),
        "file_results": results,
        "url_result": url_result,
        "sandbox_dir": str(sandbox_dir(tenant_id)),
        "config_path": str(config_path) if config_path else None,
        "kb_chunks_written": kb_chunks_written,
        "souls": souls_output,
    }


# ---------------------------------------------------------------------------
# /activate helpers — defaults and URL builder (spec §2.2 / §3.2 / §5.1)
# ---------------------------------------------------------------------------

#: 16-field compliance defaults.  ``setdefault`` only fills this when the
#: config has no ``compliance`` block, so tenant-facing tweaks survive.
DEFAULT_COMPLIANCE: dict = {
    "privacy_policy_url": "",
    "consent_mechanism_enabled": False,
    "data_retention_days": None,
    "right_to_erasure_enabled": False,
    "data_collection_disclosure": False,
    "opt_out_enabled": False,
    "coppa_compliant": False,
    "provider_registration_id": "",
    "data_cross_border_enabled": False,
    "user_identity_verification": False,
    "complaint_channel_url": "",
    "training_data_compliance": False,
}

#: 4-switch soul defaults (AI disclosure / escalation / decision notice / labeling).
DEFAULT_SOUL_CFG: dict = {
    "disclosure_enabled": False,
    "human_escalation_enabled": False,
    "automated_decision_notice": False,
    "ai_content_labeling": False,
}

#: Dream Engine defaults — spec §2.2 field.  M1 only persists these; the
#: pipeline still reads from memory (bug #9 is fixed by just landing them).
DEFAULT_DREAM_CFG: dict = {
    "trigger": "idle",
    "coverage": "all",
    "risk_threshold": "medium",
    "canary": {"stages": [5, 25, 100], "observe_hours": 24},
}


def _parse_channels(raw: str) -> list[str]:
    """Split the comma-separated ``channels`` form field, trimming each token."""
    if not raw:
        return []
    return [tok.strip() for tok in raw.split(",") if tok.strip()]


def build_urls(tenant_id: str, channels: list[str] | None = None) -> dict[str, str]:
    """Return the three sandbox URLs in path form (spec §5.1).

    Shape: ``/t/<tenant_id>/{chat,operator,admin}``. The subdomain form
    ``<tid>.sandbox.localhost`` is no longer used. ``channels`` is accepted
    for future per-channel URL variants but currently unused — the sandbox
    URL set is identical regardless of which channels are enabled.
    """
    scheme = os.getenv("WEB_SCHEME", "http")
    host = os.getenv("WEB_HOST", "localhost")
    port = os.getenv("DEMO_PORT", "8000")
    base = f"{scheme}://{host}:{port}"
    return {
        "chat": f"{base}/t/{tenant_id}/chat",
        "operator": f"{base}/t/{tenant_id}/operator",
        "admin": f"{base}/t/{tenant_id}/admin",
    }


@onboard_router.post("/activate")
async def activate_sandbox(
    tenant_id: str = Form(...),
    channels: str = Form(""),
):
    """Activate tenant sandbox — idempotent merge.

    Reads ``.autoservice/sandbox/<tid>/config.json`` (written as a skeleton
    by Step 0 ``/upload``), merges in the Step 1 payload + defaults, and
    writes it back. Calling this twice is safe: compliance / soul / dream
    blocks are ``setdefault``'d so any manual edits between calls survive.
    Spec refs: §2.2, §3.2.
    """
    from fastapi import HTTPException

    cfg_path = sandbox_dir(tenant_id) / "config.json"
    if not cfg_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Sandbox config not found for tenant {tenant_id!r} "
                f"(expected at {cfg_path}). Run /api/onboard/upload first."
            ),
        )

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Corrupt sandbox config at {cfg_path}: {exc}",
        )

    # Bug #3: channels is authoritative — Step 1 UI owns this field, so we
    # overwrite rather than setdefault.  Other fields use setdefault to stay
    # idempotent (bug #6).
    parsed_channels = _parse_channels(channels)
    cfg["channels"] = parsed_channels
    cfg.setdefault("compliance", dict(DEFAULT_COMPLIANCE))
    cfg.setdefault("soul", dict(DEFAULT_SOUL_CFG))
    # Dream block needs a deep copy so nested canary dict isn't shared.
    cfg.setdefault("dream", json.loads(json.dumps(DEFAULT_DREAM_CFG)))

    cfg_path.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "tenant_id": tenant_id,
        "status": cfg.get("status", "sandbox"),
        "channels": parsed_channels,
        "urls": build_urls(tenant_id, parsed_channels),
        "config_path": str(cfg_path),
    }


@onboard_router.post("/invite")
async def invite_team(tenant_id: str = Form(...), emails: str = Form("")):
    """Generate invite links for team members."""
    scheme = os.getenv("WEB_SCHEME", "http")
    host = os.getenv("WEB_HOST", "localhost")
    port = os.getenv("DEMO_PORT", "8000")
    base_url = f"{scheme}://{host}:{port}"

    email_list = [e.strip() for e in emails.split(",") if e.strip()]
    invites = [
        {"email": e, "token": uuid.uuid4().hex, "link": f"{base_url}/login?tenant={tenant_id}&invite={uuid.uuid4().hex}"}
        for e in email_list
    ]
    return {"tenant_id": tenant_id, "invites": invites}
