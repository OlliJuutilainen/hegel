"""Route 2/3 foundation: run Tesseract and return per-word text, boxes and confidence.

Unlike the Claude-vision route, Tesseract exposes a bounding box and a confidence
score for every word. That gives us (a) a properly positioned invisible layer and
(b) the signal needed for the future two-pass Greek targeting (route 3): low-conf
boxes are the "stumped" spots worth a second, bounded look.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytesseract
from pytesseract import Output
from PIL.Image import Image

# Tesseract's image_to_data emits rows at several levels; words are level 5.
_WORD_LEVEL = 5

# Footnote/cross-reference markers Tesseract glues onto adjacent body words
# (the*, has®, withinTM, etc.) or emits as standalone column-edge artifacts (|).
# Stripped at ingest so downstream consumers — text layer, heading detection,
# TOC parsing — see clean tokens. Cost: pasting a footnote reference symbol
# along with body text won't carry the marker; for citation copying that's
# typically what you want anyway.
_TRAILING_MARKERS = re.compile(r"[*®™†‡°§|]+$")
# Tesseract sometimes emits the trademark glyph as literal 'TM' rather than '™'.
# Strip it only when glued to a real word (3+ lowercase letters before), so
# legitimate uppercase acronyms (ATM, GTM, MGMT) are untouched.
_TRAILING_LITERAL_TM = re.compile(r"(?<=[a-z]{3})TM$")


def _sanitize_word(text: str) -> str | None:
    """Strip trailing footnote markers; return None if the token is pure marker."""
    cleaned = _TRAILING_LITERAL_TM.sub("", text)
    cleaned = _TRAILING_MARKERS.sub("", cleaned)
    if not cleaned or not any(ch.isalnum() for ch in cleaned):
        return None
    return cleaned


# Akademie-Ausgabe-style margin reference: [volume:page], e.g. '[4:408]'. These
# print in the page margin and never occur in real body text, so they can be
# dropped from the text layer (the page image still shows them) to keep copied
# selections clean. Tolerant of a dropped closing bracket and OCR'd ':' as ';'/'.'.
_MARGIN_REF = re.compile(r"^\[\d{1,3}[:;.]\d{1,4}\]?$")


def is_margin_ref(text: str) -> bool:
    return bool(_MARGIN_REF.match(text.strip()))


@dataclass
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float  # 0-100; -1 means Tesseract reported no confidence
    block_num: int = 0
    par_num: int = 0
    line_num: int = 0
    word_num: int = 0


def ocr_words(
    image: Image, lang: str = "eng", min_conf: float = 0.0, psm: int | None = None
) -> list[Word]:
    # psm = Tesseract page segmentation mode. Default (None -> 3) does full layout
    # analysis, which can drop a body line into the gap between two auto-detected
    # blocks on a single-column page with a margin note. psm 4 ("single column of
    # variable sizes") or 6 ("single uniform block") avoids those block-boundary
    # drops on plain book pages.
    config = f"--psm {psm}" if psm is not None else ""
    data = pytesseract.image_to_data(
        image, lang=lang, config=config, output_type=Output.DICT
    )
    words: list[Word] = []
    for i in range(len(data["text"])):
        if int(data["level"][i]) != _WORD_LEVEL:
            continue
        text = data["text"][i]
        if not text or not text.strip():
            continue
        sanitized = _sanitize_word(text)
        if sanitized is None:
            continue
        text = sanitized
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1.0
        if conf < min_conf:
            continue
        words.append(
            Word(
                text=text,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                conf=conf,
                block_num=int(data["block_num"][i]),
                par_num=int(data["par_num"][i]),
                line_num=int(data["line_num"][i]),
                word_num=int(data["word_num"][i]),
            )
        )
    return words
