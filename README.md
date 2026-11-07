# pdf_to_latex

Convert a PDF — typically a mathematics script — into a compiling LaTeX
document using a math-aware vision model (DeepSeek-V4.1-Flash).

The pipeline renders each page to an image, asks a vision model to transcribe
the page as a LaTeX fragment (formulas included), validates each fragment by
compiling it, repairs or slices pages when needed, and finally assembles a
complete `.tex` document.

## Requirements

- Python 3.10+
- [Poppler](https://poppler.freedesktop.org/): `pdfinfo`, `pdftotext`, `pdftoppm`
- A TeX distribution providing `pdflatex`
- Python packages: `requests`, `Pillow`

```bash
python3 -m pip install -r requirements.txt
# or, for the `pdf-to-latex` console script:
python3 -m pip install -e .
```

## API key

The vision requests need a DeepSeek API key:

```bash
export DEEPSEEK_API_KEY="sk-..."
```

## Usage

```bash
python3 main --pdf book.pdf --output book.tex
```

After `pip install -e .` the equivalent entry point is:

```bash
pdf-to-latex --pdf book.pdf --output book.tex
```

Useful options:

```text
--pages 1-20,25        process only these pages
--skip-pages 3,7       skip these pages
--workers 2            concurrent OCR requests
--model deepseek-flash vision model name
--dpi 200              page rendering resolution
--force                overwrite an existing output file
--clean                delete the work directory before starting
--strict               non-zero exit on validation warnings
--skip-model-check     skip the /models image-capability check
--verbose              debug logging
```

Run `python3 main --help` for the full list.

## Output

- `<output>.tex` — the assembled LaTeX document.
- `.<output-stem>.work/` — intermediate files (use `--workdir` to move it):
  - `pages/` rendered page images and slices
  - `text/` extracted PDF text layers
  - `fragments/` per-page LaTeX and compiled fragment PDFs
  - `build/main.tex` and `build/main.pdf` — assembled document and full compile
  - `cache/` content-addressed OCR response cache
  - `report.json`, `report.md`, `manifest.json` — conversion diagnostics
- Exit code `1` if the full document does not compile, a content page produced
  no fragment, or (with `--strict`) any validation warning remains.

## How it works

1. `pdfinfo` / `pdftotext` inspect the PDF and extract its text layer.
2. Pages with no meaningful text layer are rendered and checked for ink;
   genuinely blank pages are skipped, sparse title/formula pages are kept.
3. Content pages are rendered to JPEG and sent to the vision model with a
   transcription prompt and the text layer as a prose hint.
4. Every returned fragment is sanitized and compiled with `pdflatex`; pages are
   re-sliced or repaired when compilation or prose recall fails.
5. Fragments are assembled with a book-class preamble, compiled as a whole, and
   validated against the PDF's headings and prose.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
