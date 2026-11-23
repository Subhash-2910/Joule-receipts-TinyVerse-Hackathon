"""Per-process CPU and power: a process gets the share of CPU power equal to its share of CPU time.

Limitations: CPU share is not energy share (GPU and I/O are ignored), and macOS `ps` %CPU is a decaying average.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath

from joule.provenance import Provenance, combine


@dataclass
class ProcShare:
    name: str
    cpu_pct: float          # percent of one core (can exceed 100 on multi-core)
    watts: float | None = None
    provenance: Provenance = Provenance.ATTRIBUTED


def short_name(command: str) -> str:
    """'/Applications/Foo.app/Contents/MacOS/Foo Helper (Renderer)' -> 'Foo Helper (Renderer)'."""
    return PurePath(command.strip()).name or command.strip()


def parse_ps(text: str, exclude_pids: set[int] | None = None) -> list[tuple[str, float]]:
    """Lines of 'pid pcpu command' -> [(name, pcpu)], grouped by name."""
    totals: dict[str, float] = defaultdict(float)
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3 or (exclude_pids and parts[0].isdigit() and int(parts[0]) in exclude_pids):
            continue
        try:
            pct = float(parts[1].replace(",", "."))
        except ValueError:
            continue
        totals[short_name(parts[2])] += pct
    return sorted(totals.items(), key=lambda kv: -kv[1])


def snapshot(min_pct: float = 0.5, top_n: int = 15) -> list[tuple[str, float]]:
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,pcpu=,comm="], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    own = {os.getpid()}                       # the collector must not report itself
    return [(n, p) for n, p in parse_ps(out.stdout, own) if p >= min_pct][:top_n]


def attribute(procs: list[tuple[str, float]], cpu_power_w: float,
              power_provenance: Provenance | str) -> list[ProcShare]:
    """Split CPU power across processes by their share of CPU time.

    cpu_power_w comes from powermetrics' CPU power (MEASURED -> shares are ATTRIBUTED) or from the CPU
    utilisation model (ESTIMATED -> shares stay ESTIMATED).
    """
    cpu_sum = sum(p for _, p in procs)
    prov = combine(Provenance.ATTRIBUTED, power_provenance)
    return [ProcShare(name=n, cpu_pct=p, watts=(cpu_power_w * p / cpu_sum) if cpu_sum > 0 else 0.0, provenance=prov)
            for n, p in procs]


def anonymize(name: str, salt: str) -> str:
    """Stable pseudonym for a process name before it leaves the device."""
    return "proc-" + hashlib.sha256((salt + name).encode()).hexdigest()[:10]
