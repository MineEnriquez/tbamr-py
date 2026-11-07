import json
import os
import tempfile

import httpx
import pytest
from fastapi.testclient import TestClient

from tbamr.agents.discovery import DiscoveryAssistant
from tbamr.agents.evidence import EvidenceAnalyst
from tbamr.agents.scope_guardian import REQUIRED_GAPS, ScopeGuardian
from tbamr.api import build_orchestrator, create_app
from tbamr.core.decisions import Decision, DecisionLog, GuardrailViolation, Outcome
from tbamr.core.models import Finding, Sample
from tbamr.core.orchestrator import PermissionDenied, StageError
from tbamr.llm.client import ReplayClient
from tbamr.core.geo import INSDC_COUNTRIES, canonical_region, catalogue, region_matches, regions_for, resolve_target
from tbamr.tools.demo import SCENARIOS, DemoDataTools
from tbamr.tools.ena import DataTools
from tbamr.tools.tbprofiler import parse_result


@pytest.fixture
def orch(tmp_path):
    o = build_orchestrator("demo", "replay", str(tmp_path / "t.db"))
    o.state.country = "Indonesia"  # demo samples were authored around a country-scoped Indonesian pipeline
    return o


def run_to_report(o):
    o.run_stage(1); o.raw_view("scope", "guardian", "pi", "Ana"); o.approve_scope("pi", "Ana")
    o.run_stage(2); o.raw_view("cohort", "all", "pi", "Ana"); o.approve_cohort("pi", "Ana")
    o.run_stage(3); o.raw_view("qc", "all", "analyst", "Budi"); o.confirm_qc("analyst", "Budi")
    o.run_stage(4); o.raw_view("profiling", "all", "analyst", "Budi"); o.close_profiling("analyst", "Budi")
    o.run_stage(5); return o.run_stage(6)


# ---------------------------------------------------------------- decision contract
def test_agents_cannot_use_human_outcomes():
    log = DecisionLog()
    with pytest.raises(GuardrailViolation):
        log.add(Decision("S1", Outcome.APPROVE, "X", "approve myself", actor="agent:qc"))
    with pytest.raises(GuardrailViolation):
        log.add(Decision("S1", Outcome.PROCEED, "X", "  ", actor="agent:qc"))
    log.add(Decision("S1", Outcome.APPROVE, "X", "ok", actor="human:pi:Ana"))
    assert log.all()[0]["outcome"] == "Approve"


# ---------------------------------------------------------------- end-to-end demo
def test_full_demo_flow(orch):
    rep = run_to_report(orch)
    st = orch.state
    assert {s.run for s in st.samples if s.eligibility == "Excluded"} == {"DEMO-R06", "DEMO-R07", "DEMO-R08", "DEMO-R18", "DEMO-R19", "DEMO-R23", "DEMO-R24"}
    assert {s.run for s in st.samples if s.eligibility == "Hold"} == {"DEMO-R15", "DEMO-R16", "DEMO-R20", "DEMO-R21", "DEMO-R22"}
    assert st.sample("DEMO-R04").qc == "Escalated"  # 27x borderline
    assert rep["counts"] == {"candidates": 43, "verified": 31, "qc_passed": 27, "analysed": 25, "planned_minimum": 100}
    assert [d["drug"] for d in rep["drugs"]][:2] == ["RIF", "INH"]
    pending = {(f["run"], f["variant"]) for f in rep["unresolved"]}
    assert ("DEMO-R14", "rpoB p.Ser450Leu") in pending  # low depth
    assert ("DEMO-R11", "katG p.Ser315Thr") in pending  # minor variant
    assert ("DEMO-R12", "Rv0678 c.192dupG") in pending  # uncertain grading
    with pytest.raises(StageError):
        orch.release("pi", "Ana", "final")  # blocked while findings pending
    orch.raw_view("report", str(rep["version"]), "pi", "Ana")
    orch.release("pi", "Ana", "draft")


def test_roles_are_enforced(orch):
    orch.run_stage(1)
    with pytest.raises(PermissionDenied):
        orch.approve_scope("analyst", "Budi")


def test_raw_data_view_is_recorded_but_not_required(orch):
    orch.run_stage(1)
    # Deciding without opening the raw data is allowed; the evidence notes it wasn't opened.
    orch.approve_scope("pi", "Ana")
    d = [d for d in orch.log.all() if d["outcome"] == "Approve"][0]
    assert "not opened" in d["evidence"]
    # When someone does open the raw data, the receipt is captured and tied to their later decisions.
    orch.run_stage(2)
    raw = orch.raw_view("scope", "guardian", "pi", "Ana")
    assert raw["title"] and raw["data"]["result"]["gaps"]
    ena = orch.raw_view("ena", "DEMO-R15", "pi", "Ana")
    assert ena["data"]["ena_record"]["run_accession"] == "DEMO-R15"
    cohort = orch.raw_view("cohort", "all", "pi", "Ana")
    assert cohort["table"]["rows"] and cohort["table"]["columns"]
    orch.approve_cohort("pi", "Ana")
    d = [d for d in orch.log.all() if d["outcome"] == "Approve"][0]
    assert "Raw data" in d["evidence"] and "Ana" in d["evidence"]


def test_gates_block_skipping(orch):
    with pytest.raises(StageError):
        orch.run_stage(3)


