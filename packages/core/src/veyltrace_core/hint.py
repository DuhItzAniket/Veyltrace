"""The alert hint and its redaction (02 §5.1; M0 lead decision 2026-11-06 §2.1, D-15).

Why a leaf module: `case_manifest.t_alert_hint_ns` is the dataset's published alert time, which
under the oracle protocol is close to the injection time. Only Infralume (which writes it) and
core's alert step (which turns it into alert.json) may see it. Redaction therefore happens at the
lowest layer, in `veyltrace_core.io`, so every reader gets a redacted manifest by default; the
unredacted readers carry the word "unredacted" in their name, which the isolation literal scan
bans outside its allow-list (tests/test_isolation.py). This module is on that allow-list and
imports nothing from core, so io and context can both use it.
"""

from __future__ import annotations

from typing import Final

from veyltrace_contracts.models import CaseManifest

__all__ = ["HINT_CONTRACT", "HINT_FIELD", "HINT_READERS", "NO_HINT_SOURCE", "redact_hint"]

#: The contract that carries the hint.
HINT_CONTRACT: Final = "case_manifest"
#: The hint field (03 §2.1).
HINT_FIELD: Final = "t_alert_hint_ns"
#: hint_source paired with a null hint (03 §2.1).
NO_HINT_SOURCE: Final = "none"
#: The sub-steps allowed to see the hint (D-15): Infralume writes it, the alert step reads it.
HINT_READERS: Final[frozenset[str]] = frozenset({"infralume", "alert"})


def redact_hint(manifest: CaseManifest) -> CaseManifest:
    """Return `manifest` with the alert hint removed (t_alert_hint_ns null, hint_source "none").

    hint_source goes to "none" too, because 03 §2.1 pairs it with a null hint; a redacted manifest
    therefore looks exactly like a detected-protocol one.
    """
    return manifest.model_copy(update={HINT_FIELD: None, "hint_source": NO_HINT_SOURCE})
