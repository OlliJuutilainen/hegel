"""Prepare a scanned page for OCR: split two-page spreads, clear copier shadows, straighten.

A photocopied book rarely comes out like a library scan. One sheet often holds two
book pages side by side, each a degree or two off the horizontal, with the book's edge
and the gutter printed as black bands and dithered grey shadow. Tesseract reads the
shadow as letters ('if | Curley', 'God ©') and loses whole lines on a tilted page.

prepare_scan() turns one rendered page image into one or two Regions:

  1. spread  — a landscape sheet with a clear gap (or a dark band) near the middle
               and text on both sides is cut there into two pages;
  2. shadows — dark bands, dither and lines along the edge that reach in from a
               region's edges are whitened, up to the first block of print;
  3. skew    — each region is turned level, by the angle at which its text lines
               project most sharply onto the vertical axis.

Every step leaves a clean, level, single-page scan unchanged: no split without a gap
and text on both sides, no whitening without shadow at the edge, no rotation under
0.1°. Each Region remembers where it came from, so OCR coordinates can be mapped back
onto the original image (to_source).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

INK = 140  # grey level below which a pixel is ink (as in ocr.scanpage)
MIN_SKEW = 0.1  # degrees; anything less is left alone


@dataclass
class Region:
    image: Image.Image  # cleaned and level: what OCR reads
    plain: Image.Image  # level but not cleaned: what a reader is shown
    x0: int  # left edge of this region in the source image (px)
    angle: float  # rotation applied, degrees counter-clockwise (PIL's convention)

    def to_source(self, x: float, y: float) -> tuple[float, float]:
        """A point of this region's image, in the source image's pixels."""
        if self.angle:
            w, h = self.image.size
            cx, cy = w / 2, h / 2
            t = math.radians(self.angle)
            dx, dy = x - cx, y - cy
            x = cx + dx * math.cos(t) - dy * math.sin(t)
            y = cy + dx * math.sin(t) + dy * math.cos(t)
        return x + self.x0, y

    def from_source(self, x: float, y: float) -> tuple[float, float]:
        """A point of the source image, in this region's pixels."""
        x -= self.x0
        if self.angle:
            w, h = self.image.size
            cx, cy = w / 2, h / 2
            t = math.radians(self.angle)
            dx, dy = x - cx, y - cy
            x = cx + dx * math.cos(t) + dy * math.sin(t)
            y = cy - dx * math.sin(t) + dy * math.cos(t)
        return x, y


def prepare_scan(
    image: Image.Image, dpi: int, *, split: bool = True, clean: bool = True,
    deskew: bool = True,
) -> list[Region]:
    """One page image -> its book pages (one or two), each cleaned and level."""
    gray = np.asarray(image.convert("L"))
    cut = find_gutter(gray < INK, dpi) if split else None
    slices = [(0, gray.shape[1])] if cut is None else [(0, cut), (cut, gray.shape[1])]
    regions = []
    for x0, x1 in slices:
        part = gray[:, x0:x1]
        cleaned = clear_edge_shadows(part, dpi) if clean else part
        angle = skew_angle(cleaned < INK, dpi) if deskew else 0.0
        if abs(angle) < MIN_SKEW:
            angle = 0.0
        if cut is None and cleaned is part and not angle:
            return [Region(image, image, 0, 0.0)]  # nothing to do: the page as it came
        regions.append(Region(_rotate(cleaned, angle), _rotate(part, angle), x0, angle))
    return regions


def _rotate(a: np.ndarray, angle: float) -> Image.Image:
    im = Image.fromarray(a)
    if not angle:
        return im
    return im.rotate(angle, resample=Image.BICUBIC, fillcolor=255)


def _smooth(v: np.ndarray, n: int) -> np.ndarray:
    n = max(1, n)
    return np.convolve(v, np.ones(n) / n, "same")


# ------------------------------------------------------------------------------------
# Spreads
# ------------------------------------------------------------------------------------


