# Heritage vs. Contemporary Luxury Brands — Electronic Submission Package

**Master's Thesis:** *Heritage vs. Contemporary Luxury Brands: A Comparative Analysis of
Consumer Value Perception in Electronic Word-of-Mouth*

**Author:** Jani Henrik Albermann · **Supervisor:** Dr. Burçin Güçlü · **Program:** MSc, ESMT Berlin, 2026

This repository is the electronic submission package described in **Appendix A** of the thesis.
It contains all scripts, data files, and documentation required to reproduce the reported results.
File names and structure match the references in the thesis.

## Contents

```
Code/
  scraper_v04.py             Data collection from r/watches via the PullPush archive
                             (title keyword filtering, single-brand exclusion,
                             word-count and score filters) for all ten brand corpora
  data_cleaning.py           Post-collection cleaning pipeline (duplicate removal,
                             editorial and bot filtering, word-count thresholds,
                             date window) -> reddit_data_v04_clean.csv
  integrate_arctic_shift.py  Streaming integration of the Arctic Shift r/watches
                             archive with identical filtering and deduplication
  analysis_script.py         Statistical analysis: Layers 1-3, robustness checks,
                             AP convergence test (reproduced in full in Appendix B
                             of the thesis)

Data/
  reddit_data_v04_clean.csv  Final cleaned dataset (6,342 posts, ten brand corpora)
  LIWC-22 Results - liwc22_input_v04_clean - LIWC Analysis.csv
                             Per-post LIWC-22 scores used as input to the analysis
  thesis_analysis_v2.xlsx    Full results workbook (all tables reported in Chapter 5).
                             Aggregations (brand means, group means, effect sizes,
                             Holm correction, AP convergence) are live spreadsheet
                             formulas; statistics with no spreadsheet equivalent
                             (exact Mann-Whitney U/p, robust-SE regressions) are
                             values produced by analysis_script.py, marked in blue
                             and annotated per sheet

Reports/
  reddit_data_v04_stats.txt              Collection report (per-brand counts, filters)
  arctic_shift_integration_report.txt    Arctic Shift integration & deduplication report
```

## Reproducing the results

Run order:

```
scraper_v04.py -> data_cleaning.py -> integrate_arctic_shift.py
    -> [LIWC-22 processing] -> analysis_script.py
```

- **Requirements:** Python 3.9+, `pandas`, `numpy`, `scipy`, `statsmodels`, `openpyxl`
- `analysis_script.py` reproduces every number reported in Chapter 5 from the two CSV
  files in `Data/` and writes `thesis_analysis_v2.xlsx`.
- **Note:** do not re-run `data_cleaning.py` on the final dataset — it operates on the raw
  PullPush file and would overwrite `reddit_data_v04_clean.csv` (which already includes
  the Arctic Shift integration).
- LIWC-22 scoring requires a licensed copy of LIWC-22 (liwc.app); the scored output is
  included in `Data/` so the statistical analysis is fully reproducible without it.

## Data statement

The dataset consists of publicly posted Reddit submissions from r/watches (January 2020 -
May 2026), collected via the PullPush and Arctic Shift archives for non-commercial academic
research. In this public copy, the `author` (username) column has been removed from
`reddit_data_v04_clean.csv`; it is not used by any analysis script, so all results remain
fully reproducible. Posts are otherwise identified by their public post ID.
