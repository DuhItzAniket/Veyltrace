"""scripts/paper_generated.py (R-17, #46): the paper's copy step, SVG figures as TikZ, \\resnum values."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXP = "exp-a-v1"
SHIFTED = ("exp-s1-v1", "exp-s2-v1")


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("paper_generated", ROOT / "scripts" / "paper_generated.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


mod = _script()


def _group(system: str, method: str, ac1: float, **metrics: object) -> dict[str, object]:
    base: dict[str, object] = {
        "ac_at_k": {"ac_at_1": ac1, "ac_at_3": 0.9},
        "coverage": None,
        "cost": {"wall_ms_p95": 6951.834700001, "peak_rss_mb_p95": 524.015625, "tokens_in_p95": None},
        "retrieval_at_k": {"pool_retrieval": 1.0, "retrieval_at_k": 0.98876, "retrieval_k": [5]},
    }
    base.update(metrics)
    return {
        "dataset": f"re2-{system}",
        "system": system,
        "method": method,
        "metrics": base,
        "n_fault": 89,
        "outcomes": {"ok": 88, "failed": 1},
    }


def _summary(exp: str, ac1: dict[str, float], *, stats: bool = True) -> dict[str, object]:
    groups = [_group(s, "veyltrace:off", v) for s, v in sorted(ac1.items())]
    groups.append(_group("ob", "rcaeval:nsigma", 0.787))
    statistics: object = "not run: no statistics"
    if stats:
        statistics = {
            "intervals": [
                {
                    "dataset": "re2",
                    "system": None,
                    "method": "veyltrace:off",
                    "metric": "ac_at_1",
                    "estimate": 0.5,
                    "low": 0.41,
                    "high": 0.5895,
                },
                {
                    "dataset": "re2-ob",
                    "system": "ob",
                    "method": "veyltrace:off",
                    "metric": "ac_at_1",
                    "estimate": ac1["ob"],
                    "low": -0.0001,
                    "high": 0.648,
                },
            ],
            "comparisons": [
                {
                    "dataset": "re2-ob",
                    "system": "ob",
                    "method_a": "veyltrace:off",
                    "method_b": "rcaeval:nsigma",
                    "metric": "ac_at_1",
                    "kind": kind,
                    "difference": -0.258426966,
                    "low": -0.426966292,
                    "high": -0.06741573,
                    "holm_p": holm,
                }
                for kind, holm in (("noninferiority", None), ("superiority", 0.03079692))
            ]
            + [
                {
                    "dataset": "re2",
                    "system": None,
                    "method_a": "veyltrace:off",
                    "method_b": "rcaeval:nsigma",
                    "metric": "ac_at_1",
                    "kind": "superiority",
                    "difference": -0.269662921,
                    "low": -0.354744188,
                    "high": -0.176675185,
                    "holm_p": 0.00039996,
                }
            ],
        }
    return {"experiment_id": exp, "groups": groups, "statistics": statistics}


def _world(tmp: Path) -> Path:
    """A repository root with three experiments, one not-run and one revised entry, a replay side
    result, two sections using \\resnum, one table and a two-panel figure."""
    results, experiments = tmp / "bench" / "results", tmp / "bench" / "experiments"
    experiments.mkdir(parents=True)
    rows = {
        EXP: ({"ob": 0.528, "ss": 0.472}, True),
        SHIFTED[0]: ({"ob": 0.5, "ss": 0.47}, False),
        SHIFTED[1]: ({"ob": 0.3, "ss": 0.5}, False),
        "exp-rev-v1": ({"ob": 0.1, "ss": 0.2}, False),
    }
    for exp, (ac1, stats) in rows.items():
        (results / exp).mkdir(parents=True)
        (results / exp / "summary.json").write_text(
            json.dumps(_summary(exp, ac1, stats=stats)), encoding="utf-8"
        )
    for exp in [*rows, "exp-cut-v1", "exp-pre-v1"]:
        vs = "best_simple_baseline" if exp == EXP else "veyltrace:off"
        (experiments / f"{exp}.yaml").write_text(
            f"experiment_id: {exp}\nstatistics:\n  noninferiority: {{vs: {vs}}}\n", encoding="utf-8"
        )
    (results / "not_run.yaml").write_text(
        'exp-cut-v1: "cut for the test"\nexp-rev-v1: {revises: exp-pre-v1}\n', encoding="utf-8"
    )
    (results / "replay" / "recording").mkdir(parents=True)
    replay = {"tier1": {"rate": 1.0, "ci_low": 0.995405246, "ci_high": 1.0, "n": 801, "outcomes": {"6": 0}}}
    (results / "replay" / "recording" / "replay_summary.json").write_text(
        json.dumps(replay), encoding="utf-8"
    )
    (results / "tables").mkdir()
    (results / "tables" / "t01-demo.tex").write_bytes(b"% table\r\n\\begin{table}x\\end{table}\n")
    (results / "tables" / "t01-demo.md").write_text("| md |\n", encoding="utf-8")
    figures = results / "figures"
    figures.mkdir()
    (figures / "fig1-demo.csv").write_text("panel\n", encoding="utf-8")
    for panel in ("tt", "ob"):
        (figures / f"fig1-demo-{panel}.svg").write_text(SVG.replace("PANEL", panel), encoding="utf-8")
    (figures / "fig2-gap.svg").write_text(SVG.replace("PANEL", "gap"), encoding="utf-8")
    sections = tmp / "paper" / "sections"
    sections.mkdir(parents=True)
    (sections / "02-b.tex").write_text(
        "AC@1 is \\resnum{exp-a-v1}{ob/veyltrace:off/ac_at_1} % \\resnum{exp-a-v1}{commented/out/x}\n"
        "and \\resnum{exp-cut-v1}{ob/veyltrace:off/ac_at_1}, \\resnum{replay/recording}{tier1.ci}.\n",
        encoding="utf-8",
    )
    (sections / "01-a.tex").write_text(
        "\\resnum{exp-a-v1}{pooled/veyltrace:off-vs-best_simple_baseline/ac_at_1/holm_p}\n"
        "\\resnum{exp-a-v1}{ob/veyltrace:off/ac_at_1}\n",
        encoding="utf-8",
    )
    return tmp


SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360" \
font-family="sans-serif" font-size="11">
<title>Fig. 1: demo &amp; test, PANEL</title>
<rect x="56" y="16" width="444" height="288" fill="none" stroke="#999"/>
<text x="50" y="308" text-anchor="end">0.00</text>
<text x="14" y="160" text-anchor="middle" transform="rotate(-90 14 160)">AC@1</text>
<polyline points="56,67.78 167,71.01" fill="none" stroke="#1b6ca8" stroke-width="1.5"/>
<line x1="56" y1="103.37" x2="56" y2="38.65" stroke="#1b6ca8"/>
<circle cx="56" cy="67.78" r="3" fill="#1b6ca8"/>
<text x="56" y="354" text-anchor="start" fill="#555">50% of x_1 &lt; {y}</text>
</svg>
"""