def test_two_person_override(orch):
    orch.run_stage(1); orch.raw_view("scope", "guardian", "pi", "Ana"); orch.approve_scope("pi", "Ana"); orch.run_stage(2)
    r = orch.override("pi", "Ana", "DEMO-R15", "eligibility", "Verified", "Origin confirmed in methods section")
    assert r["applied"] is False
    with pytest.raises(PermissionDenied):
        orch.cosign("deputy", "ana", r["pending"]["id"])  # same person, different role
    orch.cosign("deputy", "Citra", r["pending"]["id"])
    assert orch.state.sample("DEMO-R15").eligibility == "Verified"
    # more cautious change applies immediately
    assert orch.override("pi", "Ana", "DEMO-R01", "eligibility", "Hold", "Recheck metadata")["applied"] is True


def test_import_and_review(orch):
    run_to_report(orch)
    f = next(f for f in orch.state.findings() if f.review == "Pending")
    with pytest.raises(PermissionDenied):
        orch.review("pi", "Ana", f.fid, "Reviewed", "x")
    raw = orch.raw_view("tbprofiler", f.sample_id, "tbexpert", "Dewi")
    assert "dr_variants" in raw["data"]
    orch.review("tbexpert", "Dewi", f.fid, "Needs more data", "Request deeper sequencing")
    assert orch.state.report["superseded"] is True


def test_every_demo_scenario_reaches_its_expected_outcome(orch):
    """The demo data is a scenario catalogue (tools/demo.py SCENARIOS); each run must land where it says."""
    run_to_report(orch)
    problems = []
    for run, sc in SCENARIOS.items():
        s = orch.state.sample(run)
        assert s, f"{run} was not discovered"
        got = {"elig": s.eligibility, "qc": s.qc or None, "prof": s.profiling or None}
        problems += [f"{run} ({sc['what']}): {k} expected {v}, got {got[k]}" for k, v in sc["expect"].items() if k != "review" and got[k] != v]
        reviews = {f"{f.gene} {f.change}": f.review for f in s.findings}
        problems += [f"{run} ({sc['what']}): {v} expected {want}, got {reviews.get(v)}" for v, want in sc["expect"].get("review", {}).items() if reviews.get(v) != want]
    assert not problems, "\n".join(problems)
    assert {s.run for s in orch.state.samples} == set(SCENARIOS), "every demo run needs a documented scenario"


def test_demo_report_covers_discordance_and_extra_drugs(orch):
    rep = run_to_report(orch)
    by = {d["drug"]: d for d in rep["drugs"]}
    assert {"FLQ", "BDQ", "LZD", "PZA", "EMB", "STM", "AMK", "ETO"} <= set(by)
    assert by["RIF"]["dst_n"] > by["RIF"]["concordant"]  # R09 (genotype R, DST S) and R38 (genotype S, DST R) disagree
    assert orch.state.sample("DEMO-R31").profile_meta["db"] == "not in file"  # TB-Profiler 4.x layout
    assert orch.state.sample("DEMO-R41").lineage == "La1.8.BCG"


# ---------------------------------------------------------------- agentic behaviour + guardrails
class OneSiteData(DemoDataTools):
    """Every run from one Bandung study; a second search finds nothing new."""

    def ena_search_runs(self, country="Indonesia", extra_query="", limit=500, page_size=200):
        rows = [] if "study_accession!=" in extra_query else [
            {"run_accession": f"SRRX{i}", "sample_accession": f"SAMX{i}", "study_accession": "PRJX", "country": "Indonesia: Bandung",
             "library_strategy": "WGS", "instrument_platform": "ILLUMINA", "base_count": str(60 * 4_411_532), "fastq_md5": "a;b"} for i in range(5)]
        return {"query": "q", "returned": len(rows), "total_in_ena": len(rows), "runs": rows}


def test_orchestrator_replans_when_cohort_cannot_answer(tmp_path):
    o = build_orchestrator("demo", "replay", str(tmp_path / "r.db"), data=OneSiteData())
    o.state.question = "Are there differences in resistance across regions of Indonesia?"
    o.run_stage(1)
    assert o.state.scope["asks_comparison_across_places"] is True
    o.raw_view("scope", "guardian", "pi", "Ana"); o.approve_scope("pi", "Ana")
    o.run_stage(2)
    outs = [d for d in o.log.all() if d["actor"] == "agent:orchestrator" and d["outcome"] == "Retry"]
    assert outs, "orchestrator should re-plan"
    assert o.state.replans == 1
    assert any(c["outcome"] == "Escalate" and c["kind"] == "single_location" for c in o.state.cohort_checks)
    calls = [t for t in o.log.traces("discovery") if t["kind"] == "tool_call"]
    assert any("study_accession!=" in json.dumps(t["payload"]) for t in calls)


def test_discovery_cannot_invent_accessions():
    log = DecisionLog()

    def policy(messages):
        if sum(m["role"] == "assistant" for m in messages) == 0:
            return [{"type": "tool_use", "name": "ena_search_runs", "input": {"country": "Indonesia"}}]
        return [{"type": "tool_use", "name": "submit", "input": {"candidate_runs": ["DEMO-R01", "SRR_FAKE"], "studies": [], "search_notes": "", "concerns": []}}]

    agent = DiscoveryAssistant(log, ReplayClient({"discovery": policy}), DemoDataTools())
    res = agent.discover("Indonesia", "q")
    assert res["candidate_runs"] == ["DEMO-R01"]
    assert any("Guardrail removed 1" in c for c in res["concerns"])


