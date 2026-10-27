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
from .core.orchestrator import Orchestrator, PermissionDenied, StageError
from .llm.client import make_client
from .tools.demo import DemoDataTools
from .tools.ena import DataTools


def build_orchestrator(data_mode: str | None = None, brain: str | None = None, db_path: str | None = None, data=None, client=None) -> Orchestrator:
    data_mode = (data_mode or os.environ.get("TBAMR_DATA", "demo")).lower()
    db_path = db_path or os.environ.get("TBAMR_DB", f"tbamr-{data_mode}.db")
    log = DecisionLog(db_path)
    return Orchestrator(log, client or make_client(brain), data or (DemoDataTools() if data_mode == "demo" else DataTools()))


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
            raise HTTPException(409, "The scope can only be edited before the Guardian runs.")
        st.question, st.country, st.target_drugs, st.cohort_target = s.question, s.country, s.target_drugs, s.cohort_target
        O().save()
        return {"ok": True}

    @app.post("/api/stages/{n}/run")
    def run_stage(n: int):
        return guard(O().run_stage, n)

    @app.post("/api/gates/scope")
    def g_scope(w: Who):
        guard(O().approve_scope, w.role, w.person)
        return {"ok": True}

    @app.post("/api/gates/cohort")
    def g_cohort(w: Who):
        guard(O().approve_cohort, w.role, w.person)
        return {"ok": True}

    @app.post("/api/gates/qc")
    def g_qc(w: Who):
        guard(O().confirm_qc, w.role, w.person)
        return {"ok": True}

    @app.post("/api/gates/profiling")
    def g_prof(w: Who):
        guard(O().close_profiling, w.role, w.person)
        return {"ok": True}

    @app.post("/api/holds/resolve")
    def resolve(r: Resolve):
        guard(O().resolve_hold, r.role, r.person, r.run, r.decision, r.rationale)
        return {"ok": True}

    @app.post("/api/qc/resolve")
    def resolve_qc(r: Resolve):
        guard(O().resolve_qc, r.role, r.person, r.run, r.decision, r.rationale)
        return {"ok": True}

    @app.post("/api/review")
    def review(r: Review):
        guard(O().review, r.role, r.person, r.fid, r.decision, r.rationale)
        return {"ok": True}

    @app.post("/api/overrides")
    def override(o: Override):
        return guard(O().override, o.role, o.person, o.run, o.field, o.to, o.rationale)

    @app.post("/api/overrides/cosign")
    def cosign(c: Cosign):
        guard(O().cosign, c.role, c.person, c.override_id)
        return {"ok": True}

    @app.post("/api/release")
    def release(r: Release):
        guard(O().release, r.role, r.person, r.kind)
        return {"ok": True}

    @app.post("/api/report/summary")
    def summary():
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
        return guard(O().import_results, role, person, parsed)

    @app.post("/api/profiling/run")
    def run_profiler(r: RunProfiler):
        return guard(O().run_profiler, r.role, r.person, r.runs)

    @app.post("/api/reset")
    def reset(data: str = "demo", brain: str | None = None):
        path = Path(os.environ.get("TBAMR_DB", f"tbamr-{data}.db"))
        if path.exists() and str(path) != ":memory:":
            path.unlink()
        app.state.orch = build_orchestrator(data, brain, str(path))
        return {"ok": True}

    # serve the built React app if present
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app


app = create_app() if os.environ.get("TBAMR_NO_APP") != "1" else None
