"""Settings, paths and the stated assumptions. Every assumption carries its source so reports can print it."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def give_back(path: Path) -> None:
    """Under `sudo`, files we create would belong to root and lock the normal user out: hand them back."""
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid and hasattr(os, "geteuid") and os.geteuid() == 0:
        for p in [path, *(path.glob("**/*") if path.is_dir() else [])]:
            try:
                os.chown(p, int(uid), int(gid or uid))
            except OSError:
                pass


def data_dir() -> Path:
    path = Path(os.environ.get("JOULE_DATA", ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    give_back(path)
    return path


def db_path() -> Path:
    return Path(os.environ.get("JOULE_DB", data_dir() / "joule.db"))


@dataclass(frozen=True)
class Assumptions:
    """Numbers we do not measure. Printed with every cost / CO2 figure."""
    tariff_inr_per_kwh: float = field(default_factory=lambda: _float("JOULE_TARIFF", 5.80))
    tariff_source: str = field(default_factory=lambda: os.environ.get(
        "JOULE_TARIFF_SOURCE", "BESCOM Domestic (LT-1) base energy rate, FY 2026-27 (energy charge only: fixed charges, "
        "fuel adjustment and tax not included)"))
    grid_kg_per_kwh: float = field(default_factory=lambda: _float("JOULE_GRID_FACTOR", 0.716))
    grid_source: str = field(default_factory=lambda: os.environ.get(
        "JOULE_GRID_SOURCE", "approx. CEA CO2 Baseline Database, Indian grid weighted average (verify latest version)"))
    usage_hours_per_day: float = field(default_factory=lambda: _float("JOULE_USAGE_HOURS", 8.0))
    # CPU-utilisation power model (ESTIMATED until calibrated against a measured source)
    est_idle_w: float = field(default_factory=lambda: _float("JOULE_EST_IDLE_W", 3.0))
    est_max_w: float = field(default_factory=lambda: _float("JOULE_EST_MAX_W", 22.0))
    # Simulated sensor model (SIMULATED)
    sim_idle_w: float = field(default_factory=lambda: _float("JOULE_SIM_IDLE_W", 3.0))
    sim_w_per_core: float = field(default_factory=lambda: _float("JOULE_SIM_W_PER_CORE", 4.5))

    def as_dict(self) -> dict:
        return {
            "tariff_inr_per_kwh": self.tariff_inr_per_kwh, "tariff_source": self.tariff_source,
            "grid_kg_co2_per_kwh": self.grid_kg_per_kwh, "grid_source": self.grid_source,
            "usage_hours_per_day": self.usage_hours_per_day,
        }


@dataclass(frozen=True)
class Settings:
    llm_base_url: str = field(default_factory=lambda: os.environ.get("JOULE_LLM_BASE_URL", "http://localhost:11434"))
    llm_model: str = field(default_factory=lambda: os.environ.get("JOULE_LLM_MODEL", "qwen2.5:1.5b"))
    llm_timeout_s: float = field(default_factory=lambda: _float("JOULE_LLM_TIMEOUT", 120.0))
    cloud_url: str = field(default_factory=lambda: os.environ.get("JOULE_CLOUD_URL", "http://localhost:8787"))
    sample_interval_s: float = field(default_factory=lambda: _float("JOULE_INTERVAL", 1.0))
    device_id: str = field(default_factory=lambda: os.environ.get("JOULE_DEVICE_ID", "laptop-1"))
