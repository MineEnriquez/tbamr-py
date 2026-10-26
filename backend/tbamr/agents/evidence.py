"""Genomic Evidence & Scientific Validation Analyst (rule classes + Claude agent) — Stage 5.

1. Rules classify each TB-Profiler annotation (EVID-v1.0): WHO grading, depth, read fraction, DST.
2. The Claude agent reads the findings for each sample and writes an interpretation note per
   finding (an AI draft for the reviewer) and may ask for additional review.
3. Guardrails: the agent can only make things MORE cautious. It can add a finding to the review
   queue but never remove one, and never mark anything confirmed.
"""
from __future__ import annotations

import re
from typing import Any

from ..core.decisions import Outcome
from ..core.models import RULES, THRESHOLDS, Finding, Sample
from ..tools.tbprofiler import DRUG_NAMES
from .base import LLMAgent

GRADE = {0: "Grading not reported by tool", 1: "Group 1 · Assoc. w/ R", 2: "Group 2 · Assoc. w/ R (interim)", 3: "Group 3 · Uncertain", 5: "Group 5 · Not assoc. w/ R"}


def classify(s: Sample, m: dict[str, Any]) -> Finding:
    fid = re.sub(r"[^A-Za-z0-9_.:-]", "_", f"{s.run}-{m['gene']}-{m['change']}-{m['drug']}")
    f = Finding(fid=fid, sample_id=s.run, drug=m["drug"], gene=m["gene"], change=m["change"], grade=m.get("grade", 0),
                depth=m.get("depth"), freq=m.get("freq", 1.0), confidence=m.get("confidence", ""))
    dst = s.dst.get(m["drug"])
    if f.grade == 5:
        f.cls, f.reason = "other", "Catalogued as not associated with resistance (lineage marker); not counted."
    elif f.grade == 3:
        f.cls, f.review, f.reason = "uncertain", "Pending", "WHO group 3 — uncertain significance; cannot be promoted automatically."
    elif f.depth is not None and f.depth < THRESHOLDS["min_depth"]:
        f.review, f.reason = "Pending", f"Only {f.depth:g} reads at the resistance position (min {THRESHOLDS['min_depth']})."
    elif f.freq < THRESHOLDS["min_freq"]:
        f.review, f.reason = "Pending", f"Variant in {round(f.freq * 100)}% of reads — possible mixed infection or heteroresistance."
    elif dst == "S":
        f.review, f.reason = "Pending", "Genotype predicts resistance but matched DST is susceptible (discordance)."
    elif f.grade == 0:
        f.reason = "Tool classifies this variant as resistance-associated; catalogue grading not in the result file."
    else:
        f.reason = "QC passing; established catalogue grading."
    return f


class EvidenceAnalyst(LLMAgent):
    name = "evidence"
    title = "Genomic Evidence & Scientific Validation Analyst"
    description = "Classifies TB-Profiler findings by rule, writes an interpretation note per finding for the reviewer, and routes uncertain evidence to human review."
    system_prompt = (
        "For each finding, write a short interpretation note for the TB Microbiologist: what the evidence shows, what limits it, "
        "and what to check. You may request review of any finding you think needs a human, but you cannot clear findings "
        "from review or confirm resistance."
    )
    max_steps = 3
    submit_schema = {
        "type": "object",
        "properties": {"notes": {"type": "array", "items": {"type": "object", "properties": {
            "fid": {"type": "string"}, "interpretation": {"type": "string"}, "request_review": {"type": "boolean"}, "why": {"type": "string"}},
            "required": ["fid", "interpretation"]}}},
        "required": ["notes"],
    }

    def validate(self, sub: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        allowed = {f["fid"] for f in ctx.get("findings", [])}
        return {"notes": [n for n in sub.get("notes", []) if n.get("fid") in allowed]}

    def evaluate(self, samples: list[Sample]) -> dict[str, int]:
        todo = [s for s in samples if s.profiling == "Done" and not s.findings and s.profile_meta.get("evaluated") is not True]
        for s in todo:
            muts = s.profile_meta.get("mutations", [])
            s.findings = [classify(s, m) for m in muts]
            s.profile_meta["evaluated"] = True
            if not s.findings:
                self.decide(s.run, Outcome.PROCEED, RULES["evid"], "No resistance-associated variants reported; QC passing.", stage=5)
                continue
            ctx = {"sample": {"run": s.run, "lineage": s.lineage, "tbprofiler_type": s.drtype, "dst": s.dst or "unavailable"},
                   "findings": [{"fid": f.fid, "drug": DRUG_NAMES.get(f.drug, f.drug), "variant": f"{f.gene} {f.change}", "grading": GRADE.get(f.grade, f.confidence),
                                 "depth": f.depth, "read_fraction": f.freq, "rule_classification": f.cls, "rule_review": f.review, "rule_reason": f.reason} for f in s.findings]}
            res = self.run(f"Interpret the findings for {s.run}.", ctx)
            notes = {n["fid"]: n for n in res.get("notes", [])} if res.get("ok") else {}
            for f in s.findings:
                n = notes.get(f.fid)
                if n:
                    f.interpretation = n.get("interpretation", "")
                    if n.get("request_review") and f.review == "Not required" and f.cls != "other":  # more cautious only
                        f.review, f.reason = "Pending", f"{f.reason} Agent requested review: {n.get('why', '')}".strip()
                self.decide(s.run, Outcome.ESCALATE if f.review == "Pending" else Outcome.PROCEED, RULES["evid"],
                            f"{f.gene} {f.change} ({f.drug}): {f.reason}", f"{GRADE.get(f.grade, f.confidence)}; depth {f.depth}; read fraction {f.freq}", stage=5)
        pending = sum(f.review == "Pending" for s in samples for f in s.findings)
        return {"evaluated": len(todo), "pending_review": pending}
