"""Per-service onsets, silent services and the incident onset `t_onset` (03-anomara §3.6–3.7).

Why the second-earliest external onset: one noisy early series must not set the incident onset
(02 §6.3), and the clamp keeps it within [t_alert − 60 s, t_alert + 300 s]. Onsets stay in source
time; consumers add Causync's offset of the recorded `*_onset_source` (03 §4.2).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from veyltrace_anomara.robust import Score
from veyltrace_anomara.series import Series
from veyltrace_anomara.settings import OnsetConfig, SilenceConfig

__all__ = ["SERVICE_SIGNALS", "Method", "Scored", "TOnset", "per_service", "series_onsets", "t_onset"]

#: Signals whose silence makes the whole service silent (03-anomara §3.5).
SERVICE_SIGNALS = frozenset({"rps", "workload", "log_rate"})
Method = Literal["second_external", "single_external", "t_alert_fallback"]


@dataclass(frozen=True)
class Scored:
    """One series and its detector scores (`robust_z`, `bocpd`, `silence`; nsigma is not used here)."""

    series: Series
    robust_z: Score
    bocpd: Score
    silence: Score


def series_onsets(scored: Scored, cfg: OnsetConfig) -> tuple[int | None, int | None]:
    """(τ of the robust_z detection, τ of the silence detection) of one series (03-anomara §3.6 step 1).

    τ_z moves back to the BOCPD onset when it lies in [τ_z − bocpd_max_lead, τ_z]: BOCPD finds where
    a ramp began. Each is None when its detector is below threshold.
    """
    tau: int | None = None
    if scored.robust_z.above_threshold and scored.robust_z.onset_ns is not None:
        tau = scored.robust_z.onset_ns
        tau_b = scored.bocpd.onset_ns
        if scored.bocpd.above_threshold and tau_b is not None and tau - cfg.bocpd_max_lead_ns <= tau_b <= tau:
            tau = tau_b
    silent = scored.silence.onset_ns if scored.silence.above_threshold else None
    return tau, silent


def _earliest(cands: Iterable[tuple[int, str, str]]) -> tuple[int | None, str | None]:
    """(onset, source) of the earliest candidate (τ, series_id, source); ties → smallest series_id."""
    found = sorted(cands)
    return (found[0][0], found[0][2]) if found else (None, None)


def per_service(
    services: Sequence[str], scored: Sequence[Scored], onset: OnsetConfig, silence: SilenceConfig
) -> list[dict[str, Any]]:
    """`onsets.per_service`: one entry per manifest service, sorted (03 §4.2; 03-anomara §3.5–3.6)."""
    out: list[dict[str, Any]] = []
    by_service: dict[str, list[Scored]] = {}
    for item in scored:
        by_service.setdefault(item.series.service, []).append(item)
    for service in sorted(services):
        external: list[tuple[int, str, str]] = []
        internal: list[tuple[int, str, str]] = []
        items = by_service.get(service, [])
        for item in items:
            s = item.series
            tau, tau_sil = series_onsets(item, onset)
            # robust_z counts by klass; a silent context series is externally visible (§3.6 step 2).
            candidates = (
                (tau, s.klass == "external", s.klass == "internal"),
                (tau_sil, s.klass in ("external", "context"), s.klass == "internal"),
            )
            for t, ok_ext, ok_int in candidates:
                if t is None:
                    continue
                if ok_ext:
                    external.append((t, s.series_id, s.source))
                if ok_int:
                    internal.append((t, s.series_id, s.source))
        metric = [i for i in items if i.series.source == "metrics"]
        silent_metrics = sum(1 for i in metric if i.silence.above_threshold)
        silent = any(i.silence.above_threshold for i in items if i.series.signal in SERVICE_SIGNALS) or (
            bool(metric) and silent_metrics >= silence.service_metric_share * len(metric)
        )
        ext_ns, ext_src = _earliest(external)
        int_ns, int_src = _earliest(internal)
        out.append(
            {
                "service": service,
                "external_onset_ns": ext_ns,
                "external_onset_source": ext_src,
                "internal_onset_ns": int_ns,
                "internal_onset_source": int_src,
                "silent": silent,
            }
        )
    return out


@dataclass(frozen=True)
class TOnset:
    """The incident onset and how it was chosen (03 §4.2 `method`)."""

    t_onset_ns: int
    method: Method


def t_onset(external_onsets: Iterable[int | None], t_alert_ns: int, cfg: OnsetConfig) -> TOnset:
    """Second-earliest external onset, else the only one, else `t_alert`; clamped (03-anomara §3.7)."""
    found = sorted(t for t in external_onsets if t is not None)
    method: Method
    if len(found) >= 2:
        value, method = found[1], "second_external"
    elif found:
        value, method = found[0], "single_external"
    else:
        value, method = t_alert_ns, "t_alert_fallback"
    low, high = t_alert_ns + cfg.clamp_ns[0], t_alert_ns + cfg.clamp_ns[1]
    return TOnset(min(max(value, low), high), method)
