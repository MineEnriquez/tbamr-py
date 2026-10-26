"""Provenance & Eligibility Verification Tasker (rule pre-checks + Claude agent) — Stage 2.

1. Deterministic pre-checks (ELIG-v1.0) classify every run: clear passes and clear failures are
   decided by rule, so they are reproducible.
2. Ambiguous runs (missing country, repeated BioSample, unusual platform) go to the Claude agent,
   which gathers evidence with its tools (study lookups, publication search) and proposes an outcome.
3. Guardrails: the agent can never mark a run Verified when the ENA country field does not name
   the study country — that becomes Hold + Escalate with the agent's evidence attached.
4. Cohort-level checks (ELIG-v1.1) look at the verified set as a whole.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..core.decisions import Outcome
from ..core.models import RULES, Sample
from .base import LLMAgent, Tool


class VerificationTasker(LLMAgent):
    name = "verification"
    title = "Provenance & Eligibility Verification Tasker"
    description = "Applies eligibility rules to every run, investigates ambiguous provenance with its tools, and checks whether the cohort can answer the question."
    system_prompt = (
        "Some runs could not be decided by the eligibility rules. For each one, gather evidence with your tools and propose "
        "Hold, Exclude or Escalate with a short rationale and the evidence you found. Verified origin requires the ENA country "
        "field; a publication alone can support a human decision but cannot verify a run."
    )
    max_steps = 8
    submit_schema = {
        "type": "object",
        "properties": {
            "proposals": {"type": "array", "items": {"type": "object", "properties": {
                "run": {"type": "string"}, "outcome": {"type": "string", "enum": ["Hold", "Exclude", "Escalate"]},
                "rationale": {"type": "string"}, "evidence": {"type": "string"}}, "required": ["run", "outcome", "rationale"]}},
        },
        "required": ["proposals"],
    }

    def __init__(self, log, client, data):
        self.data = data
        super().__init__(log, client)

    def build_tools(self):
        d = self.data
        return [
            Tool("ena_study", "Look up a study (BioProject) by accession.", {"type": "object", "properties": {"study_accession": {"type": "string"}}, "required": ["study_accession"]},
                 lambda study_accession: d.ena_study(study_accession)),
            Tool("find_publications", "Search Europe PMC for publications, e.g. by study accession.", {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]},
                 lambda query, limit=5: d.find_publications(query, limit)),
        ]

    # 1. rule pre-checks -----------------------------------------------------------
    def precheck(self, samples: list[Sample], country: str) -> list[tuple[Sample, str]]:
        seen: dict[str, str] = {}
        ambiguous: list[tuple[Sample, str]] = []
        for s in samples:
            c = s.country.strip()
            if s.library_strategy.upper() != "WGS":
                s.eligibility, s.eligibility_note = "Excluded", f"library_strategy is {s.library_strategy or 'missing'}, not WGS."
                self.decide(s.run, Outcome.EXCLUDE, RULES["elig"], s.eligibility_note, f"ENA run {s.run}", stage=2)
            elif c and country.lower() not in c.lower():
                s.eligibility, s.eligibility_note = "Excluded", f'Country "{c}" is outside the approved scope.'
                self.decide(s.run, Outcome.EXCLUDE, RULES["elig"], s.eligibility_note, f"ENA run {s.run}", stage=2)
            elif not c:
                ambiguous.append((s, "country field missing in ENA"))
            elif s.biosample and s.biosample in seen:
                ambiguous.append((s, f"BioSample {s.biosample} already used by {seen[s.biosample]} (possible repeated isolate)"))
            elif s.platform.upper() != "ILLUMINA":
                ambiguous.append((s, f"platform {s.platform or 'missing'} is not the approved ILLUMINA"))
            else:
                s.eligibility, s.eligibility_note = "Verified", f'Country "{c}"; WGS; Illumina; BioSample not shared.'
                self.decide(s.run, Outcome.PROCEED, RULES["elig"], s.eligibility_note, f"ENA run {s.run}, BioSample {s.biosample}", stage=2)
            if s.biosample and s.biosample not in seen:
                seen[s.biosample] = s.run
        return ambiguous

    # 2-3. agent investigation + guardrails ---------------------------------------
    def validate(self, sub: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        allowed = set(ctx.get("runs", []))
        props = []
        for p in sub.get("proposals", []):
            if p.get("run") not in allowed:
                continue
            outcome = p.get("outcome") if p.get("outcome") in ("Hold", "Exclude", "Escalate") else "Escalate"
            props.append({"run": p["run"], "outcome": outcome, "rationale": p.get("rationale", ""), "evidence": p.get("evidence", "")})
        return {"proposals": props}

    def verify(self, samples: list[Sample], country: str) -> dict[str, Any]:
        ambiguous = self.precheck(samples, country)
        proposals: dict[str, dict[str, Any]] = {}
        if ambiguous:
            ctx = {"runs": [s.run for s, _ in ambiguous],
                   "ambiguous_runs": [{"run": s.run, "issue": why, "study": s.study, "biosample": s.biosample, "country": s.country, "platform": s.platform} for s, why in ambiguous]}
            res = self.run(f"{len(ambiguous)} run(s) need investigation. Gather evidence and propose an outcome for each.", ctx)
            if res.get("ok"):
                proposals = {p["run"]: p for p in res["proposals"]}
        for s, why in ambiguous:
            p = proposals.get(s.run)
            if p and p["outcome"] == "Exclude" and "BioSample" in why:
                s.eligibility, s.eligibility_note = "Excluded", f"Repeated isolate: {p['rationale']}"
                self.decide(s.run, Outcome.EXCLUDE, RULES["elig"], s.eligibility_note, p.get("evidence", ""), stage=2)
                continue
            # anything else stays on Hold for a human, carrying the agent's evidence
            s.eligibility = "Hold"
            s.eligibility_note = f"{why[0].upper() + why[1:]}." + (f" Agent: {p['rationale']}" if p else " Agent could not investigate.")
            self.decide(s.run, Outcome.ESCALATE, RULES["elig"], s.eligibility_note, (p or {}).get("evidence", ""), stage=2)
        return {"verified": sum(s.eligibility == "Verified" for s in samples), "held": sum(s.eligibility == "Hold" for s in samples),
                "excluded": sum(s.eligibility == "Excluded" for s in samples)}

    # 4. cohort checks (rules) -----------------------------------------------------
    def cohort_checks(self, samples: list[Sample], asks_places: bool, total_in_ena: int) -> list[dict[str, Any]]:
        v = [s for s in samples if s.eligibility == "Verified"]
        checks: list[dict[str, Any]] = []
        locs, studies = Counter(s.location for s in v), Counter(s.study for s in v)
        if v and len(locs) == 1:
            loc = next(iter(locs))
            if asks_places:
                checks.append({"outcome": "Escalate", "kind": "single_location", "text": f"Comparison across places not supported: all {len(v)} verified runs come from one location ({loc})."})
            else:
                checks.append({"outcome": "Proceed", "kind": "single_location", "text": f"All verified runs come from one location ({loc}); results describe that site only."})
        if v and len(studies) == 1:
            checks.append({"outcome": "Proceed", "kind": "single_study", "text": f"All verified runs come from a single study ({next(iter(studies))}), so results reflect its sampling design."})
        if total_in_ena and total_in_ena > len(samples):
            checks.append({"outcome": "Proceed", "kind": "search_limit", "text": f"ENA lists {total_in_ena} matching runs; {len(samples)} were retrieved."})
        for c in checks:
            self.decide("COHORT", Outcome(c["outcome"]), RULES["cohort"], c["text"], stage=2)
        return checks
