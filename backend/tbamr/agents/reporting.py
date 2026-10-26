"""Research Evidence Consolidation & Reporting Orchestrator (rules + Claude draft) — Stage 6.

All numbers are computed by rule from the pipeline state (denominators from verified,
QC-passed, profiled samples only). Claude may draft a plain-language summary, labelled as a draft.
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Any

from ..core.decisions import Outcome
from ..core.models import RULES, PipelineState
from ..tools.tbprofiler import DRUG_NAMES
from .base import RuleAgent


class ReportingOrchestrator(RuleAgent):
    name = "reporting"
    title = "Research Evidence Consolidation & Reporting Orchestrator"
    description = "Builds the evidence report with correct denominators, mandatory fields and limitations; Claude can draft the summary. Release stays human."

    def __init__(self, log, client):
        super().__init__(log)
        self.client = client

    def build(self, st: PipelineState, version: int) -> dict[str, Any]:
        cohort = [s for s in st.samples if s.in_cohort and s.eligibility == "Verified"]
        qc = [s for s in cohort if s.qc == "Pass"]
        analysed = [s for s in qc if s.profiling == "Done" and s.profile_meta.get("evaluated")]
        n = len(analysed)
        fx = [f for s in analysed for f in s.findings]
        pri = {"RIF": 0, "INH": 1}
        drugs = sorted({"RIF", "INH", *[f.drug for f in fx]}, key=lambda d: (pri.get(d, 2), d))
        rows = []
        for d in drugs:
            pred = {f.sample_id for f in fx if f.drug == d and f.cls == "tech" and f.review != "Not supported"}
            unc = {f.sample_id for f in fx if f.drug == d and (f.cls == "uncertain" or f.review in ("Pending", "Needs more data"))}
            rev = {f.sample_id for f in fx if f.drug == d and f.review == "Reviewed"}
            with_dst = [s for s in analysed if d in s.dst]
            agree = sum(("R" if s.run in pred else "S") == s.dst[d] for s in with_dst)
            rows.append({"drug": d, "name": DRUG_NAMES.get(d, d), "predicted_resistant": len(pred), "n": n,
                         "uncertain_or_pending": len(unc), "reviewed": len(rev), "dst_n": len(with_dst), "concordant": agree if with_dst else None})
        muts = Counter(f"{f.gene} {f.change}" for f in fx if f.cls != "other").most_common(10)
        lineages = Counter(s.lineage for s in analysed if s.lineage).most_common()
        pending = [f for f in fx if f.review in ("Pending", "Needs more data")]
        limitations = [c["text"] for c in st.cohort_checks]
        if not n:
            limitations.append("No TB-Profiler results yet, so there are no resistance predictions.")
        limitations += ["No isolate-matched phenotypic DST is linked unless shown above; missing DST is never counted as agreement.",
                        "Public genomes are a convenience sample: no national prevalence estimate and no clinical use."]
        report = {
            "version": version, "generated_at": time.time(), "rule_version": RULES["rpt"], "superseded": False,
            "counts": {"candidates": len(st.samples), "verified": len(cohort), "qc_passed": len(qc), "analysed": n},
            "drugs": rows, "top_mutations": muts, "lineages": lineages,
            "exclusions": [{"run": s.run, "status": s.eligibility if s.eligibility != "Verified" else s.qc, "reason": s.eligibility_note if s.eligibility != "Verified" else s.qc_note}
                           for s in st.samples if s.eligibility != "Verified" or (s.qc and s.qc != "Pass")],
            "unresolved": [{"run": f.sample_id, "variant": f"{f.gene} {f.change}", "drug": f.drug, "review": f.review, "reason": f.reason} for f in pending],
            "limitations": limitations,
            "provenance": {"tools": sorted({s.profile_meta.get("tool") for s in analysed if s.profile_meta.get("tool")}),
                           "databases": sorted({str(s.profile_meta.get("db")) for s in analysed if s.profile_meta.get("db")}), "rules": RULES},
            "gates": st.gates, "summary_draft": None,
        }
        self.decide("—", Outcome.INFO, RULES["rpt"], f"Draft report v{version} assembled: {n} analysed of {len(cohort)} verified; {len(pending)} unresolved finding(s).", stage=6)
        return report

    def draft_summary(self, report: dict[str, Any]) -> str:
        brief = {k: report[k] for k in ("counts", "drugs", "top_mutations", "lineages", "limitations")}
        system = ("You draft plain-language summaries of TB genomic resistance evidence reports for researchers. Use only the numbers given, "
                  "state denominators, never claim clinical relevance or prevalence, and call nothing confirmed unless 'reviewed' > 0. About 150 words.")
        text = self.client.text(system, f"Report data: {brief}")
        if getattr(self.client, "mode", "") == "replay":
            c = report["counts"]
            text += (f" Counts: {c['candidates']} candidates, {c['verified']} verified, {c['qc_passed']} passed QC, {c['analysed']} profiled and evaluated. "
                     + " ".join(f"{r['name']}: {r['predicted_resistant']}/{r['n']} predicted resistant ({r['uncertain_or_pending']} uncertain or pending)." for r in report["drugs"]))
        return text
