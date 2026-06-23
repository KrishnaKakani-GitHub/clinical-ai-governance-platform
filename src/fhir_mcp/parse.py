"""Nemotron Parse integration — raw document → structured text.

Nemotron Parse (NVIDIA NIM) overcomes traditional OCR limitations:
  - Multi-column layout support (prior auth letters, EOB statements)
  - Table extraction with spatial grounding (formulary tables, benefit grids)
  - Reading-order reconstruction (critical for insurance documents)
  - Markdown formatting with structure preserved

This module is the first stage of the end-to-end pipeline:

  Raw PDF/Doc
    → Nemotron Parse (this module)  → structured markdown
    → ClinicalNLP.extract_entities()  → ICD-10/LOINC/NPI entities
    → LOINC deterministic validator    → accept / reject / warn
    → propose_observation              → staged write
    → human approve_write              → committed observation
    → SHA-256 audit chain              → tamper-evident record

API: NVIDIA NIM (OpenAI-compatible)
  https://integrate.api.nvidia.com/v1/chat/completions
  Model: nvidia/nemotron-parse
  Auth:  NVIDIA_API_KEY environment variable

For PHI compliance, deploy NIM self-hosted on-premises so no document
content leaves your infrastructure. The cloud NIM endpoint is suitable
for synthetic or de-identified documents only.

PHI NOTE: If NVIDIA_API_KEY is set and documents contain PHI, use the
self-hosted NIM endpoint (NEMOTRON_PARSE_BASE_URL env var).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_logger = logging.getLogger("fhir_mcp.parse")

_NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
_BASE_URL = os.environ.get(
    "NEMOTRON_PARSE_BASE_URL",
    "https://integrate.api.nvidia.com/v1",
)
_MODEL = "nvidia/nemotron-parse"
_TIMEOUT = 60  # seconds; large documents may take time

_PARSE_SYSTEM_PROMPT = (
    "You are a clinical document parser. Extract and structure all content "
    "from the provided document. Preserve table structure as markdown tables. "
    "Maintain reading order. Extract: patient demographics, diagnosis codes, "
    "procedure codes, medication lists, authorization decisions, dates, and "
    "provider information. Output clean, structured markdown."
)


class ParseResult:
    """Result from Nemotron Parse."""

    def __init__(
        self,
        structured_text: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = _MODEL,
        parse_method: str = "nemotron_parse",
    ) -> None:
        self.structured_text = structured_text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model = model
        self.parse_method = parse_method
        # Rough word count for logging (no PHI content)
        self.output_word_count = len(structured_text.split())

    def to_dict(self) -> dict[str, Any]:
        return {
            "structured_text": self.structured_text,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model": self.model,
            "parse_method": self.parse_method,
            "output_word_count": self.output_word_count,
        }


def parse_document(
    source: str | Path | bytes,
    document_type: str = "clinical",
) -> ParseResult:
    """Parse a clinical document using Nemotron Parse.

    Args:
        source: One of:
          - str/Path: local file path (PDF, PNG, JPG, TIFF)
          - bytes:    raw document bytes
          - str starting with 'http': public URL (non-PHI only)
        document_type: Hint for the parser. One of:
          'clinical', 'prior_auth', 'eob', 'treatment_plan', 'lab_report'

    Returns:
        ParseResult with structured_text (markdown) ready for NLP extraction.

    Raises:
        ValueError: If source type is unrecognised.
        RuntimeError: If the NIM API returns an error.

    PHI NOTE: Document content is sent to NVIDIA NIM. Use a self-hosted
    NIM endpoint (NEMOTRON_PARSE_BASE_URL) for documents containing PHI.
    """
    if not _NVIDIA_API_KEY:
        _logger.warning(
            "NVIDIA_API_KEY not set — falling back to raw text extraction. "
            "Set NVIDIA_API_KEY to enable Nemotron Parse."
        )
        return _fallback_parse(source)

    # Prepare document content
    if isinstance(source, (str, Path)) and not str(source).startswith("http"):
        path = Path(source)
        if not path.exists():
            raise ValueError(f"File not found: {path}")
        doc_bytes = path.read_bytes()
        media_type = _infer_media_type(path)
        doc_b64 = base64.b64encode(doc_bytes).decode()
        content_item: dict[str, Any] = {
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{doc_b64}"},
        }
    elif isinstance(source, bytes):
        doc_b64 = base64.b64encode(source).decode()
        content_item = {
            "type": "image_url",
            "image_url": {"url": f"data:application/pdf;base64,{doc_b64}"},
        }
    elif isinstance(source, str) and source.startswith("http"):
        content_item = {
            "type": "image_url",
            "image_url": {"url": source},
        }
    else:
        raise ValueError(f"Unsupported source type: {type(source)}")

    system_prompt = (
        f"{_PARSE_SYSTEM_PROMPT} "
        f"Document type: {document_type}."
    )

    payload = json.dumps({
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    content_item,
                    {
                        "type": "text",
                        "text": "Parse this document and return structured markdown.",
                    },
                ],
            },
        ],
        "max_tokens": 4096,
        "temperature": 0,
    }).encode()

    req = urllib.request.Request(
        f"{_BASE_URL}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_NVIDIA_API_KEY}",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"Nemotron Parse API error {e.code}: {body}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        _logger.warning("Nemotron Parse unreachable: %s — using fallback", e)
        return _fallback_parse(source)

    structured_text = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    usage = data.get("usage", {})

    _logger.info(
        "Nemotron Parse complete: output_words=%d input_tokens=%d output_tokens=%d",
        len(structured_text.split()),
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )

    return ParseResult(
        structured_text=structured_text,
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        model=_MODEL,
        parse_method="nemotron_parse_nim",
    )


def _infer_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }.get(suffix, "application/octet-stream")


def _fallback_parse(source: str | Path | bytes) -> ParseResult:
    """Fallback: return raw text when NVIDIA_API_KEY is not set."""
    if isinstance(source, bytes):
        try:
            text = source.decode("utf-8", errors="replace")
        except Exception:
            text = "[Binary content — set NVIDIA_API_KEY for structured parsing]"
    elif isinstance(source, (str, Path)) and not str(source).startswith("http"):
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = f"[Could not read {path} — set NVIDIA_API_KEY for structured parsing]"
    else:
        text = str(source)

    return ParseResult(
        structured_text=text,
        parse_method="raw_text_fallback",
    )
