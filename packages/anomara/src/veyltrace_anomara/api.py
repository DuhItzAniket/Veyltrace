"""Engine entry point of Anomara (registered as `veyltrace.engines:anomara`; 03-anomara §2).

Pipeline step 3: scores every `signal_cube.series` series with every enabled detector (`robust_z`,
`nsigma`, `bocpd`, `silence`), one `anomalies` row each even below threshold (03 §4.1), then derives
per-service onsets and `t_onset` into `onsets.json` (03 §4.2). Reads no answer key and never the
alert hint: `alert.json` is the only time anchor (AGENTS Never 1 of this package).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from veyltrace_anomara.bocpd import Standardised, bocpd
from veyltrace_anomara.onsets import Scored, per_service, t_onset
from veyltrace_anomara.robust import Score, nsigma, robust_scale, robust_z
from veyltrace_anomara.series import Series, covered_buckets, effective_step, grid, in_window, split_series
from veyltrace_anomara.settings import AnomaraConfig, anomara_config
from veyltrace_anomara.silence import silence
from veyltrace_causalith.entry import entry_config, run_entry_services
from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core.context import EngineResult, RunContext

__all__ = ["DETECTORS", "ENGINE", "run"]

ENGINE = "anomara"
#: The detectors written for every series (03 §4.1); `tsfm` (O-10) is not built yet.
DETECTORS = ("robust_z", "nsigma", "bocpd", "silence")


def _source_ends(series: list[Series]) -> dict[str, int]:
    """Last observation per source anywhere in the case (03-anomara §3.5 truncated-case rule)."""
    ends: dict[str, int] = {}
    for s in series:
        if s.t.size:
            last = int(s.t[-1])
            ends[s.source] = max(ends.get(s.source, last), last)
    return ends


def _score_all(
    series: list[Series], alert: models.Alert, cfg: AnomaraConfig
) -> list[tuple[Series, dict[str, Score]]]:
    """Every detector on every series; BOCPD runs once per grid step on the stacked series."""
    baseline, incident = alert.windows.baseline, alert.windows.incident
    span = (baseline[0], incident[1])
    ends = _source_ends(series)
    scored: list[tuple[Series, dict[str, Score]]] = []
    stacks: dict[int, list[tuple[int, Standardised]]] = {}
    for k, s in enumerate(series):
        step = effective_step(s, cfg.grid.bucket_ns)
        eps = cfg.robust_z.epsilon_for(s.family, s.unit)
        scores = {
            "robust_z": robust_z(s.t, s.x, baseline, incident, step, eps, cfg.robust_z),
            "nsigma": nsigma(s.t, s.x, baseline, incident, step, eps, cfg.robust_z, cfg.nsigma),
            "bocpd": Score.flat(cfg.bocpd.threshold),
            "silence": silence(s, step, baseline, incident, ends.get(s.source), cfg.silence),
        }
        in_b = in_window(s.t, baseline)
        if covered_buckets(s.t[in_b], step) >= cfg.robust_z.min_baseline_steps:
            med, scale = robust_scale(s.x[in_b], eps, cfg.robust_z)
            if scale > 0.0:
                stacks.setdefault(step, []).append((k, Standardised(grid(s.t, s.x, step, span), med, scale)))
        scored.append((s, scores))
    for step in sorted(stacks):
        members = stacks[step]
        results = bocpd([m for _, m in members], incident, cfg.robust_z.persist_steps, cfg.bocpd)
        for (k, _), score in zip(members, results, strict=True):
            scored[k][1]["bocpd"] = score
    return scored


def _row(s: Series, detector: str, score: Score) -> dict[str, Any]:
    return {
        "series_id": s.series_id,
        "service": s.service,
        "component": s.component,
        "family": s.family,
        "klass": s.klass,
        "source": s.source,
        "detector": detector,
        "score": score.score,
        "score_norm": score.score_norm,
        "direction": score.direction,
        "onset_ns": score.onset_ns,
        "threshold": score.threshold,
        "above_threshold": score.above_threshold,
    }


def run(ctx: RunContext) -> EngineResult:
    """Write `anomalies` and `onsets` for one run (03-anomara §2)."""
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    alert = ctx.read_model("alert", models.Alert)
    cfg = anomara_config(ctx.config)
    entry_cfg = entry_config(ctx.config.section("causalith"))
    series = list(split_series(ctx.read_table("signal_cube.series")))
    edges = ctx.read_table("signal_cube.edges", columns=["caller", "callee"])
    scored = _score_all(series, alert, cfg)
    rows = [_row(s, d, scores[d]) for s, scores in scored for d in DETECTORS]
    services = per_service(
        manifest.services,
        [Scored(s, sc["robust_z"], sc["bocpd"], sc["silence"]) for s, sc in scored],
        cfg.onset,
        cfg.silence,
    )
    onset = t_onset((p["external_onset_ns"] for p in services), alert.t_alert_ns, cfg.onset)
    detected = alert.protocol == "detected"
    onsets: Mapping[str, Any] = {
        "schema_version": CONTRACTS["onsets"].version,
        "t_onset_ns": onset.t_onset_ns,
        "method": onset.method,
        "slo_breach_ns": alert.t_alert_ns - alert.shift_ns if detected else None,
        "entry_services": run_entry_services(alert, edges, manifest.services, manifest.system, entry_cfg),
        "per_service": services,
    }
    outputs = (("anomalies", ctx.write("anomalies", rows)), ("onsets", ctx.write("onsets", dict(onsets))))
    above = sum(1 for r in rows if r["above_threshold"])
    return EngineResult(
        engine=ENGINE,
        status="ok",
        outputs=outputs,
        metrics={"series": len(series), "rows_above_threshold": above},
    )
