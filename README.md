# hegel
Makes Great PDFs – just as Hegel does!

## Which tool?

Choose by what you want to come out, not by what went in:

| You want | Run | Works on |
|---|---|---|
| a **Markdown file** (text with *italics*, headings, footnotes) | `pdf_to_markdown.py` | anything: e-books, JSTOR articles, library scans, photocopies |
| the **same PDF, searchable**: an invisible text layer to select, search and highlight | `run_tesseract.py` | scans and photocopies |
| **bookmarks** (a clickable table of contents) in a PDF | `add_outline.py` (+ helpers below) | a PDF with a text layer |
| your **old highlights** moved onto a new OCR'd copy | `migrate_annotations.py` | two PDFs of the same scan |
| **page images cropped** top and bottom to the text block | `vcrop.py` | a folder of .jpg/.png book scans |

`pdf_to_markdown.py` decides page by page how to read: from the text layer where the
PDF has real typesetting, by OCR where the page is a picture. So a JSTOR article, a
born-digital article and a teacher's photocopy without any text layer all go through
the same command.

Never run `run_tesseract.py` on a typeset PDF: it rebuilds the pages from images and
throws the real text layer (and its italics) away. You don't need it before
`pdf_to_markdown.py` either; that does its own OCR.

## Setup

```
brew install tesseract poppler          # only needed for scans (check first: tesseract --version)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Photocopies and rough scans

Both OCR tools prepare each scanned page before reading it (`ocr/preprocess.py`):

- **Two-page spreads**: a landscape sheet with a gap or the dark fold near its middle
  and text on both sides is read as two pages, left then right. Running heads, page
  numbers and footnotes then belong to the right page.
- **Copier shadows**: black bands and grey dithered shadow along the sheet's edges and
  at the fold, and lines along the edges, are ignored, so OCR doesn't read them as
  letters.
- **Tilt**: each page is levelled (up to ±5°) before OCR.

A clean, level, single-page scan passes through unchanged. `--no-cleanup` switches all
of this off. Not handled: curved lines next to a book's spine, and handwriting in the
margins (OCR reads pencil notes as stray words).

## PDF → Markdown

```
python3 pdf_to_markdown.py book.pdf                          # writes book.md
python3 pdf_to_markdown.py book.pdf -o ote.md --pages 12-18 --page-markers
```

Typeset pages (e-books, born-digital articles) are read from the text layer; scanned
pages (JSTOR, library scans, photocopies) are OCR'd with Tesseract and cross-checked
against any OCR layer the PDF already carries. Both kinds can sit in one file.

- Italic/bold → `*italic*`, `**bold**`: from the fonts on typeset pages, from the slant
  of the strokes on scans.
- Two-column pages are read column by column; titles and footnotes that span both
  columns stay in place.
- Larger type → `#` headings; centered section numerals (I, II, III) → `##`.
- Footnotes → `[^1]` references with the notes collected at the end, also when the
  font sets them as the characters `¹²³`; on scans the small raised figures are found
  in the image and matched to the notes in order.
- Letterspaced capitals (`P A R T  I`) are closed up; a numbered section heading in
  bold body type (`1.1 Introduction`) becomes a heading one level below its chapter,
  and a smaller subtitle under a title is joined with a colon.
- Subscripts on scans → `s₁`; numbered premises → `1.` lists; block quotes → `>`.
- Running heads, page numbers, JSTOR "This content downloaded…" stamps and the
  citation footer on a chapter's first page (`… © Author 2024.` above `DOI: …`) are
  dropped; a cover picture in front of a typeset book is skipped; a JSTOR cover page becomes front matter (title, author, journal, volume,
  issue, date, pages, URL).
- Bibliographic data: a DOI printed on the first pages (the copyright page of a book,
  the first page of an article) is looked up in Crossref, and the record goes into the
  front matter: title, subtitle, authors, editors, date, journal / volume / issue or
  book title, pages, series, place, publisher (a Springer book's imprint, e.g. Palgrave
  Macmillan, from its copyright page), DOI and ISBN. The DOI is the only thing sent;
  `--no-lookup` keeps just the DOI. A DOI whose title isn't on the first pages (one
  cited in the text) is left out. Without a DOI, the PDF's own title and author are
  used if they look real.