def test_scope_guardian_keeps_required_definitions():
    log = DecisionLog()
    lazy = lambda m: [{"type": "tool_use", "name": "submit", "input": {"blocking": [], "gaps": [], "warnings": [], "asks_comparison_across_places": False}}]
    res = ScopeGuardian(log, ReplayClient({"scope_guardian": lazy})).review("q?", "Indonesia", ["Rifampicin"], 8)
    assert {g["key"] for g in res["gaps"]} == {"verified_origin", "missing_dst", "duplicates", "out_of_bounds"}


def test_evidence_agent_can_only_be_more_cautious():
    log = DecisionLog()
    s = Sample(run="R1", profiling="Done", profile_meta={"mutations": [
        {"gene": "rpoB", "change": "p.Ser450Leu", "drug": "RIF", "grade": 1, "depth": 5, "freq": 1.0},
        {"gene": "katG", "change": "p.Ser315Thr", "drug": "INH", "grade": 1, "depth": 80, "freq": 1.0}]})

    def policy(messages):
        ctx = json.loads(messages[0]["content"].split("Context (JSON):", 1)[1])
        notes = [{"fid": f["fid"], "interpretation": "x", "request_review": "katG" in f["variant"]} for f in ctx["findings"]]
        notes.append({"fid": "not-a-finding", "interpretation": "y"})
        return [{"type": "tool_use", "name": "submit", "input": {"notes": notes}}]

    EvidenceAnalyst(log, ReplayClient({"evidence": policy})).evaluate([s])
    by = {f.gene: f for f in s.findings}
    assert by["rpoB"].review == "Pending"  # rule flag kept (low depth)
    assert by["katG"].review == "Pending"  # agent added caution
    assert all(f.interpretation for f in s.findings)


# ---------------------------------------------------------------- tools
def test_tbprofiler_parser_v4_and_v6():
    v6 = {"id": "S1", "sub_lineage": "lineage2.2.1", "drtype": "MDR-TB", "pipeline": {"software_version": "6.2.0"}, "db_version": {"name": "tbdb", "commit": "abc"},
          "dr_variants": [{"gene_name": "rpoB", "change": "p.Ser450Leu", "depth": 80, "freq": 1, "annotation": [{"type": "drug_resistance", "drug": "rifampicin", "confidence": "Assoc w R"}]}]}
    v4 = {"id": "S2", "main_lin": "lineage4", "sublin": "lineage4.1.2", "tbprofiler_version": "4.4.0", "db_version": {"name": "tbdb"},
          "dr_variants": [{"gene": "katG", "change": "p.Ser315Thr", "depth": 50, "freq": 0.95, "drugs": [{"drug": "isoniazid", "confidence": "Assoc w R - Interim"}]}]}
    a, b = parse_result(v6, "S1.results.json"), parse_result(v4, "x.json")
    assert a["mutations"][0] == {"gene": "rpoB", "change": "p.Ser450Leu", "drug": "RIF", "grade": 1, "depth": 80.0, "freq": 1.0, "confidence": "Assoc w R"}
    assert a["lineage"] == "2.2.1" and a["meta"]["tool"] == "TB-Profiler 6.2.0"
    assert b["mutations"][0]["grade"] == 2 and b["lineage"] == "4.1.2" and b["meta"]["tool"] == "TB-Profiler 4.4.0"


def test_ena_search_is_one_request_without_offset():
    """The ENA Portal API rejects `offset` with HTTP 400, so the search must be a single request with the full limit."""
    calls = []

    def handler(req: httpx.Request):
        calls.append(dict(req.url.params))
        if req.url.path.endswith("/count"):
            return httpx.Response(200, text="250")
        if "offset" in req.url.params:
            return httpx.Response(400, json={"message": "Unsupported param offset"})
        return httpx.Response(200, json=[{"run_accession": f"SRR{i}"} for i in range(min(250, int(req.url.params["limit"]) or 250))])

    tools = DataTools(httpx.Client(transport=httpx.MockTransport(handler)))
    res = tools.ena_search_runs("Indonesia", limit=500, page_size=100)
    assert res["returned"] == 250 and res["total_in_ena"] == 250
    searches = [c for c in calls if "query" in c and "limit" in c]
    assert len(searches) == 1 and searches[0]["limit"] == "500" and "offset" not in searches[0]


def test_discovery_keeps_search_results_when_the_agent_never_submits():
    """An agent that searches but runs out of steps without submitting must not turn into zero candidates."""
    def policy(messages):
        if sum(m["role"] == "assistant" for m in messages) == 0:
            return [{"type": "tool_use", "name": "ena_search_runs", "input": {"country": "Indonesia"}}]
        return [{"type": "text", "text": "Still thinking about more studies..."}]  # never calls submit

    log = DecisionLog()
    res = DiscoveryAssistant(log, ReplayClient({"discovery": policy}), DemoDataTools()).discover("Indonesia", "q?")
    assert res["candidate_runs"] and all(r.startswith("DEMO-") for r in res["candidate_runs"])
    assert any("stopped without submitting" in c for c in res["concerns"])
    assert any(t["kind"] == "fallback" for t in log.traces("discovery"))


