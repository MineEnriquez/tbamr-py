"""Scope Guardian (Claude agent) — Stage 1.

Reviews the research question against the playbook, proposes definitions for gaps and
raises warnings. The playbook's four required definitions are always present, even if the
model leaves one out (guardrail).
"""
from __future__ import annotations

from typing import Any

from ..core.decisions import Outcome
from ..core.geo import resolve_target
from ..core.models import RULES
from ..logutil import logged
from .base import LLMAgent

# The playbook's four required definitions, worded as the rules in this codebase actually apply them.
# These texts are what the PI approves, so they must change whenever the rules change (tests pin them).
REQUIRED_GAPS = [
    ("verified_origin", "Verified geographic origin",
     "Scoped to a country: a run is Verified only when its ENA country field names that country; another country is "
     "Excluded; a missing country is put on Hold for a person (a linked publication can inform that decision but never "
     "verifies a run). Scoped to a region: the ENA location must also name the region, otherwise Hold. Worldwide: origin "
     "is recorded but does not gate verification."),
    ("missing_dst", "Samples without matched phenotypic DST",
     'Kept in the cohort with DST recorded as "unavailable". Missing DST is never counted as agreement or disagreement; '
     "concordance is reported only over runs that have DST."),
    ("duplicates", "Repeated isolates (several runs from one BioSample)",
     "The first run seen for a BioSample is kept. Each later run sharing it is checked by the Verification agent: Excluded "
     "as a repeated isolate when the agent confirms it, otherwise put on Hold for a person. One run per isolate."),
    ("out_of_bounds", "Out-of-bounds conclusions",
     "No prevalence or incidence estimates, no clinical or treatment advice, no new-mutation claims. Regional figures are "
     "counts, not rates. Reports stay exploratory until reviewed."),
]


class ScopeGuardian(LLMAgent):
    name = "scope_guardian"
    title = "Research Scope & Scientific Integrity Guardian"
    description = "Checks the research question, proposes definitions for the playbook's gaps and flags what the data may not support."
    system_prompt = (
        "Review the researcher's scope. Identify blocking gaps (missing question, drugs or numbers). "
        "The target population has already been resolved by rule and is given as `target` in the context: either one "
        "country (optionally one subnational region inside it), or worldwide because the researcher asked for it explicitly. "
        "Never widen or change it. If the target "
        "has a `problem`, it is already blocking. The four playbook definitions are fixed by the pipeline's rules (given as "
        "`required_policy_gaps` with their applied text); you may add a suggestion for any of them, but it is shown as a "
        "suggestion and not applied. Warn about parts "
        "of the question that public genomes may not support (prevalence, clinical use, comparisons across places). "
        "You propose; the researcher approves."
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
        # Guardrail: the applied definitions always come from the rules, never from the model. The model's own wording
        # is kept as a suggestion (shown, not applied) when it says something different.
        proposed = {g.get("key"): g for g in (sub.get("gaps") or []) if isinstance(g, dict)}
        gaps = []
        for key, gap, applied in REQUIRED_GAPS:
            m = proposed.pop(key, None) or {}
            text = str(m.get("proposal") or "").strip()
            g = {"key": key, "gap": gap, "proposal": applied, "applied": True}
            if text and text != applied:
                g["suggestion"] = text
            gaps.append(g)
        for g in proposed.values():  # extra gaps the model raised: suggestions only
            if str(g.get("proposal") or g.get("gap") or "").strip():
                gaps.append({"key": g.get("key") or "other", "gap": g.get("gap") or "Other", "proposal": "", "applied": False,
                             "suggestion": str(g.get("proposal") or "").strip()})
        blocking = list(sub.get("blocking") or [])
        if not str(ctx.get("question", "")).strip():
            blocking.append("Research question is empty.")
        if not ctx.get("target_drugs"):
            blocking.append("No target drugs selected.")
        # Target population (rule, not model): one country, or worldwide only when explicitly asked for.
        target = ctx.get("target") or resolve_target(ctx.get("question"), ctx.get("country"), ctx.get("region"))
        if target["problem"]:
            blocking.append(target["problem"])
        warnings = list(sub.get("warnings") or [])
        for extra in (target.get("note"), target.get("notice")):  # rule notes lead the Guardian's own warnings
            if extra and extra not in warnings:
                warnings.insert(0, extra)
        return {"blocking": sorted(set(blocking)), "gaps": gaps, "warnings": warnings,
                "asks_comparison_across_places": bool(sub.get("asks_comparison_across_places")), "target": target}

    @logged("tbamr.agents")
    def review(self, question: str, country: str, target_drugs: list[str], cohort_target: int, region: str = "") -> dict[str, Any]:
        target = resolve_target(question, country, region)
        ctx = {"question": question, "country": country, "region": region, "target": target, "target_drugs": target_drugs, "cohort_target": cohort_target,
               "required_policy_gaps": [{"key": k, "gap": g, "applied": p} for k, g, p in REQUIRED_GAPS]}
        res = self.run("Review this research scope and submit your assessment.", ctx)
        if not res.get("ok"):
            res = {"blocking": [target["problem"]] if target["problem"] else [], "gaps": [{"key": k, "gap": g, "proposal": p, "applied": True} for k, g, p in REQUIRED_GAPS],
                   "warnings": ([target["notice"]] if target.get("notice") else []) + ["The Guardian could not complete its review; a human should check the scope."], "asks_comparison_across_places": False,
                   "target": target}
        self.log.put_raw("scope", "guardian", {"input": ctx, "result": res, "brain": self.client.mode})
        outcome = Outcome.HOLD if res["blocking"] else Outcome.ESCALATE
        place = target["country"] + (f" · {target['region']}" if target.get("region") else "")
        where = (f"Target population: {place} (from the {target['source']})." if not target["problem"]
                 else f"Target population unclear: {target['problem']}")
        self.decide("SCOPE", outcome, RULES["scope"],
                    f"{where} {len(res['blocking'])} blocking gap(s); {len(res['gaps'])} definitions applied by rule; {len(res['warnings'])} warning(s). Researcher approval needed.",
                    stage=1)
        return res
