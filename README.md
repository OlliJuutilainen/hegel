# hegel
Makes Great PDFs – just as Hegel does!

## Which tool?

| You have | Run | You get |
|---|---|---|
| a **scan** (page images, no usable text) | `run_tesseract.py` | the same PDF with an invisible, selectable OCR text layer |
| a **typeset PDF** (e-book style: text can be selected and copied) | `pdf_to_markdown.py` | a Markdown file with *italics*, headings and footnotes |
| a **scanned article or book** you want as text (JSTOR etc.) | `pdf_to_markdown.py` | the same, read by OCR; italics from the image |

Never run `run_tesseract.py` on a typeset PDF: it rebuilds the pages from images and
throws the real text layer (and its italics) away.

## Setup

```
brew install tesseract poppler          # only needed for scans (check first: tesseract --version)
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

## Any PDF → Markdown

```
python3 pdf_to_markdown.py book.pdf                          # writes book.md
python3 pdf_to_markdown.py book.pdf -o ote.md --pages 12-18 --page-markers
```

Typeset pages (e-books, born-digital articles) are read from the text layer; scanned
pages (JSTOR, library scans) are OCR'd with Tesseract and cross-checked against any
OCR layer the PDF already carries. Both kinds can sit in one file.

- Italic/bold → `*italic*`, `**bold**`: from the fonts on typeset pages, from the slant
  of the strokes on scans.
- Two-column pages are read column by column; titles and footnotes that span both
  columns stay in place.
- Larger type → `#` headings; centered section numerals (I, II, III) → `##`.
- Footnotes → `[^1]` references with the notes collected at the end; on scans the
  small raised figures are found in the image and matched to the notes in order.
- Subscripts on scans → `s₁`; numbered premises → `1.` lists; block quotes → `>`.
- Running heads, page numbers and JSTOR "This content downloaded…" stamps are
  dropped; a JSTOR cover page becomes YAML front matter (title, author, source, URL).
  `--page-markers` puts the printed page number where each page begins, as `{p. 25}`.
- Line-end hyphenation is undone, keeping real compounds (`self-consciousness`,
  `Being-for-self`, `so-called`).
- Scans take a few seconds per page (`--dpi 300` is faster, `--no-ocr` skips OCR and
  uses the PDF's own layer). The OCR vote uses the system word list
  (`/usr/share/dict/words` on macOS); `--dictionary` points to another one.
- Output follows iA Writer's Markdown: metadata as plain `key: value` lines between
  `---`, footnotes as `[^1]`, unmatched superscripts as `^x^`, and characters iA gives
  a meaning (`~ ^ $ ==`, a leading `//`, `/` or `+++`) are backslash-escaped.
- DRM-protected PDFs can't be read.

## Other tools

`add_outline.py`, `find_headings.py`, `parse_printed_toc.py`: build a PDF outline
(bookmarks) from a table of contents. `migrate_annotations.py`: move highlights from
an old copy of a PDF onto the OCR'd one. `run_ocrmypdf.py`: OCR via OCRmyPDF instead.
