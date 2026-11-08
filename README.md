# pdf_to_latex

Convert a PDF — typically a mathematics script — into a compiling LaTeX
document using a math-aware vision model (DeepSeek-V4.1-Flash).

The pipeline renders each page to an image, asks a vision model to transcribe
the page as a LaTeX fragment (formulas included), extracts figures as cropped
artwork from the original PDF, validates each fragment by compiling it, repairs
or slices pages when needed, and finally assembles a complete `.tex` document
inside a self-contained output bundle.

## Requirements

- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or Anaconda
- [Poppler](https://poppler.freedesktop.org/): `pdfinfo`, `pdftotext`, `pdftoppm`
- A full TeX distribution providing `pdflatex` and the packages used by the
  preamble (`amsmath`, `amssymb`, `amsthm`, `mathtools`, `geometry`, `hyperref`,
  `booktabs`, `enumitem`, `lmodern`)

The Python dependencies (Python 3.15.2, `requests` 2.34.2, `Pillow` 13.0.0) are
pinned in `environment.yaml`.

## Setup

Create and activate the conda environment:

```bash
conda env create -f environment.yaml
conda activate pdf_to_latex
```

Poppler and TeX Live are system tools, not conda packages in this environment.
On Debian/Ubuntu, for example:

```bash
sudo apt install poppler-utils texlive-latex-extra texlive-fonts-recommended fonts-lmodern
```

The `texlive-core` package on conda-forge contains only the TeX binaries, not
the LaTeX class and package files this project needs, so install a full system
TeX Live distribution.

Optional: install the `pdf-to-latex` console script into the environment:

```bash
python -m pip install -e .
```

`requirements.txt` still lists the Python packages for pip-only setups. To
refresh an existing environment after editing `environment.yaml`:

```bash
conda env update -f environment.yaml --prune
```

## API key

The vision requests need a DeepSeek API key:

```bash
export DEEPSEEK_API_KEY="sk-..."
```

## Usage

Activate the environment first, then run:

```bash
conda activate pdf_to_latex
python main --pdf book.pdf --output book
```

After the optional `pip install -e .`, the equivalent entry point is:

```bash
pdf-to-latex --pdf book.pdf --output book
```

`--output` names the output bundle. `--output book` and `--output book.tex`
both produce a `book/` directory (see [Output](#output)).

Useful options:

```text
--pages 1-20,25        process only these pages
--skip-pages 3,7       skip these pages
--workers 2            concurrent OCR requests
--model deepseek-flash vision model name
--dpi 200              page rendering resolution
--figure-dpi 300       resolution for cropped figure artwork
--figure-padding 0.02  padding around each figure crop
--no-figures           transcribe text only, without extracting artwork
--force                overwrite an existing output file
--clean                delete the work directory before starting
--strict               non-zero exit on validation warnings
--skip-model-check     skip the /models image-capability check
--verbose              debug logging
```

Run `python main --help` for the full list.

## Output

`--output book` (or `--output book.tex`) creates a bundle that must be kept
together when the document is compiled elsewhere:

```text
book/
  book.tex            assembled LaTeX document
  book.pdf            compiled document (when the full compile succeeds)
  figures/book/       cropped artwork referenced by book.tex
```

Figure paths in the `.tex` are relative to the bundle root, so compile from
inside the bundle (`cd book && pdflatex book.tex`); the same paths work in the
internal build directory.

Intermediate files live in `.<output-stem>.work/` (use `--workdir` to move it):

- `pages/` rendered page images, slices and high-resolution figure renders
- `text/` extracted PDF text layers
- `fragments/` per-page LaTeX and compiled fragment PDFs
- `build/main.tex`, `build/main.pdf` and `build/figures/` — assembled document,
  full compile and figure staging area
- `cache/` content-addressed OCR response cache
- `report.json`, `report.md`, `manifest.json` — conversion diagnostics

Exit code `1` if the full document does not compile, a content page produced
no fragment, or (with `--strict`) any validation warning remains.

## How it works

1. `pdfinfo` / `pdftotext` inspect the PDF and extract its text layer.
2. Pages with no meaningful text layer are rendered and checked for ink;
   genuinely blank pages are skipped, sparse title/formula pages are kept.
3. Content pages are rendered to JPEG and sent to the vision model with a
   transcription prompt and the text layer as a prose hint. The model reports a
   `% FIG-BOX` rectangle for every figure and emits an
   `\includegraphics{FIG:<n>}` placeholder instead of redrawing the artwork.
4. Each figure box is cropped from a high-resolution render of the original
   page and written to `figures/<bundle>/`. A missing or unusable box falls back
   to the whole page image; a page with no usable OCR output is included as a
   whole-page figure so it is not dropped from the document.
5. Every returned fragment is sanitized and compiled with `pdflatex`; pages are
   re-sliced or repaired when compilation or prose recall fails.
6. Fragments are assembled with a book-class preamble, compiled as a whole, and
   validated against the PDF's headings and prose.

## Tests

```bash
conda activate pdf_to_latex
python -m unittest discover -s tests -v
```