def find_gutter(ink: np.ndarray, dpi: int) -> int | None:
    """Column where a two-page spread divides, or None for a single page.

    Only a landscape sheet can be a spread. The gutter is either an empty gap between
    the two text blocks or the dark band of the book's fold, somewhere in the middle
    30% of the sheet, with text on both sides of it.
    """
    h, w = ink.shape
    if w < 1.15 * h:
        return None
    prof = _smooth(ink[int(0.1 * h):int(0.9 * h)].mean(axis=0), dpi // 12)
    texty = prof[(prof > 0.02) & (prof < 0.5)]
    if texty.size < 0.2 * w:
        return None
    level = float(np.median(texty))
    lo, hi = int(0.35 * w), int(0.65 * w)
    zone = prof[lo:hi]

    def text_on_both_sides(cut: int) -> bool:
        margin = dpi // 6
        left = prof[int(0.05 * w):max(int(0.05 * w) + 1, cut - margin)]
        right = prof[min(cut + margin, int(0.95 * w) - 1):int(0.95 * w)]
        return (np.mean((left > 0.3 * level) & (left < 0.5)) > 0.3
                and np.mean((right > 0.3 * level) & (right < 0.5)) > 0.3)

    # The widest empty gap, at least a tenth of an inch. (The fold's grey shadow may
    # split the gap in two; either half will do, the shadow is cleared afterwards.)
    low = np.concatenate(([False], zone < 0.25 * level, [False])).astype(np.int8)
    starts = np.flatnonzero(np.diff(low) == 1)
    ends = np.flatnonzero(np.diff(low) == -1)
    if starts.size:
        k = int(np.argmax(ends - starts))
        if ends[k] - starts[k] >= dpi / 10:
            cut = lo + int((starts[k] + ends[k]) / 2)
            if text_on_both_sides(cut):
                return cut
    # The dark band of the fold.
    dark = np.flatnonzero(zone > 0.6)
    if dark.size and dark[-1] - dark[0] < 0.1 * w:
        cut = lo + int((dark[0] + dark[-1]) / 2)
        if text_on_both_sides(cut):
            return cut
    return None


# ------------------------------------------------------------------------------------
# Shadows at the edges
# ------------------------------------------------------------------------------------


EMPTY, PRINT, DARK, DITHER, VLINE, HLINE = range(6)


def _runs_at_least(m: np.ndarray, n: int) -> np.ndarray:
    """Cells of boolean `m` lying in a run of at least `n` along axis 0."""
    out = np.zeros_like(m)
    for c in range(m.shape[1]):
        r = 0
        while r < m.shape[0]:
            if m[r, c]:
                e = r
                while e < m.shape[0] and m[e, c]:
                    e += 1
                if e - r >= n:
                    out[r:e, c] = True
                r = e
            else:
                r += 1
    return out


def _classify_blocks(ink: np.ndarray, bs: int) -> np.ndarray:
    """Classify each bs×bs block: EMPTY, PRINT, DARK band, DITHER, VLINE or HLINE.

    Print and dither differ in texture: a letter's strokes are several pixels thick,
    so a row or column crosses an ink edge about once per three ink pixels; the dots
    of a dithered shadow are one or two pixels across, so nearly every ink pixel is an
    edge (measured on a 300 dpi copier scan: print 0.3–0.5, shadow 1.7–2.0).

    The edge of the book or of the copier glass prints as a line along the sheet's
    edge. A line has print's texture, but fills its block in one direction and runs
    on for at least three blocks — taller and wider than any letter.
    """
    h, w = ink.shape
    nh, nw = h // bs, w // bs
    a = ink[: nh * bs, : nw * bs]
    tx = np.zeros_like(a, dtype=np.uint8)
    ty = np.zeros_like(a, dtype=np.uint8)
    tx[:, 1:] = a[:, 1:] != a[:, :-1]
    ty[1:, :] = a[1:, :] != a[:-1, :]

    def per_block(m: np.ndarray) -> np.ndarray:
        return m.reshape(nh, bs, nw, bs).sum(axis=(1, 3)).astype(float)

    n = per_block(a)
    edges = (per_block(tx) + per_block(ty)) / 2
    blocks = a.reshape(nh, bs, nw, bs)
    rows_inked = blocks.any(axis=3).sum(axis=1)
    cols_inked = blocks.any(axis=1).sum(axis=2)
    frac = n / (bs * bs)
    ratio = edges / np.maximum(n, 1)
    cls = np.full((nh, nw), PRINT, dtype=np.uint8)
    cls[frac < 0.004] = EMPTY
    printed = cls == PRINT
    vline = printed & (rows_inked >= 0.9 * bs) & (cols_inked <= 0.6 * bs)
    hline = printed & (cols_inked >= 0.9 * bs) & (rows_inked <= 0.6 * bs)
    cls[_runs_at_least(vline, 3)] = VLINE
    cls[_runs_at_least(hline.T, 3).T] = HLINE
    cls[(frac >= 0.004) & (ratio >= 1.0)] = DITHER
    cls[frac > 0.6] = DARK
    return cls


def _walk(row: np.ndarray, reach: int, line: int) -> list[int]:
    """Blocks of shadow reached from index 0 of `row` before the first print block.

    Shadow is a dark band, dither, or a `line` running along the edge. It has to
    start within `reach` blocks of the edge; empty blocks inside it are passed over
    (a dither thins out towards the page). A mark in the outermost two blocks, or a
    short line along the shadow's inner rim, counts as shadow when nothing but white
    follows it for three blocks. The
    shadow block right next to real print is kept, so a letter that touches it is
    never cut.
    """
    across = HLINE if line == VLINE else VLINE  # a line across the walk is print
    hits: list[int] = []
    for i, c in enumerate(row):
        if c == EMPTY:
            continue
        if c in (DARK, DITHER, line):
            if not hits and i >= reach:
                break
            hits.append(i)
            continue
        # print (or a line across the walk)
        ahead = row[i + 1:i + 4]
        alone = len(ahead) == 3 and not np.isin(ahead, (PRINT, across)).any()
        if alone and (i <= 1 or (hits and hits[-1] == i - 1)):
            hits.append(i)  # debris at the very edge, or the shadow's inner rim
            continue
        if hits and hits[-1] == i - 1:
            hits.pop()
        break
    return hits


def clear_edge_shadows(gray: np.ndarray, dpi: int) -> np.ndarray:
    """Whiten dark bands, dithered shadow and edge lines that reach in from the
    image's edges."""
    bs = max(8, round(24 * dpi / 300))
    cls = _classify_blocks(gray < INK, bs)
    nh, nw = cls.shape
    noise = np.zeros_like(cls, dtype=bool)
    reach_x, reach_y = max(2, int(0.08 * nw)), max(2, int(0.08 * nh))
    for r in range(nh):
        for i in _walk(cls[r], reach_x, VLINE):
            noise[r, i] = True
        for i in _walk(cls[r, ::-1], reach_x, VLINE):
            noise[r, nw - 1 - i] = True
    for c in range(nw):
        for i in _walk(cls[:, c], reach_y, HLINE):
            noise[i, c] = True
        for i in _walk(cls[::-1, c], reach_y, HLINE):
            noise[nh - 1 - i, c] = True
    if not noise.any():
        return gray
    out = gray.copy()
    mask = np.kron(noise, np.ones((bs, bs), dtype=bool))
    out[: mask.shape[0], : mask.shape[1]][mask] = 255
    # The strip past the last whole block, if it belongs to a shadow beside it.
    if noise[:, -1].any():
        rows = np.repeat(noise[:, -1], bs)
        out[: rows.size, nw * bs:][rows] = 255
    if noise[-1, :].any():
        cols = np.repeat(noise[-1, :], bs)
        out[nh * bs:, : cols.size][:, cols] = 255
    return out


# ------------------------------------------------------------------------------------
# Skew
# ------------------------------------------------------------------------------------


def skew_angle(ink: np.ndarray, dpi: int) -> float:
    """Rotation (degrees, PIL's counter-clockwise) that levels the text lines.

    Lines of print, projected onto the vertical axis at their own slope, give the
    sharpest profile: tall peaks for the lines, empty valleys between them. The angle
    is searched within ±5°, coarse then fine, on a thinned set of ink pixels.
    """
    ys, xs = np.nonzero(ink)
    if ys.size < 500:
        return 0.0
    step = max(1, ys.size // 200_000)
    ys, xs = ys[::step].astype(float), xs[::step].astype(float)
    xs -= ink.shape[1] / 2
    bin_h = max(1.0, dpi / 150)

    def score(deg: float) -> float:
        t = math.radians(deg)
        # A point's height once the image is turned by `deg` counter-clockwise.
        y = ys * math.cos(t) - xs * math.sin(t)
        hist = np.bincount(((y - y.min()) / bin_h).astype(int))
        return float((hist.astype(float) ** 2).sum())

    best = max(np.arange(-5.0, 5.01, 0.1), key=score)
    best = max(np.arange(best - 0.1, best + 0.101, 0.01), key=score)
    return round(float(best), 2)
