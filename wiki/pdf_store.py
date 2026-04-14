"""PDF 파일 시스템 저장. `core.config.PDF_PATH` 기반.

기본 경로: `~/Documents/research-wiki/pdfs/` (ADR-002 vault 옆).
"""

from __future__ import annotations

from pathlib import Path

from core import config


def pdf_dir() -> Path:
    return config.PDF_PATH


def pdf_path(arxiv_id: str) -> Path:
    return pdf_dir() / f"{arxiv_id}.pdf"


def pdf_exists(arxiv_id: str) -> bool:
    return pdf_path(arxiv_id).is_file()


def save_pdf(arxiv_id: str, data: bytes) -> Path:
    path = pdf_path(arxiv_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
