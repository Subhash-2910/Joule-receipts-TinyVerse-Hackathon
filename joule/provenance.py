"""Where a number came from. Shown next to every value in the UI and reports.

MEASURED   read directly from a hardware sensor (powermetrics, battery gauge)
ATTRIBUTED a measured total split between processes by their CPU share (an estimate of a share)
ESTIMATED  computed from a model with stated constants (e.g. CPU utilisation -> watts)
SIMULATED  produced by the simulation model, for CI / Docker / machines without sensors
"""
from __future__ import annotations

from enum import Enum


class Provenance(str, Enum):
    MEASURED = "MEASURED"
    ATTRIBUTED = "ATTRIBUTED"
    ESTIMATED = "ESTIMATED"
    SIMULATED = "SIMULATED"

    @property
    def rank(self) -> int:
        return _ORDER.index(self)

    def __str__(self) -> str:  # so f-strings print MEASURED, not Provenance.MEASURED
        return self.value


_ORDER = [Provenance.MEASURED, Provenance.ATTRIBUTED, Provenance.ESTIMATED, Provenance.SIMULATED]


def combine(*items: Provenance | str) -> Provenance:
    """A number computed from several inputs is only as trustworthy as its weakest input."""
    provs = [Provenance(p) for p in items if p is not None]
    if not provs:
        raise ValueError("combine() needs at least one provenance")
    return max(provs, key=lambda p: p.rank)
