"""FastAPI service exposing the agent team to the React screen.

Run:  uvicorn tbamr.api:app --reload      (from the backend folder)
Env:  TBAMR_DATA=demo|live   TBAMR_BRAIN=replay|claude   ANTHROPIC_API_KEY=...   TBAMR_DB=path.db
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .article import render_article_html
from .core import auth
from .core.decisions import DecisionLog, GuardrailViolation
from .core.executions import capture_execution
from .core.geo import country_catalogue, regions_for, resolve_target
from .core.models import DEFAULT_COHORT_TARGET, DRUGS, GATES
from .core.orchestrator import Orchestrator, PermissionDenied, StageError
from .llm.client import make_client
from .stores import cache as cache_module, mongo as mongo_module, results as results_module
from .stores.cache import CACHE_NAMESPACES
from .tools.demo import DemoDataTools
from .tools.ena import DataTools


def build_orchestrator(data_mode: str | None = None, brain: str | None = None, db_path: str | None = None, data=None, client=None) -> Orchestrator:
    data_mode = (data_mode or os.environ.get("TBAMR_DATA", "demo")).lower()
    db_path = db_path or os.environ.get("TBAMR_DB", f"tbamr-{data_mode}.db")
    log = DecisionLog(db_path)
    from .core import rulesettings
    rulesettings.apply()  # load the PI's saved thresholds / rule versions before any stage runs
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
        loc = (f"{st.region}, {st.country}" if st.region else st.country) or "target not set"
        drugs = ", ".join(st.target_drugs or [])
        return f"Scope: {loc}" + (f" · {drugs}" if drugs else "")
    if (st.question or "").strip():
        q = st.question.strip().split(".")[0]
        return (q[:80] + "…") if len(q) > 80 else q
    return ""


class Who(BaseModel):
    role: str
    person: str = ""


class RuleChange(Who):
    changes: dict[str, float] = {}
    rationale: str = ""
    status: dict[str, str] = {}
    basis: dict[str, str] = {}


class CacheToggle(BaseModel):
    enabled: bool


class WarningResponse(Who):
    decision: str  # "accept" | "disagree"
    rationale: str = ""


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
    country: str = ""  # INSDC country name or "Worldwide"; empty → must be named in the question, else Stage 1 blocks
    region: str = ""  # optional subnational target inside the country (free text, e.g. "West Java")
    target_drugs: list[str] = list(DRUGS)  # chosen from models.DRUGS; default all
    cohort_target: int = DEFAULT_COHORT_TARGET


class RunProfiler(Who):
    runs: list[str]


class SummaryEdit(BaseModel):
    text: str
    role: str = ""  # with sign-in on, the role you're acting in (PI or Deputy PI)


class Login(BaseModel):
    name: str
    password: str


class PasswordChange(BaseModel):
    current: str
    new: str


class NewUser(BaseModel):
    name: str
    password: str
    roles: list[str] = []
    admin: bool = False


class UserPatch(BaseModel):
    roles: list[str] | None = None
    admin: bool | None = None
    disabled: bool | None = None


class PasswordReset(BaseModel):
    password: str


def create_app(orch: Orchestrator | None = None) -> FastAPI:
    app = FastAPI(title="TB-AMR Agentic Pipeline", version="0.2.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])
    app.state.orch = orch or build_orchestrator()

    def O() -> Orchestrator:
        return app.state.orch

    # ---- Sign-in (TBAMR_AUTH=on) ----------------------------------------------
    # With auth on, every /api call except sign-in/status needs a valid session cookie, and the
    # person on every decision is the signed-in user, acting only in a role an admin assigned them.
    # With auth off (the demo default) requests are trusted as before and the UI says so.
    OPEN = {"/api/auth/login", "/api/auth/status"}

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        request.state.user = None
        if auth.enabled() and request.url.path.startswith("/api/"):
            try:
                request.state.user = auth.user_from_token(request.cookies.get(auth.COOKIE))
            except auth.AuthError as e:
                if request.url.path not in OPEN:
                    return JSONResponse({"detail": str(e), "auth": "required"}, status_code=401)
        return await call_next(request)

    def W(request: Request, role: str, person: str = "") -> tuple[str, str]:
        """(role, person) for this request: the signed-in user when auth is on, else what was sent."""
        if not auth.enabled():
            return role, person
        try:
            return auth.act_as(request.state.user, role)
        except auth.Forbidden as e:
            raise HTTPException(403, str(e))

    def need(request: Request, *, admin: bool = False, roles: list[str] | None = None) -> None:
        """With auth on, require the admin flag or one of `roles` (either is enough when both are given)."""
        if not auth.enabled():
            return
        u = request.state.user
        if (admin and u.get("admin")) or (roles and set(roles) & set(u.get("roles", []))):
            return
        what = " or ".join((["admin"] if admin else []) + [auth.ROLES[r] for r in roles or []])
        raise HTTPException(403, f"This needs {what} permission.")

    def user_api(fn, *a, **k):
        try:
            return fn(*a, **k)
        except auth.UserError as e:
            raise HTTPException(400, str(e))

    def set_cookie(resp: Response, u: dict[str, Any]) -> None:
        resp.set_cookie(auth.COOKIE, auth.issue_token(u), max_age=auth.SESSION_TTL, httponly=True, samesite="strict",
                        secure=os.environ.get("TBAMR_COOKIE_SECURE", "").lower() in ("1", "on", "true"), path="/")

    @app.get("/api/auth/status")
    def auth_status(request: Request):
        u = request.state.user
        return {"enabled": auth.enabled(), "user": auth.public(u) if u else None}

    @app.post("/api/auth/login")
    def login(b: Login, response: Response):
        if not auth.enabled():
            raise HTTPException(409, "Sign-in is off (TBAMR_AUTH is not set).")
        try:
            u = auth.authenticate(b.name, b.password)
        except auth.AuthError as e:
            raise HTTPException(401, str(e))
        set_cookie(response, u)
        return {"user": auth.public(u)}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, everywhere: bool = False):
        if everywhere and request.state.user:
            auth.sign_out_everywhere(request.state.user["name"])
        response.delete_cookie(auth.COOKIE, path="/")
        return {"ok": True}

    @app.post("/api/auth/password")
    def change_password(b: PasswordChange, request: Request, response: Response):
        u = request.state.user
        if not u:
            raise HTTPException(409, "Sign-in is off.")
        try:
            auth.authenticate(u["name"], b.current)
        except auth.AuthError:
            raise HTTPException(403, "Current password is wrong.")
        user_api(auth.set_password, u["name"], b.new, by=u["name"])
        set_cookie(response, auth.get_user(u["name"]))  # keep this browser signed in; others are signed out
        return {"ok": True}

    # ---- Admin: users and permissions (admin flag only) -------------------------
    @app.get("/api/admin/users")
    def users_list(request: Request):
        need(request, admin=True)
        return {"enabled": auth.enabled(), "users": auth.list_users(), "history": auth.history(), "roles": auth.ROLES}

    @app.post("/api/admin/users")
    def users_create(b: NewUser, request: Request):
        need(request, admin=True)
        return user_api(auth.create_user, b.name, b.password, b.roles, b.admin, by=(request.state.user or {}).get("name", "unauthenticated"))

    @app.patch("/api/admin/users/{name}")
    def users_update(name: str, b: UserPatch, request: Request):
        need(request, admin=True)
        return user_api(auth.update_user, name, (request.state.user or {}).get("name", "unauthenticated"), b.roles, b.admin, b.disabled)

    @app.post("/api/admin/users/{name}/password")
    def users_reset_password(name: str, b: PasswordReset, request: Request):
        need(request, admin=True)
        user_api(auth.set_password, name, b.password, by=(request.state.user or {}).get("name", "unauthenticated"))
        return {"ok": True}

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
    def raw_receipts(request: Request, role: str = "pi", person: str = ""):
        role, person = W(request, role, person)
        return O().log.receipts(O().ident(role, person))

    @app.get("/api/reports")
    def reports():
        return O().log.report_history()

    @app.get("/api/raw/{kind}/{key}")
    def raw_view(kind: str, key: str, request: Request, role: str = "pi", person: str = ""):
        role, person = W(request, role, person)
        try:
            return O().raw_view(kind, key, role, person)
        except StageError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/scope")
    def set_scope(s: Scope):
        st = O().state
        if st.stage_status["1"] != "ready":
            raise HTTPException(409, "The scope can only be edited before the Guardian runs. Use /api/scope/reopen to go back.")
        if s.question.strip() != (st.question or "").strip():
            st.revision_rounds = 0  # the researcher wrote their own question: it is no longer the Guardian's wording
        known = {d.lower(): d for d in DRUGS}
        unknown = [d for d in s.target_drugs if d.strip().lower() not in known]
        if unknown:
            raise HTTPException(400, f"Unknown drug(s): {', '.join(unknown)}. Choose from: {', '.join(DRUGS)}.")
        chosen = {known[d.strip().lower()] for d in s.target_drugs}
        drugs = [d for d in DRUGS if d in chosen]  # canonical names, catalogue order, no duplicates
        st.question, st.country, st.region, st.target_drugs, st.cohort_target = s.question, s.country, s.region, drugs, s.cohort_target
        O().save()
        return {"ok": True}

    @app.get("/api/geo/countries")
    def geo_countries():
        """Country options: WHO high-burden TB countries, the WHO watchlist, then all other countries."""
        return country_catalogue()

    @app.get("/api/geo/regions")
    def geo_regions(country: str = ""):
        """First-level regions (provinces, states, ...) for a catalogued country; [] when none are on file."""
        return {"country": country, "regions": [{"name": r["name"], "type": r.get("type")} for r in regions_for(country)]}

    @app.get("/api/scope/target")
    def scope_target(question: str = "", country: str = "", region: str = ""):
        """Resolve the target population the same way Stage 1 will, so the form can show it before running."""
        return resolve_target(question, country, region)

    @app.post("/api/scope/warnings/{idx}")
    def respond_warning(idx: int, b: WarningResponse, request: Request):
        b.role, b.person = W(request, b.role, b.person)
        with capture_execution(O().log, f"Respond to scope warning {idx + 1}"):
            guard(O().respond_warning, b.role, b.person, idx, b.decision, b.rationale)
        return {"ok": True}

    @app.post("/api/scope/revised-question")
    def adopt_revised_question(b: Who, request: Request):
        b.role, b.person = W(request, b.role, b.person)
        with capture_execution(O().log, "Adopt revised question"):
            return {"question": guard(O().adopt_revised_question, b.role, b.person)}

    @app.post("/api/scope/reopen")
    def reopen_scope():
        with capture_execution(O().log, "Reopen scope"):
            guard(O().reopen_scope)
        return {"ok": True}

    @app.post("/api/stages/{n}/run")
    def run_stage(n: int):
        with capture_execution(O().log, f"Stage {n}") as ctx:
            return ctx.record(guard(O().run_stage, n))

    @app.post("/api/gates/scope")
    def g_scope(w: Who, request: Request):
        w.role, w.person = W(request, w.role, w.person)
        with capture_execution(O().log, "Approve scope") as ctx:
            guard(O().approve_scope, w.role, w.person)
            ctx.record({"by": w.person, "role": w.role})
        return {"ok": True}

    @app.post("/api/gates/cohort")
    def g_cohort(w: Who, request: Request):
        w.role, w.person = W(request, w.role, w.person)
        with capture_execution(O().log, "Approve cohort") as ctx:
            guard(O().approve_cohort, w.role, w.person)
            ctx.record({"by": w.person, "role": w.role, "cohort_size": sum(1 for s in O().state.samples if s.in_cohort)})
        return {"ok": True}

    @app.post("/api/gates/qc")
    def g_qc(w: Who, request: Request):
        w.role, w.person = W(request, w.role, w.person)
        with capture_execution(O().log, "Confirm QC") as ctx:
            guard(O().confirm_qc, w.role, w.person)
            samples = O().state.samples
            ctx.record({"by": w.person, "role": w.role,
                        "qc_pass": sum(s.qc == "Pass" for s in samples),
                        "qc_escalated": sum(s.qc == "Escalated" for s in samples),
                        "qc_excluded": sum(s.qc == "Excluded" for s in samples)})
        return {"ok": True}

    @app.post("/api/gates/profiling")
    def g_prof(w: Who, request: Request):
        w.role, w.person = W(request, w.role, w.person)
        with capture_execution(O().log, "Close profiling batch") as ctx:
            guard(O().close_profiling, w.role, w.person)
            ctx.record({"by": w.person, "role": w.role,
                        "profiled": sum(s.profiling == "Done" for s in O().state.samples)})
        return {"ok": True}

    @app.post("/api/holds/resolve")
    def resolve(r: Resolve, request: Request):
        r.role, r.person = W(request, r.role, r.person)
        with capture_execution(O().log, f"Resolve hold · {r.run}") as ctx:
            guard(O().resolve_hold, r.role, r.person, r.run, r.decision, r.rationale)
            ctx.record({"run": r.run, "decision": r.decision, "rationale": r.rationale, "by": r.person, "role": r.role})
        return {"ok": True}

    @app.post("/api/qc/resolve")
    def resolve_qc(r: Resolve, request: Request):
        r.role, r.person = W(request, r.role, r.person)
        with capture_execution(O().log, f"Resolve QC · {r.run}") as ctx:
            guard(O().resolve_qc, r.role, r.person, r.run, r.decision, r.rationale)
            ctx.record({"run": r.run, "decision": r.decision, "rationale": r.rationale, "by": r.person, "role": r.role})
        return {"ok": True}

    @app.post("/api/review")
    def review(r: Review, request: Request):
        r.role, r.person = W(request, r.role, r.person)
        with capture_execution(O().log, f"Finding review · {r.fid}") as ctx:
            guard(O().review, r.role, r.person, r.fid, r.decision, r.rationale)
            ctx.record({"fid": r.fid, "decision": r.decision, "rationale": r.rationale, "by": r.person, "role": r.role})
        return {"ok": True}

    @app.post("/api/overrides")
    def override(o: Override, request: Request):
        o.role, o.person = W(request, o.role, o.person)
        with capture_execution(O().log, f"Override · {o.run}") as ctx:
            return ctx.record(guard(O().override, o.role, o.person, o.run, o.field, o.to, o.rationale))

    @app.post("/api/overrides/cosign")
    def cosign(c: Cosign, request: Request):
        c.role, c.person = W(request, c.role, c.person)
        with capture_execution(O().log, f"Cosign override · {c.override_id}") as ctx:
            guard(O().cosign, c.role, c.person, c.override_id)
            ctx.record({"override_id": c.override_id, "by": c.person, "role": c.role})
        return {"ok": True}

    @app.post("/api/release")
    def release(r: Release, request: Request):
        r.role, r.person = W(request, r.role, r.person)
        with capture_execution(O().log, f"Release report ({r.kind})") as ctx:
            guard(O().release, r.role, r.person, r.kind)
            rep = O().state.report or {}
            ctx.record({"kind": r.kind, "version": rep.get("version"), "by": r.person, "role": r.role})
        return {"ok": True}

    @app.post("/api/report/summary")
    def summary():
        with capture_execution(O().log, "Draft report summary") as ctx:
            text = guard(O().draft_summary)
            ctx.record({"text": text})
            return {"text": text}

    @app.put("/api/report/summary")
    def save_summary(s: SummaryEdit, request: Request):
        if auth.enabled():
            role, _ = W(request, s.role)
            if role not in GATES["release"]:
                raise HTTPException(403, "Only the PI or Deputy PI can edit the report summary.")
        return {"text": guard(O().save_summary, s.text)}

    @app.get("/api/report/{version}/article.html")
    def report_article(version: int, print: int = 0, download: int = 0):
        """Self-contained publishable HTML article for a released (or draft) report version.
        `?print=1` auto-opens the browser Print dialog so the user can Save-as-PDF in one click.
        `?download=1` sets Content-Disposition: attachment for a direct file download."""
        rep = O().state.report
        if not rep:
            raise HTTPException(404, "No report has been built yet (Stage 6).")
        if int(rep.get("version") or 0) != int(version):
            raise HTTPException(404, f"No report v{version} (current is v{rep.get('version')}).")
        html_doc = render_article_html(O().state, rep, print_mode=bool(print),
                                       download_url=f"/api/report/{version}/article.html?download=1" if not download else None)
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="tbamr-report-v{version}.html"'
        return HTMLResponse(html_doc, headers=headers)

    @app.post("/api/profiling/import")
    async def import_results(request: Request, role: str, person: str = "", files: list[UploadFile] = File(...)):
        role, person = W(request, role, person)
        parsed = []
        for f in files:
            try:
                parsed.append((f.filename or "result.json", json.loads(await f.read())))
            except ValueError:
                raise HTTPException(400, f"{f.filename} is not valid JSON.")
        with capture_execution(O().log, f"Import TB-Profiler results ({len(parsed)} file(s))") as ctx:
            return ctx.record(guard(O().import_results, role, person, parsed))

    @app.post("/api/profiling/run")
    def run_profiler(r: RunProfiler, request: Request):
        r.role, r.person = W(request, r.role, r.person)
        # The pool runs asynchronously in a background thread; capture happens there, inside run_profiler().
        return guard(O().run_profiler, r.role, r.person, r.runs)

    @app.post("/api/reset")
    def reset(request: Request, data: str = "demo", brain: str | None = None):
        """Reset the pipeline. Previously this unlinked the DB file, which raced against concurrent
        frontend polls (metrics/state/decisions) — their open SQLite connections auto-recreated the
        file without a schema, so the next SELECT hit `no such table: trace`. We now clear tables
        in place behind the orchestrator's own lock so the schema is always valid, and only unlink
        the file when switching modes (demo <-> live use different file paths anyway).

        Executions and their captured logs are preserved across resets: the active pipeline run is
        closed (ended_at + a label derived from the scope), a new run is opened, and the Logs tab
        can look back at previous runs. Decisions, agent traces, raw-data cache, view receipts and
        pipeline state are still cleared so the next cycle starts fresh."""
        need(request, admin=True, roles=["pi"])
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

    # ---- Admin: Mongo + cache -------------------------------------------------
    # Everything here is best-effort against Mongo; if Mongo is down the endpoints still return 200
    # with `connected: false` so the admin UI can render a helpful "Mongo not reachable" state.
    @app.get("/api/admin/rules")
    def rules_current():
        """Editable thresholds, rule versions, provenance (provisional / validated + basis) and change history."""
        from .core import rulesettings
        return rulesettings.current()

    @app.post("/api/admin/rules")
    def rules_change(b: RuleChange, request: Request):
        b.role, b.person = W(request, b.role, b.person)
        with capture_execution(O().log, "Change pipeline rules"):
            return guard(O().change_rules, b.role, b.person, b.changes, b.rationale, b.status, b.basis)

    @app.get("/api/admin/mongo")
    def mongo_status(request: Request):
        need(request, admin=True)
        return mongo_module.status()

    @app.post("/api/admin/mongo/reconnect")
    def mongo_reconnect(request: Request):
        need(request, admin=True)
        return mongo_module.reconnect()

    @app.get("/api/admin/cache")
    def cache_overview(request: Request):
        need(request, admin=True)
        return {"mongo": mongo_module.status(), "caches": cache_module.cache.stats()}

    @app.post("/api/admin/cache/{ns}/toggle")
    def cache_toggle(ns: str, t: CacheToggle, request: Request):
        need(request, admin=True)
        if ns not in CACHE_NAMESPACES:
            raise HTTPException(404, f"Unknown cache namespace: {ns!r}")
        cache_module.cache.set_enabled(ns, t.enabled)
        return {"ok": True, "namespace": ns, "enabled": t.enabled}

    @app.post("/api/admin/cache/{ns}/clear")
    def cache_clear(ns: str, request: Request):
        need(request, admin=True)
        if ns not in CACHE_NAMESPACES:
            raise HTTPException(404, f"Unknown cache namespace: {ns!r}")
        return {"ok": True, "namespace": ns, "deleted": cache_module.cache.clear(ns)}

    @app.post("/api/admin/cache/clear-all")
    def cache_clear_all(request: Request):
        need(request, admin=True)
        return {"ok": True, "deleted": cache_module.cache.clear_all()}

    @app.get("/api/admin/results")
    def results_list(limit: int = 50):
        return results_module.list_releases(limit=max(1, min(500, int(limit))))

    @app.get("/api/admin/results/{release_id}")
    def results_load(release_id: str):
        doc = results_module.load_release(release_id)
        if not doc:
            raise HTTPException(404, f"No release {release_id!r} in Mongo (or Mongo is down).")
        return doc

    # serve the built React app if present
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app


app = create_app() if os.environ.get("TBAMR_NO_APP") != "1" else None
