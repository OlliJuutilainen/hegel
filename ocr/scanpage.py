"""Read one scanned PDF page into styled text lines for pdf_to_markdown.py.

A scanned page carries its text only as an image, plus — often — an invisible OCR
layer that someone else made (JSTOR, a library, an earlier OCRmyPDF run). Neither
source is good enough alone: the layer has no italics and no font sizes, and both
OCR engines stumble on different things. So this module:

  1. renders the scan and runs Tesseract on it (hOCR: lines, words, baselines);
  2. reads the existing invisible layer, line by line, and lets the two readings
     vote word by word, with a dictionary as referee;
  3. looks at the ink itself for what neither OCR reports reliably:
       - italics, from the slant of each word's strokes,
       - footnote references and labels (small raised figures),
       - subscripts (the 1 in s₁), and comma-versus-period at a word's end;
  4. finds horizontal rules (footnote separators) in the image.

Coordinates come back in PDF points (origin bottom-left), like pdfminer's.
"""

from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

import numpy as np

# --------------------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------------------


@dataclass
class ScanWord:
    text: str
    x0: float
    x1: float
    italic: bool = False
    sup_before: str | None = None  # footnote label in front of the word ('1', or '?')
    sup_after: str | None = None  # footnote reference after the word


@dataclass
class ScanLine:
    words: list[ScanWord]
    x0: float
    x1: float
    top: float
    bottom: float
    baseline: float
    size: float  # estimated type size in points


@dataclass
class ScanPage:
    lines: list[ScanLine] = field(default_factory=list)
    rules: list[tuple[float, float, float]] = field(default_factory=list)  # (x0, x1, y)
    used_layer: bool = False


# --------------------------------------------------------------------------------------
# Lexicon
# --------------------------------------------------------------------------------------

_DICT_PATHS = ["/usr/share/dict/words", "/usr/share/dict/web2", "/usr/dict/words"]
_ROMAN = re.compile(r"^(?=[ivxlcdm]+$)m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")
_EDGE_PUNCT = "\"'“”‘’()[]{}.,;:!?*—–-"


class Lexicon:
    """System word list (macOS ships one) plus words both OCR readings agree on."""

    def __init__(self, path: str | None = None):
        self.words: set[str] = set()
        for p in [path] + _DICT_PATHS if path else _DICT_PATHS:
            if p and os.path.exists(p):
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    self.words = {w.strip().lower() for w in fh if w.strip()}
                break
        self.has_dictionary = bool(self.words)

    def add(self, word: str) -> None:
        core = word.strip(_EDGE_PUNCT).lower()
        if core.isalpha():
            self.words.add(core)

    def _known(self, w: str) -> bool:
        if w in self.words:
            return True
        for suf, rep in (("'s", ""), ("’s", ""), ("ies", "y"), ("ied", "y"), ("es", ""),
                         ("s", ""), ("ed", ""), ("ed", "e"), ("d", ""), ("ing", ""),
                         ("ing", "e"), ("ly", ""), ("er", ""), ("est", ""), ("ness", ""),
                         ("ity", "e"), ("al", "")):
            if w.endswith(suf) and len(w) > len(suf) + 1 and w[: len(w) - len(suf)] + rep in self.words:
                return True
        return False

    def valid(self, token: str) -> bool:
        """A token that reads as a real word, number, roman numeral or initial."""
        core = token.strip(_EDGE_PUNCT)
        if not core:
            return True  # pure punctuation
        low = core.lower().replace("’", "'")
        if re.fullmatch(r"\d+([.,]\d+)*", low) or _ROMAN.match(low):
            return True
        if len(core) == 1 and core.isalpha():
            return True
        if re.search(r"[^a-z'\-]", low):
            return False
        if "'" in low:
            stem, _, suffix = low.rpartition("'")
            if suffix in ("s", "t", "ve", "re", "ll", "d", "m", ""):
                low = stem
        parts = [p for p in re.split(r"[-']", low) if p]
        return bool(parts) and all(self._known(p) for p in parts)


