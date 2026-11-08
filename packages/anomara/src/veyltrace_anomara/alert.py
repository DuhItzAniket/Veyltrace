"""`detect_alert(telemetry)`: the first sustained SLO breach on the entry services (03-anomara §3.8).

Core's alert step (pipeline step 1) calls this under the detected-alert protocol, through the
`veyltrace.alert_detectors:default` entry point, before Signalyth exists (02 §5.1). It reads only
telemetry and the descriptive manifest fields, never `t_alert_hint_ns`, a window or a file, and it
uses no clock and no RNG. Like an online watcher, each decision uses only the trailing baseline, the
bucket itself and the next `persist_steps − 1` buckets that confirm it, so it cannot look ahead.

Cross-lane API: the signature is frozen (packages/anomara/AGENTS.md); changes need the lead.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import numpy as np

from veyltrace_anomara.robust import robust_scale
from veyltrace_anomara.settings import RobustZConfig, SloConfig, anomara_config
from veyltrace_anomara.slis import Sli, metric_slis, span_call_pairs, span_parents, trace_slis
from veyltrace_causalith.entry import entry_config, entry_services
from veyltrace_contracts.models import CaseManifest
from veyltrace_core.adapters import AlertDetection, TelemetryTables

__all__ = ["detect_alert", "scan"]


def scan(sli: Sli, data_start_ns: int, slo: SloConfig, rz: RobustZConfig) -> int | None:
    """Start of the first sustained breach of one SLI, or None (§3.8 steps 3–4).

    At bucket t the baseline is the SLI's values in [t − gap − window, t − gap) (at least
    `min_baseline_points`), scaled as robust_z (§3.2); a one-sided z ≥ k on `persist_steps`
    consecutive SLI buckets starts a breach at the first of them.
    """
    eps = rz.epsilon_for(sli.family, sli.unit)
    first = data_start_ns + slo.window_ns + slo.gap_ns
    z = np.full(sli.t.size, -np.inf)
    for i in range(sli.t.size):
        t = int(sli.t[i])
        if t < first:
            continue
        lo, hi = np.searchsorted(sli.t, [t - slo.gap_ns - slo.window_ns, t - slo.gap_ns], side="left")
        if hi - lo < slo.min_baseline_points:
            continue
        med, scale = robust_scale(sli.x[lo:hi], eps, rz)
        z[i] = (sli.x[i] - med) / scale
    # Confirmation counts the SLI's next observed buckets: skipped buckets (< min_spans, or no
    # scrape on a 15 s metric) neither break nor confirm a breach.
    hot = z >= slo.k
    for i in range(sli.t.size - slo.persist_steps + 1):
        if bool(hot[i : i + slo.persist_steps].all()):
            return int(sli.t[i])
    return None


def detect_alert(telemetry: TelemetryTables, manifest: CaseManifest, config: Any) -> AlertDetection | None:
    """The first sustained SLO breach on the entry services, or None (§3.8).

    `config` is the run's Anomara EngineConfig (core passes `ResolvedConfig.engine("anomara")`);
    the entry rule's keys are read from its `causalith` section.
    """
    section = cast("Mapping[str, Any]", config)
    cfg = anomara_config(section)
    spans = telemetry.spans
    pairs = span_call_pairs(spans) if spans.num_rows else []
    entries = entry_services(
        pairs, manifest.services, manifest.system, entry_config(config.section("causalith"))
    )
    if not entries:
        return None
    slis: list[Sli] = []
    if spans.num_rows:
        parents = span_parents(spans)
        slis = [s for e in entries for s in trace_slis(spans, parents, e, cfg.slo)]
    else:  # no traces: the entry services' latency and error metrics (§3.8 step 2)
        slis = [s for e in entries for s in metric_slis(telemetry.metrics, e, cfg.slo)]
    found: list[tuple[int, int, str, str]] = []
    for sli in slis:
        t = scan(sli, manifest.data_start_ns, cfg.slo, cfg.robust_z)
        if t is not None:
            found.append((t, sli.kind, sli.service, sli.signal))
    if not found:
        return None
    t, _, _, signal = min(found)
    return AlertDetection(t_alert_ns=t, entry_services=tuple(entries), signal=signal, threshold=cfg.slo.k)
