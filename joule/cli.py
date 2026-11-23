"""Command line: python -m joule <command>. Every feature works offline; only `sync` needs the server."""
from __future__ import annotations

import argparse
import json
import sys
import time

from joule import config, db
from joule.sensors import NAMES, SensorUnavailable, get_sensor


def _conn(args):
    return db.connect(args.db)


def cmd_init(args):
    conn = _conn(args)
    print(f"database ready: {args.db or config.db_path()}")
    print(json.dumps(config.Assumptions().as_dict(), indent=2))


def cmd_sense(args):
    sensor = get_sensor(args.source, args.interval)
    print(f"sensor: {sensor.name} ({sensor.provenance}) - {sensor.description}")
    for _ in range(args.n):
        try:
            r = sensor.read()
            print(f"{time.strftime('%H:%M:%S')}  {r.watts:7.3f} W  {r.provenance}  {r.detail or ''}")
        except SensorUnavailable as e:
            print(f"unavailable: {e}")
        if not sensor.blocking:
            time.sleep(args.interval)


def cmd_collect(args):
    from joule.collector import collect
    sensor = get_sensor(args.source, args.interval)
    print(f"collecting {args.seconds}s from {sensor.name} ({sensor.provenance}) every {args.interval}s")
    print(collect(_conn(args), sensor, args.seconds, args.interval, with_procs=not args.no_procs))


def cmd_experiment(args):
    from joule.experiment import experiment_and_receipt
    sensor = get_sensor(args.source, args.interval, seed=args.seed)
    eid, rid, receipt = experiment_and_receipt(_conn(args), args.scenario, sensor, args.repeats, args.quick,
                                               args.idle, args.interval, rec_id=args.rec, predict=not args.no_predict)
    print(f"\nexperiment {eid}, receipt {rid} (queued for sync)")
    print_receipt(receipt)


def print_receipt(b: dict):
    from joule.analytics.recommend import r
    print("=" * 72)
    print(f" RECEIPT · {b['title']}  [{b['provenance']} via {b['sensor']}]")
    print("=" * 72)
    print(f" baseline : {b['baseline']}\n optimized: {b['optimized']}")
    print(f" runs     : {b['repeats']} each, interleaved; idle power {b['idle_w']} W (median); basis: {b.get('basis')}")
    print(f" energy   : median {r(b['baseline_wh'] * 1000)} -> {r(b['optimized_wh'] * 1000)} mWh per run "
          f"(mean {r(b['baseline_wh_mean'] * 1000)} ± {r(b['baseline_wh_std'] * 1000)} -> "
          f"{r(b['optimized_wh_mean'] * 1000)} ± {r(b['optimized_wh_std'] * 1000)})")
    print(f" saved    : {r(b['measured_saved_wh'] * 1000)} mWh ({b['saved_pct']}%)  "
          f"significant: {'yes' if b['significant'] else 'no'} (Mann-Whitney p={b.get('p_value')}; "
          f"mean-based noise ±{r(b['noise_wh'] * 1000)} mWh)")
    if b.get("predicted_saved_wh") is not None:
        print(f" predicted: {r(b['predicted_saved_wh'] * 1000)} mWh (pilot)  error: {b.get('prediction_error_pct')}%")
    print(f" cost/CO2 : ₹{b['saved_inr']:.6f} · {b['saved_co2_g']:.4f} g CO2e per run "
          f"(₹{b['assumptions']['tariff_inr_per_kwh']}/kWh, {b['assumptions']['grid_kg_co2_per_kwh']} kg/kWh)")
    print(f" same work: {'yes' if b['equivalent_work'] else 'NO'} · trade-off: {b['tradeoff']}")


def cmd_calibrate(args):
    from joule.analytics.power_model import calibrate
    measured = get_sensor(args.source)
    if measured.provenance != "MEASURED":
        sys.exit("calibration needs a MEASURED source (unplug for battery, or sudo for powermetrics)")
    print(json.dumps(calibrate(measured, args.seconds), indent=2))


def cmd_analyze(args):
    from joule.analytics import recommend
    ids, summary = recommend.refresh(_conn(args))
    s = {k: v for k, v in summary.items() if k != "matrix"}
    print(json.dumps(s, indent=2, default=str))
    print(f"recommendations refreshed: {ids}")


def cmd_recommend(args):
    from joule.analytics import recommend
    conn = _conn(args)
    recommend.refresh(conn)
    for rec in db.list_recommendations(conn, None if args.all else "open"):
        flag = " ⚠ review" if rec["needs_review"] else ""
        pred = rec["facts"].get("prediction") or {}
        print(f"[{rec['id']}] {rec['title']} ({rec['status']}, confidence {rec['confidence']}){flag}")
        print(f"     {rec['facts'].get('headline', '')}")
        if pred:
            print(f"     predicted: {pred.get('saved_wh_per_day')} Wh/day, ₹{pred.get('saved_inr_per_month')}/month "
                  f"({pred.get('provenance')})")


def cmd_explain(args):
    from joule.slm import explain
    conn = _conn(args)
    rec = db.get_recommendation(conn, args.rec)
    if not rec:
        sys.exit(f"no recommendation {args.rec}")
    res = explain.explain(rec["facts"], model=args.model)
    rid = db.save_report(conn, "explanation", res.text, res.model, res.grounded, res.ungrounded, rec_id=rec["id"],
                         facts=rec["facts"], latency_s=res.latency_s, tokens=res.tokens)
    print(f"--- {res.model} | grounded={res.grounded} | attempts={res.attempts} | saved as report {rid}")
    print(res.text)
    for bad in res.rejected:
        print(f"\n(rejected draft, numbers not in facts)\n{bad}")