_GARBAGE = re.compile(r"[©®°~£€^|\\<>{}¢¥ļ]|^/|/$")


def _norm(token: str) -> str:
    """Comparison form: typographic quotes, dashes and spacing don't count."""
    t = token.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("—", "-").replace("–", "-")
    return re.sub(r"['\"]+", "'", t)


def clean_quotes(text: str) -> str:
    """Undo Tesseract's habit of doubling the strokes of curly double quotes."""
    text = re.sub(r"[“‘]{2,}|‘“|“‘", "“", text)
    text = re.sub(r"[”’]{2,}|’”|”’", "”", text)
    return text


# --------------------------------------------------------------------------------------
# hOCR
# --------------------------------------------------------------------------------------


@dataclass
class _HLine:
    bbox: tuple[int, int, int, int]
    slope: float
    offset: float
    x_size: float
    words: list[dict]

    def baseline_at(self, x: float) -> float:
        return self.bbox[3] + self.offset + self.slope * (x - self.bbox[0])


class _HocrParser(HTMLParser):
    _LINE_CLASSES = {"ocr_line", "ocr_caption", "ocr_textfloat", "ocr_header"}

    def __init__(self):
        super().__init__()
        self.lines: list[_HLine] = []
        self._stack: list[str] = []
        self._word: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        title = a.get("title", "")
        self._stack.append(cls)
        if cls in self._LINE_CLASSES:
            bbox = tuple(int(v) for v in re.search(r"bbox (\d+) (\d+) (\d+) (\d+)", title).groups())
            m = re.search(r"baseline (-?[\d.]+) (-?[\d.]+)", title)
            xs = re.search(r"x_size ([\d.]+)", title)
            self.lines.append(_HLine(bbox, float(m.group(1)) if m else 0.0,
                                     float(m.group(2)) if m else 0.0,
                                     float(xs.group(1)) if xs else bbox[3] - bbox[1], []))
        elif cls == "ocrx_word" and self.lines:
            bbox = tuple(int(v) for v in re.search(r"bbox (\d+) (\d+) (\d+) (\d+)", title).groups())
            conf = re.search(r"x_wconf (\d+)", title)
            self._word = {"bbox": bbox, "conf": int(conf.group(1)) if conf else 0, "text": ""}
            self.lines[-1].words.append(self._word)

    def handle_endtag(self, tag):
        cls = self._stack.pop() if self._stack else ""
        if cls == "ocrx_word":
            self._word = None

    def handle_data(self, data):
        if self._word is not None:
            self._word["text"] += data


def parse_hocr(hocr: str) -> list[_HLine]:
    p = _HocrParser()
    p.feed(hocr)
    for ln in p.lines:
        ln.words = [w for w in ln.words if w["text"].strip()]
        for w in ln.words:
            w["text"] = w["text"].strip()
    return [ln for ln in p.lines if ln.words]


# --------------------------------------------------------------------------------------
# Ink geometry: clusters, super/subscripts, slant, rules
# --------------------------------------------------------------------------------------