- The front matter keys are the ones [Latomo](https://ollijuutilainen.github.io/luin/latomo.html)
  reads for a reference (`type: academic` selects a scholarly text there).
  `--page-markers` puts the printed page number where each page begins, as `{p. 25}`
  (or `{p. pdf 7b}`, the PDF page and side, when no number could be read).
- Line-end hyphenation is undone, keeping real compounds (`self-consciousness`,
  `Being-for-self`, `so-called`).
- Scans take a few seconds per page (`--dpi 300` is faster, `--no-ocr` skips OCR and
  uses the PDF's own layer). The OCR vote uses the system word list
  (`/usr/share/dict/words` on macOS); `--dictionary` points to another one. A PDF
  without any text layer has nothing to vote with, so OCR misreadings stay.
- Output follows iA Writer's Markdown: metadata as plain `key: value` lines between
  `---`, footnotes as `[^1]`, unmatched superscripts as `^x^`, and characters iA gives
  a meaning (`~ ^ $ ==`, a leading `//`, `/` or `+++`) are backslash-escaped.
- DRM-protected PDFs can't be read.

## Scan → searchable PDF

```
python3 run_tesseract.py scan.pdf scan_OCR.pdf --drop-running-heads --text-out scan.txt
python3 run_tesseract.py copy.pdf copy_OCR.pdf --split-spreads    # one book page per page
```

- The pages keep their own images; the text layer is placed over them. With
  `--split-spreads` each book page of a spread becomes a page of its own, levelled —
  easier to read on a small screen, but the page count no longer matches the source
  (so `migrate_annotations.py` can't pair the two).
- Footnote reference markers are stripped from the body text and footnotes stay
  separate paragraphs; the running head (title + page number) is never glued onto
  the first paragraph. `--drop-running-heads` leaves it out of the text layer.
- `--text-out` also writes the cleaned paragraphs as plain text, one section per book
  page (`===== PAGE 3a =====` for the left page of the third sheet).
- `--dpi 400` can help with small footnote type.
- Italics are not detected (Tesseract does not report them); use `pdf_to_markdown.py`
  for those.

## Bookmarks and highlights

- `parse_printed_toc.py` drafts an `outline.md` from the book's printed table of
  contents; `find_headings.py` drafts one from type sizes when the printed contents
  are too coarse. Edit the draft by hand (see `outline.example.md`), then
  `add_outline.py outline.md book_OCR.pdf book_outlined.pdf` adds the bookmarks.
- `migrate_annotations.py old.pdf new_OCR.pdf merged.pdf` lifts highlights and notes
  from an old copy of the same scan onto the OCR'd one (same pages, same sizes).

## Crop page images to the text block

```
python3 -m venv ~/hegel/venv && source ~/hegel/venv/bin/activate
pip install "opencv-python<4.10" "numpy<2"     # macOS 11 on Intel: newest prebuilt wheels
python vcrop.py scans/ cropped/ --debug debug/
```

- Each page is cut just above its first and below its last line of content, plus
  `--pad` (default 0.02 of the page height). The width is never touched; nothing is
  scaled and no border is added. Running heads and page numbers are content and stay.
- Pages are written to OUT_DIR under the same names and format (JPEG quality 95); the
  originals are never changed. A page is copied as it is when less than `--min-gain`
  (default 0.03 of its height) would go (already cropped), when it is listed in
  `--skip skip.txt` (one file name per line), or when no text block taller than 40 %
  of the page is found.
- `OUT_DIR/vcrop_log.csv` lists `file,action,height,top_cut,bottom_cut` per page, with
  action `cropped`, `unchanged`, `skipped` or `failed`.
- `--debug DIR` writes a small copy of each page: regions taken for dust or scanner
  edge in red, the text block in green, the crop lines in blue. Look through it
  before using the crops.
- Dust and specks under 0.05 % of the page are ignored, but a small region as tall as
  a line of text (a lone page number) is kept. A pencil mark or a large blot in the
  margin counts as content, so that page is cropped less.
- On a newer Mac a plain `pip install opencv-python numpy` works.
