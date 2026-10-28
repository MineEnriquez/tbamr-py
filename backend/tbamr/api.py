"""FastAPI service exposing the agent team to the React screen.

Run:  uvicorn tbamr.api:app --reload      (from the backend folder)
Env:  TBAMR_DATA=demo|live   TBAMR_BRAIN=replay|claude   ANTHROPIC_API_KEY=...   TBAMR_DB=path.db
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .core.decisions import DecisionLog, GuardrailViolation
from .core.executions import capture_execution
from .core.orchestrator import Orchestrator, PermissionDenied, StageError
from .llm.client import make_client
from .tools.demo import DemoDataTools
from .tools.ena import DataTools


def build_orchestrator(data_mode: str | None = None, brain: str | None = None, db_path: str | None = None, data=None, client=None) -> Orchestrator:
    data_mode = (data_mode or os.environ.get("TBAMR_DATA", "demo")).lower()
    db_path = db_path or os.environ.get("TBAMR_DB", f"tbamr-{data_mode}.db")
    log = DecisionLog(db_path)
    return Orchestrator(log, client or make_client(brain), data or (DemoDataTools() if data_mode == "demo" else DataTools()))


def _run_label_from_state(orch: Orchestrator) -> str:
    """Describe the run that's about to be closed, so previous runs are legible in the Logs tab.
    Prefers the released report version, then the approved scope's country+drugs, then just the
    scope question. Falls back to '' (the UI shows the start time)."""
    st = orch.state
    rep = st.report
    if rep and rep.get("version"):
        return f"Report v{rep['version']}" + (" · final" if st.gates.get("release", {}).get("kind") == "final" else "")
    if st.scope and st.gates.get("scope"):
        loc = st.country or "worldwide"
        drugs = ", ".join(st.target_drugs or [])
        return f"Scope: {loc}" + (f" · {drugs}" if drugs else "")
    if (st.question or "").strip():
        q = st.question.strip().split(".")[0]
        return (q[:80] + "…") if len(q) > 80 else q
    return ""


class Who(BaseModel):
    role: str
    person: str = ""


class Resolve(Who):
    run: str
    decision: str
    rationale: str = ""


class Review(Who):
    fid: str
    decision: str
    rationale: str = ""


class Override(Who):
    run: str
    field: str
    to: str
    rationale: str = ""


class Cosign(Who):
    override_id: str


class Release(Who):
    kind: str = "draft"


class Scope(BaseModel):
    question: str
    country: str = ""  # empty = worldwide search
    target_drugs: list[str] = ["Rifampicin", "Isoniazid"]
    cohort_target: int = 8


class RunProfiler(Who):
    runs: list[str]


def create_app(orch: Orchestrator | None = None) -> FastAPI:
    app = FastAPI(title="TB-AMR Agentic Pipeline", version="0.2.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])
    app.state.orch = orch or build_orchestrator()

    def O() -> Orchestrator:
        return app.state.orch

    def guard(fn, *a, **k):
        try:
            return fn(*a, **k)
        except PermissionDenied as e:
            raise HTTPException(403, str(e))
        except (StageError, GuardrailViolation) as e:
            raise HTTPException(409, str(e))

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return O().snapshot()

    @app.get("/api/team")
    def team():
        return O().team()

    @app.get("/api/decisions")
    def decisions(sample: str | None = None):
        return O().log.for_sample(sample) if sample else O().log.all()

    @app.get("/api/trace")
    def trace(agent: str | None = None, limit: int = 300):
        return O().log.traces(agent, limit)

    @app.get("/api/metrics")
    def metrics():
        return O().metrics()

    @app.get("/api/raw/receipts")
    def raw_receipts(role: str = "pi", person: str = ""):
        return O().log.receipts(O().ident(role, person))

    @app.get("/api/raw/{kind}/{key}")
    def raw_view(kind: str, key: str, role: str = "pi", person: str = ""):
        try:
            return O().raw_view(kind, key, role, person)
        except StageError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/scope")
    def set_scope(s: Scope):
        st = O().state
        if st.stage_status["1"] != "ready":
            raise HTTPException(409, "The scope can only be edited before the Guardian runs. Use /api/scope/reopen to go back.")
        st.question, st.country, st.target_drugs, st.cohort_target = s.question, s.country, s.target_drugs, s.cohort_target
        O().save()
        return {"ok": True}

    @app.post("/api/scope/reopen")
    def reopen_scope():
        with capture_execution(O().log, "Reopen scope"):
            guard(O().reopen_scope)
        return {"ok": True}

    @app.post("/api/stages/{n}/run")
    def run_stage(n: int):
        with capture_execution(O().log, f"Stage {n}"):
            return guard(O().run_stage, n)

    @app.post("/api/gates/scope")
    def g_scope(w: Who):
        with capture_execution(O().log, "Approve scope"):
            guard(O().approve_scope, w.role, w.person)
        return {"ok": True}

    @app.post("/api/gates/cohort")
    def g_cohort(w: Who):
        with capture_execution(O().log, "Approve cohort"):
            guard(O().approve_cohort, w.role, w.person)
        return {"ok": True}

    @app.post("/api/gates/qc")
    def g_qc(w: Who):
        with capture_execution(O().log, "Confirm QC"):
            guard(O().confirm_qc, w.role, w.person)
        return {"ok": True}

    @app.post("/api/gates/profiling")
    def g_prof(w: Who):
        with capture_execution(O().log, "Close profiling batch"):
            guard(O().close_profiling, w.role, w.person)
        return {"ok": True}

    @app.post("/api/holds/resolve")
    def resolve(r: Resolve):
        with capture_execution(O().log, f"Resolve hold · {r.run}"):
            guard(O().resolve_hold, r.role, r.person, r.run, r.decision, r.rationale)
        return {"ok": True}

    @app.post("/api/qc/resolve")
    def resolve_qc(r: Resolve):
        with capture_execution(O().log, f"Resolve QC · {r.run}"):
            guard(O().resolve_qc, r.role, r.person, r.run, r.decision, r.rationale)
        return {"ok": True}

    @app.post("/api/review")
    def review(r: Review):
        with capture_execution(O().log, f"Finding review · {r.fid}"):
            guard(O().review, r.role, r.person, r.fid, r.decision, r.rationale)
        return {"ok": True}

    @app.post("/api/overrides")
    def override(o: Override):
        with capture_execution(O().log, f"Override · {o.run}"):
            return guard(O().override, o.role, o.person, o.run, o.field, o.to, o.rationale)

    @app.post("/api/overrides/cosign")
    def cosign(c: Cosign):
        with capture_execution(O().log, f"Cosign override · {c.override_id}"):
            guard(O().cosign, c.role, c.person, c.override_id)
        return {"ok": True}

    @app.post("/api/release")
    def release(r: Release):
        with capture_execution(O().log, f"Release report ({r.kind})"):
            guard(O().release, r.role, r.person, r.kind)
        return {"ok": True}

    @app.post("/api/report/summary")
    def summary():
        with capture_execution(O().log, "Draft report summary"):
            return {"text": guard(O().draft_summary)}

    class SummaryEdit(BaseModel):
        text: str

    @app.put("/api/report/summary")
    def save_summary(s: SummaryEdit):
        return {"text": guard(O().save_summary, s.text)}

    @app.post("/api/profiling/import")
    async def import_results(role: str, person: str = "", files: list[UploadFile] = File(...)):
        parsed = []
        for f in files:
            try:
                parsed.append((f.filename or "result.json", json.loads(await f.read())))
            except ValueError:
                raise HTTPException(400, f"{f.filename} is not valid JSON.")
        with capture_execution(O().log, f"Import TB-Profiler results ({len(parsed)} file(s))"):
            return guard(O().import_results, role, person, parsed)

    @app.post("/api/profiling/run")
    def run_profiler(r: RunProfiler):
        # The pool runs asynchronously in a background thread; capture happens there, inside run_profiler().
        return guard(O().run_profiler, r.role, r.person, r.runs)

    @app.post("/api/reset")
    def reset(data: str = "demo", brain: str | None = None):
        """Reset the pipeline. Previously this unlinked the DB file, which raced against concurrent
        frontend polls (metrics/state/decisions) — their open SQLite connections auto-recreated the
        file without a schema, so the next SELECT hit `no such table: trace`. We now clear tables
        in place behind the orchestrator's own lock so the schema is always valid, and only unlink
        the file when switching modes (demo <-> live use different file paths anyway).

        Executions and their captured logs are preserved across resets: the active pipeline run is
        closed (ended_at + a label derived from the scope), a new run is opened, and the Logs tab
        can look back at previous runs. Decisions, agent traces, raw-data cache, view receipts and
        pipeline state are still cleared so the next cycle starts fresh."""
        path = Path(os.environ.get("TBAMR_DB", f"tbamr-{data}.db"))
        old = getattr(app.state, "orch", None)
        if old is not None:
            with old.lock:
                try:
                    rid = old.log.active_run_id()
                    has_execs = old.log.db.execute("SELECT 1 FROM executions WHERE run_id = ? LIMIT 1", (rid,)).fetchone()
                    if has_execs:  # only close+rotate if the active run has something worth preserving
                        old.log.close_active_run(_run_label_from_state(old))
                        for table in ("decisions", "trace", "kv", "raw", "views"):
                            old.log.db.execute(f"DELETE FROM {table}")
                        old.log.db.commit()
                        old.log.start_run()
                    else:
                        for table in ("decisions", "trace", "kv", "raw", "views"):
                            old.log.db.execute(f"DELETE FROM {table}")
                        old.log.db.commit()
                except Exception:
                    pass  # schema was already broken; rebuilding below will recreate it
        app.state.orch = build_orchestrator(data, brain, str(path))
        return {"ok": True}

    @app.get("/api/runs")
    def list_runs():
        runs = O().log.list_runs()
        active_id = O().log.active_run_id()
        for r in runs:
            r["active"] = r["id"] == active_id
        return runs

    @app.get("/api/executions")
    def list_executions(limit: int = 100, run_id: int | None = None):
        return O().log.list_executions(limit=max(1, min(500, int(limit))), run_id=run_id)

    @app.get("/api/executions/{execution_id}")
    def get_execution(execution_id: int):
        row = O().log.get_execution(execution_id)
        if not row:
            raise HTTPException(404, f"No execution {execution_id}.")
        return row

    # serve the built React app if present
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app


app = create_app() if os.environ.get("TBAMR_NO_APP") != "1" else None
