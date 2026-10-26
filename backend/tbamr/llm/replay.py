"""Scripted agent policies for replay mode (no API key needed).

Each policy imitates what a careful agent would do with the same tools, step by step, so the
pipeline, guardrails, trace and UI can be exercised offline. Every thought is prefixed
"[replay]" so the trace never passes for live reasoning.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any


def _ctx(messages: list[dict[str, Any]]) -> dict[str, Any]:
    first = messages[0]["content"]
    if isinstance(first, str) and "Context (JSON):" in first:
        return json.loads(first.split("Context (JSON):", 1)[1])
    return {}


def _step(messages) -> int:
    return sum(1 for m in messages if m["role"] == "assistant")


def _results(messages) -> list[Any]:
    last = messages[-1]
    if last["role"] != "user" or not isinstance(last["content"], list):
        return []
    out = []
    for r in last["content"]:
        try:
            out.append(json.loads(r["content"]))
        except (TypeError, ValueError, KeyError):
            out.append(None)
    return out


def _all_results(messages) -> list[Any]:
    out = []
    for m in messages[1:]:
        if m["role"] == "user" and isinstance(m["content"], list):
            for r in m["content"]:
                try:
                    out.append(json.loads(r["content"]))
                except (TypeError, ValueError, KeyError):
                    pass
    return out


def think(text: str) -> dict[str, Any]:
    return {"type": "text", "text": "[replay] " + text}


def use(name: str, **inp) -> dict[str, Any]:
    return {"type": "tool_use", "name": name, "input": inp}


PLACES = re.compile(r"region|province|geograph|differences across|urban|cities|settings|across|compare", re.I)


def scope_guardian(messages):
    c = _ctx(messages)
    q = c.get("question", "")
    warnings = []
    if re.search(r"prevalence|national rate|how common", q, re.I):
        warnings.append("The question mentions prevalence. Public genomes are a convenience sample and cannot estimate national prevalence.")
    if re.search(r"treat|therapy|regimen|patient", q, re.I):
        warnings.append("The question mentions treatment or patients; clinical decisions are outside this workflow.")
    places = bool(PLACES.search(q))
    if places:
        warnings.append("The question compares places; that needs verified isolates from several locations, which will be checked after discovery.")
    gaps = [{"key": g["key"], "gap": g["gap"], "proposal": p} for g, p in zip(c.get("required_policy_gaps", []), [
        "Verified only if the ENA/BioSample country field names the study country; publication-only origin → Hold for human confirmation.",
        'Keep samples without DST; record DST as "unavailable", never as agreement.',
        "Runs sharing a BioSample → Hold + Escalate as possible duplicates; one run per isolate.",
        "No prevalence estimates, clinical advice or new-mutation claims; reports exploratory until reviewed.",
    ])]
    return [think(f"Read the question ({len(q)} characters) and {len(c.get('target_drugs', []))} target drug(s). Proposing the four playbook definitions; {len(warnings)} warning(s)."),
            use("submit", blocking=[], gaps=gaps, warnings=warnings, asks_comparison_across_places=places)]


def discovery(messages):
    c, step = _ctx(messages), _step(messages)
    exclude = [s for s in c.get("exclude_studies", [])]
    if step == 0:
        extra = " AND ".join(f'study_accession!="{s}"' for s in exclude)
        return [think(f"Searching ENA for M. tuberculosis runs from {c.get('country')}" + (f", excluding {', '.join(exclude)}." if exclude else ".")),
                use("ena_search_runs", country=c.get("country", "Indonesia"), extra_query=extra, limit=500)]
    res = next((r for r in _all_results(messages) if isinstance(r, dict) and "runs" in r), {"runs": []})
    runs = res.get("runs", [])
    known = set(c.get("already_known", []))
    new = [r for r in runs if r["run_accession"] not in known]
    studies = Counter(r["study_accession"] for r in new)
    if step == 1 and studies:
        top, n = studies.most_common(1)[0]
        msg = f"{len(new)} new run(s) across {len(studies)} study(ies); {top} holds {n}."
        return [think(msg + " Looking up the largest study and searching the literature for it."),
                use("ena_study", study_accession=top), use("find_publications", query=top, limit=3)]
    titles = {r.get("study_accession"): r.get("study_title") for r in _all_results(messages) if isinstance(r, dict) and "study_title" in r}
    pubs = [r for r in _all_results(messages) if isinstance(r, list)]
    concerns = []
    if studies and studies.most_common(1)[0][1] / max(1, len(new)) > 0.8:
        concerns.append(f"Most candidates come from one study ({studies.most_common(1)[0][0]}).")
    if res.get("total_in_ena") and res["total_in_ena"] > len(runs):
        concerns.append(f"ENA lists {res['total_in_ena']} runs; {len(runs)} retrieved.")
    if not new:
        concerns.append("No additional runs found with this search.")
    return [think("Submitting the candidates I actually retrieved."),
            use("submit", candidate_runs=[r["run_accession"] for r in new],
                studies=[{"accession": s, "title": titles.get(s), "runs": n, "publications": (pubs[0] if pubs and s == studies.most_common(1)[0][0] else [])} for s, n in studies.items()],
                search_notes=f"Searched {res.get('query', '')}.", concerns=concerns)]


def verification(messages):
    c, step = _ctx(messages), _step(messages)
    amb = c.get("ambiguous_runs", [])
    if step == 0:
        studies = sorted({a["study"] for a in amb if "country" in a["issue"]})
        calls = [use("find_publications", query=s, limit=3) for s in studies] + [use("ena_study", study_accession=s) for s in studies]
        return [think(f"{len(amb)} ambiguous run(s). Checking studies and publications for those missing a country." if calls else f"{len(amb)} ambiguous run(s); the records themselves hold the evidence.")] + (calls or [use("submit", proposals=_proposals(amb, []))])
    return [think("Proposing outcomes with the evidence found."), use("submit", proposals=_proposals(amb, _all_results(messages)))]


def _proposals(amb, results):
    pubs = [p for r in results if isinstance(r, list) for p in r]
    out = []
    for a in amb:
        if "BioSample" in a["issue"]:
            out.append({"run": a["run"], "outcome": "Exclude", "rationale": "Same isolate as an earlier run; keep the earlier run as the isolate's representative.", "evidence": f"BioSample {a['biosample']}"})
        elif "country" in a["issue"]:
            pub = next((p for p in pubs if p and "Indonesia" in (p.get("title") or "")), None)
            if pub:
                out.append({"run": a["run"], "outcome": "Escalate", "rationale": "ENA country is missing, but a publication linked to the study describes Indonesian isolates. A human must confirm origin.", "evidence": pub.get("title", "")})
            else:
                out.append({"run": a["run"], "outcome": "Hold", "rationale": "ENA country is missing and no publication evidence was found.", "evidence": ""})
        else:
            out.append({"run": a["run"], "outcome": "Escalate", "rationale": "The approved configuration assumes Illumina reads; a human decides whether to accept this platform.", "evidence": f"platform {a.get('platform')}"})
    return out


def evidence(messages):
    c = _ctx(messages)
    notes = []
    for f in c.get("findings", []):
        depth = "n/a" if f["depth"] is None else f"{f['depth']:g}"
        txt = f"{f['variant']} is reported for {f['drug']} ({f['grading']}), seen at depth {depth} in {round((f['read_fraction'] or 1) * 100)}% of reads. "
        if f["rule_classification"] == "other":
            txt += "Catalogued as not associated with resistance; treat as a lineage marker."
        elif f["rule_review"] == "Pending":
            txt += f"Needs review: {f['rule_reason']}"
        else:
            txt += "Well-established grading with adequate depth; technically assessed, not yet scientifically reviewed."
        req = "interim" in str(f["grading"]).lower() and f["rule_review"] != "Pending"
        notes.append({"fid": f["fid"], "interpretation": txt, "request_review": req, "why": "interim (Group 2) grading; borderline mutations can be missed by phenotypic DST." if req else ""})
    return [think(f"Writing interpretation notes for {len(notes)} finding(s)."), use("submit", notes=notes)]


POLICIES = {"scope_guardian": scope_guardian, "discovery": discovery, "verification": verification, "evidence": evidence}