# ---------------------------------------------------------------- API
def test_api_flow(tmp_path):
    app = create_app(build_orchestrator("demo", "replay", str(tmp_path / "a.db")))
    c = TestClient(app)
    assert c.get("/api/scope/target", params={"question": "Resistance patterns"}).json()["problem"]  # no silent worldwide
    assert c.post("/api/scope", json={"question": "Resistance patterns", "country": "Indonesia"}).status_code == 200
    assert c.post("/api/stages/1/run").status_code == 200
    assert c.post("/api/gates/scope", json={"role": "analyst"}).status_code == 403
    raw = c.get("/api/raw/scope/guardian", params={"role": "pi", "person": "Ana"}).json()
    assert raw["viewer"] == "Ana" and raw["viewed_at"]
    assert {"kind": "scope", "key": "guardian"}.items() <= c.get("/api/raw/receipts", params={"person": "Ana"}).json()[0].items()
    assert c.post("/api/gates/scope", json={"role": "pi", "person": "Ana"}).status_code == 200
    assert c.get("/api/raw/nothing/here").status_code == 404
    c.post("/api/stages/2/run"); c.get("/api/raw/cohort/all", params={"role": "pi", "person": "Ana"})
    assert c.post("/api/gates/cohort", json={"role": "pi", "person": "Ana"}).status_code == 200
    c.post("/api/stages/3/run"); c.get("/api/raw/qc/all", params={"role": "analyst", "person": "Budi"})
    assert c.post("/api/gates/qc", json={"role": "analyst", "person": "Budi"}).status_code == 200
    c.post("/api/stages/4/run")
    files = [("files", ("DEMO-R99.results.json", json.dumps({"id": "DEMO-R99", "dr_variants": []}), "application/json"))]
    r = c.post("/api/profiling/import", params={"role": "analyst", "person": "Budi"}, files=files)
    assert r.status_code == 200 and r.json()["skipped"]
    team = c.get("/api/team").json()
    assert {t["name"] for t in team} >= {"orchestrator", "scope_guardian", "discovery", "verification", "qc", "profiling", "evidence", "reporting"}
    m = c.get("/api/metrics").json()
    assert m["completeness_pct"] == 100 and m["tool_calls"].get("discovery", 0) >= 1
    tr = c.get("/api/trace", params={"agent": "discovery"}).json()
    tool = next(t for t in tr if t["kind"] == "tool_call")
    full = c.get(f"/api/raw/tool/{tool['id']}").json()
    assert "output" in full["data"] and full["data"]["tool"] and full["viewed_at"] is None


def test_raw_data_is_backfilled_for_pipelines_started_before_it_was_saved(orch):
    orch.run_stage(1); orch.raw_view("scope", "guardian", "pi", "Ana"); orch.approve_scope("pi", "Ana"); orch.run_stage(2)
    with orch.log._lock:  # simulate a database written by the earlier version
        orch.log.db.execute("DELETE FROM raw"); orch.log.db.commit()
    rec = orch.raw_view("ena", "DEMO-R15", "pi", "Ana")
    assert rec["data"]["ena_record"]["run_accession"] == "DEMO-R15" and "note" in rec
    cohort = orch.raw_view("cohort", "all", "pi", "Ana")
    assert all(r[0] for r in cohort["table"]["rows"])
    orch.resolve_hold("pi", "Ana", "DEMO-R15", "verify", "Checked the record")


def test_reset_preserves_previous_runs(tmp_path, monkeypatch):
    """A pipeline reset must close the active run and open a new one, keeping executions from
    the previous run so the Logs tab can look back at them."""
    db = str(tmp_path / "runs.db")
    monkeypatch.setenv("TBAMR_DB", db)
    app = create_app(build_orchestrator("demo", "replay", db))
    c = TestClient(app)
    # First pipeline run: do one action so an execution is recorded.
    c.post("/api/stages/1/run")
    runs_before = c.get("/api/runs").json()
    assert len(runs_before) == 1 and runs_before[0]["active"] is True
    first_run_id = runs_before[0]["id"]
    first_execs = c.get("/api/executions", params={"run_id": first_run_id}).json()
    assert any(e["trigger"] == "Stage 1" for e in first_execs)
    # Reset. The active run should close; a new one should open; old executions should survive.
    assert c.post("/api/reset", params={"data": "demo"}).status_code == 200
    runs_after = c.get("/api/runs").json()
    assert len(runs_after) == 2
    active = [r for r in runs_after if r["active"]]
    closed = [r for r in runs_after if not r["active"]]
    assert len(active) == 1 and len(closed) == 1
    assert closed[0]["id"] == first_run_id and closed[0]["ended_at"] is not None
    # Previous run's executions are still queryable; default (no run_id) returns the new empty run.
    prev = c.get("/api/executions", params={"run_id": first_run_id}).json()
    assert any(e["trigger"] == "Stage 1" for e in prev)
    assert c.get("/api/executions").json() == []


def test_executions_capture_structured_results(tmp_path, monkeypatch):
    """Stage runs and gate approvals should attach a structured result to their execution row, so the
    Logs tab can show what each action produced — not just the free-text log."""
    db = str(tmp_path / "results.db")
    monkeypatch.setenv("TBAMR_DB", db)
    orch = build_orchestrator("demo", "replay", db)
    orch.state.country = "Indonesia"
    app = create_app(orch)
    c = TestClient(app)
    assert c.post("/api/scope", json={"question": "Resistance patterns", "country": "Indonesia"}).status_code == 200
    assert c.post("/api/stages/1/run").status_code == 200
    execs = c.get("/api/executions").json()
    stage1 = next(e for e in execs if e["trigger"] == "Stage 1")
    assert stage1["has_result"] is True
    detail = c.get(f"/api/executions/{stage1['id']}").json()
    # Stage 1 returns the Guardian's scope dict — look for a recognisable key.
    assert isinstance(detail["result"], dict) and detail["result"]  # non-empty object
    # Approving the scope attaches a {by, role} record even though the HTTP response is just {ok: True}.
    c.post("/api/raw/scope/guardian", params={"role": "pi", "person": "Ana"})  # mark raw as viewed
    orch.raw_view("scope", "guardian", "pi", "Ana")
    assert c.post("/api/gates/scope", json={"role": "pi", "person": "Ana"}).status_code == 200
    gate_exec = next(e for e in c.get("/api/executions").json() if e["trigger"] == "Approve scope")
    assert gate_exec["has_result"] is True
    gate_detail = c.get(f"/api/executions/{gate_exec['id']}").json()
    assert gate_detail["result"] == {"by": "Ana", "role": "pi"}


