#!/usr/bin/env python3
"""Extract an outline.md draft from an EPUB's table of contents.

When you have both an EPUB and a scanned PDF of the same edition, the EPUB
already carries a clean, hierarchically-nested table of contents — no OCR,
no font-size heuristics, no roman-numeral fixups. This script pulls it out
and writes a markdown outline ready for add_outline.py to wire up against
the OCR'd PDF.

EPUB 3 (preferred): reads the navigation document (manifest item with
`properties="nav"`) and walks its <nav epub:type="toc"> <ol>/<li> tree.
EPUB 2 (fallback): reads the NCX file and walks the <navMap>/<navPoint>
tree. Nesting depth maps directly to '#' levels: top-level entries = '#',
nested entries = '##', and so on.

No `@ N` page hints are emitted: EPUB is reflowable and has no physical
page numbers, but add_outline.py searches forward from the last match by
default, which handles entries-in-reading-order without hints.

Usage:
    python epub_outline.py inwood.epub > outline.md
    python epub_outline.py inwood.epub outline.md
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET


# Namespaces we encounter in EPUB containers, OPF, EPUB 3 nav, and NCX.
_NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}


@dataclass
class TocItem:
    title: str
    level: int  # 1 = topmost


def _read_xml(zf: zipfile.ZipFile, path: str) -> ET.Element:
    with zf.open(path) as handle:
        return ET.parse(handle).getroot()


def _opf_path(zf: zipfile.ZipFile) -> str:
    root = _read_xml(zf, "META-INF/container.xml")
    rootfile = root.find("container:rootfiles/container:rootfile", _NS)
    if rootfile is None or "full-path" not in rootfile.attrib:
        raise ValueError("EPUB container.xml has no rootfile/full-path")
    return rootfile.attrib["full-path"]


def _normalize(text: str | None) -> str:
    """Collapse whitespace; turn an empty string into ''."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _walk_xhtml_list(ol_elem: ET.Element, level: int, out: list[TocItem]) -> None:
    """Walk an EPUB 3 nav <ol>/<li>/<a> tree, emitting TocItems by nesting depth."""
    for li in ol_elem.findall("xhtml:li", _NS):
        # ET.Element with no children is falsy by legacy quirk; check `is None`.
        a = li.find("xhtml:a", _NS)
        if a is None:
            a = li.find("xhtml:span", _NS)
        if a is not None:
            title = _normalize("".join(a.itertext()))
            if title:
                out.append(TocItem(title=title, level=level))
        for child_ol in li.findall("xhtml:ol", _NS):
            _walk_xhtml_list(child_ol, level + 1, out)


def _parse_epub3_nav(zf: zipfile.ZipFile, opf_root: ET.Element, opf_dir: str) -> list[TocItem] | None:
    """Find an EPUB 3 nav doc via OPF manifest and walk its toc <ol>."""
    manifest = opf_root.find("opf:manifest", _NS)
    if manifest is None:
        return None
    nav_href = None
    for item in manifest.findall("opf:item", _NS):
        props = item.attrib.get("properties", "")
        if "nav" in props.split():
            nav_href = item.attrib.get("href")
            break
    if not nav_href:
        return None
    nav_path = _resolve(opf_dir, nav_href).split("#", 1)[0]
    try:
        nav_root = _read_xml(zf, nav_path)
    except KeyError:
        return None
    # Find <nav epub:type="toc">; fall back to first <nav> if untagged.
    toc_nav = None
    for nav in nav_root.iter(f"{{{_NS['xhtml']}}}nav"):
        if nav.attrib.get(f"{{{_NS['epub']}}}type") == "toc":
            toc_nav = nav
            break
    if toc_nav is None:
        toc_nav = nav_root.find(f".//{{{_NS['xhtml']}}}nav")
    if toc_nav is None:
        return None
    ol = toc_nav.find("xhtml:ol", _NS)
    if ol is None:
        return None
    items: list[TocItem] = []
    _walk_xhtml_list(ol, 1, items)
    return items or None


def _walk_navpoints(parent: ET.Element, level: int, out: list[TocItem]) -> None:
    for nav_point in parent.findall("ncx:navPoint", _NS):
        label = nav_point.find("ncx:navLabel/ncx:text", _NS)
        title = _normalize(label.text if label is not None else "")
        if title:
            out.append(TocItem(title=title, level=level))
        _walk_navpoints(nav_point, level + 1, out)


def _parse_epub2_ncx(zf: zipfile.ZipFile, opf_root: ET.Element, opf_dir: str) -> list[TocItem] | None:
    """Find and walk the EPUB 2 NCX (navMap)."""
    manifest = opf_root.find("opf:manifest", _NS)
    spine = opf_root.find("opf:spine", _NS)
    if manifest is None:
        return None
    # Prefer the manifest item referenced by spine/@toc
    ncx_id = spine.attrib.get("toc") if spine is not None else None
    ncx_href = None
    if ncx_id:
        for item in manifest.findall("opf:item", _NS):
            if item.attrib.get("id") == ncx_id:
                ncx_href = item.attrib.get("href")
                break
    if not ncx_href:
        for item in manifest.findall("opf:item", _NS):
            if item.attrib.get("media-type") == "application/x-dtbncx+xml":
                ncx_href = item.attrib.get("href")
                break
    if not ncx_href:
        return None
    ncx_path = _resolve(opf_dir, ncx_href)
    try:
        ncx_root = _read_xml(zf, ncx_path)
    except KeyError:
        return None
    nav_map = ncx_root.find("ncx:navMap", _NS)
    if nav_map is None:
        return None
    items: list[TocItem] = []
    _walk_navpoints(nav_map, 1, items)
    return items or None


def _resolve(base_dir: str, href: str) -> str:
    """Resolve href relative to base_dir, normalizing '..' segments."""
    parts = (base_dir.split("/") if base_dir else []) + href.split("/")
    out: list[str] = []
    for p in parts:
        if p in ("", "."):
            continue
        if p == "..":
            if out:
                out.pop()
        else:
            out.append(p)
    return "/".join(out)


def extract(epub_path: str) -> list[TocItem]:
    with zipfile.ZipFile(epub_path) as zf:
        opf_path = _opf_path(zf)
        opf_dir = "/".join(opf_path.split("/")[:-1])
        opf_root = _read_xml(zf, opf_path)
        items = _parse_epub3_nav(zf, opf_root, opf_dir)
        if items:
            return items
        items = _parse_epub2_ncx(zf, opf_root, opf_dir)
        if items:
            return items
    raise ValueError(
        f"No navigation document or NCX found in {epub_path}. "
        f"The EPUB may be malformed or lack a TOC."
    )


def render(items: list[TocItem]) -> str:
    out = [
        "// Outline extracted from EPUB navigation by epub_outline.py.",
        "// Hierarchy is exact (from the EPUB itself), not heuristic.",
        "// Hand off to add_outline.py to wire titles to PDF positions.",
        "",
    ]
    for item in items:
        out.append(f"{'#' * item.level} {item.title}")
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to the EPUB file")
    parser.add_argument(
        "output",
        nargs="?",
        help="Optional output path; writes to stdout if omitted.",
    )
    args = parser.parse_args()
    items = extract(args.input)
    text = render(items)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"Wrote {len(items)} entries to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