@pytest.fixture
def world(tmp_path: Path) -> Path:
    return _world(tmp_path)


def _resolver(root: Path) -> Any:
    return mod.Resolver(root / "bench" / "results", root / "bench" / "experiments", tracked=None)


# ------------------------------------------------------------------ selectors


def test_parse_selector_forms() -> None:
    s = mod.parse_selector("ob/veyltrace:off/cost.wall_ms_p95")
    assert (s.system, s.method_a, s.method_b, s.metric, s.part, s.vs) == (
        "ob",
        "veyltrace:off",
        None,
        "cost.wall_ms_p95",
        None,
        (),
    )
    c = mod.parse_selector("pooled/veyltrace:brief-vs-veyltrace:off/ac_at_1/ci")
    assert (c.method_a, c.method_b, c.part) == ("veyltrace:brief", "veyltrace:off", "ci")
    d = mod.parse_selector(f"tt/veyltrace:off/ac_at_1/max_drop/vs:{SHIFTED[0]},{SHIFTED[1]}")
    assert (d.part, d.vs) == ("max_drop", SHIFTED)


@pytest.mark.parametrize(
    "bad",
    [
        "ob/veyltrace:off",  # no metric
        "ob/veyltrace:off/ac_at_1/median",  # unknown part
        "ob/veyltrace:off/ac_at_1/difference/vs:",  # empty experiment list
        "ob/veyltrace:off/ac_at_1/max_drop",  # max_drop needs vs:
        "ob/a-vs-b/ac_at_1/difference/vs:x",  # a comparison is within one experiment
        "ob/veyltrace:off/ac_at_1/ci/extra",
        "ob/a-vs-b/ac_at_1",  # a comparison names its statistic
        "ob/veyltrace:off/ac at 1",
    ],
)
def test_parse_selector_refuses(bad: str) -> None:
    with pytest.raises(mod.SelectorError):
        mod.parse_selector(bad)


def test_resolve_group_metrics_and_formats(world: Path) -> None:
    r = _resolver(world)
    assert r.resolve(EXP, "ob/veyltrace:off/ac_at_1") == "0.528"  # ac_at_k.ac_at_1 shortened
    assert r.resolve(EXP, "ob/veyltrace:off/ac_at_k.ac_at_3") == "0.900"
    assert r.resolve(EXP, "ss/veyltrace:off/retrieval_at_k") == "0.989"  # entry named as its key
    assert r.resolve(EXP, "ob/veyltrace:off/cost.wall_ms_p95") == "6952"  # ms as integers
    assert r.resolve(EXP, "ob/veyltrace:off/cost.peak_rss_mb_p95") == "524"  # MiB as integers
    assert r.resolve(EXP, "ob/veyltrace:off/outcomes.failed") == "1"