def cmd_report(args):
    from joule.slm.report import build_report
    out = build_report(_conn(args), use_slm=not args.no_slm, model=args.model)
    print(json.dumps(out, indent=2))


def cmd_decide(args):
    did = db.record_decision(_conn(args), args.rec, args.decision, args.note, config.Settings().device_id)
    print(f"decision {did} stored and queued for sync")


def cmd_queue(args):
    from joule.sync import outbox
    conn = _conn(args)
    print(json.dumps(outbox.stats(conn)))
    for it in outbox.items(conn, args.status, args.limit):
        nxt = max(0, it["next_attempt_at"] - time.time())
        print(f"#{it['id']:<4} {it['kind']:<12} {it['status']:<9} attempts={it['attempts']} "
              f"next_in={nxt:5.1f}s key={it['idem_key'][:8]} {it['last_error'] or ''}")


def cmd_sync(args):
    from joule.sync.worker import SyncWorker
    w = SyncWorker(args.db, args.url)
    if args.watch:
        print(f"watching {w.cloud_url} every {args.poll}s (Ctrl+C to stop)")
        try:
            w.run(args.poll)
        except KeyboardInterrupt:
            pass
    else:
        print(w.tick(_conn(args)) or "cloud unreachable - nothing sent, queue kept")


def cmd_cloud(args):
    from joule.sync import server
    argv = ["--port", str(args.port), "--db", args.cloud_db, "--fail-rate", str(args.fail_rate),
            "--drop-response-rate", str(args.drop_rate)]
    return server.main(argv)


def cmd_status(args):
    from joule.slm import client
    from joule.sync import outbox
    conn = _conn(args)
    s = config.Settings()
    n = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    print(f"database     : {args.db or config.db_path()} ({n} samples)")
    print(f"best sensor  : {get_sensor('auto').name}")
    print(f"SLM          : {s.llm_model} at {s.llm_base_url} -> "
          f"{'available' if client.is_available(settings=s) else 'not available (template fallback)'}")
    print(f"outbox       : {outbox.stats(conn)}")
    print(f"assumptions  : {json.dumps(config.Assumptions().as_dict())}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="joule", description="Joule Receipts - offline-first energy copilot")
    p.add_argument("--db", default=None, help="SQLite path (default data/joule.db or $JOULE_DB)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, "create the database and show assumptions")
    sp = add("sense", cmd_sense, "print live readings")
    sp.add_argument("--source", choices=NAMES, default="auto")
    sp.add_argument("--n", type=int, default=5)
    sp.add_argument("--interval", type=float, default=1.0)
    sp = add("collect", cmd_collect, "store readings + per-process attribution")
    sp.add_argument("--source", choices=NAMES, default="auto")
    sp.add_argument("--seconds", type=float, default=60)
    sp.add_argument("--interval", type=float, default=1.0)
    sp.add_argument("--no-procs", action="store_true")
    sp = add("experiment", cmd_experiment, "baseline vs optimized A/B runs -> receipt")
    sp.add_argument("scenario", choices=["idle", "batching", "inference"])
    sp.add_argument("--source", choices=NAMES, default="auto")
    sp.add_argument("--repeats", type=int, default=5)
    sp.add_argument("--idle", type=float, default=20.0, help="seconds of idle measurement first")
    sp.add_argument("--interval", type=float, default=1.0)
    sp.add_argument("--quick", action="store_true", help="small sizes (for a fast check)")
    sp.add_argument("--no-predict", action="store_true")
    sp.add_argument("--rec", type=int, default=None, help="recommendation id this experiment verifies")
    sp.add_argument("--seed", type=int, default=42)
    sp = add("calibrate", cmd_calibrate, "fit the CPU estimate against a measured source")
    sp.add_argument("--source", choices=["auto", "battery", "powermetrics"], default="auto")
    sp.add_argument("--seconds", type=float, default=15.0, help="seconds per load level")
    add("analyze", cmd_analyze, "states, Markov summary, refresh recommendations")
    sp = add("recommend", cmd_recommend, "list recommendations")
    sp.add_argument("--all", action="store_true")
    sp = add("explain", cmd_explain, "SLM explanation of one recommendation (grounded)")
    sp.add_argument("rec", type=int)
    sp.add_argument("--model", default=None)
    sp = add("report", cmd_report, "write a Markdown report (SLM summary)")
    sp.add_argument("--no-slm", action="store_true")
    sp.add_argument("--model", default=None)
    sp = add("decide", cmd_decide, "accept / reject / defer a recommendation (queued for sync)")
    sp.add_argument("rec", type=int)
    sp.add_argument("decision", choices=["accept", "reject", "defer"])
    sp.add_argument("--note", default="")
    sp = add("queue", cmd_queue, "show the outbox")
    sp.add_argument("--status", default=None)
    sp.add_argument("--limit", type=int, default=20)
    sp = add("sync", cmd_sync, "send queued items now, or --watch to auto-sync on reconnect")
    sp.add_argument("--watch", action="store_true")
    sp.add_argument("--poll", type=float, default=3.0)
    sp.add_argument("--url", default=None)
    sp = add("cloud", cmd_cloud, "run the cloud sync server locally")
    sp.add_argument("--port", type=int, default=8787)
    sp.add_argument("--cloud-db", default="cloud-data/cloud.db")
    sp.add_argument("--fail-rate", type=float, default=0.0)
    sp.add_argument("--drop-rate", type=float, default=0.0)
    add("status", cmd_status, "what is available right now")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args) or 0