def _clusters(ink: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Runs of ink-bearing columns: (c0, c1, top_row, bottom_row) in crop coordinates."""
    cols = ink.any(axis=0)
    if not cols.any():
        return []
    padded = np.concatenate([[False], cols, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    out = []
    for c0, c1 in zip(edges[::2], edges[1::2]):
        rows = np.flatnonzero(ink[:, c0:c1].any(axis=1))
        out.append((int(c0), int(c1), int(rows[0]), int(rows[-1])))
    return out


def _classify(top: float, bottom: float) -> str:
    """Kind of a glyph cluster from its extent above the baseline (units: x_size)."""
    height = top - bottom
    if 0.16 <= bottom <= 0.56 and top >= 0.6 and height >= 0.33:
        return "sup"  # a raised figure: as tall as a small digit, sitting well above the line
    if bottom >= 0.3 and top >= 0.55:
        return "quote"  # shorter than a figure: a quote mark or apostrophe
    if top <= 0.25 and bottom <= -0.24 and height >= 0.32:
        return "sub"
    if top <= 0.24 and bottom <= -0.07:
        return "comma"
    if top <= 0.2 and bottom >= -0.06:
        return "period"
    return "glyph"


_SUBSCRIPT = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _analyse_word(ink: np.ndarray, line: _HLine, word: dict) -> dict:
    """Split a Tesseract word into its body text and any sup/sub decorations."""
    x0, y0, x1, y1 = word["bbox"]
    crop = ink[y0 : y1 + 1, x0 : x1 + 1]
    text = word["text"]
    res = {"text": text, "sup_after": None, "sup_before": None, "sub": False, "crop": crop,
           "xh": [], "caps": []}
    xs = line.x_size or (y1 - y0)
    if xs <= 0 or crop.size == 0:
        return res
    base = line.baseline_at((x0 + x1) / 2) - y0
    clusters = _clusters(crop)
    kinds = [(_classify((base - t) / xs, (base - b) / xs), c0, c1) for c0, c1, t, b in clusters]
    # Heights of lowercase bodies and of capitals, for the line's type size — measured
    # from this word's own ink baseline, which is steadier than the line model's.
    bottoms = [b for _, _, _, b in clusters if abs(base - b) <= 0.12 * xs]
    if bottoms:
        wb = float(np.median(bottoms))
        res["xh"] = [wb - t for _, _, t, b in clusters
                     if abs(b - wb) <= 0.06 * xs and 0.3 <= (wb - t) / xs <= 0.62]
        res["caps"] = [wb - t for _, _, t, b in clusters
                       if abs(b - wb) <= 0.06 * xs and (wb - t) / xs > 0.62]
    if not kinds:
        return res
    chars = list(text)

    # Leading raised figure: a footnote label ('¹ Some philosophers ...').
    if len(kinds) >= 1 and kinds[0][0] == "sup" and chars:
        n = 0
        while n < len(kinds) and kinds[n][0] == "sup":
            n += 1
        if n < len(kinds) or len(chars) <= 3:
            label = "".join(chars[:n]) if n <= len(chars) else ""
            res["sup_before"] = label if label.isdigit() else "?"
            chars = chars[n:] if n < len(chars) else []

    # Trailing decorations, walked from the end while clusters are small marks.
    i_c, i_ch = len(kinds) - 1, len(chars) - 1
    tail: list[str] = []
    sup_digits = ""
    seen_sup = False
    while i_c >= 0 and i_ch >= 0 and i_c > 0:
        kind = kinds[i_c][0]
        ch = chars[i_ch]
        if kind == "sup" and all(not t.isalnum() for t in tail):
            seen_sup = True
            if ch in ".,;:":
                i_c -= 1  # the figure has no letter of its own: Tesseract dropped it
                continue
            sup_digits = (ch if ch.isdigit() else "") + sup_digits
        elif kind == "sub":
            digit = ch if ch.isdigit() else "1"
            tail.insert(0, digit.translate(_SUBSCRIPT))
        elif kind == "comma" and ch in ".,;":
            tail.insert(0, ",")
        elif kind == "period" and ch in ".,":
            tail.insert(0, ".")
        elif kind in ("comma", "period", "quote") and not ch.isalnum():
            tail.insert(0, ch)
        else:
            break
        i_c -= 1
        i_ch -= 1
    if seen_sup or tail:
        body = "".join(chars[: i_ch + 1])
        if body in ("5", "§") and any(c in "₀₁₂₃₄₅₆₇₈₉" for c in tail):
            body = "s"  # an italic s before a subscript, read as a figure
        res["text"] = body + "".join(tail)
        res["sub"] = any(c in "₀₁₂₃₄₅₆₇₈₉" for c in tail)
        if seen_sup:
            res["sup_after"] = sup_digits or "?"
    elif len(kinds) > len(chars) and kinds[-1][0] == "sup" and chars and not chars[-1].isalnum():
        # Tesseract dropped the raised figure altogether ('evil.' for 'evil.¹').
        res["sup_after"] = "?"
    else:
        res["text"] = "".join(chars)
    return res


_ANGLES = np.radians(np.arange(-8, 26, 2.0))


def word_slant(ink: np.ndarray) -> tuple[float | None, float]:
    """(best shear angle in degrees, sharpness gain over upright) of a word's strokes.

    Shearing an italic word back by its slant makes its vertical strokes line up, which
    sharpens the column histogram; upright type is sharpest unsheared.
    """
    h, w = ink.shape
    if h < 8 or w < 4 or ink.sum() < 20:
        return None, 0.0
    ys, xs = np.nonzero(ink)
    scores = []
    for a in _ANGLES:
        col = xs - np.round((h - 1 - ys) * np.tan(a)).astype(int)
        col -= col.min()
        scores.append(float((np.bincount(col).astype(float) ** 2).sum()))
    scores_a = np.array(scores)
    best = int(scores_a.argmax())
    upright = scores_a[int(np.argmin(np.abs(_ANGLES)))]
    return float(np.degrees(_ANGLES[best])), float(scores_a[best] / upright) if upright else 0.0


def find_rules(ink: np.ndarray, text_boxes: list[tuple[int, int, int, int]], dpi: int):
    """Horizontal rules: thin rows of ink at least ~1 inch long, outside text lines."""
    h, w = ink.shape
    min_len = max(int(0.8 * dpi), w // 12)
    counts = ink.sum(axis=1)
    covered = np.zeros(h, dtype=bool)
    for _, t, _, b in text_boxes:
        covered[max(t + 2, 0) : max(b - 2, 0)] = True
    rules = []
    y = 0
    while y < h:
        if counts[y] >= min_len and not covered[y]:
            y_start = y
            while y < h and counts[y] >= min_len:
                y += 1
            if y - y_start <= max(3, dpi // 60):
                row = ink[(y_start + y) // 2]
                padded = np.concatenate([[False], row, [False]])
                edges = np.flatnonzero(padded[1:] != padded[:-1])
                runs = [(a, b) for a, b in zip(edges[::2], edges[1::2]) if b - a >= min_len]
                for a, b in runs:
                    rules.append((int(a), int(b), (y_start + y) // 2))
        y += 1
    return rules


# --------------------------------------------------------------------------------------
# Voting between Tesseract and the existing layer
# --------------------------------------------------------------------------------------


def _match_layer_line(hl: _HLine, words: list[str], layer_lines):
    """The layer line that reads as this Tesseract line.

    Positions in a foreign OCR layer drift (whole lines can sit half a line low), so
    candidates come from a generous vertical window and the one whose text is most
    alike wins — and only if it is alike enough to be the same line.
    """
    x0, y0, x1, y1 = hl.bbox
    h = y1 - y0
    cy = (y0 + y1) / 2
    mine = " ".join(_norm(w) for w in words)
    best, best_ratio = None, 0.0
    for ll in layer_lines:
        lx0, ltop, lx1, lbot, toks = ll
        if not (ltop - 1.5 * h <= cy <= lbot + 1.5 * h):
            continue
        if min(x1, lx1) - max(x0, lx0) <= 0.3 * min(x1 - x0, lx1 - lx0):
            continue
        ratio = difflib.SequenceMatcher(None, mine, " ".join(_norm(t) for t in toks),
                                        autojunk=False).ratio()
        if ratio > best_ratio:
            best, best_ratio = ll, ratio
    return best if best_ratio >= 0.6 else None


def _choose(tess: list[str], layer: list[str], lex: Lexicon) -> list[str]:
    """Pick between two readings of the same stretch of text."""
    if not layer:
        # Tesseract-only tokens: keep words, drop lone symbols ('©', '~').
        return [t for t in tess if lex.valid(t) and not _GARBAGE.search(t) or re.search(r"[A-Za-z]{2}", t)]
    if not tess:
        return []
    a, b = "".join(map(_norm, tess)), "".join(map(_norm, layer))
    if difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() < 0.5:
        return tess  # not two readings of the same thing
    va = all(lex.valid(t) for t in tess)
    vb = all(lex.valid(t) for t in layer)
    ga = any(_GARBAGE.search(t) for t in tess)
    gb = any(_GARBAGE.search(t) for t in layer)
    if a.replace("'", "") == b.replace("'", ""):
        # Same letters; only spacing or quote style differ ('Anomniscient,' / 'An omniscient,').
        if not va and vb and len(layer) > len(tess):
            return layer
        if not va and vb and "'" in b and "'" not in a:
            return layer  # 'we ve' -> "we've"
        return tess
    if ga and not gb:
        return layer
    if gb and not ga:
        return tess
    if va and not vb:
        return tess
    if vb and not va:
        return layer
    if va and vb and a in b and len(b) > len(a):
        return layer  # Tesseract lost letters: 'fan' / 'if an'
    return tess


def _vote_word(info: dict, layer_tok: str, lex: Lexicon):
    """One Tesseract word against one layer word."""
    box = (info["bbox"][0], info["bbox"][2])
    if info["sub"]:
        # Geometry knows it is 'x₁'; the layer may still know the letter better ('5₁').
        m = re.match(r"^\d", info["text"])
        if m and layer_tok[:1].isalpha():
            info = dict(info, text=layer_tok[0] + info["text"][1:])
        return [(info["text"], info, box)]
    if info["sup_after"] or info["sup_before"]:
        m = re.fullmatch(r"(.*[A-Za-z][.,;:!?)]?)(\d{1,2})", layer_tok)
        if m and info["sup_after"] == "?":
            info["sup_after"] = m.group(2)
        core = m.group(1) if m else layer_tok
        choice = _choose([info["text"]], [core], lex) if info["text"] else []
        text = choice[0] if len(choice) == 1 else info["text"]
        return [(text, info, box)]
    choice = _choose([info["text"]], [layer_tok], lex)
    if len(choice) == 1:
        return [(choice[0], info, box)]
    return [(t, dict(info, sup_after=None) if k < len(choice) - 1 else info, b)
            for k, (t, b) in enumerate(zip(choice, _split_box(box[0], box[1], choice)))]


def _split_box(x0: float, x1: float, texts: list[str]) -> list[tuple[float, float]]:
    total = sum(len(t) for t in texts) + len(texts) - 1
    out, pos = [], x0
    for t in texts:
        w = (x1 - x0) * len(t) / max(total, 1)
        out.append((pos, pos + w))
        pos += w + (x1 - x0) / max(total, 1)
    return out


# --------------------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------------------


def read_scan_page(
    image,  # PIL image of the scanned area only
    origin: tuple[float, float],  # (x, y) in PDF points of the image's top-left corner
    dpi: int,
    layer_lines: list[tuple[float, float, float, float, list[str]]],  # pt, y-up
    lexicon: Lexicon,
    lang: str = "eng",
) -> ScanPage:
    import pytesseract

    gray = image.convert("L")
    ink = np.asarray(gray) < 140
    hocr = pytesseract.image_to_pdf_or_hocr(gray, extension="hocr", lang=lang).decode("utf-8")
    hlines = parse_hocr(hocr)
    s = dpi / 72.0
    ox, oy = origin

    # Layer lines into image pixel space.
    px_layer = [((x0 - ox) * s, (oy - y1) * s, (x1 - ox) * s, (oy - y0) * s, toks)
                for x0, y0, x1, y1, toks in layer_lines]

    page = ScanPage(used_layer=bool(px_layer))
    analysed: list[list[dict]] = []
    angles: list[float] = []
    for hl in hlines:
        row = []
        for w in hl.words:
            info = _analyse_word(ink, hl, w)
            ang, gain = word_slant(info["crop"])
            info.update(bbox=w["bbox"], angle=ang, gain=gain, raw=w["text"])
            if ang is not None and len(re.sub(r"\W", "", info["text"])) >= 3:
                angles.append(ang)
            row.append(info)
        analysed.append(row)
    page_angle = float(np.median(angles)) if angles else 0.0

    # Drop cap: the layer keeps the big initial as a line of its own ('T' beside
    # 'HIS paper is ...'); Tesseract usually skips it.
    initials = [ll for ll in px_layer if len(ll[4]) == 1 and re.fullmatch(r"[A-Z]", ll[4][0])]
    for hl, row in zip(hlines, analysed):
        first = row[0]["text"] if row else ""
        if not (first.isalpha() and first.isupper() and len(first) >= 2):
            continue
        x0, y0, _, y1 = hl.bbox
        for ll in initials:
            lx0, ltop, lx1, lbot, toks = ll
            if lx1 <= x0 + 5 and x0 - lx1 < 3 * (y1 - y0) and ltop <= y1 and lbot >= y0:
                row[0]["text"] = toks[0] + first
                initials.remove(ll)
                break

    # Words both readings agree on are vocabulary, whatever the dictionary says.
    matched = [(_match_layer_line(hl, [i["text"] for i in row], px_layer) if px_layer else None)
               for hl, row in zip(hlines, analysed)]
    for row, ll in zip(analysed, matched):
        if ll:
            for tok in set(i["text"] for i in row) & set(ll[4]):
                lexicon.add(tok)

    for hl, row, ll in zip(hlines, analysed, matched):
        words = _vote_line(row, ll[4] if ll else None, lexicon)
        out_words: list[ScanWord] = []
        for text, info, (bx0, bx1) in words:
            ang, gain = info["angle"], info["gain"]
            # Italic type leans 10-18 degrees; the stroke histogram must sharpen clearly
            # when sheared back (diagonal letters like 'w' and 'y' fake a weaker gain).
            italic = (
                ang is not None
                and 8 <= ang - page_angle <= 20
                and gain >= (1.12 if len(text) <= 2 else 1.1)
            )
            text = clean_quotes(text)
            if text == "/" and italic:
                text = "I"  # italic capital I, read as a slash
            if not out_words and re.fullmatch(r"[.·:'’,]{2,3}\.?", text):
                text, italic = "∴", False  # 'therefore' sign at the head of a line
            out_words.append(ScanWord(
                text=text,
                x0=ox + bx0 / s,
                x1=ox + bx1 / s,
                italic=italic,
                sup_before=info["sup_before"] if bx0 == info["bbox"][0] else None,
                sup_after=info["sup_after"] if bx1 == info["bbox"][2] else None,
            ))
        if not out_words:
            continue
        x0, y0, x1, y1 = hl.bbox
        base = hl.baseline_at((x0 + x1) / 2)
        xh = [v for i in row for v in i["xh"]]
        caps = [v for i in row for v in i["caps"]]
        if len(xh) >= 3:
            size_px = float(np.median(xh)) / 0.45
        elif caps:
            size_px = float(np.median(caps)) / 0.68
        else:
            size_px = hl.x_size / 0.7
        page.lines.append(ScanLine(
            words=out_words,
            x0=ox + x0 / s,
            x1=ox + x1 / s,
            top=oy - y0 / s,
            bottom=oy - y1 / s,
            baseline=oy - base / s,
            size=size_px / s,
        ))

    _attach_stray_figures(page.lines)
    page.rules = [(ox + a / s, ox + b / s, oy - y / s)
                  for a, b, y in find_rules(ink, [hl.bbox for hl in hlines], dpi)]
    return page


def _attach_stray_figures(lines: list[ScanLine]) -> None:
    """A footnote figure that Tesseract read as a tiny line of its own ('a.' floating
    above the end of a line) goes back onto that line as a reference."""
    if len(lines) < 3:
        return
    sizes = sorted(ln.size for ln in lines)
    body = sizes[len(sizes) // 2]
    for tiny in list(lines):
        if len(tiny.words) != 1 or len(tiny.words[0].text) > 3:
            continue
        if tiny.top - tiny.bottom > 0.75 * body:
            continue
        for host in lines:
            if host is tiny or not host.words:
                continue
            level = host.bottom <= tiny.bottom <= host.top
            near = -0.2 * body <= tiny.x0 - host.x1 <= 1.0 * body
            if level and near and tiny.bottom > host.baseline + 0.15 * host.size:
                text = tiny.words[0].text
                host.words[-1].sup_after = re.sub(r"\D", "", text) or "?"
                lines.remove(tiny)
                break


def _vote_line(row: list[dict], layer_tokens: list[str] | None, lex: Lexicon):
    """Final words of one line: [(text, analysis, (x0, x1) px)]."""
    tess = [i["text"] for i in row]
    if not layer_tokens:
        return [(i["text"], i, (i["bbox"][0], i["bbox"][2])) for i in row if i["text"]]

    layer = list(layer_tokens)
    # Drop cap: the layer has the big initial ('T HIS paper') that Tesseract skipped.
    if (len(layer) >= 2 and re.fullmatch(r"[A-Z]", layer[0]) and tess
            and tess[0].isupper() and len(tess[0]) >= 2 and _norm(layer[1]) == _norm(tess[0])):
        row[0]["text"] = layer[0] + row[0]["text"]
        tess[0] = row[0]["text"]
        layer = [layer[0] + layer[1]] + layer[2:]

    sm = difflib.SequenceMatcher(a=[_norm(t) for t in tess], b=[_norm(t) for t in layer], autojunk=False)
    out = []
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        infos = row[a1:a2]
        if op == "equal":
            out.extend((i["text"], i, (i["bbox"][0], i["bbox"][2])) for i in infos)
            continue
        if op == "insert":
            continue  # layer-only words have no reliable position; Tesseract saw nothing
        span_layer = layer[b1:b2]
        # Layer digits name a footnote reference that geometry found but couldn't read.
        for i in infos:
            if i["sup_after"] == "?":
                for lt in span_layer:
                    m = re.search(r"[A-Za-z][.,;:!?)]?(\d{1,2})$", lt)
                    if m:
                        i["sup_after"] = m.group(1)
        if len(infos) == len(span_layer) and len(infos) > 1:
            # Word for word: decide each pair on its own.
            for i, lt in zip(infos, span_layer):
                out.extend(_vote_word(i, lt, lex))
            continue
        if any(i["sub"] or i["sup_after"] or i["sup_before"] for i in infos):
            if len(infos) == 1 and len(span_layer) == 1:
                out.extend(_vote_word(infos[0], span_layer[0], lex))
            else:
                out.extend((i["text"], i, (i["bbox"][0], i["bbox"][2])) for i in infos)
            continue
        if span_layer:
            # Strip a glued reference figure before comparing ('evil.1' vs 'evil.').
            cleaned = []
            for lt in span_layer:
                m = re.fullmatch(r"(.*[A-Za-z][.,;:!?)])(\d{1,2})", lt)
                if m and infos:
                    infos[-1]["sup_after"] = infos[-1]["sup_after"] or m.group(2)
                    lt = m.group(1)
                cleaned.append(lt)
            span_layer = cleaned
        choice = _choose([i["text"] for i in infos], span_layer, lex)
        if choice == [i["text"] for i in infos]:
            out.extend((i["text"], i, (i["bbox"][0], i["bbox"][2])) for i in infos)
        elif infos:
            x0, x1 = infos[0]["bbox"][0], infos[-1]["bbox"][2]
            boxes = _split_box(x0, x1, choice)
            for k, (t, box) in enumerate(zip(choice, boxes)):
                # Each new word borrows the analysis of the Tesseract word under it.
                mid = (box[0] + box[1]) / 2
                src = min(infos, key=lambda i: abs((i["bbox"][0] + i["bbox"][2]) / 2 - mid))
                src = dict(src)
                if k < len(choice) - 1:
                    src["sup_after"] = None
                if k > 0:
                    src["sup_before"] = None
                out.append((t, src, (int(box[0]) if k else x0, int(box[1]) if k < len(choice) - 1 else x1)))
    return out
