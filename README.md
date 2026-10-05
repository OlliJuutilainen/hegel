# hegel
Makes Great PDFs – just as Hegel does!

## Which tool?

| You have | Run | You get |
|---|---|---|
| a **scan** (page images, no usable text) | `run_tesseract.py` | the same PDF with an invisible, selectable OCR text layer |
| a **typeset PDF** (e-book style: text can be selected and copied) | `pdf_to_markdown.py` | a Markdown file with *italics*, headings and footnotes |

Never run `run_tesseract.py` on a typeset PDF: it rebuilds the pages from images and
throws the real text layer (and its italics) away.

## Setup

```
brew install tesseract poppler          # only needed for scans
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Scans → searchable PDF

```
python3 run_tesseract.py scan.pdf scan_OCR.pdf --drop-running-heads --text-out scan.txt
```

- Footnote reference markers are stripped from the body text and footnotes stay
  separate paragraphs; the running head (title + page number) is never glued onto
  the first paragraph. `--drop-running-heads` leaves it out of the text layer.
- `--text-out` also writes the cleaned paragraphs as plain text.
- `--dpi 400` can help with small footnote type.
- Italics are not detected (Tesseract does not report them).

## Typeset PDF → Markdown

```
python3 pdf_to_markdown.py book.pdf                          # writes book.md
python3 pdf_to_markdown.py book.pdf -o ote.md --pages 12-18 --page-markers
```

- Italic/bold from the fonts → `*italic*`, `**bold**`; larger type → `#` headings.
- Footnotes → `[^1]` references with the notes collected at the end.
- Running heads and page numbers are dropped; `--page-markers` puts the printed page
  number where each page begins, as `{p. 25}`, for citing.
- Line-end hyphenation is undone, keeping real compounds (`self-consciousness`,
  `Being-for-self`).
- DRM-protected PDFs can't be read; an OCR text layer has no real italics (the
  script warns about both).

## Other tools

`add_outline.py`, `find_headings.py`, `parse_printed_toc.py`: build a PDF outline
(bookmarks) from a table of contents. `migrate_annotations.py`: move highlights from
an old copy of a PDF onto the OCR'd one. `run_ocrmypdf.py`: OCR via OCRmyPDF instead.
