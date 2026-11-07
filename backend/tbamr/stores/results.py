"""Pipeline-result archive in Mongo. One document per released (or draft) report.

Why: the SQLite DecisionLog retains every decision but is scoped to the current pipeline DB file.
A persistent archive across runs — queryable by country, drug, release date, etc. — fits a document
store well. Mongo being down must never block a release; the decision log in SQLite is still the
authoritative record. Writes here are best-effort.

Document shape:
  _id              generated ObjectId
  version          int (report version)
  released_at      unix time
  released_by      {role, person}
  kind             "final" | "draft"
  country          scope.country
  question         scope.question
  target_drugs     [str]
  report           full report dict as the UI sees it
  state_snapshot   trimmed PipelineState dict for context (samples list is sampled, not full)
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .mongo import mongo

log = logging.getLogger("tbamr.results")

_COLL = "pipeline_results"
_MAX_SAMPLES_SNAPSHOT = 200  # cap the embedded sample list so each doc stays well under 16 MB


def save_release(state: Any, report: dict[str, Any], release_gate: dict[str, Any]) -> str | None:
    """Insert a document for this release. Returns the inserted _id as a string, or None on failure."""
    db = mongo()
    if db is None:
        return None
    try:
        samples = getattr(state, "samples", []) or []
        snap_samples = [_sample_to_doc(s) for s in samples[:_MAX_SAMPLES_SNAPSHOT]]
        doc: dict[str, Any] = {
            "version": int(report.get("version") or 0),
            "released_at": time.time(),
            "released_by": {"role": release_gate.get("role"), "person": release_gate.get("person") or release_gate.get("by")},
            "kind": release_gate.get("kind") or "draft",
            "country": getattr(state, "country", "") or "",
            "question": getattr(state, "question", "") or "",
            "target_drugs": list(getattr(state, "target_drugs", []) or []),
            "report": report,
            "state_snapshot": {
                "n_samples_total": len(samples),
                "samples_sampled": snap_samples,
                "gates": dict(getattr(state, "gates", {}) or {}),
                "stage_status": dict(getattr(state, "stage_status", {}) or {}),
            },
        }
        res = db[_COLL].insert_one(doc)
        return str(res.inserted_id)
    except Exception as e:
        log.warning("could not archive release to Mongo: %s", e)
        return None


def _sample_to_doc(s: Any) -> dict[str, Any]:
    """Reduce a Sample dataclass to the fields the archive needs (keeps docs small)."""
    get = lambda k: getattr(s, k, None)  # noqa: E731
    return {
        "run": get("run"), "country": get("country"), "lineage": get("lineage"),
        "eligibility": get("eligibility"), "qc": get("qc"), "profiling": get("profiling"),
        "in_cohort": bool(get("in_cohort")),
    }


def list_releases(limit: int = 50) -> list[dict[str, Any]]:
    """Most recent releases first. Used by the admin page history view."""
    db = mongo()
    if db is None:
        return []
    try:
        cur = db[_COLL].find({}, {"state_snapshot": 0}).sort("released_at", -1).limit(limit)
        return [_jsonable(d) for d in cur]
    except Exception as e:
        log.warning("list_releases failed: %s", e)
        return []


def load_release(release_id: str) -> dict[str, Any] | None:
    db = mongo()
    if db is None:
        return None
    try:
        from bson.objectid import ObjectId  # type: ignore
        doc = db[_COLL].find_one({"_id": ObjectId(release_id)})
        return _jsonable(doc) if doc else None
    except Exception as e:
        log.warning("load_release(%s) failed: %s", release_id, e)
        return None


def _jsonable(doc: dict[str, Any]) -> dict[str, Any]:
    """Turn Mongo's ObjectId into a plain string so FastAPI can serialise the response."""
    if not doc:
        return doc
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out
