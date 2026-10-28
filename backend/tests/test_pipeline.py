import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tbamr.agents.discovery import DiscoveryAssistant
from tbamr.agents.evidence import EvidenceAnalyst
from tbamr.agents.scope_guardian import ScopeGuardian
from tbamr.api import build_orchestrator, create_app
from tbamr.core.decisions import Decision, DecisionLog, GuardrailViolation, Outcome
from tbamr.core.models import Finding, Sample
from tbamr.core.orchestrator import PermissionDenied, StageError
from tbamr.llm.client import ReplayClient
from tbamr.tools.demo import DemoDataTools
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
    assert {s.run for s in st.samples if s.eligibility == "Excluded"} == {"DEMO-R06", "DEMO-R07", "DEMO-R08"}
    assert {s.run for s in st.samples if s.eligibility == "Hold"} == {"DEMO-R15", "DEMO-R16"}
    assert st.sample("DEMO-R04").qc == "Escalated"  # 27x borderline
    assert rep["counts"]["analysed"] == 10
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


def test_ena_paging_with_mock_transport():
    calls = []

    def handler(req: httpx.Request):
        calls.append(dict(req.url.params))
        if req.url.path.endswith("/count"):
            return httpx.Response(200, text="250")
        off, lim = int(req.url.params["offset"]), int(req.url.params["limit"])
        n = max(0, min(lim, 250 - off))
        return httpx.Response(200, json=[{"run_accession": f"SRR{off + i}"} for i in range(n)])

    tools = DataTools(httpx.Client(transport=httpx.MockTransport(handler)))
    res = tools.ena_search_runs("Indonesia", limit=500, page_size=100)
    assert res["returned"] == 250 and res["total_in_ena"] == 250
    assert [c.get("offset") for c in calls if "offset" in c] == ["0", "100", "200"]


# ---------------------------------------------------------------- API
def test_api_flow(tmp_path):
    app = create_app(build_orchestrator("demo", "replay", str(tmp_path / "a.db")))
    c = TestClient(app)
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
