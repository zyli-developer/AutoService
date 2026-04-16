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
import logging
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger("onboarding")


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

    return {
        "tenant_id": tenant_id,
        "brand_name": brand_name,
        "industry": industry,
        "files_parsed": len([r for r in results if r.get("status") == "ok"]),
        "file_results": results,
        "url_result": url_result,
    }


@onboard_router.post("/activate")
async def activate_sandbox(tenant_id: str = Form(...)):
    """Generate sandbox URL for tenant."""
    sandbox_url = f"https://{tenant_id}.sandbox.localhost"
    return {"tenant_id": tenant_id, "sandbox_url": sandbox_url, "status": "active"}


@onboard_router.post("/invite")
async def invite_team(tenant_id: str = Form(...), emails: str = Form("")):
    """Generate invite links for team members."""
    email_list = [e.strip() for e in emails.split(",") if e.strip()]
    invites = [
        {"email": e, "token": uuid.uuid4().hex, "link": f"https://{tenant_id}.sandbox.localhost/invite?t={uuid.uuid4().hex}"}
        for e in email_list
    ]
    return {"tenant_id": tenant_id, "invites": invites}
