"""Scope Guardian (Claude agent) — Stage 1.

Reviews the research question against the playbook, proposes definitions for gaps and
raises warnings. The playbook's four required definitions are always present, even if the
model leaves one out (guardrail).
"""
from __future__ import annotations

from typing import Any

from ..core.decisions import Outcome
from ..core.models import RULES
from .base import LLMAgent

REQUIRED_GAPS = [
    ("verified_origin", '"Verified geographic origin" is not defined.',
     "If the researcher scoped the search to a country or region, Verified only when the ENA/BioSample country field names it. Worldwide searches: origin is informational, not a verification gate. Origin stated only in a publication → Hold for human confirmation."),
    ("missing_dst", "No policy for samples without matched phenotypic DST.",
     'Keep them in the cohort; record DST as "unavailable". Never count missing DST as agreement or disagreement.'),
    ("duplicates", "No rule for repeated isolates (several runs from one sample).",
     "Runs that share a BioSample accession → Hold + Escalate as possible duplicates; one run per isolate in the primary cohort."),
    ("out_of_bounds", "Out-of-bounds conclusions are not stated.",
     "No prevalence estimates, no clinical treatment advice, no new-mutation claims. Reports stay exploratory until reviewed."),
]


class ScopeGuardian(LLMAgent):
    name = "scope_guardian"
    title = "Research Scope & Scientific Integrity Guardian"
    description = "Checks the research question, proposes definitions for the playbook's gaps and flags what the data may not support."
    system_prompt = (
        "Review the researcher's scope. Identify blocking gaps (missing question, drugs or numbers; country is OPTIONAL — "
        "an empty country means a worldwide search and is valid). Propose concrete definitions for the playbook's policy gaps, "
        "and warn about parts of the question that public genomes may not support (prevalence, clinical use, comparisons across "
        "places). You propose; the researcher approves."
    )
    max_steps = 3
    submit_schema = {
        "type": "object",
        "properties": {
            "blocking": {"type": "array", "items": {"type": "string"}},
            "gaps": {"type": "array", "items": {"type": "object", "properties": {"key": {"type": "string"}, "gap": {"type": "string"}, "proposal": {"type": "string"}}, "required": ["gap", "proposal"]}},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "asks_comparison_across_places": {"type": "boolean"},
        },
        "required": ["blocking", "gaps", "warnings", "asks_comparison_across_places"],
    }

    def validate(self, sub: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        gaps = list(sub.get("gaps") or [])
        keys = {g.get("key") for g in gaps}
        for key, gap, proposal in REQUIRED_GAPS:  # never let a required definition disappear
            if key not in keys:
                gaps.append({"key": key, "gap": gap, "proposal": proposal, "added_by": "guardrail"})
        blocking = list(sub.get("blocking") or [])
        if not str(ctx.get("question", "")).strip():
            blocking.append("Research question is empty.")
        if not ctx.get("target_drugs"):
            blocking.append("No target drugs selected.")
        return {"blocking": sorted(set(blocking)), "gaps": gaps, "warnings": list(sub.get("warnings") or []),
                "asks_comparison_across_places": bool(sub.get("asks_comparison_across_places"))}

    def review(self, question: str, country: str, target_drugs: list[str], cohort_target: int) -> dict[str, Any]:
        ctx = {"question": question, "country": country, "target_drugs": target_drugs, "cohort_target": cohort_target,
               "required_policy_gaps": [{"key": k, "gap": g} for k, g, _ in REQUIRED_GAPS]}
        res = self.run("Review this research scope and submit your assessment.", ctx)
        if not res.get("ok"):
            res = {"blocking": [], "gaps": [{"key": k, "gap": g, "proposal": p} for k, g, p in REQUIRED_GAPS],
                   "warnings": ["The Guardian could not complete its review; a human should check the scope."], "asks_comparison_across_places": False}
        self.log.put_raw("scope", "guardian", {"input": ctx, "result": res, "brain": self.client.mode})
        outcome = Outcome.HOLD if res["blocking"] else Outcome.ESCALATE
        self.decide("SCOPE", outcome, RULES["scope"],
                    f"{len(res['blocking'])} blocking gap(s); {len(res['gaps'])} definitions proposed; {len(res['warnings'])} warning(s). Researcher approval needed.",
                    stage=1)
        return res
