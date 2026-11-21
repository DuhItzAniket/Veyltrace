# paper/ — the Veyltrace research paper

Draft v1 of the paper planned in [docs/11](../docs/11-research-paper-plan.md) (task R-18, [#47](https://github.com/DuhItzAniket/Veyltrace/issues/47)). The plan wins on structure, claims and the writing workflow; [docs/04](../docs/04-evaluation-protocol.md) at tag `prereg-v1` wins on every protocol detail.

## Build

From this folder, with TeX Live or MiKTeX (the `acmart` class ships with both):

```bash
latexmk
```

`latexmkrc` runs pdflatex and BibTeX and writes everything, including `main.pdf`, to `build/` (git-ignored). `latexmk -C` cleans it. The build needs no lane file and no generated file: missing ones print a coloured placeholder.

## Format decisions (lead, R-18)

| Decision | Why |
|---|---|
| LaTeX, one file per section | [11 §10](../docs/11-research-paper-plan.md#10-writing-workflow) |
| `acmart` `sigconf,review,anonymous` | KDD 2027 cycle 2 is the primary target ([11 §7](../docs/11-research-paper-plan.md#7-venue-plan-and-arxiv)) and uses `acmart`; `review` numbers the lines. ISSRE (the alternative) uses IEEEtran: switching changes only `main.tex` and the bibliography style, at M4 |
| One sentence per line | diffs and review comments land on one sentence |
| No bibliography merge script | 11 §10 proposed per-lane `.bib` files merged into a generated `refs.bib`. BibTeX reads several files directly, so `refs.bib` is the lead's file and each lane may add `sections/<lane>-refs.bib`, which `.github/lanes.yml` already gives that lane. No generated file, no script. A key lives in exactly one file |

## Who edits what

| Path | Owner |
|---|---|
| `main.tex`, `preamble.tex`, `refs.bib`, `latexmkrc`, `sections/<nn>-<slug>.tex` | lead (Reason lane) |
| `sections/observe-*.tex`, `sections/observe-refs.bib` | Observe lane |
| `sections/explain-*.tex`, `sections/explain-refs.bib` | Explain lane |
| `generated/` | nobody by hand: a copy step from R-17 ([#46](https://github.com/DuhItzAniket/Veyltrace/issues/46)) fills it |

The lead's sections include the lane files by name and show a stub (or the lead's draft) until they exist, so no lead PR creates a file in another lane's path:

| Slot in the paper | Lane file | Until it exists |
|---|---|---|
| §3.1 Observe part of the pipeline | `sections/observe-pipeline.tex` | stub |
| §3.4 The proposer | `sections/explain-proposer.tex` | stub |
| §3.7 Receipts and replay | `sections/explain-receipts.tex` | stub |

## Rules for text

- **No hand-typed result numbers** ([AGENTS.md §4.8](../AGENTS.md)). Write `\resnum{<experiment_id>}{<selector>}`; it prints a red blank naming its source until `generated/numbers.tex` defines it with `\defresnum{<experiment_id>}{<selector>}{<value>}` (no generator yet). One quantity has one key wherever it appears:
  - `<experiment_id>` is exactly one id from `bench/experiments/`: the experiment whose `summary.json` holds the value. A value computed across experiments (an alert shift against no shift, an RCAEval-C cell against the no-change cell, a maximum over several shifts) takes the reference experiment's id, the unperturbed one, and ends the selector with `/vs:<id>[,<id>…]`, listing the perturbed experiments. A value that no experiment's `summary.json` can hold (the RQ6 replay rates) takes the experiment whose recorded runs it measures.
  - `<selector>` is `<system>/<method>/<metric>[/<part>]`: `<system>` is `ob`, `ss`, `tt`, `pooled` (the benchmark-level row) or a dataset id; `<method>` is a method id, or `<a>-vs-<b>` for a paired comparison (`best_simple_baseline` names the 04 §2 choice); `<metric>` is the `summary.json` entry and key (`ac_at_k.ac_at_1` may be shortened to `ac_at_1`; `cost.wall_ms_p95`) or, for a metric `bench_summary` 1.1 lacks, its 04 §9 metric id; `<part>` names the statistic: `difference`, `ci` or `holm_p` for comparisons and intervals, `max_drop` for a maximum over experiments.
  - Units are the stored ones (`wall_ms`, `peak_rss_mb`); the prose names the same unit.
- **Other numbers.** The only numbers typed by hand are design constants from docs/02 and the engine specs, literature numbers quoted as context with their source, and numbers already committed under `bench/results/` cited with their experiment id.
- **Tables and figures are generated.** `\resulttable{<label>}{<caption>}{<experiment ids>}{<name>}` (and `\resultfigure`; starred forms span both columns) input `generated/<name>.tex` or `.pdf` and show a placeholder until then. R-17 writes `bench/results/tables/<name>.{md,tex}` and `bench/results/figures/<name>.{csv,svg}`; a copy step puts the `.tex` files in `generated/` and converts the SVG figures to PDF ([11 §10](../docs/11-research-paper-plan.md#10-writing-workflow); the conversion is not built yet). `<name>` is R-17's table or figure name, e.g. `t05-rq1-re2-oracle` or `fig7-shift`.
- **Citations** come only from sources that `docs/`, `reports/` or `research_notes/` cite with a URL, DOI or arXiv id, copied from there; each `refs.bib` entry names the note it came from in a `source` field, which BibTeX ignores. Anything else is `\citeneeded{...}`. Hedge claims as the claim register requires ([11 §11](../docs/11-research-paper-plan.md#11-claim-register-what-to-hedge-or-avoid)).
- **Estimates** carry `\estimate`. Questions for the lead are `\leadq{...}`, printed in blue.
