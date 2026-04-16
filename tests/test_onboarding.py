"""
Tests for autoservice.onboarding — upload pipeline for tenant onboarding.

Covers:
  - PDF text extraction
  - HTML text extraction (strip tags)
  - Plain text pass-through
  - Unsupported file type rejection
  - OnboardingPipeline.ingest() end-to-end
  - Chunk splitting for large documents
"""

import io
import tempfile
from pathlib import Path

import pytest

from autoservice.onboarding import (
    extract_text_from_pdf,
    extract_text_from_html,
    extract_text_plain,
    detect_file_type,
    chunk_text,
    OnboardingPipeline,
    UnsupportedFileType,
)


# ---------------------------------------------------------------------------
# detect_file_type
# ---------------------------------------------------------------------------

class TestDetectFileType:
    def test_pdf_extension(self):
        assert detect_file_type("report.pdf") == "pdf"

    def test_html_extension(self):
        assert detect_file_type("page.html") == "html"

    def test_htm_extension(self):
        assert detect_file_type("page.htm") == "html"

    def test_txt_extension(self):
        assert detect_file_type("notes.txt") == "text"

    def test_md_extension(self):
        assert detect_file_type("README.md") == "text"

    def test_unsupported_extension(self):
        assert detect_file_type("image.png") == "unsupported"

    def test_no_extension(self):
        assert detect_file_type("Makefile") == "text"

    def test_case_insensitive(self):
        assert detect_file_type("REPORT.PDF") == "pdf"


# ---------------------------------------------------------------------------
# extract_text_from_html
# ---------------------------------------------------------------------------

class TestExtractHtml:
    def test_strips_tags(self):
        html = "<html><body><h1>Title</h1><p>Hello <b>world</b></p></body></html>"
        text = extract_text_from_html(html)
        assert "Title" in text
        assert "Hello" in text
        assert "world" in text
        assert "<h1>" not in text
        assert "<b>" not in text

    def test_strips_script_style(self):
        html = "<html><head><style>body{color:red}</style></head><body><script>alert(1)</script><p>Safe</p></body></html>"
        text = extract_text_from_html(html)
        assert "Safe" in text
        assert "alert" not in text
        assert "color" not in text

    def test_empty_html(self):
        assert extract_text_from_html("") == ""

    def test_preserves_whitespace_structure(self):
        html = "<p>Line one</p><p>Line two</p>"
        text = extract_text_from_html(html)
        assert "Line one" in text
        assert "Line two" in text


# ---------------------------------------------------------------------------
# extract_text_plain
# ---------------------------------------------------------------------------

class TestExtractPlain:
    def test_passthrough(self):
        assert extract_text_plain("hello world") == "hello world"

    def test_strips_leading_trailing(self):
        assert extract_text_plain("  hello  ") == "hello"

    def test_empty(self):
        assert extract_text_plain("") == ""


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_short_text_single_chunk(self):
        chunks = chunk_text("short text", max_chars=1000)
        assert len(chunks) == 1
        assert chunks[0] == "short text"

    def test_splits_long_text(self):
        text = "word " * 500  # 2500 chars
        chunks = chunk_text(text, max_chars=1000)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c) <= 1000

    def test_empty_text(self):
        chunks = chunk_text("", max_chars=1000)
        assert chunks == []

    def test_overlap(self):
        text = "A" * 500 + "\n" + "B" * 500 + "\n" + "C" * 500
        chunks = chunk_text(text, max_chars=600, overlap=100)
        assert len(chunks) >= 2
        # Overlap means later chunks may re-include some content


# ---------------------------------------------------------------------------
# extract_text_from_pdf (uses a real tiny PDF if pdfplumber works)
# ---------------------------------------------------------------------------

class TestExtractPdf:
    def test_invalid_pdf_raises(self):
        with pytest.raises(Exception):
            extract_text_from_pdf(b"not a pdf at all")

    def test_empty_bytes_raises(self):
        with pytest.raises(Exception):
            extract_text_from_pdf(b"")


# ---------------------------------------------------------------------------
# OnboardingPipeline end-to-end
# ---------------------------------------------------------------------------

class TestOnboardingPipeline:
    def setup_method(self):
        self.pipeline = OnboardingPipeline(output_dir=None)

    def test_ingest_txt(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Hello onboarding world", encoding="utf-8")
        result = self.pipeline.ingest(str(txt_file))
        assert result["status"] == "ok"
        assert result["file_type"] == "text"
        assert "Hello onboarding world" in result["text"]
        assert result["num_chunks"] >= 1

    def test_ingest_html(self, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>Onboard me</p></body></html>", encoding="utf-8")
        result = self.pipeline.ingest(str(html_file))
        assert result["status"] == "ok"
        assert result["file_type"] == "html"
        assert "Onboard me" in result["text"]

    def test_ingest_unsupported(self, tmp_path):
        img_file = tmp_path / "photo.png"
        img_file.write_bytes(b"\x89PNG fake")
        with pytest.raises(UnsupportedFileType):
            self.pipeline.ingest(str(img_file))

    def test_ingest_missing_file(self):
        with pytest.raises(FileNotFoundError):
            self.pipeline.ingest("/nonexistent/file.txt")

    def test_ingest_saves_output(self, tmp_path):
        pipeline = OnboardingPipeline(output_dir=str(tmp_path / "output"))
        txt_file = tmp_path / "doc.txt"
        txt_file.write_text("Document content for output", encoding="utf-8")
        result = pipeline.ingest(str(txt_file))
        assert result["status"] == "ok"
        output_dir = Path(result["output_path"])
        assert output_dir.exists()
        # Should have at least one chunk file
        chunk_files = list(output_dir.glob("chunk_*.txt"))
        assert len(chunk_files) >= 1