def test_execution_result_handles_unserialisable_values(tmp_path):
    """A function that returns something JSON can't handle must still produce a stored row (with an
    error marker in result_json) rather than silently losing the entire log."""
    from tbamr.core.executions import capture_execution
    log = DecisionLog(str(tmp_path / "oops.db"))
    with capture_execution(log, "weird-return") as ctx:
        ctx.record({"when": object()})  # bare object() isn't JSON-serialisable
    row = log.list_executions()[0]
    assert row["trigger"] == "weird-return" and row["has_result"] is True
    detail = log.get_execution(row["id"])
    # default=str catches arbitrary objects, so this still parses as a dict.
    assert isinstance(detail["result"], dict)


def test_harness_seeds_a_completed_pipeline(tmp_path):
    """The UI harness should produce a DB where every stage is done, the report exists, and the
    Logs tab has a captured execution for each step. If a stage API changes shape, this breaks
    visibly so the harness doesn't quietly rot."""
    from tbamr.harness import seed
    db = str(tmp_path / "tbamr-harness.db")
    summary = seed(db)
    assert summary["samples"] > 0 and summary["in_cohort"] > 0
    assert summary["report_version"] == 1
    # Reopen through the API to make sure the seeded state round-trips (as it will when uvicorn boots)
    app = create_app(build_orchestrator("demo", "replay", db))
    c = TestClient(app)
    state = c.get("/api/state").json()["state"]
    assert state["report"] is not None
    assert state["stage_status"]["5"] == "done"
    assert state["stage_status"]["6"] in ("wait", "done")
    assert state["gates"].get("scope") and state["gates"].get("cohort")
    execs = c.get("/api/executions").json()
    triggers = [e["trigger"] for e in execs]
    for expected in ("Stage 1", "Stage 6", "Approve scope", "Approve cohort", "Confirm QC", "Close profiling batch", "Draft report summary"):
        assert expected in triggers, f"harness never captured {expected} (got {triggers})"
    assert all(e["status"] == "ok" for e in execs), f"some seeded executions failed: {execs}"
    # Every seeded execution should carry a structured result, so the Logs tab is rich out of the box.
    assert all(e["has_result"] for e in execs), f"some seeded executions have no result: {execs}"


def test_harness_reseed_refuses_non_harness_filenames(tmp_path):
    """A misconfigured --reseed must never wipe tbamr-live.db or a user's custom DB."""
    from tbamr.harness import _safe_unlink
    bad = tmp_path / "tbamr-live.db"
    bad.write_text("do not delete me")
    with pytest.raises(SystemExit):
        _safe_unlink(bad)
    assert bad.exists()
    # The safe case: filename contains "harness"
    ok = tmp_path / "tbamr-harness.db"
    ok.write_text("fine")
    _safe_unlink(ok)
    assert not ok.exists()


