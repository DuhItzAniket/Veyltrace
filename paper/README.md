# paper/ — the Veyltrace research paper

Draft v1 of the paper planned in [docs/11](../docs/11-research-paper-plan.md) (task R-18, [#47](https://github.com/DuhItzAniket/Veyltrace/issues/47)). The plan wins on structure, claims and the writing workflow; [docs/04](../docs/04-evaluation-protocol.md) at tag `prereg-v1` wins on every protocol detail.

## Build

From the repository root, then this folder, with TeX Live or MiKTeX (the `acmart` class and TikZ ship with both):

```bash
uv run veyltrace bench tables              # R-17: bench/results/tables/ and figures/ from committed results
uv run python scripts/paper_generated.py   # fills paper/generated/ (tables, figures, numbers.tex)
cd paper && latexmk
```

`latexmkrc` runs pdflatex and BibTeX and writes everything, including `main.pdf`, to `build/` (git-ignored). `latexmk -C` cleans it. The build needs no lane file and no generated file: missing ones print a coloured placeholder, so `latexmk` alone still builds a draft.

`scripts/paper_generated.py` ([#46](https://github.com/DuhItzAniket/Veyltrace/issues/46)) writes three kinds of file into `generated/`, and removes `.tex` files there that it no longer produces:

- `<name>.tex` per table: a byte copy of `bench/results/tables/<name>.tex`.
- `<name>.tex` per figure: R-17's `bench/results/figures/<name>[-<panel>].svg` panels as TikZ, one `tikzpicture` per panel at 1 px = 1 pt, clipped to the SVG's view box. A figure is named by its `<name>.csv`; an SVG with no CSV (a figure R-17 could not draw) is a one-panel figure of its own. The converter knows exactly what `veyltrace_bench.tables.svg` writes (`rect`, `line`, `circle`, `polyline`, `path` with absolute `M`/`L`/`Z`, `text` with `text-anchor`, `fill` and a `rotate` about its own anchor, `title` as a comment; `#rgb`/`#rrggbb`/`none` colours; the `sans-serif`, `serif` or `monospace` family). Any other element, attribute or value stops the script with an error naming the file: nothing is dropped silently.
- `numbers.tex`: `\defresnum{<key>}{<selector>}{<value>}` for every `\resnum` in `sections/*.tex` (outside TeX comments) that resolves, sorted, then one comment line per unresolved key with the reason.

It prints a report: how many keys resolve, and each unresolved key with its first use (file:line) and reason. `--check` writes nothing and exits 1 if any `\resnum` is unresolved or unparseable; use it before a release build. Two runs on the same commit write the same bytes (no timestamps, sorted output).

**`generated/` is not committed** (`.gitignore`). Every file in it is a deterministic function of committed files (`bench/results/` and `paper/sections/`), so committing it would only add a second copy that can go stale and conflict in every PR that touches a result or a sentence. The cost is one command before `latexmk`; an arXiv or venue upload runs the script once and ships the folder. Revisit only if the build must run where Python is unavailable.

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
| `generated/` | nobody by hand: `scripts/paper_generated.py` (R-17, [#46](https://github.com/DuhItzAniket/Veyltrace/issues/46)) fills it; git ignores it |

The lead's sections include the lane files by name and show a stub (or the lead's draft) until they exist, so no lead PR creates a file in another lane's path:

| Slot in the paper | Lane file | Until it exists |
|---|---|---|
| §3.1 Observe part of the pipeline | `sections/observe-pipeline.tex` | stub |
| §3.4 The proposer | `sections/explain-proposer.tex` | stub |
| §3.7 Receipts and replay | `sections/explain-receipts.tex` | the lead's draft, `sections/03-receipts.tex` |
| §5.2 RQ2 proposer | `sections/explain-rq2.tex` | the lead's placeholders, `sections/05-rq2.tex` |
| §5.4 RQ4 alert shifts and telemetry ablation | `sections/observe-rq4.tex` | the lead's placeholders, `sections/05-rq4-shift-ablation.tex` |
| §5.5 RQ5 cost | `sections/observe-rq5.tex` | the lead's placeholders, `sections/05-rq5.tex` |
| §5.6 RQ6 replay | `sections/explain-rq6.tex` | the lead's placeholders, `sections/05-rq6.tex` |

## Rules for text

- **No hand-typed result numbers** ([AGENTS.md §4.8](../AGENTS.md)). Write `\resnum{<experiment_id>}{<selector>}`; it prints a red blank naming its source until `generated/numbers.tex` defines it with `\defresnum{<experiment_id>}{<selector>}{<value>}` (written by `scripts/paper_generated.py`; "Selector grammar" below says exactly what resolves). One quantity has one key wherever it appears:
  - `<experiment_id>` is exactly one id from `bench/experiments/`: the experiment whose `summary.json` holds the value. A value computed across experiments (an alert shift against no shift, an RCAEval-C cell against the no-change cell, a maximum over several shifts) takes the reference experiment's id, the unperturbed one, and ends the selector with `/vs:<id>[,<id>…]`, listing the perturbed experiments. A value that no experiment's `summary.json` can hold (the RQ6 replay rates) takes the experiment whose recorded runs it measures.
  - `<selector>` is `<system>/<method>/<metric>[/<part>]`: `<system>` is `ob`, `ss`, `tt` or `pooled` (the benchmark-level statistics row, which exists only for interval and comparison statistics and waits for the pooled bootstrap, R-16 B9); `<method>` is a method id, or `<a>-vs-<b>` for a paired comparison (`best_simple_baseline` names the 04 §2 choice); `<metric>` is the `summary.json` entry and key (`ac_at_k.ac_at_1` may be shortened to `ac_at_1`, an entry whose only key has its own name to the entry, e.g. `retrieval_at_k`, and group counts are `outcomes.<outcome>`; `cost.wall_ms_p95`) or, for a metric `bench_summary` 1.1 lacks, its 04 §9 metric id with a provisional sub-key (`set_size.mean`, `risk_coverage.aurc_v`/`aurc_f`, `no_fault_rates.normal_declared_no_fault`/`wrong_no_fault`, `selective_accuracy.confirmed`, and `replay.tier1_*`/`tier2` for the replay rates, which are not bench output); provisional keys must be renamed to match the contract change that adds the metric; `<part>` names the statistic: `difference`, `ci` or `holm_p` for comparisons and intervals, `max_drop` for a maximum over experiments.
  - Units are the stored ones (`wall_ms`; `peak_rss_mb` is MiB); the prose names the same unit, and thresholds next to a blank are written in that unit (proportions as 0.10, not 10 points). A key never names a value derived across systems or groups (a maximum over systems, a p95 over pooled cases): the paper reports the per-system values instead.
- **Other numbers.** The only numbers typed by hand are design constants from docs/02 and the engine specs, literature numbers quoted as context with their source, and numbers already committed under `bench/results/` cited with their experiment id.
- **Tables and figures are generated.** `\resulttable{<label>}{<caption>}{<experiment ids>}{<name>}` (and `\resultfigure`; starred forms span both columns) input `generated/<name>.tex` or `.pdf` and show a placeholder until then. R-17 writes `bench/results/tables/<name>.{md,tex}` and `bench/results/figures/<name>.csv` with one `<name>[-<panel>].svg` per panel. `scripts/paper_generated.py` copies the `.tex` tables into `generated/`; `\resulttable` unwraps R-17's float (its caption is printed below the table as a note, its notes and source lines are kept). It also converts each figure's SVG panels to one `generated/<name>.tex` of TikZ pictures, which `\resultfigure` inputs (else `generated/<name>.pdf`, else the placeholder): vector output in the PDF, as [11 §10](../docs/11-research-paper-plan.md#10-writing-workflow) asks, with no converter to install (no `rsvg-convert`, Inkscape or matplotlib). Each panel is scaled as a whole, text included, as an SVG viewer scales it: two panels to a row in a starred figure, stacked in a one-column figure. `<name>` is R-17's table or figure name, e.g. `t05-rq1-re2-oracle` or `fig7-shift`.

### Selector grammar

`numbers.tex` defines a key only from committed files: `bench/results/<experiment_id>/summary.json` (which git must track, unchanged since HEAD), the experiment's `bench/experiments/<experiment_id>.yaml` and `bench/results/not_run.yaml`. No statistic is estimated; the only arithmetic is the point difference between two experiments' committed values (`/vs:`), taken exactly in decimal on the values as the files write them, so it rounds as a reader subtracting the files by hand would; a difference of two JSON integers (counts) prints as an integer, any other as a rate.

```text
selector   = system "/" method "/" metric [ "/" part ]
system     = "ob" | "ss" | "tt" | … | "pooled"        group "system" field; pooled = the statistics row with system null
method     = method_id | method_id "-vs-" method_id   e.g. veyltrace:off, veyltrace:brief-vs-veyltrace:off
metric     = name { "." name }                        e.g. ac_at_1, ac_at_k.ac_at_1, cost.wall_ms_p95, outcomes.failed
part       = "ci" | "difference" | "holm_p"
           | "difference/vs:" experiment_id            point difference: value there minus value here
           | "max_drop/vs:" experiment_id { "," experiment_id }   point estimate: max over the list of (here minus there)
```

| Selector form | Value | From |
|---|---|---|
| `<system>/<method>/<metric>` | the group's value | `groups[]` with that `system` and `method` (one group; `ob` is `re2-ob`'s `system` field, so no dataset is named). `<metric>` is `<entry>.<key>` of `metrics`; `<key>` alone when exactly one entry holds it (`ac_at_1` → `ac_at_k.ac_at_1`) or the entry is named as its key (`retrieval_at_k`, `coverage`, `decoy_ranked_first`); `outcomes.<outcome>`; a top-level `n_*` count |
| `pooled/<method>/<metric>` | the pooled point estimate | `statistics.intervals[]` with `system` null, that `method` and `metric` = the last name of `<metric>`: its `estimate` (summary.json has no pooled group) |
| `…/<method>/<metric>/ci` | `[low, high]`, the 95% interval | the same `statistics.intervals[]` row (per system, or `system` null for `pooled`) |
| `<system>/<a>-vs-<b>/<metric>/difference`, `/ci`, `/holm_p` | A − B, its 95% interval, the Holm-adjusted p | `statistics.comparisons[]` with that `system` (null for `pooled`), `method_a`, `method_b` and `metric`; the non-inferiority and superiority rows share `difference` and `ci`, and `holm_p` is the superiority row's. `<b>` = `best_simple_baseline` matches the `method_b` that summary.json chose, and only when the experiment's YAML says `noninferiority: {vs: best_simple_baseline}` |
| `<system>/<method>/<metric>/difference/vs:<id>` | value in `<id>` minus value in `<experiment_id>` (a point estimate, no interval) | the two experiments' values by the first row of this table |
| `<system>/<method>/<metric>/max_drop/vs:<id>,…` | the largest drop, max of (value in `<experiment_id>` − value in `<id>`) over the list (a point estimate) | the same; one unresolved experiment leaves the key unresolved, never a maximum over fewer |

Side results, which no experiment's `summary.json` holds, take a key naming the file and a dotted JSON path as the selector (a number indexes a list; a final `ci` prints the object's `low`/`high` or `ci_low`/`ci_high` as an interval):

| Key | File | Example |
|---|---|---|
| `rq3-intervals/<experiment_id>` | `bench/results/rq3-intervals/<experiment_id>/summary.json` | `\resnum{rq3-intervals/re2-oracle-rq3-off-v1}{intervals.pooled.coverage.estimate}` |
| `replay/<site>` (`recording`, `second-laptop`) | `bench/results/replay/<site>/replay_summary.json` | `\resnum{replay/recording}{tier1.ci}` |
| `rq5-ai-cost` | `bench/results/rq5-ai-cost/summary.json` | `\resnum{rq5-ai-cost}{systems.ob.model_wall_ms_p95}` |

**Formats** (the leaf is the last JSON key read): proportions, rates, means and differences with 3 decimals, ROUND_HALF_UP of the value as the file writes it, the tables' rule (`veyltrace_bench.tables.cells.fixed`), so prose and tables agree; intervals as `[low, high]` with 3 decimals, a bound that rounds to zero keeping its sign as in the tables; a leaf with `ms` or `mb` as a word (`wall_ms_p95`, `peak_rss_mb_p95`) or starting `tokens_`/`turns_` as an integer in the stored unit; JSON integers (counts) as integers; p-values (`holm_p`, any leaf ending `_p`) with 3 significant digits (0.000400). A negative value prints a minus sign (`\ensuremath{-}`), not a hyphen.

**Unresolved keys stay undefined**, so the PDF prints the red blank naming them, and the report says why: the experiment is in `not_run.yaml` (its reason), it was revised by a 04 §12 revision (key the prose to the revision id), it has no YAML in `bench/experiments/`, its results file is missing, not tracked by git or changed since HEAD, the group or statistics row does not exist, or the value is null (undefined for that group). Provisional metric keys (`set_size.mean`, `risk_coverage.aurc_v`, `no_fault_rates.wrong_no_fault`, `replay.tier1_*` on an experiment) resolve only once a key of that name exists; the report lists them until the prose uses the stored name (`set_size.set_size_mean`, `risk_coverage.aurc_verdict`, …) or a side-result key.
- **Citations** come only from sources that `docs/`, `reports/` or `research_notes/` cite with a URL, DOI or arXiv id, copied from there; each `refs.bib` entry names the note it came from in a `source` field, which BibTeX ignores. Anything else is `\citeneeded{...}`. Hedge claims as the claim register requires ([11 §11](../docs/11-research-paper-plan.md#11-claim-register-what-to-hedge-or-avoid)).
- **Estimates** carry `\estimate`. Questions for the lead are `\leadq{...}`, printed in blue.
