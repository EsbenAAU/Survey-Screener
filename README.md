# Survey Screener

A small, local tool for the **record-selection stage of survey and systematic reviews**. It takes the
exports of your literature searches, helps you screen titles/abstracts and full texts, fetches missing
metadata and PDFs, and produces the numbers you need to report the selection — including a
**PRISMA 2020 flow diagram** (SVG and LaTeX/TikZ), a per-record screening table (CSV) and a draft
methods paragraph.

Everything runs on your own computer in the browser. Nothing is uploaded anywhere except the
metadata/PDF look-ups you start yourself (OpenAlex, Semantic Scholar, Crossref, Unpaywall, publisher sites).

> Survey Screener supports the screening; it does not make decisions for you. Term matching and
> automatic exclusion are recall-oriented aids, and every decision can be inspected and undone.

## Features

- **Import** RIS (`.ris`), BibTeX (`.bib`) and EndNote XML (`.xml`) exported from Scopus, Web of Science,
  IEEE Xplore, Zotero, Mendeley, RefWorks, EndNote, … Each file is labelled with its source database.
- **Duplicate detection** on DOI, and on normalised title + year.
- **Search terms**: inclusion terms are highlighted and can be used to sort and filter; exclusion terms are
  highlighted in red and can auto-exclude records (reported separately in PRISMA as
  *records marked as ineligible by automation tools*). Wildcards (`fish*`) and regular expressions
  (`/sonar|acoustic/`) are supported, and terms are also searched in downloaded full texts.
- **Metadata update**: fills missing abstracts, DOIs, years, venues and authors from OpenAlex,
  Semantic Scholar, Crossref and IEEE Xplore. Existing values are never overwritten.
- **PDF download**: open-access copies (OpenAlex/Unpaywall), publisher links and the DOI landing page;
  optionally a real Chrome/Edge window (Playwright) that reuses your institutional login.
  PDFs can also be attached by dragging them onto a record.
- **Two-stage screening** with keyboard shortcuts: title/abstract (include / maybe / exclude + reason)
  and full text (include / exclude + reason, including *not retrieved*). Bulk-exclude the current
  filtered view, e.g. everything matching a search.
- **PRISMA 2020 summary**: live counts, flow diagram (SVG / TikZ), exclusion reasons, screening record
  (CSV), BibTeX of the included studies, and a draft methods paragraph.

## Installation

Requires Python 3.9 or newer. The core uses only the standard library.

```bash
git clone https://github.com/<username>/survey-screener.git
cd survey-screener
pip install -r requirements.txt        # optional extras, see below
python run.py                          # opens http://localhost:8765
```

On Windows you can double-click `start.bat`.

Optional extras (in `requirements.txt`):

| Package | Used for |
|---|---|
| `pypdf` | reading PDF text if `pdftotext` (poppler) is not installed |
| `playwright` | the browser option for PDFs behind logins / bot protection (uses your installed Chrome or Edge; no extra browser download needed) |

Options: `python run.py --port 9000 --projects D:/reviews --no-browser`

## Workflow

1. **Import & terms** — create a project, import one file per database, enter inclusion and exclusion
   terms, set your e-mail address (sent to the APIs as a courtesy) and your exclusion reasons.
   Optionally preview and apply automatic exclusion. Run *Update metadata & abstracts* to fill gaps.
2. **Screen** — work through *To screen* with `j`/`k` to move, `i` include, `e` exclude (with the reason
   selected on the card), `m` maybe, `u` undo, `a` expand the abstract, `o` open PDF/DOI.
   Included records move to *Full text*. Run *Download PDFs* (or drop PDFs onto cards), then make the
   full-text decision for each report.
3. **PRISMA & export** — check progress and download the flow diagram, screening record and included
   studies. The methods text is a starting point; edit it to suit your paper.

## How the PRISMA 2020 boxes are counted

| Box | Definition in Survey Screener |
|---|---|
| Records identified | all imported records, per source |
| Duplicate records removed | records flagged as duplicates on import |
| Records marked as ineligible by automation tools | title/abstract exclusions created by *Apply auto-exclusion* |
| Records screened | identified − duplicates − automation |
| Records excluded | manual title/abstract exclusions |
| Reports sought for retrieval | records included at title/abstract stage |
| Reports not retrieved | full-text exclusions with reason *Not retrieved* |
| Reports assessed for eligibility | reports with a full-text decision (excluding *not retrieved*) |
| Reports excluded (with reasons) | full-text exclusions |
| Studies included | full-text inclusions |

Records still marked *maybe* or without a decision are reported as pending, below the diagram.

## Project files

Each project is a folder under `projects/`:

```
projects/<name>/
  project.json     records, decisions, terms, settings, import log (plain JSON — easy to archive, e.g. on Zenodo)
  pdf/             full texts
  text/            extracted text (cache for term search)
```

`project.json` and the screening CSV can be shared as supplementary material. Do not publish the
`pdf/` folder — it contains copyrighted articles.

## Limitations

- Duplicate detection is exact (DOI, or normalised title + year); near-duplicates with different titles
  are not merged.
- PDF retrieval depends on your network access and on publishers' terms of use. Download politely
  and only what you need for screening.
- Single-reviewer workflow; there is no built-in dual-screening or conflict resolution.

## Citation

If you use Survey Screener in a published review, please cite the archived version:
`<Author>. Survey Screener (version X). Zenodo. https://doi.org/10.5281/zenodo.XXXXXXX`

## License

MIT — see `LICENSE`.
