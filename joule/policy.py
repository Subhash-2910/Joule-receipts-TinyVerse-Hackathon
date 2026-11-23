"""The Goal switch: one setting that tunes the whole copilot. Stored in the local database, so it survives restarts,
and every change is queued for sync like any other decision.

               which models explain              anomaly alert when an app uses  hide advice saving less than
best quality   1.5B only                          4x its usual power              1 Wh/day
balanced       0.5B first, 1.5B if it fails check 3x                              0.2 Wh/day
lowest energy  0.5B only (template if it fails)   2x                              0 (show everything)
"""
from __future__ import annotations

from joule import config, db

GOALS: dict[str, dict] = {
    "quality": {"label": "Best quality", "models": ["qwen2.5:1.5b"], "anomaly_ratio": 4.0, "min_wh_day": 1.0,
                "blurb": "Always the larger model; only strong alerts and big savings."},
    "balanced": {"label": "Balanced", "models": ["qwen2.5:0.5b", "qwen2.5:1.5b"], "anomaly_ratio": 3.0,
                 "min_wh_day": 0.2,
                 "blurb": "Small model first, larger one only when the fact check fails."},
    "lowest": {"label": "Lowest energy", "models": ["qwen2.5:0.5b"], "anomaly_ratio": 2.0, "min_wh_day": 0.0,
               "blurb": "Small model only (template if it fails); every alert and saving shown."},
}
DEFAULT = "balanced"


def get_goal(conn) -> str:
    g = db.get_meta(conn, "goal", DEFAULT)
    return g if g in GOALS else DEFAULT


def policy(conn) -> dict:
    g = get_goal(conn)
    return {"goal": g, **GOALS[g]}


def set_goal(conn, goal: str) -> bool:
    """Returns True if the goal changed. The change and its outbox item commit together."""
    from joule.sync import outbox
    if goal not in GOALS:
        raise ValueError(f"goal must be one of {list(GOALS)}")
    if goal == get_goal(conn):
        return False
    with db.tx(conn):
        db.set_meta(conn, "goal", goal, in_tx=True)
        outbox.enqueue(conn, "policy", {"device_id": config.Settings().device_id, "goal": goal,
                                        "models": GOALS[goal]["models"]}, in_tx=True)
    return True