def test_resolve_intervals_and_comparisons(world: Path) -> None:
    r = _resolver(world)
    assert r.resolve(EXP, "pooled/veyltrace:off/ac_at_1") == "0.500"  # pooled point = interval estimate
    assert r.resolve(EXP, "pooled/veyltrace:off/ac_at_1/ci") == "[0.410, 0.590]"
    assert r.resolve(EXP, "ob/veyltrace:off/ac_at_1/ci") == "[\\ensuremath{-}0.000, 0.648]"  # signed bound
    sel = "ob/veyltrace:off-vs-best_simple_baseline/ac_at_1"
    assert r.resolve(EXP, f"{sel}/difference") == "\\ensuremath{-}0.258"
    assert r.resolve(EXP, f"{sel}/ci") == "[\\ensuremath{-}0.427, \\ensuremath{-}0.067]"
    assert r.resolve(EXP, f"{sel}/holm_p") == "0.0308"  # 3 significant digits
    assert r.resolve(EXP, "pooled/veyltrace:off-vs-rcaeval:nsigma/ac_at_1/holm_p") == "0.000400"


def test_resolve_cross_experiment_point_differences(world: Path) -> None:
    r = _resolver(world)
    # difference/vs: the value in the named experiment minus the reference's
    assert r.resolve(EXP, f"ob/veyltrace:off/ac_at_1/difference/vs:{SHIFTED[1]}") == "\\ensuremath{-}0.228"
    # max_drop: the largest reference-minus-perturbed difference
    vs = ",".join(SHIFTED)
    assert r.resolve(EXP, f"ob/veyltrace:off/ac_at_1/max_drop/vs:{vs}") == "0.228"
    assert r.resolve(EXP, f"ss/veyltrace:off/ac_at_1/max_drop/vs:{vs}") == "0.002"


def test_resolve_side_result_json_path(world: Path) -> None:
    r = _resolver(world)
    assert r.resolve("replay/recording", "tier1.rate") == "1.000"
    assert r.resolve("replay/recording", "tier1.n") == "801"
    assert r.resolve("replay/recording", "tier1.outcomes.6") == "0"
    assert r.resolve("replay/recording", "tier1.ci") == "[0.995, 1.000]"


@pytest.mark.parametrize(
    ("key", "selector", "reason"),
    [
        ("exp-cut-v1", "ob/veyltrace:off/ac_at_1", "not run: cut for the test"),
        ("exp-pre-v1", "ob/veyltrace:off/ac_at_1", "revised by exp-rev-v1"),
        ("exp-none-v1", "ob/veyltrace:off/ac_at_1", "no bench/experiments/exp-none-v1.yaml"),
        (EXP, "ob/veyltrace:off/coverage", "null"),
        (EXP, "ob/veyltrace:off/cost.tokens_in_p95", "null"),
        (EXP, "ob/veyltrace:brief/ac_at_1", "no group"),
        (EXP, "pooled/veyltrace:off/coverage", "no interval"),
        (EXP, "ob/veyltrace:off/set_size.mean", "no metric"),
        (SHIFTED[0], "ob/veyltrace:off/ac_at_1/ci", "statistics"),
        (SHIFTED[0], "ob/veyltrace:off-vs-rcaeval:nsigma/ac_at_1/difference", "statistics"),
        ("exp-rev-v1", "ob/veyltrace:off-vs-best_simple_baseline/ac_at_1/difference", "best_simple_baseline"),
        (EXP, "ob/veyltrace:off/ac_at_1/max_drop/vs:exp-cut-v1", "exp-cut-v1: not run"),
        ("replay/recording", "tier1.missing", "no key"),
        ("replay/second-laptop", "tier1.rate", "no committed"),
    ],
)
def test_unresolved_reasons(world: Path, key: str, selector: str, reason: str) -> None:
    with pytest.raises(mod.Unresolved, match=reason):
        _resolver(world).resolve(key, selector)


def test_untracked_results_are_refused(world: Path) -> None:
    r = mod.Resolver(world / "bench" / "results", world / "bench" / "experiments", tracked=frozenset())
    with pytest.raises(mod.Unresolved, match="not committed"):
        r.resolve(EXP, "ob/veyltrace:off/ac_at_1")


# ------------------------------------------------------------------ SVG -> TikZ


