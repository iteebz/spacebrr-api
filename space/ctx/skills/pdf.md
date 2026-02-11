---
description: Extract, OCR, merge, split, compress PDFs from CLI
---

# PDF

## Install

```bash
brew install poppler qpdf ghostscript ocrmypdf tesseract
```

## Inspect

```bash
pdfinfo file.pdf          # metadata, page count
pdffonts file.pdf         # embedded fonts (empty = scanned)
pdftotext file.pdf - | head   # test if text extracts
```

## Extract

```bash
pdftotext -layout file.pdf -              # text to stdout
pdftotext -layout file.pdf out.txt        # text to file
pdftoppm -png -r 200 file.pdf out/page    # pages as images
```

## OCR (scanned PDFs)

```bash
ocrmypdf --deskew --rotate-pages in.pdf out.pdf
ocrmypdf -l eng+fra in.pdf out.pdf        # multi-language
```

## Structural Edits

```bash
qpdf --empty --pages a.pdf b.pdf -- merged.pdf       # merge
qpdf in.pdf --pages . 1-3 -- part.pdf                # extract pages
qpdf in.pdf --rotate=+90:1-z -- rotated.pdf          # rotate all
```

## Compress

```bash
gs -sDEVICE=pdfwrite -dPDFSETTINGS=/screen -dNOPAUSE -dQUIET -dBATCH -sOutputFile=small.pdf in.pdf
```

Profiles: `/screen` (smallest), `/ebook`, `/printer`, `/prepress`

## Loop

1. `pdfinfo` → is it scanned or text?
2. If scanned → `ocrmypdf`
3. Extract/edit as needed
4. Verify output
