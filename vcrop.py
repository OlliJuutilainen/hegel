#!/usr/bin/env python3
"""Crop the top and bottom margins of scanned book pages to their text block.

Each page image in IN_DIR is cut just above the first line of content and just below
the last, plus a little padding. The width is never touched, nothing is scaled and no
border is added. Running heads and page numbers count as content and are kept.

Usage:
    python vcrop.py IN_DIR OUT_DIR
    python vcrop.py scans/ cropped/ --pad 0.02 --min-gain 0.03 --skip skip.txt
    python vcrop.py scans/ cropped/ --debug debug/     # see what was detected

The originals are never changed: every page is written to OUT_DIR under the same
name and format (JPEG at quality 95). A page is copied as it is when there is little
to gain (already cropped), when it is listed in --skip, or when no text block could
be found. OUT_DIR/vcrop_log.csv records what was done to each page.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

EXTENSIONS = {".jpg", ".jpeg", ".png"}
JPEG_QUALITY = 95

MIN_AREA = 0.0005  # of the page: smaller regions are dust and specks
EDGE_MAX_HEIGHT = 0.02  # of the page height: low regions touching the edge are scan border
MIN_CONTENT_HEIGHT = 0.40  # of the page height: a smaller text block is a failed detection
DILATE_WIDTH = 0.02  # of the page width: joins the letters and words of a line
LINE_HEIGHT_SHARE = 0.5  # a small region at least this tall (vs. a typical line) is text

DEBUG_HEIGHT = 1200
RED, GREEN, BLUE = (0, 0, 255), (0, 170, 0), (255, 0, 0)


@dataclass
class Detection:
    top: int | None = None  # first content row
    bottom: int | None = None  # one past the last content row
    kept: list[tuple[int, int, int, int]] = field(default_factory=list)  # x, y, w, h
    rejected: list[tuple[int, int, int, int]] = field(default_factory=list)


def natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def detect_text_block(gray: np.ndarray) -> Detection:
    """Find the rows the page's content spans."""
    h, w = gray.shape
    block = max(15, (min(h, w) // 30) | 1)
    ink = cv2.adaptiveThreshold(
        cv2.medianBlur(gray, 3), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, 15
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(w * DILATE_WIDTH)), 1))
    lines = cv2.dilate(ink, kernel)

    _, _, stats, _ = cv2.connectedComponentsWithStats(lines, connectivity=8)
    regions = []
    for x, y, bw, bh, area in stats[1:]:
        touches_edge = x == 0 or y == 0 or x + bw >= w or y + bh >= h
        regions.append(((int(x), int(y), int(bw), int(bh)), area >= MIN_AREA * h * w, touches_edge))

    # A lone page number is smaller than MIN_AREA, but as tall as a line of text;
    # dust and specks are not. So a small region stays if it is line-tall.
    line_heights = [box[3] for box, large, edge in regions if large and not edge]
    min_text_height = LINE_HEIGHT_SHARE * float(np.median(line_heights)) if line_heights else np.inf

    det = Detection()
    for box, large, touches_edge in regions:
        bh = box[3]
        text_sized = large or bh >= min_text_height
        if not text_sized or (touches_edge and bh < EDGE_MAX_HEIGHT * h):
            det.rejected.append(box)
        else:
            det.kept.append(box)
    if det.kept:
        det.top = min(y for _, y, _, _ in det.kept)
        det.bottom = max(y + bh for _, y, _, bh in det.kept)
    return det


def write_debug(path: Path, img: np.ndarray, det: Detection, cut: tuple[int, int] | None, action: str) -> None:
    h, w = img.shape[:2]
    scale = min(1.0, DEBUG_HEIGHT / h)
    view = cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    if view.dtype != np.uint8:
        view = cv2.convertScaleAbs(view, alpha=255.0 / 65535.0)
    if view.ndim == 2:
        view = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)

    def rect(box, color, thickness):
        x, y, bw, bh = (round(v * scale) for v in box)
        cv2.rectangle(view, (x, y), (x + max(bw, 1), y + max(bh, 1)), color, thickness)

    for box in det.rejected:
        rect(box, RED, 1)
    for box in det.kept:
        rect(box, GREEN, 1)
    if det.top is not None:
        x0 = min(x for x, _, _, _ in det.kept)
        x1 = max(x + bw for x, _, bw, _ in det.kept)
        rect((x0, det.top, x1 - x0, det.bottom - det.top), GREEN, 3)
    if cut is not None:
        for y in cut:
            yy = min(view.shape[0] - 1, round(y * scale))
            cv2.line(view, (0, yy), (view.shape[1] - 1, yy), BLUE, 2)
    cv2.putText(view, action, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, BLUE, 2, cv2.LINE_AA)
    params = [cv2.IMWRITE_JPEG_QUALITY, 85] if path.suffix.lower() in {".jpg", ".jpeg"} else []
    cv2.imwrite(str(path), view, params)


