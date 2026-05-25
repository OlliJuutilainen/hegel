#!/usr/bin/env python3
"""Re-OCR a scanned PDF with Claude vision and bake a clean invisible text layer onto it.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python run_ocr.py input.pdf output.pdf
"""

from __future__ import annotations

import argparse
import os
import sys

from ocr.pipeline import Settings, run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to the scanned source PDF")
    parser.add_argument("output", help="Path for the OCR'd output PDF")
    parser.add_argument(
        "--model",
        default="claude-opus-4-7",
        help="Vision model (e.g. claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5)",
    )
    parser.add_argument("--dpi", type=int, default=200, help="Render resolution (default: 200)")
    parser.add_argument(
        "--max-tokens", type=int, default=8000, help="Max output tokens per page"
    )
    parser.add_argument(
        "--image-format", choices=["PNG", "JPEG"], default="PNG", help="Upload format"
    )
    parser.add_argument(
        "--font-file", default=None, help="Path to a Unicode TTF for the text layer"
    )
    parser.add_argument(
        "--text-out", default=None, help="Optional path to also dump the plain transcription"
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 1
    if not os.path.exists(args.input):
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    settings = Settings(
        model=args.model,
        dpi=args.dpi,
        max_tokens=args.max_tokens,
        image_format=args.image_format,
        font_file=args.font_file,
    )
    failures = run(args.input, args.output, settings, text_sidecar=args.text_out)

    if failures:
        print(f"\nDone, but {len(failures)} page(s) failed:", file=sys.stderr)
        for page_no, err in failures:
            print(f"  page {page_no}: {err}", file=sys.stderr)
        return 2
    print(f"\nDone. Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
