"""Orchestrator: coordinates the agent team, enforces human gates and re-plans on escalation.

The Orchestrator is deliberately rule-based: it decides WHO works next and WHEN a human must
approve, but every judgment call inside a stage belongs to an agent or a human.
"""
from __future__ import annotations

import json
import os
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..agents.discovery import DiscoveryAssistant
from ..agents.evidence import EvidenceAnalyst
from ..agents.profiling import ProfilingTasker
from ..agents.qc import QCAnalyst
from ..agents.reporting import ReportingOrchestrator
from ..agents.scope_guardian import ScopeGuardian
from ..agents.verification import VerificationTasker
from ..tools.demo import DST as DEMO_DST
from ..tools.demo import demo_tbprofiler_json
from ..tools.tbprofiler import parse_result
from .decisions import Decision, DecisionLog, Outcome
from .models import GATES, ROLES, RULES, STAGES, THRESHOLDS, PipelineState, Sample


class PermissionDenied(Exception):
    pass


class StageError(Exception):
    pass


class Orchestrator:
    name = "orchestrator"
    title = "Orchestrator"
    description = "Hands work between agents, stops at human gates, and re-plans when an agent escalates (for example, asks Discovery for more studies)."

    def __init__(self, log: DecisionLog, client, data, runner=None, max_replans: int = 1):
        self.log, self.client, self.data = log, client, data
        self.lock = threading.RLock()
        self.agents = {
            "scope_guardian": ScopeGuardian(log, client),
            "discovery": DiscoveryAssistant(log, client, data),
            "verification": VerificationTasker(log, client, data),
            "qc": QCAnalyst(log),
            "profiling": ProfilingTasker(log, runner),
            "evidence": EvidenceAnalyst(log, client),
            "reporting": ReportingOrchestrator(log, client),
        }
        self.max_replans = max_replans
        saved = log.get("state")
        self.state = PipelineState.from_dict(saved) if saved else PipelineState()
        self.pending_overrides: list[dict[str, Any]] = log.get("pending_overrides", [])
        self.busy: str | None = None

    # ------------------------------------------------------------------ helpers
    @property
    def demo(self) -> bool:
        return bool(getattr(self.data, "is_demo", False))

    def save(self) -> None:
        self.log.put("state", self.state.to_dict())
        self.log.put("pending_overrides", self.pending_overrides)

    def orch(self, sample: str, outcome: Outcome, rule: str, text: str, stage: int = 0) -> None:
        self.log.add(Decision(sample_id=sample, outcome=outcome, rule_version=rule, rationale=text, actor="agent:orchestrator", stage=stage))
        self.log.trace("orchestrator", "handoff", {"text": text})

    def human(self, role: str, person: str, sample: str, outcome: Outcome, rule: str, text: str, stage: int = 0, evidence: str = "") -> None:
        self.log.add(Decision(sample_id=sample, outcome=outcome, rule_version=rule, rationale=text, actor=f"human:{role}:{person or 'unnamed'}",
                              stage=stage, evidence=evidence))

    # ------------------------------------------------------------------ raw data before decisions
    @staticmethod
    def ident(role: str, person: str) -> str:
        return (person or "").strip() or ROLES.get(role, role)

    def note_raw(self, role: str, person: str, kind: str, key: str, what: str) -> str:
        """Note whether this person opened the raw data behind their decision. Not required, but recorded."""
        ts = self.log.viewed_at(self.ident(role, person), kind, key)
        if not ts:
            return f"Raw data ({kind}/{key}) for {what} was not opened before this decision."
        import time as _t
        return f"Raw data ({kind}/{key}) viewed by {self.ident(role, person)} at {_t.strftime('%Y-%m-%d %H:%M:%S', _t.localtime(ts))}"

    def raw_view(self, kind: str, key: str, role: str, person: str) -> dict[str, Any]:
        payload = self._assemble_raw(kind, key)
        if payload is None:
            hint = " The original TB-Profiler file was not saved by the earlier version: import it again in Stage 4." if kind == "tbprofiler" else ""
            raise StageError(f"No raw data has been recorded for {kind}/{key} yet.{hint}")
        if '"_note"' in json.dumps(payload.get("data"), default=str):
            payload["note"] = "This pipeline was started before raw data was saved, so part of this record was filled in afterwards (marked _note in the JSON). It may differ from what the agents saw if the source changed since."
        ts = None if kind == "tool" else self.log.record_view(self.ident(role, person), role, kind, key)
        return {"kind": kind, "key": key, "viewed_at": ts, "viewer": self.ident(role, person), **payload}

    LATE = "This pipeline was started before raw data was saved, so this record was fetched again just now from the same source. It may differ from what the agents saw if the source changed since."

    def _backfill(self, kind: str, key: str) -> None:
        """Fill raw data missing from pipelines started with an older version."""
        st, log = self.state, self.log
        try:
            if kind == "ena" and log.get_raw("ena", key) is None:
                rec = self.data.ena_run(key)
                if rec:
                    log.put_raw("ena", key, {**rec, "_note": self.LATE})
            elif kind in ("cohort", "qc"):
                runs = [s.run for s in st.samples if kind == "cohort" or s.in_cohort]
                for run in runs:
                    if log.get_raw("ena", run) is None:
                        self._backfill("ena", run)
            elif kind == "scope" and log.get_raw("scope", "guardian") is None and st.scope:
                log.put_raw("scope", "guardian", {"result": st.scope, "_note": "This pipeline was started before raw data was saved: the Guardian's original input was not recorded, only its stored result."})
            elif kind in ("tbprofiler", "profiling"):
                runs = [key] if kind == "tbprofiler" else [s.run for s in st.samples if s.profiling == "Done"]
                for run in runs:
                    if log.get_raw("tbprofiler", run) is None and self.demo:
                        j = demo_tbprofiler_json(run)
                        if j:
                            log.put_raw("tbprofiler", run, {**j, "_note": self.LATE})
            elif kind == "report" and log.get_raw("report", key) is None and st.report and str(st.report.get("version")) == key:
                log.put_raw("report", key, st.report)
        except Exception:  # never let a backfill failure hide the real error message
            pass

    def _assemble_raw(self, kind: str, key: str) -> dict[str, Any] | None:
        self._backfill(kind, key)
        st, raw = self.state, self.log.get_raw
        src = "simulated demo records" if self.demo else "ENA Portal API (read_run)"
        if kind == "scope":
            d = raw("scope", "guardian")
            return d and {"title": "Scope Guardian: input and result", "source": f"Scope Guardian ({d.get('brain')})",
                          "explanation": "Exactly what the Guardian received and what it returned, before you approve the scope.", "data": d}
        if kind == "ena":
            d = raw("ena", key)
            if d is None:
                return None
            s = st.sample(key)
            derived = {"base_count": d.get("base_count"), "genome_length_bp": THRESHOLDS["genome_bp"],
                       "estimated_coverage": round(int(d["base_count"]) / THRESHOLDS["genome_bp"], 1) if str(d.get("base_count", "")).isdigit() else None}
            return {"title": f"Source record for {key}", "source": src,
                    "explanation": "The run's record exactly as the archive returned it, the evidence an agent gathered (if any), and how coverage was derived.",
                    "data": {"ena_record": d, "agent_evidence": raw("evidence", key), "derived": derived,
                             "current_status": {"eligibility": s.eligibility, "qc": s.qc} if s else None}}
        if kind == "cohort":
            rows = [raw("ena", s.run) or {} for s in st.samples]
            cols = ["run_accession", "sample_accession", "study_accession", "country", "library_strategy", "instrument_platform", "base_count", "fastq_md5"]
            stat = {s.run: s.eligibility for s in st.samples}
            return {"title": "All candidate runs (raw archive records)", "source": src,
                    "explanation": "Every candidate run as returned by the archive, with the eligibility the agents assigned. Check locations, studies and duplicates yourself before approving.",
                    "table": {"columns": cols + ["eligibility"], "rows": [[r.get(c, "") for c in cols] + [stat.get(r.get("run_accession"))] for r in rows]},
                    "data": {"records": rows, "cohort_checks": st.cohort_checks}}
        if kind == "qc":
            rows = []
            for s in st.samples:
                if s.in_cohort:
                    r = raw("ena", s.run) or {}
                    rows.append([s.run, r.get("base_count"), THRESHOLDS["genome_bp"], s.coverage, r.get("fastq_md5", ""), s.qc])
            return {"title": "QC inputs: base counts and checksums", "source": src,
                    "explanation": f"Estimated coverage = base_count ÷ {THRESHOLDS['genome_bp']:,} bp. Thresholds: ≥{THRESHOLDS['min_cov']:g}× pass, {THRESHOLDS['border_cov']:g}–{THRESHOLDS['min_cov']:g}× escalate, below {THRESHOLDS['border_cov']:g}× exclude.",
                    "table": {"columns": ["run", "base_count", "genome_bp", "est_coverage", "fastq_md5", "qc"], "rows": rows}, "data": {"rows": rows, "thresholds": THRESHOLDS}}
        if kind == "profiling":
            rows = []
            for s in st.samples:
                if s.qc == "Pass":
                    m = s.profile_meta or {}
                    rows.append([s.run, s.profiling, m.get("tool"), m.get("db"), len(m.get("mutations", [])), m.get("median_depth"), m.get("file")])
            return {"title": "TB-Profiler results in this batch", "source": "TB-Profiler result files",
                    "explanation": "One row per QC-passed run. Open any run to see its full TB-Profiler JSON.",
                    "table": {"columns": ["run", "status", "tool", "database", "resistance annotations", "median depth", "file"], "rows": rows}, "data": {"rows": rows}}
        if kind == "tbprofiler":
            d = raw("tbprofiler", key)
            return d and {"title": f"TB-Profiler result for {key}", "source": "TB-Profiler JSON, verbatim",
                          "explanation": "The full result file. Resistance calls are under dr_variants; the Evidence Analyst's findings are derived from it.", "data": d}
        if kind == "report":
            d = raw("report", key)
            return d and {"title": f"Report v{key}: underlying data", "source": "Reporting Orchestrator", "explanation": "Every number shown in the report, as computed.", "data": d}
        if kind == "tool":
            d = raw("tool", key)
            return d and {"title": f"Full tool response: {d.get('tool')}", "source": f"{d.get('agent')} agent tool call", "explanation": "Exactly what the tool returned to the agent.", "data": d}
        return None


    @staticmethod
    def require(role: str, allowed: list[str]) -> None:
        if role not in allowed:
            raise PermissionDenied(f"This needs the {' or '.join(ROLES[r] for r in allowed)} role.")

    def _status(self, n: int) -> str:
        return self.state.stage_status[str(n)]

    def _set(self, n: int, status: str) -> None:
        self.state.stage_status[str(n)] = status

    def _complete(self, n: int) -> None:
        self._set(n, "done")
        if n < 6 and self._status(n + 1) == "locked":
            self._set(n + 1, "ready")

    # ------------------------------------------------------------------ stages
    def run_stage(self, n: int) -> dict[str, Any]:
        with self.lock:
            status = self._status(n)
            allowed = status == "ready" or (n == 5 and status == "done") or (n == 6 and status == "wait")
            if not allowed:
                raise StageError(f"Stage {n} is {status} and cannot run now.")
            self.busy = STAGES[n - 1]["name"]
            try:
                out = [self._s1, self._s2, self._s3, self._s4, self._s5, self._s6][n - 1]()
            finally:
                self.busy = None
                self.save()
            return out

    def _s1(self):
        st = self.state
        self.orch("—", Outcome.INFO, RULES["scope"], "Handing the research scope to the Scope Guardian.", 1)
        st.scope = self.agents["scope_guardian"].review(st.question, st.country, st.target_drugs, st.cohort_target)
        self._set(1, "wait")
        return st.scope

    def _s2(self):
        st = self.state
        self.orch("—", Outcome.INFO, RULES["elig"], "Asking the Discovery Assistant for candidate runs.", 2)
        found = self.agents["discovery"].discover(st.country, st.question)
        self._add_rows(found["rows"])
        self.orch("—", Outcome.INFO, RULES["elig"], f"Handing {len(st.samples)} candidate(s) to the Verification Tasker.", 2)
        self.agents["verification"].verify(st.samples, st.country)
        st.cohort_checks = self._cohort_checks(found.get("total_in_ena", 0))
        # re-plan: the cohort cannot answer a comparison across places → ask Discovery to widen the search once
        if any(c["kind"] == "single_location" and c["outcome"] == "Escalate" for c in st.cohort_checks) and st.replans < self.max_replans:
            st.replans += 1
            studies = sorted({s.study for s in st.samples if s.eligibility == "Verified"})
            self.orch("COHORT", Outcome.RETRY, RULES["cohort"], f"Re-planning: asking Discovery for studies other than {', '.join(studies)} to support the comparison.", 2)
            more = self.agents["discovery"].discover(st.country, st.question, already_known=[s.run for s in st.samples],
                                                     focus=f"The verified cohort comes from one location. Find runs from other studies than {', '.join(studies)}.",
                                                     exclude_studies=studies)
            new = self._add_rows(more["rows"])
            if new:
                self.agents["verification"].verify(new, st.country)
            st.cohort_checks = self._cohort_checks(max(found.get("total_in_ena", 0), more.get("total_in_ena", 0)))
            self.orch("COHORT", Outcome.INFO, RULES["cohort"], f"Re-plan added {len(new)} run(s).", 2)
        self._set(2, "wait")
        return {"candidates": len(st.samples), "checks": st.cohort_checks}

    def _add_rows(self, rows: list[dict[str, Any]]) -> list[Sample]:
        known = {s.run for s in self.state.samples}
        new = []
        for r in rows:
            if r["run_accession"] in known:
                continue
            s = Sample(run=r["run_accession"], biosample=r.get("sample_accession", ""), study=r.get("study_accession", ""),
                       country=r.get("country", "") or "", library_strategy=r.get("library_strategy", "") or "",
                       platform=r.get("instrument_platform", "") or "", base_count=int(r["base_count"]) if str(r.get("base_count", "")).isdigit() else None,
                       md5=bool(r.get("fastq_md5")))
            if self.demo:
                s.dst = dict(DEMO_DST.get(s.run, {}))
            self.log.put_raw("ena", s.run, r)
            self.state.samples.append(s)
            new.append(s)
            known.add(s.run)
        return new

    def _cohort_checks(self, total: int) -> list[dict[str, Any]]:
        asks = bool(self.state.scope.get("asks_comparison_across_places"))
        return self.agents["verification"].cohort_checks(self.state.samples, asks, total)

    def _s3(self):
        res = self.agents["qc"].assess(self.state.samples)
        self._set(3, "wait")
        return res

    def _s4(self):
        n = self.agents["profiling"].queue(self.state.samples)
        if self.demo:  # simulate the analyst importing TB-Profiler files
            for s in self.state.samples:
                j = demo_tbprofiler_json(s.run) if s.profiling == "Awaiting results" else None
                if j:
                    self.agents["profiling"].apply_result(s, parse_result(j, f"{s.run}.results.json"), "simulated demo result", j)
        self._set(4, "wait")
        return {"queued": n}

    def _s5(self):
        res = self.agents["evidence"].evaluate(self.state.samples)
        self._complete(5)
        return res

    def _s6(self):
        prev = self.state.report["version"] if self.state.report else 0
        self.state.report = self.agents["reporting"].build(self.state, prev + 1)
        self.log.put_raw("report", str(prev + 1), self.state.report)
        self._set(6, "wait")
        return self.state.report

    # ------------------------------------------------------------------ human gates
    def approve_scope(self, role: str, person: str) -> None:
        with self.lock:
            self.require(role, GATES["scope"])
            if self._status(1) != "wait":
                raise StageError("The scope has not been reviewed yet.")
            if self.state.scope.get("blocking"):
                raise StageError("Fix the blocking gaps first.")
            ev = self.note_raw(role, person, "scope", "guardian", "the Scope Guardian's result")
            self.state.gates["scope"] = {"by": person, "role": role}
            self.human(role, person, "—", Outcome.APPROVE, RULES["scope"], "Scope approved; proposed definitions accepted.", 1, ev)
            self._complete(1)
            self.save()

    def resolve_hold(self, role: str, person: str, run: str, decision: str, rationale: str) -> None:
        with self.lock:
            self.require(role, GATES["cohort"])
            s = self._sample(run)
            if s.eligibility != "Hold":
                raise StageError(f"{run} is not on hold.")
            if not rationale.strip():
                raise StageError("A rationale is required.")
            ev = self.note_raw(role, person, "ena", run, run)
            if decision == "verify":
                s.eligibility, s.eligibility_note = "Verified", f"Human decision: {rationale}"
                self.human(role, person, run, Outcome.PROCEED, RULES["elig"], rationale, 2, ev)
            elif decision == "exclude":
                s.eligibility, s.eligibility_note = "Excluded", f"Human decision: {rationale}"
                self.human(role, person, run, Outcome.EXCLUDE, RULES["elig"], rationale, 2, ev)
            else:
                self.human(role, person, run, Outcome.HOLD, RULES["elig"], rationale, 2, ev)
            if self._status(2) == "done" and s.eligibility == "Verified":
                s.in_cohort = True
                self._revalidate(s)
            self.save()

    def approve_cohort(self, role: str, person: str) -> None:
        with self.lock:
            self.require(role, GATES["cohort"])
            if self._status(2) != "wait":
                raise StageError("Discovery and verification have not run yet.")
            ev = self.note_raw(role, person, "cohort", "all", "the candidate runs")
            n = 0
            for s in self.state.samples:
                if s.eligibility == "Verified":
                    s.in_cohort, n = True, n + 1
            self.state.gates["cohort"] = {"by": person, "role": role, "n": n, "accepted_checks": [c["text"] for c in self.state.cohort_checks]}
            self.human(role, person, "—", Outcome.APPROVE, RULES["elig"], f"Cohort approved: {n} verified run(s); cohort checks accepted as limitations.", 2, ev)
            self._complete(2)
            self.save()

    def confirm_qc(self, role: str, person: str) -> None:
        with self.lock:
            self.require(role, ["analyst"])
            if self._status(3) != "wait":
                raise StageError("QC has not run yet.")
            ev = self.note_raw(role, person, "qc", "all", "the QC inputs")
            self.human(role, person, "—", Outcome.APPROVE, RULES["qc"], "QC decisions confirmed.", 3, ev)
            self._complete(3)
            self.save()

    def resolve_qc(self, role: str, person: str, run: str, decision: str, rationale: str) -> None:
        with self.lock:
            self.require(role, ["analyst"])
            s = self._sample(run)
            if s.qc != "Escalated" or not rationale.strip():
                raise StageError("Only escalated QC results can be resolved, with a rationale.")
            ev = self.note_raw(role, person, "ena", run, run)
            s.qc, s.qc_note = ("Pass", f"Analyst exception: {rationale}") if decision == "proceed" else ("Excluded", f"Excluded by analyst: {rationale}")
            self.human(role, person, run, Outcome.PROCEED if decision == "proceed" else Outcome.EXCLUDE, RULES["qc"], rationale, 3, ev)
            self._revalidate(s)
            self.save()

    def import_results(self, role: str, person: str, files: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        with self.lock:
            self.require(role, ["analyst"])
            ok, skipped = [], []
            for fname, data in files:
                p = parse_result(data, fname)
                s = self.state.sample(p["sample_id"])
                if not s:
                    skipped.append(f"{fname}: {p['sample_id']} is not in this cohort")
                    continue
                if s.qc != "Pass":
                    skipped.append(f"{fname}: {s.run} did not pass QC")
                    continue
                self.agents["profiling"].apply_result(s, p, f"imported by {person or ROLES[role]}", data)
                ok.append(s.run)
            if ok and self._status(5) == "done":
                self.agents["evidence"].evaluate(self.state.samples)
            if ok and self.state.report:
                self.state.report["superseded"] = True
            self.save()
            return {"imported": ok, "skipped": skipped}

    def run_profiler(self, role: str, person: str, runs: list[str]) -> dict[str, Any]:
        """Run TB-Profiler locally in a bounded thread pool so several samples profile at once.

        Concurrency comes from the TBAMR_PROFILER_CONCURRENCY env var (default max(1, cpu_count//2)).
        Each worker also uses TBAMR_PROFILER_THREADS cores (default 4) inside tb-profiler and
        fasterq-dump. Keep concurrency × threads below your physical core count."""
        self.require(role, ["analyst"])
        default_conc = max(1, (os.cpu_count() or 2) // 2)
        concurrency = max(1, int(os.environ.get("TBAMR_PROFILER_CONCURRENCY", str(default_conc))))
        inflight: set[str] = set()

        def refresh_busy() -> None:
            if not inflight:
                self.busy = None
            else:
                head = sorted(inflight)[:2]
                extra = len(inflight) - len(head)
                self.busy = f"TB-Profiler: {', '.join(head)}" + (f" + {extra} more" if extra > 0 else "")

        def profile_one(r: str) -> None:
            # Any failure here (runner crash, log DB write failure, …) is caught so one bad sample never
            # kills the whole pool thread; the error gets written to the sample's note and logged.
            import logging as _lg
            s = self.state.sample(r)
            if not s or s.qc != "Pass":
                return
            with self.lock:
                inflight.add(r)
                refresh_busy()
            try:
                try:
                    self.agents["profiling"].run_one(s)
                except Exception as e:
                    _lg.getLogger("tbamr.profiling").exception("profile_one crashed for %s", r)
                    try:
                        s.profiling = s.profiling or "Failed"
                        s.profiling_note = f"Worker crashed: {type(e).__name__}: {e}"
                    except Exception:
                        pass
            finally:
                with self.lock:
                    inflight.discard(r)
                    refresh_busy()
                    try:
                        self.save()
                    except Exception:
                        _lg.getLogger("tbamr.profiling").exception("state save failed after %s", r)

        def work() -> None:
            with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="tbp") as pool:
                for _ in pool.map(profile_one, runs):
                    pass
            with self.lock:
                self.busy = None
                try:
                    self.save()
                except Exception:
                    pass
        threading.Thread(target=work, daemon=True).start()
        return {"started": runs, "concurrency": concurrency, "threads_per_sample": self.agents["profiling"].runner.threads}

    def close_profiling(self, role: str, person: str) -> None:
        with self.lock:
            self.require(role, GATES["profiling_batch"])
            done = sum(s.profiling == "Done" for s in self.state.samples)
            if not done:
                raise StageError("Import or run at least one TB-Profiler result first.")
            ev = self.note_raw(role, person, "profiling", "all", "the TB-Profiler results")
            self.human(role, person, "—", Outcome.APPROVE, RULES["prof"], f"Profiling batch closed with {done} result(s).", 4, ev)
            self._complete(4)
            self.save()

    def review(self, role: str, person: str, fid: str, decision: str, rationale: str) -> None:
        with self.lock:
            self.require(role, ["tbexpert"])
            f = next((f for f in self.state.findings() if f.fid == fid), None)
            if not f or f.review != "Pending":
                raise StageError("That finding is not pending review.")
            if decision not in ("Reviewed", "Not supported", "Needs more data") or not rationale.strip():
                raise StageError("Choose a review decision and give a rationale.")
            ev = self.note_raw(role, person, "tbprofiler", f.sample_id, f"{f.sample_id}'s TB-Profiler result")
            f.review, f.reviewer, f.rationale = decision, f"{ROLES[role]} ({person})" if person else ROLES[role], rationale
            self.human(role, person, f.sample_id, {"Reviewed": Outcome.PROCEED, "Needs more data": Outcome.HOLD}.get(decision, Outcome.EXCLUDE),
                       RULES["evid"], f"Review of {f.gene} {f.change}: {decision} — {rationale}", 5, ev)
            if self.state.report:
                self.state.report["superseded"] = True
            self.save()

    def release(self, role: str, person: str, kind: str) -> None:
        with self.lock:
            self.require(role, GATES["release"])
            rep = self.state.report
            if not rep:
                raise StageError("No report yet.")
            pending = len(rep.get("unresolved", []))
            if kind == "final" and (pending or rep.get("superseded")):
                raise StageError("Final release is blocked while findings are pending or the report is superseded.")
            ev = self.note_raw(role, person, "report", str(rep["version"]), f"report v{rep['version']}")
            self.state.gates["release"] = {"by": person, "role": role, "kind": kind, "version": rep["version"]}
            self.human(role, person, "—", Outcome.APPROVE, RULES["rpt"], f"{'Final release' if kind == 'final' else 'Exploratory draft shared'}: report v{rep['version']}.", 6, ev)
            if kind == "final":
                self._set(6, "done")
            self.save()

    def draft_summary(self) -> str:
        if not self.state.report:
            raise StageError("No report yet.")
        text = self.agents["reporting"].draft_summary(self.state.report)
        self.state.report["summary_draft"] = text
        self.save()
        return text

    def save_summary(self, text: str) -> str:
        """Save a human-edited plain-language summary. Trusts the editor; they're the author now."""
        if not self.state.report:
            raise StageError("No report yet.")
        self.state.report["summary_draft"] = text
        self.state.report["summary_edited"] = True  # mark it as human-edited (vs AI-drafted)
        self.save()
        return text

    # ------------------------------------------------------------------ overrides (two-person rule)
    ORDER = {"eligibility": {"Verified": 0, "Hold": 1, "Excluded": 2}, "qc": {"Pass": 0, "Escalated": 1, "Hold": 1, "Excluded": 2}}

    def override(self, role: str, person: str, run: str, field: str, to: str, rationale: str) -> dict[str, Any]:
        with self.lock:
            owners = GATES["cohort"] if field == "eligibility" else ["analyst"]
            self.require(role, owners)
            s = self._sample(run)
            frm = getattr(s, field)
            if not rationale.strip() or frm == to:
                raise StageError("Give a rationale and a different status.")
            if self.ORDER[field].get(to, 9) > self.ORDER[field].get(frm, 0):  # more cautious → immediate
                self._apply_override(s, field, frm, to, rationale, [f"{ROLES[role]} ({person})"])
                return {"applied": True}
            p = {"id": f"ov{len(self.pending_overrides) + 1}-{run}", "run": run, "field": field, "from": frm, "to": to,
                 "rationale": rationale, "role": role, "person": person}
            self.pending_overrides.append(p)
            self.human(role, person, run, Outcome.OVERRIDE, RULES["elig" if field == "eligibility" else "qc"],
                       f"Requested {frm} → {to} (relaxes a safeguard); waiting for a second, different person.", 0)
            self.save()
            return {"applied": False, "pending": p}

    def cosign(self, role: str, person: str, override_id: str) -> None:
        with self.lock:
            p = next((x for x in self.pending_overrides if x["id"] == override_id), None)
            if not p:
                raise StageError("No such pending override.")
            if not person or person.strip().lower() == (p["person"] or "").strip().lower():
                raise PermissionDenied("The second sign-off must come from a different, named person.")
            if role not in ROLES:
                raise PermissionDenied("Unknown role.")
            self.pending_overrides.remove(p)
            self._apply_override(self._sample(p["run"]), p["field"], p["from"], p["to"], p["rationale"],
                                 [f"{ROLES[p['role']]} ({p['person']})", f"{ROLES[role]} ({person})"])

    def _apply_override(self, s: Sample, field: str, frm: str, to: str, rationale: str, signers: list[str]) -> None:
        setattr(s, field, to)
        setattr(s, field + "_note", f"Override: {rationale}")
        if field == "eligibility" and to != "Verified":
            s.in_cohort = False
        self.log.add(Decision(sample_id=s.run, outcome=Outcome.OVERRIDE, rule_version=RULES["elig" if field == "eligibility" else "qc"],
                              rationale=f"{frm} → {to}: {rationale}", actor="human:" + " + ".join(signers), evidence="original agent decision kept in history"))
        self._revalidate(s)
        self.save()

    def _revalidate(self, s: Sample) -> None:
        self.orch(s.run, Outcome.INFO, RULES["rpt"], "Re-validation: downstream results for this run are recomputed.")
        if self.state.report:
            self.state.report["superseded"] = True
        if s.eligibility == "Verified" and self._status(2) == "done":
            s.in_cohort = True
        if s.in_cohort and self._status(3) in ("wait", "done") and not s.qc:
            self.agents["qc"].assess([s])
        if s.qc == "Pass" and self._status(4) in ("wait", "done") and not s.profiling:
            self.agents["profiling"].queue([s])

    def _sample(self, run: str) -> Sample:
        s = self.state.sample(run)
        if not s:
            raise StageError(f"Unknown run {run}.")
        return s

    # ------------------------------------------------------------------ reads
    def metrics(self) -> dict[str, Any]:
        L = self.log.all()
        agent = [d for d in L if d["actor"].startswith("agent:") and d["outcome"] != "Info"]
        human = [d for d in L if d["actor"].startswith("human:")]
        c = Counter(d["outcome"] for d in L)
        approvals, overrides = c.get("Approve", 0), c.get("Override", 0)
        esc_runs = {d["sample_id"] for d in L if d["outcome"] == "Escalate" and d["sample_id"] not in ("—", "COHORT", "SCOPE")}
        times, resolved, false_holds = [], 0, 0
        for r in esc_runs:
            e = min(d["ts"] for d in L if d["sample_id"] == r and d["outcome"] == "Escalate")
            h = [d for d in L if d["sample_id"] == r and d["actor"].startswith("human:")]
            if h:
                resolved += 1
                times.append(min(d["ts"] for d in h) - e)
                false_holds += any(d["outcome"] == "Proceed" for d in h)
        traces = self.log.traces(limit=2000)
        return {
            "decisions": len(L), "agent_decisions": len(agent), "human_decisions": len(human),
            "agreement_pct": round(approvals / (approvals + overrides) * 100) if approvals + overrides else None,
            "escalation_rate_pct": round(c.get("Escalate", 0) / len(agent) * 100) if agent else 0,
            "escalations_resolved": resolved, "escalations_open": len(esc_runs) - resolved,
            "median_resolution_s": sorted(times)[len(times) // 2] if times else None, "possible_false_holds": false_holds,
            "overrides": overrides, "by_outcome": dict(c),
            "by_agent": dict(Counter(d["actor"].split(":")[1] if d["actor"].startswith("agent:") else "human" for d in L)),
            "tool_calls": dict(Counter(t["agent"] for t in traces if t["kind"] == "tool_call")),
            "guardrail_events": sum(1 for t in traces if t["kind"] == "guardrail") + sum(1 for t in traces if t["kind"] == "submit" and any("guardrail" in str(x) for x in (t["payload"].get("concerns") or []) if isinstance(t["payload"], dict))),
            "completeness_pct": round(sum(bool(d["sample_id"] and d["outcome"] and d["rule_version"] and d["ts"]) for d in L) / len(L) * 100) if L else 100,
        }

    def team(self) -> list[dict[str, Any]]:
        cards = [{"name": self.name, "title": self.title, "kind": "coordinator", "description": self.description, "tools": ["handoff", "re-plan"]}]
        cards += [a.card() for a in self.agents.values()]
        traces = self.log.traces(limit=3000)
        for c in cards:
            mine = [t for t in traces if t["agent"] == c["name"]]
            c["activity"] = {"tool_calls": sum(t["kind"] == "tool_call" for t in mine), "thoughts": sum(t["kind"] == "thought" for t in mine),
                             "submissions": sum(t["kind"] == "submit" for t in mine), "last": mine[0] if mine else None}
            c["decisions"] = sum(1 for d in self.log.all() if d["actor"] == f"agent:{c['name']}")
        return cards

    def snapshot(self) -> dict[str, Any]:
        default_conc = max(1, (os.cpu_count() or 2) // 2)
        return {"state": self.state.to_dict(), "pending_overrides": self.pending_overrides, "busy": self.busy,
                "mode": {"data": "demo" if self.demo else "live", "brain": self.client.mode, "tbprofiler": self.agents["profiling"].runner.available()},
                "profiler_concurrency": int(os.environ.get("TBAMR_PROFILER_CONCURRENCY", str(default_conc))),
                "profiler_threads": self.agents["profiling"].runner.threads,
                "roles": ROLES, "stages": STAGES, "gates": GATES, "rules": RULES}