def process(src: Path, dst: Path, pad: float, min_gain: float, debug_dir: Path | None) -> tuple[str, int, int, int]:
    """Crop one page. Returns action, height, top_cut, bottom_cut."""
    img = cv2.imread(str(src), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
    if img is None:
        shutil.copy2(src, dst)
        return "failed", 0, 0, 0
    h = img.shape[0]

    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:
        gray = cv2.convertScaleAbs(gray, alpha=255.0 / 65535.0)
    det = detect_text_block(gray)

    cut = None
    if det.top is None or det.bottom - det.top < MIN_CONTENT_HEIGHT * h:
        action, top_cut, bottom_cut = "failed", 0, 0
    else:
        new_top = max(0, det.top - round(pad * h))
        new_bottom = min(h, det.bottom + round(pad * h))
        top_cut, bottom_cut = new_top, h - new_bottom
        cut = (new_top, new_bottom)
        action = "unchanged" if top_cut + bottom_cut < min_gain * h else "cropped"

    if action == "cropped":
        params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY] if src.suffix.lower() in {".jpg", ".jpeg"} else []
        if not cv2.imwrite(str(dst), img[new_top:new_bottom], params):
            raise OSError(f"could not write {dst}")
    else:
        shutil.copy2(src, dst)
        top_cut = bottom_cut = 0

    if debug_dir is not None:
        write_debug(debug_dir / src.name, img, det, cut, action)
    return action, h, top_cut, bottom_cut


def read_skip_list(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            names.add(Path(line).name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("in_dir", type=Path, help="Folder of page images (.jpg/.jpeg/.png)")
    parser.add_argument("out_dir", type=Path, help="Folder for the cropped pages and vcrop_log.csv")
    parser.add_argument(
        "--pad", type=float, default=0.02, help="Margin kept around the text block, as a fraction of the page height (default: 0.02)"
    )
    parser.add_argument(
        "--min-gain",
        type=float,
        default=0.03,
        help="Copy the page unchanged when less than this fraction of its height would be removed (default: 0.03)",
    )
    parser.add_argument("--skip", type=Path, help="Text file of page file names to copy as they are, one per line")
    parser.add_argument("--debug", type=Path, metavar="DEBUG_DIR", help="Write a small annotated copy of each page here")
    args = parser.parse_args()

    if not args.in_dir.is_dir():
        parser.error(f"{args.in_dir} is not a folder")
    in_dir = args.in_dir.resolve()
    for name, d in (("OUT_DIR", args.out_dir), ("DEBUG_DIR", args.debug)):
        if d is not None and d.resolve() == in_dir:
            parser.error(f"{name} must not be IN_DIR: the originals are never overwritten")
    skip = read_skip_list(args.skip) if args.skip else set()

    pages = sorted(
        (p for p in in_dir.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS),
        key=lambda p: natural_key(p.name),
    )
    if not pages:
        print(f"No .jpg/.jpeg/.png files in {args.in_dir}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.debug:
        args.debug.mkdir(parents=True, exist_ok=True)

    counts: Counter[str] = Counter()
    with open(args.out_dir / "vcrop_log.csv", "w", newline="", encoding="utf-8") as log_file:
        log = csv.writer(log_file)
        log.writerow(["file", "action", "height", "top_cut", "bottom_cut"])
        for page in pages:
            dst = args.out_dir / page.name
            if page.name in skip:
                shutil.copy2(page, dst)
                img = cv2.imread(str(page), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
                row = ("skipped", 0 if img is None else img.shape[0], 0, 0)
            else:
                row = process(page, dst, args.pad, args.min_gain, args.debug)
            log.writerow([page.name, *row])
            counts[row[0]] += 1
            action, _, top_cut, bottom_cut = row
            detail = f"  top -{top_cut}px, bottom -{bottom_cut}px" if action == "cropped" else ""
            print(f"{page.name}: {action}{detail}")

    print(f"\n{len(pages)} pages: " + ", ".join(
        f"{counts[a]} {a}" for a in ("cropped", "unchanged", "skipped", "failed")
    ))
    print(f"Log: {args.out_dir / 'vcrop_log.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
