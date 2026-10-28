"""UI harness: seed a demo pipeline through every stage so the UI opens on a fully-populated state.

Usage:
  python -m tbamr.harness seed                 (re)create a seeded demo DB
  python -m tbamr.harness serve                seed if the DB is missing, then launch uvicorn
  python -m tbamr.harness serve --reseed       force a fresh seed, then launch
  python -m tbamr.harness --db some.db serve   point everything at a different DB file

Why this exists: iterating on the UI shouldn't require Docker + TB-Profiler to go round every
time. The harness builds the same pipeline the demo mode uses, runs it to completion through the
orchestrator API, captures a scoped execution for every step so the Logs tab has rich content,
and persists the resulting SQLite file. The server then starts against that DB in replay mode.

For live-reload UI work, run `npm run dev` in another terminal — it already proxies /api to :8000.

A soft guard on --reseed only unlinks files whose name contains "harness" so pointing the tool at
a real pipeline DB cannot wipe it by accident.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .api import build_orchestrator, create_app


HARNESS_DB_DEFAULT = "tbamr-harness.db"


SCOPE = {
    "question": "What is the lineage composition and resistance profile of recent MTB sequencing in Indonesia?",
    "country": "Indonesia",
    "target_drugs": ["Rifampicin", "Isoniazid"],
    "cohort_target": 8,
}

PI = {"role": "pi", "person": "Ana"}
ANALYST = {"role": "analyst", "person": "Budi"}


def seed(db_path: str) -> dict:
    """Build a demo orchestrator and step through all six stages via the real HTTP endpoints, so each
    step gets the same scoped execution + structured result the UI would see when a human clicks it.
    Returns a small summary dict so callers (and tests) can assert what was produced."""
    from fastapi.testclient import TestClient  # local import: fastapi is already in the backend deps

    orch = build_orchestrator("demo", "replay", db_path)
    # Pre-seed the Indonesia-shaped scope on the state object: the demo samples were authored around
    # it, and setting it here lets us POST /api/scope through the normal validation path below.
    orch.state.country = SCOPE["country"]
    orch.save()
    app = create_app(orch)

    def expect(resp, label: str) -> dict:
        if resp.status_code >= 400:
            raise SystemExit(f"harness step {label!r} failed with {resp.status_code}: {resp.text}")
        try:
            return resp.json()
        except ValueError:
            return {}

    with TestClient(app) as c:
        expect(c.post("/api/scope", json=SCOPE), "set scope")
        expect(c.post("/api/stages/1/run"), "Stage 1")
        # Mark the Guardian's raw as viewed so the gate's note_raw records a receipt (not required,
        # but it keeps the audit trail in the seeded DB looking realistic).
        orch.raw_view("scope", "guardian", **PI)
        expect(c.post("/api/gates/scope", json=PI), "Approve scope")
        expect(c.post("/api/stages/2/run"), "Stage 2")
        orch.raw_view("cohort", "all", **PI)
        expect(c.post("/api/gates/cohort", json=PI), "Approve cohort")
        expect(c.post("/api/stages/3/run"), "Stage 3")
        orch.raw_view("qc", "all", **ANALYST)
        expect(c.post("/api/gates/qc", json=ANALYST), "Confirm QC")
        expect(c.post("/api/stages/4/run"), "Stage 4")
        orch.raw_view("profiling", "all", **ANALYST)
        expect(c.post("/api/gates/profiling", json=ANALYST), "Close profiling batch")
        expect(c.post("/api/stages/5/run"), "Stage 5")
        expect(c.post("/api/stages/6/run"), "Stage 6")
        expect(c.post("/api/report/summary"), "Draft report summary")

    return {
        "db": db_path,
        "samples": len(orch.state.samples),
        "in_cohort": sum(1 for s in orch.state.samples if s.in_cohort),
        "qc_pass": sum(1 for s in orch.state.samples if s.qc == "Pass"),
        "profiled": sum(1 for s in orch.state.samples if s.profiling == "Done"),
        "report_version": (orch.state.report or {}).get("version"),
    }


def _safe_unlink(db_path: Path) -> None:
    """Soft guard: only remove files whose name contains 'harness' so --reseed cannot wipe a real DB."""
    if "harness" not in db_path.name:
        raise SystemExit(f"refusing to --reseed {db_path}: the filename does not contain 'harness'. "
                         "Rename the target or use --db tbamr-harness.db.")
    if db_path.exists():
        db_path.unlink()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("command", choices=["seed", "serve"], help="seed: create the DB · serve: seed-if-missing then start uvicorn")
    p.add_argument("--db", default=os.environ.get("TBAMR_HARNESS_DB", HARNESS_DB_DEFAULT),
                   help=f"path to the SQLite file (default: {HARNESS_DB_DEFAULT})")
    p.add_argument("--reseed", action="store_true", help="delete the DB first (only works on *harness*.db files)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    db_path = Path(args.db)
    if args.reseed:
        _safe_unlink(db_path)

    if not db_path.exists():
        print(f"Seeding {db_path}…", file=sys.stderr)
        summary = seed(str(db_path))
        print(f"Seeded: {summary}", file=sys.stderr)
    else:
        print(f"Using existing {db_path} (pass --reseed to rebuild).", file=sys.stderr)

    if args.command == "seed":
        return 0

    # serve: launch uvicorn with the seeded DB. The env is set BEFORE importing uvicorn/app so the
    # module-level `app = create_app()` in api.py reads these when it builds its orchestrator.
    os.environ["TBAMR_DB"] = str(db_path)
    os.environ.setdefault("TBAMR_DATA", "demo")
    os.environ.setdefault("TBAMR_BRAIN", "replay")
    import uvicorn
    uvicorn.run("tbamr.api:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
