"""Orchestrate the OCR pipeline: render -> transcribe -> overlay, page by page."""

from __future__ import annotations

from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter
from tqdm import tqdm

from . import render
from .overlay import build_overlay_page, get_text_font
from .transcribe import Transcriber


@dataclass
class Settings:
    model: str
    dpi: int
    max_tokens: int
    image_format: str = "PNG"
    font_file: str | None = None


def run(
    input_pdf: str,
    output_pdf: str,
    settings: Settings,
    text_sidecar: str | None = None,
) -> list[tuple[int, str]]:
    """Process every page and write the OCR'd PDF. Returns a list of (page, error) failures."""
    total = render.page_count(input_pdf)
    transcriber = Transcriber(settings.model, settings.max_tokens, settings.image_format)
    font = get_text_font(settings.font_file)

    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    failures: list[tuple[int, str]] = []
    sidecar_parts: list[str] = []

    for page_no in tqdm(range(1, total + 1), desc="OCR", unit="page"):
        page = reader.pages[page_no - 1]
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)

        text = ""
        try:
            image = render.render_page(input_pdf, page_no, settings.dpi)
            text = transcriber.transcribe(image)
        except Exception as exc:  # one bad page must not abort a 300-page run
            failures.append((page_no, repr(exc)))

        if text:
            overlay = build_overlay_page(text, width, height, font=font)
            page.merge_page(overlay)
        writer.add_page(page)

        if text_sidecar is not None:
            sidecar_parts.append(f"\n\n===== PAGE {page_no} =====\n{text}")

    with open(output_pdf, "wb") as handle:
        writer.write(handle)

    if text_sidecar is not None:
        with open(text_sidecar, "w", encoding="utf-8") as handle:
            handle.write("".join(sidecar_parts).lstrip())

    return failures
