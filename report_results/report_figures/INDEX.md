# EE541 report figure/evidence package

Use the five `main/` figures for a 5–7-page report. `supporting/` contains revised
copies of all 20 original plots; `supporting_extra/` adds absolute noise-outcome
responses. Every figure has vector PDF, 300-dpi PNG and a plotted-data CSV.
`FIGURE_INDEX.csv` maps source tables, analysis functions, images and captions.

Read `CAPTIONS.md`, `TABLE_NOTES.md`, `FINDINGS.md` and `VALIDATION.json` before interpreting results.
`tables/` retains paired comparisons, cohorts/throughput/rejection, common-score
weight comparisons, forecast errors, runtime/solver evidence and offline gaps.
`inputs/` contains small saved input tables/configurations/audit reports and a
runtime-metadata capsule; no raw slot/packet/offline-plan ledgers or solar downloads.
The stored audits were completed previously, not replayed by this script.
Production hashes were checked before/after the read-only analysis.

The script imports no simulator/optimizer. For a fresh replot from the compact
capsule: `python prepare_report_figures.py --input inputs --out replotted --zip replotted.zip`.
Runtime metadata is reused in capsule mode; hashes then refer to the capsule,
not an independent recheck of the omitted production ledgers. No experiments
are rerun. Adaptive penalty updates remain out of scope. This is figure/evidence
material, not the final project report.
