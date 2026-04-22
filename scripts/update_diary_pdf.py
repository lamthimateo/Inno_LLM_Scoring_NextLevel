#!/usr/bin/env python3
"""
Append an entry page to the existing project diary PDF.

Creates: AI_CHATGPT_Project_Diary_updated.pdf

Run:
  . .venv/bin/activate
  python scripts/update_diary_pdf.py
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
INPUT_PDF = ROOT / "AI_CHATGPT_Project_Diary.pdf"
OUTPUT_PDF = ROOT / "AI_CHATGPT_Project_Diary_updated.pdf"


ENTRY_TITLE = f"Project Diary Update — {date.today().isoformat()}"
ENTRY_LINES = [
    "Summary of changes (repo):",
    "- Integrated OpenAI API end-to-end (run-openai): request → response → parse/score → SQLite → export.",
    "- Added retry/backoff + per-model isolation so one failing API call doesn’t abort the run.",
    "- Stored raw model outputs plus provider metadata (meta_json) in SQLite; added lightweight migration.",
    "- Added unit tests for parser/scoring edges, DB migration, and OpenAI missing-key error path.",
    "- Refactored CLI into src/benchmark/* with scripts/benchmark.py kept as a backwards-compatible wrapper.",
    "",
    "Key files (high signal):",
    "  - src/adapters/openai_adapter.py",
    "  - src/benchmark/cli.py, src/benchmark/pipeline.py, src/benchmark/prompting.py",
    "  - src/storage/schema.py, src/storage/db.py",
    "  - tests/test_*.py",
]


def _make_entry_page_pdf_bytes() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Use a built-in font if DejaVu isn't available; register if present.
    try:
        font_path = "/Library/Fonts/DejaVuSans.ttf"
        if Path(font_path).exists():
            pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
            base_font = "DejaVuSans"
        else:
            base_font = "Helvetica"
    except Exception:
        base_font = "Helvetica"

    margin_x = 20 * mm
    y = height - 25 * mm

    c.setFont(base_font, 16)
    c.drawString(margin_x, y, ENTRY_TITLE)
    y -= 12 * mm

    c.setFont(base_font, 10.5)
    line_height = 5.2 * mm

    for line in ENTRY_LINES:
        # simple wrap at ~100 chars
        if len(line) <= 100:
            c.drawString(margin_x, y, line)
            y -= line_height
            continue

        chunk = ""
        for word in line.split(" "):
            if len(chunk) + len(word) + 1 > 100:
                c.drawString(margin_x, y, chunk.rstrip())
                y -= line_height
                chunk = ""
            chunk += word + " "
        if chunk.strip():
            c.drawString(margin_x, y, chunk.rstrip())
            y -= line_height

        y -= 1.5 * mm

    c.showPage()
    c.save()
    return buf.getvalue()


def main() -> None:
    if not INPUT_PDF.exists():
        raise SystemExit(f"Missing input PDF: {INPUT_PDF}")

    reader = PdfReader(str(INPUT_PDF))
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)

    entry_pdf = PdfReader(io.BytesIO(_make_entry_page_pdf_bytes()))
    for p in entry_pdf.pages:
        writer.add_page(p)

    with OUTPUT_PDF.open("wb") as f:
        writer.write(f)

    print(f"Wrote updated diary PDF: {OUTPUT_PDF}")


if __name__ == "__main__":
    main()

