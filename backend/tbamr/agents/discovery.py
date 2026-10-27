"""Public TB Dataset Discovery Assistant (Claude agent) — Stage 2.

Goal: find public M. tuberculosis WGS runs relevant to the approved scope. It chooses its own
searches (ENA run search with paging, study lookups, Europe PMC), notices concentration in a
single study, and can be re-tasked by the Orchestrator to look for additional studies.
Guardrail: it may only return accessions that its tools actually returned.
"""
from __future__ import annotations

from typing import Any

from ..core.decisions import Outcome
from ..core.models import RULES
from .base import LLMAgent, Tool


class DiscoveryAssistant(LLMAgent):
    name = "discovery"
    title = "Public TB Dataset Discovery Assistant"
    description = "Searches ENA and the literature for candidate genomes, pages through results and looks for additional studies when the cohort is too narrow."
    system_prompt = (
        "Find candidate runs for the approved scope. Search ENA first; if most runs come from one study, look up that study and "
        "search the literature for related or additional datasets. Report every study you found and any concerns about how narrow "
        "or broad the candidate set is. You never decide eligibility — the Verification Tasker does."
    )
    max_steps = 8
    submit_schema = {
        "type": "object",
        "properties": {
            "candidate_runs": {"type": "array", "items": {"type": "string"}},
            "studies": {"type": "array", "items": {"type": "object", "properties": {"accession": {"type": "string"}, "title": {"type": ["string", "null"]}, "runs": {"type": "integer"}, "publications": {"type": "array", "items": {"type": "object"}}}}},
            "search_notes": {"type": "string"},
            "concerns": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["candidate_runs", "studies", "search_notes", "concerns"],
    }

    def __init__(self, log, client, data):
        self.data = data
        super().__init__(log, client)

    def build_tools(self):
        d = self.data
        return [
            Tool("ena_search_runs", "Search ENA read runs for M. tuberculosis, paging through results. Set country to a country name (prefix match) to scope the search; leave it empty to search worldwide. Optional extra_query adds ENA query terms, e.g. study_accession!=\"PRJNA1\".",
                 {"type": "object", "properties": {"country": {"type": "string", "description": "Country name prefix; empty string for worldwide."}, "extra_query": {"type": "string"}, "limit": {"type": "integer"}}, "required": []},
                 lambda country="", extra_query="", limit=500: d.ena_search_runs(country=country, extra_query=extra_query, limit=limit)),
            Tool("ena_study", "Look up an ENA/INSDC study (BioProject) by accession.",
                 {"type": "object", "properties": {"study_accession": {"type": "string"}}, "required": ["study_accession"]},
                 lambda study_accession: d.ena_study(study_accession)),
            Tool("find_publications", "Search Europe PMC (titles, abstracts, accession mentions).",
                 {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]},
                 lambda query, limit=5: d.find_publications(query, limit)),
        ]

    def validate(self, sub: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        seen = {r["run_accession"]: r for out in self.called.get("ena_search_runs", []) if isinstance(out, dict) for r in out.get("runs", [])}
        exclude = set(ctx.get("already_known", []))
        cands = [a for a in sub.get("candidate_runs", []) if a in seen and a not in exclude]
        invented = [a for a in sub.get("candidate_runs", []) if a not in seen]
        if not sub.get("candidate_runs"):  # agent may summarise instead of listing; fall back to everything it actually saw
            cands = [a for a in seen if a not in exclude]
        concerns = list(sub.get("concerns") or [])
        if invented:
            concerns.append(f"Guardrail removed {len(invented)} accession(s) that no tool returned.")
        totals = [o.get("total_in_ena") for o in self.called.get("ena_search_runs", []) if isinstance(o, dict)]
        return {"candidate_runs": cands, "rows": [seen[a] for a in cands], "studies": sub.get("studies") or [],
                "search_notes": sub.get("search_notes", ""), "concerns": concerns, "total_in_ena": max([t for t in totals if t] or [0])}

    def discover(self, country: str, question: str, already_known: list[str] | None = None, focus: str = "",
                 exclude_studies: list[str] | None = None) -> dict[str, Any]:
        scope = f"from {country}" if country else "worldwide"
        task = (f"Find candidate M. tuberculosis WGS runs ({scope}) for this question: {question}"
                + (f"\nFollow-up from the Orchestrator: {focus}" if focus else ""))
        res = self.run(task, {"country": country, "already_known": already_known or [], "focus": focus,
                             "exclude_studies": exclude_studies or []})
        if not res.get("ok"):
            self.decide("—", Outcome.ESCALATE, RULES["elig"], f"Discovery did not complete: {res.get('error')}", stage=2)
            return {"candidate_runs": [], "rows": [], "studies": [], "search_notes": "", "concerns": [res.get("error", "")], "total_in_ena": 0}
        self.decide("—", Outcome.INFO, RULES["elig"],
                    f"Found {len(res['candidate_runs'])} candidate run(s) in {len(res['studies'])} study(ies). {res['search_notes']}".strip(),
                    evidence="; ".join(res["concerns"]), stage=2)
        return res
