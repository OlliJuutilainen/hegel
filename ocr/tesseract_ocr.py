"""Route 2/3 foundation: run Tesseract and return per-word text, boxes and confidence.

Unlike the Claude-vision route, Tesseract exposes a bounding box and a confidence
score for every word. That gives us (a) a properly positioned invisible layer and
(b) the signal needed for the future two-pass Greek targeting (route 3): low-conf
boxes are the "stumped" spots worth a second, bounded look.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytesseract
from pytesseract import Output
from PIL.Image import Image

# Tesseract's image_to_data emits rows at several levels; words are level 5.
_WORD_LEVEL = 5


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


def ocr_words(image: Image, lang: str = "eng", min_conf: float = 0.0) -> list[Word]:
    data = pytesseract.image_to_data(image, lang=lang, output_type=Output.DICT)
    words: list[Word] = []
    for i in range(len(data["text"])):
        if int(data["level"][i]) != _WORD_LEVEL:
            continue
        text = data["text"][i]
        if not text or not text.strip():
            continue
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