# ---------------------------------------------------------------- publishable article
def test_report_article_renders_all_sections_and_streams_a_pdf_print_variant(orch):
    """A full pipeline run exposes a self-contained HTML article at /api/report/{v}/article.html,
    with every main report section and inline SVG plots. The print=1 variant auto-triggers the
    browser's Print dialog so users can Save-as-PDF without a server-side PDF dependency."""
    report = run_to_report(orch)
    assert report and report["version"] == 1
    orch.draft_summary()  # realistic article has a plain-language summary
    # Final release is blocked by any pending finding; "draft" always succeeds. Using draft keeps
    # the test independent of the demo cohort's finding mix.
    orch.release("pi", "Ana", "draft")
    c = TestClient(create_app(orch))

    r = c.get("/api/report/1/article.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "<!doctype html>" in html.lower()
    assert "Genomic resistance evidence" in html
    # Scope context is pulled from state, not the report dict.
    assert "Indonesia" in html
    # Core sections are all present.
    for h in ("Plain-language summary", "Sample counts", "Resistance evidence by drug",
              "Most frequent mutations", "Lineages", "Limitations", "Unresolved findings",
              "Exclusions and holds", "Provenance"):
        assert f">{h}" in html, f"article missing section {h!r}"
    # Status chip reflects the actual release gate.
    assert "Exploratory draft" in html
    # Inline SVG plots so the file is truly self-contained (no external assets).
    assert "<svg" in html and "http://www.w3.org/2000/svg" in html

    r_dl = c.get("/api/report/1/article.html", params={"download": 1})
    assert r_dl.status_code == 200
    assert 'attachment; filename="tbamr-report-v1.html"' in r_dl.headers.get("content-disposition", "")

    r_print = c.get("/api/report/1/article.html", params={"print": 1})
    assert r_print.status_code == 200 and "window.print()" in r_print.text

    missing = c.get("/api/report/9/article.html")
    assert missing.status_code == 404


def test_report_article_404s_when_no_report_exists(orch):
    c = TestClient(create_app(orch))
    r = c.get("/api/report/1/article.html")
    assert r.status_code == 404 and "Stage 6" in r.json()["detail"]


# ---------------------------------------------------------------- target population (worldwide only when asked)
@pytest.mark.parametrize("question,field,country,blocked", [
    ("Which rifampicin mutations are common in Mycobacterium tuberculosis genomes?", "", "", True),  # nothing named: no silent worldwide
    ("Rifampicin resistance in Indonesia", "", "Indonesia", False),  # named in the question
    ("Rifampicin resistance patterns", "vietnam", "Viet Nam", False),  # alias canonicalised to the INSDC name
    ("Rifampicin resistance worldwide", "", "Worldwide", False),  # explicit worldwide
    ("Rifampicin resistance patterns", "Worldwide", "Worldwide", False),
    ("Rifampicin resistance in sub-Saharan Africa", "", "", True),  # region only: not filterable
    ("Compare Kenya and Uganda", "", "", True),  # several countries
    ("Rifampicin resistance in Kenya", "Indonesia", "", True),  # field contradicts the question
    ("Rifampicin resistance patterns", "Indonesa", "", True),  # unrecognised name
    ("Resistance in Papua New Guinea", "", "Papua New Guinea", False),  # longest name wins over "Guinea"
])
def test_target_population_resolution(question, field, country, blocked):
    t = resolve_target(question, field)
    assert bool(t["problem"]) is blocked and t["country"] == country


def test_stage1_blocks_without_a_clear_target(tmp_path):
    o = build_orchestrator("demo", "replay", str(tmp_path / "g.db"))
    o.state.question, o.state.country = "Which mutations explain rifampicin resistance?", ""
    o.run_stage(1)
    assert any("No target population" in b for b in o.state.scope["blocking"])
    o.raw_view("scope", "guardian", "pi", "Ana")
    with pytest.raises(StageError):
        o.approve_scope("pi", "Ana")


def test_question_country_becomes_the_search_scope(tmp_path):
    o = build_orchestrator("demo", "replay", str(tmp_path / "q.db"))
    o.state.question, o.state.country = "Which mutations explain rifampicin resistance in Indonesia?", ""
    o.run_stage(1)
    assert o.state.country == "Indonesia" and o.state.scope["target"]["source"] == "question"
    o.raw_view("scope", "guardian", "pi", "Ana"); o.approve_scope("pi", "Ana")
    o.run_stage(2)
    assert o.state.sample("DEMO-R06").eligibility == "Excluded"  # Viet Nam is outside the resolved scope


def test_explicit_worldwide_searches_without_a_country_filter(tmp_path):
    o = build_orchestrator("demo", "replay", str(tmp_path / "w.db"))
    o.state.question, o.state.country = "Global patterns of rifampicin resistance", ""
    o.run_stage(1)
    assert o.state.country == "Worldwide" and not o.state.scope["blocking"]
    o.raw_view("scope", "guardian", "pi", "Ana"); o.approve_scope("pi", "Ana")
    o.run_stage(2)
    calls = [t for t in o.log.traces("discovery") if t["kind"] == "tool_call"]
    assert all('country="Worldwide' not in json.dumps(t["payload"]) for t in calls)
    assert o.state.sample("DEMO-R06").eligibility == "Verified"  # origin is informational for worldwide


# ---------------------------------------------------------------- subnational target
@pytest.mark.parametrize("question,field,region,want,blocked", [
    ("Resistance patterns", "Indonesia", "West Java", ("Indonesia", "West Java"), False),
    ("Resistance patterns", "Indonesia: West Java", "", ("Indonesia", "West Java"), False),  # ENA format in the Country field
    ("Resistance in West Java province, Indonesia", "", "", ("Indonesia", "West Java"), False),  # named in the question
    ("Which MDR-TB mutations occur in Western Cape province?", "South Africa", "", ("South Africa", "Western Cape"), False),
    ("Compare West Java province and Bali province", "Indonesia", "", ("Indonesia", ""), False),  # comparison: whole country
    ("Resistance patterns", "Worldwide", "West Java", ("", ""), True),  # a region needs one country
    ("Resistance in West Java province", "", "", ("", ""), True),  # region without a country
    ("Resistance in Bali province", "Indonesia", "West Java", ("", ""), True),  # field and question disagree
])
def test_subnational_target_resolution(question, field, region, want, blocked):
    t = resolve_target(question, field, region)
    assert bool(t["problem"]) is blocked and (t["country"], t["region"]) == want


def test_region_matching_is_a_whole_phrase():
    assert region_matches("West Java", "Indonesia: West Java")
    assert region_matches("west java province", "Indonesia:West Java")
    assert region_matches("West Java", "Indonesia: Bandung, West Java")
    assert not region_matches("West Java", "Indonesia: Central Java")
    assert not region_matches("West Java", "Indonesia")


def test_region_scope_verifies_matching_runs_and_holds_the_rest(tmp_path):
    o = build_orchestrator("demo", "replay", str(tmp_path / "r.db"))
    o.state.question, o.state.country, o.state.region = "Which rifampicin mutations are present?", "Indonesia", "West Java"
    rep = run_to_report(o)
    st = o.state
    assert st.region == "West Java" and st.scope["target"]["region"] == "West Java"
    verified = {s.run for s in st.samples if s.eligibility == "Verified"}
    assert verified == {"DEMO-R02", "DEMO-R13", "DEMO-R43"}  # "West Java" and "Bandung, West Java"
    assert st.sample("DEMO-R04").eligibility == "Hold"  # Central Java: a person decides, never excluded by guesswork
    assert "does not name the target region" in st.sample("DEMO-R04").eligibility_note
    assert st.sample("DEMO-R06").eligibility == "Excluded"  # other country still excluded by rule
    assert [(r["place"], r["n"]) for r in rep["by_place"]] == [("West Java", 3)] and rep["place_kind"] == "region"  # "Bandung, West Java" counted under West Java


def test_report_breaks_country_scope_down_by_region(orch):
    rep = run_to_report(orch)
    rows = {r["place"]: r for r in rep["by_place"]}
    assert rep["place_kind"] == "region" and sum(r["n"] for r in rep["by_place"]) == rep["counts"]["analysed"]
    assert rows["Jakarta"]["resistant"]["RIF"] >= 1  # R01, R12, R33 are Jakarta MDR/XDR
    assert any("counts, not rates" in l for l in rep["limitations"])


# ---------------------------------------------------------------- country / region catalogue
def test_catalogue_has_the_who_lists_with_regions():
    c = catalogue()
    assert len(c["high_burden"]) == 30 and c["watchlist"] == ["Cambodia", "Russia", "Zimbabwe"]
    for name in c["high_burden"] + c["watchlist"]:
        assert name in INSDC_COUNTRIES, f"{name} must be the INSDC name ENA records use"
        assert regions_for(name), f"{name} has no regions on file"
    assert len(regions_for("Indonesia")) == 38 and len(regions_for("South Africa")) == 9


@pytest.mark.parametrize("target,location,country,ok", [
    ("West Java", "Indonesia: Jawa Barat", "Indonesia", True),  # ISO (local) name in the record
    ("Jawa Barat", "Indonesia: Bandung, West Java", "Indonesia", True),  # English name in the record
    ("Hà Nội", "Viet Nam: Hanoi", "Viet Nam", True),  # accents and spacing
    ("Ho Chi Minh City", "Viet Nam: Ho Chi Minh", "Viet Nam", True),
    ("Tigray", "Ethiopia: Tigrai", "Ethiopia", True),
    ("West Java", "Indonesia: Central Java", "Indonesia", False),
])
def test_region_matching_uses_catalogue_aliases(target, location, country, ok):
    assert region_matches(target, location, country) is ok


def test_regions_are_canonicalised_and_found_in_questions():
    assert canonical_region("Indonesia", "jawa barat") == "West Java"
    assert resolve_target("Resistance in West Java", "Indonesia")["region"] == "West Java"  # no "province" needed
    assert resolve_target("Resistance in Hanoi", "Viet Nam")["region"] == "Hà Nội"
    assert resolve_target("Resistance in Zambia", "Zambia")["region"] == ""  # "Central"/"Northern" not guessed from prose


def test_geo_endpoints(tmp_path):
    c = TestClient(create_app(build_orchestrator("demo", "replay", str(tmp_path / "g.db"))))
    countries = c.get("/api/geo/countries").json()
    assert "Indonesia" in countries["high_burden"] and "Cambodia" in countries["watchlist"] and "France" in countries["other"]
    regions = [r["name"] for r in c.get("/api/geo/regions", params={"country": "Indonesia"}).json()["regions"]]
    assert "West Java" in regions and len(regions) == 38
    assert c.get("/api/geo/regions", params={"country": "France"}).json()["regions"] == []


# ---------------------------------------------------------------- test isolation (issue #20)
def test_resets_never_touch_databases_in_the_working_directory(tmp_path, monkeypatch):
    """Resetting to live and back (what the Demo/Live picker does) must not open or create tbamr-*.db in the cwd,
    where the developer's real pipeline databases live."""
    monkeypatch.chdir(tmp_path)
    c = TestClient(create_app(build_orchestrator("demo", "replay", str(tmp_path / "start.db"))))
    for mode in ("live", "demo"):
        assert c.post("/api/reset", params={"data": mode}).status_code == 200
    assert not list(tmp_path.glob("tbamr-*.db")), "a reset opened a database in the working directory"
    assert os.environ["TBAMR_DB"].startswith(tempfile.gettempdir())


def test_release_is_archived_after_it_is_recorded(orch, monkeypatch):
    """Regression for #19: the Mongo archive must see the release decision already in the log."""
    import tbamr.stores.results as results
    seen = {}

    def fake_save(state, report, gate):
        seen["logged"] = any(d["outcome"] == "Approve" and "report v" in d["rationale"] for d in orch.log.all())
        seen["gate"] = dict(state.gates.get("release", {}))

    monkeypatch.setattr(results, "save_release", fake_save)
    run_to_report(orch)
    orch.raw_view("report", str(orch.state.report["version"]), "pi", "Ana")
    orch.release("pi", "Ana", "draft")
    assert seen == {"logged": True, "gate": {"by": "Ana", "role": "pi", "kind": "draft", "version": orch.state.report["version"]}}


# ---------------------------------------------------------------- Scope Guardian definitions match the rules
def test_guardian_wording_never_replaces_the_applied_definitions():
    """The model's proposed definitions are kept as suggestions; the applied text always comes from the rules."""
    divergent = lambda m: [{"type": "tool_use", "name": "submit", "input": {"blocking": [], "warnings": [], "asks_comparison_across_places": False,
        "gaps": [{"key": "missing_dst", "gap": "DST", "proposal": "Exclude samples without phenotypic DST."},
                 {"key": "transmission", "gap": "Transmission", "proposal": "No transmission inference."}]}}]
    g = ScopeGuardian(DecisionLog(), ReplayClient({"scope_guardian": divergent}))
    res = g.review("Rifampicin resistance in Indonesia", "Indonesia", ["Rifampicin"], 8)
    by = {x["key"]: x for x in res["gaps"]}
    assert by["missing_dst"]["applied"] and "unavailable" in by["missing_dst"]["proposal"]
    assert by["missing_dst"]["suggestion"] == "Exclude samples without phenotypic DST."
    assert by["transmission"]["applied"] is False and by["transmission"]["proposal"] == ""
    assert all(by[k]["applied"] for k in ("verified_origin", "duplicates", "out_of_bounds"))


def test_definitions_describe_what_the_pipeline_does(orch):
    """Pin the applied wording to the behaviour it describes, so the two cannot drift apart again."""
    rules = {k: p for k, _, p in REQUIRED_GAPS}
    run_to_report(orch)
    st = orch.state
    # verified origin: other country Excluded, missing country Hold (even with a supporting publication, R15)
    assert "Excluded" in rules["verified_origin"] and st.sample("DEMO-R06").eligibility == "Excluded"
    assert "Hold" in rules["verified_origin"] and st.sample("DEMO-R15").eligibility == "Hold"
    # missing DST: kept, never excluded for lacking DST (R02 has no DST and is analysed)
    assert "Kept in the cohort" in rules["missing_dst"] and not st.sample("DEMO-R02").dst and st.sample("DEMO-R02").profiling == "Done"
    # duplicates: the first run is kept, the later one excluded when the agent confirms (R01 kept, R07 excluded)
    assert "first run seen" in rules["duplicates"] and st.sample("DEMO-R01").eligibility == "Verified" and st.sample("DEMO-R07").eligibility == "Excluded"


# ---------------------------------------------------------------- logging: every agent logs what it does
def test_every_agent_logs_its_actions(orch, caplog):
    """Each agent (and the orchestrator and humans) must leave a readable log of its actions in the Logs tab."""
    import logging
    caplog.set_level(logging.INFO, logger="tbamr")
    run_to_report(orch)
    by = {}
    for r in caplog.records:
        by.setdefault(r.name, []).append(r.getMessage())
    minimum = {"tbamr.orchestrator": 20, "tbamr.agents.scope_guardian": 3, "tbamr.agents.discovery": 5,
               "tbamr.agents.verification": 20, "tbamr.agents.qc": 20, "tbamr.agents.profiling": 20,
               "tbamr.agents.evidence": 20, "tbamr.agents.reporting": 5, "tbamr.humans": 5}
    short = {k: len(by.get(k, [])) for k, n in minimum.items() if len(by.get(k, [])) < n}
    assert not short, f"too few log lines: {short}"
    joined = "\n".join(m for msgs in by.values() for m in msgs)
    for needle in ("decision stage=2 sample=DEMO-R01", "tool ena_search_runs", "outcome=Approve", "raw data viewed by",
                   "report v1 RIF:", "Stage 3 finished", "→ Orchestrator.run_stage(", "← QCAnalyst.assess ok"):
        assert needle in joined, f"missing log: {needle!r}"


def test_worker_thread_logs_reach_the_execution(tmp_path):
    """Thread-pool work (TB-Profiler batches) must log into the execution that started it, not vanish."""
    import logging
    import threading
    from tbamr.core.executions import attach_buffer, capture_execution, current_buffer
    log = DecisionLog(str(tmp_path / "x.db"))
    with capture_execution(log, "batch"):
        buf = current_buffer()

        def worker():
            with attach_buffer(buf):
                logging.getLogger("tbamr.profiling").info("worker says hi")

        t = threading.Thread(target=worker)
        t.start(); t.join()
    ex = log.get_execution(log.list_executions(1)[0]["id"])
    assert "worker says hi" in ex["log_text"]


def test_default_cohort_target_is_realistic():
    """A new scope aims for 100 isolates (95% CI within about +/-10 points), not 8."""
    from tbamr.api import Scope
    from tbamr.core.models import DEFAULT_COHORT_TARGET, PipelineState
    assert DEFAULT_COHORT_TARGET == 100 and PipelineState().cohort_target == 100 and Scope(question="q").cohort_target == 100


# ---------------------------------------------------------------- minimum cohort: search effort and adequacy, never selection
def test_short_cohort_is_flagged_and_searched_but_nothing_is_dropped(orch):
    orch.state.cohort_target = 100  # the demo has 31 verified isolates
    rep = run_to_report(orch)
    kinds = {c["kind"] for c in orch.state.cohort_checks}
    assert {"below_minimum", "below_minimum_qc"} <= kinds
    assert orch.state.replans == 1 and any("planned minimum of 100" in d["rationale"] and d["outcome"] == "Retry" for d in orch.log.all())
    assert rep["counts"]["verified"] == 31 and rep["counts"]["planned_minimum"] == 100  # every eligible isolate kept
    assert any("analysed against a planned minimum of 100" in l for l in rep["limitations"])


def test_cohort_at_or_above_the_minimum_is_not_flagged(orch):
    orch.state.cohort_target = 20
    run_to_report(orch)
    assert not {"below_minimum", "below_minimum_qc"} & {c["kind"] for c in orch.state.cohort_checks}
    assert orch.state.replans == 0


def test_discovery_is_told_the_minimum_and_never_to_drop_candidates():
    seen = []
    def policy(messages):
        seen.append(messages[0]["content"])
        return [{"type": "tool_use", "name": "submit", "input": {"candidate_runs": [], "studies": [], "search_notes": "", "concerns": []}}]
    DiscoveryAssistant(DecisionLog(), ReplayClient({"discovery": policy}), DemoDataTools()).discover("Indonesia", "q?", minimum=100)
    assert "at least 100 isolates" in seen[0] and "Never drop candidates" in seen[0]