def test_svg_to_tikz_converts_every_element() -> None:
    out = mod.svg_to_tikz(SVG.replace("PANEL", "ob"), "fig1-demo-ob.svg")
    assert out.startswith("% fig1-demo-ob.svg: Fig. 1: demo & test, ob\n\\begin{tikzpicture}[x=1pt,y=-1pt,")
    assert "\\clip (0,0) rectangle (640,360);" in out
    assert (
        "\\path[draw={rgb,255:red,153;green,153;blue,153},line width=1pt] (56,16) rectangle ++(444,288);"
        in out
    )
    assert "\\node[anchor=base east,inner sep=0pt,outer sep=0pt] at (50,308) {0.00};" in out
    assert "\\node[anchor=base,inner sep=0pt,outer sep=0pt,rotate=90] at (14,160) {AC@1};" in out
    blue = "{rgb,255:red,27;green,108;blue,168}"
    assert f"\\path[draw={blue},line width=1.5pt] (56,67.78) -- (167,71.01);" in out
    assert f"\\path[draw={blue},line width=1pt] (56,103.37) -- (56,38.65);" in out
    assert f"\\path[fill={blue}] (56,67.78) circle[radius=3pt];" in out
    grey = "{rgb,255:red,85;green,85;blue,85}"
    assert (
        f"\\node[anchor=base west,inner sep=0pt,outer sep=0pt,text={grey}] at (56,354) "
        "{50\\% of x\\_1 \\textless{} \\{y\\}};"
    ) in out
    assert out.endswith("\\end{tikzpicture}")


@pytest.mark.parametrize(
    "svg",
    [
        SVG.replace("<circle", '<ellipse rx="1" ry="2"'),  # an element svg.py does not write
        SVG.replace('r="3"', 'r="3" opacity="0.5"'),  # an attribute the converter does not know
        SVG.replace('fill="#1b6ca8"/>', 'fill="steelblue"/>'),  # a named colour
        SVG.replace('transform="rotate(-90 14 160)"', 'transform="rotate(-90 20 160)"'),  # off-anchor
        SVG.replace("<title>", "<g><title>").replace("</title>", "</title></g>"),  # a group
        SVG.replace('font-family="sans-serif"', 'font-family="Comic Sans"'),
    ],
)
def test_svg_to_tikz_refuses_what_it_cannot_draw(svg: str) -> None:
    with pytest.raises(mod.ConversionError):
        mod.svg_to_tikz(svg, "bad.svg")


# ------------------------------------------------------------------ the whole step


def test_build_writes_tables_figures_and_sorted_numbers(world: Path) -> None:
    out = mod.build(world, tracked=None)
    assert out.files["t01-demo.tex"] == b"% table\r\n\\begin{table}x\\end{table}\n"  # byte copy
    assert "t01-demo.md" not in out.files
    figure = out.files["fig1-demo.tex"].decode()
    assert figure.count("\\begin{tikzpicture}") == 2 and "\\vtfigpanels{2}" in figure
    assert figure.index("fig1-demo-ob.svg:") < figure.index("fig1-demo-tt.svg:")  # panels sorted
    assert "\\vtfigpanels{1}" in out.files["fig2-gap.tex"].decode()
    numbers = out.files["numbers.tex"].decode().splitlines()
    defs = [line for line in numbers if line.startswith("\\defresnum")]
    assert defs == sorted(defs)
    assert defs == [
        "\\defresnum{exp-a-v1}{ob/veyltrace:off/ac_at_1}{0.528}",
        "\\defresnum{exp-a-v1}{pooled/veyltrace:off-vs-best_simple_baseline/ac_at_1/holm_p}{0.000400}",
        "\\defresnum{replay/recording}{tier1.ci}{[0.995, 1.000]}",
    ]
    assert "% unresolved: exp-cut-v1 | ob/veyltrace:off/ac_at_1: not run: cut for the test" in numbers
    assert not any("commented/out" in line for line in numbers)  # a TeX comment is not a use
    assert len(out.resolved) == 3 and len(out.unresolved) == 1


def test_build_is_deterministic(world: Path) -> None:
    assert mod.build(world, tracked=None).files == mod.build(world, tracked=None).files


def test_main_writes_and_check_does_not(world: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "tracked_files", lambda root: None)
    generated = world / "paper" / "generated"
    assert mod.main(["--root", str(world), "--check"]) == 1  # exp-cut-v1 is unresolved
    assert not generated.exists()
    (generated / "stale.tex").parent.mkdir(parents=True)
    (generated / "stale.tex").write_text("old", encoding="utf-8")
    assert mod.main(["--root", str(world)]) == 0
    assert sorted(p.name for p in generated.iterdir()) == [
        "fig1-demo.tex",
        "fig2-gap.tex",
        "numbers.tex",
        "t01-demo.tex",
    ]
    (world / "paper" / "sections" / "02-b.tex").write_text(
        "\\resnum{exp-a-v1}{ob/veyltrace:off/ac_at_1}\n", encoding="utf-8"
    )
    (world / "paper" / "sections" / "01-a.tex").write_text("", encoding="utf-8")
    assert mod.main(["--root", str(world), "--check"]) == 0
