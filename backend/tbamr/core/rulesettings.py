"""Editable rule thresholds, with versioning, provenance and history.

The deterministic rules read THRESHOLDS and RULES (core/models.py) when they run. This module lets the
PI change the editable thresholds from the Admin page under controls that keep results comparable:

- every change bumps the owning rule set's version (QC-v1.0 -> QC-v1.1), so each decision in the log
  names exactly which thresholds produced it;
- a written rationale is required, values are range-checked, and only the PI may save;
- each rule set records its provenance: "provisional" (not benchmarked) or "validated", with a basis;
- settings live in their own JSON file (TBAMR_RULES_FILE, default backend/tbamr-rules.json), so a
  pipeline reset can't wipe them, and every change is kept in a history.

Changes apply to stages run afterwards. Decisions already made keep the version they were made with.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from .models import RULES, THRESHOLDS

log = logging.getLogger("tbamr.rules")

# Editable thresholds: which rule set owns each one, how to validate it, and how to explain it.
EDITABLE: dict[str, dict[str, Any]] = {
    "min_cov": {"rule": "qc", "type": float, "min": 1, "max": 1000, "unit": "×",
                "label": "Minimum estimated coverage (Pass)", "help": "Runs at or above this estimated mean depth pass QC."},
    "border_cov": {"rule": "qc", "type": float, "min": 1, "max": 1000, "unit": "×",
                   "label": "Borderline coverage (Escalate below minimum, Exclude below this)", "help": "Must be lower than the minimum."},
    "min_depth": {"rule": "evid", "type": int, "min": 1, "max": 1000, "unit": "reads",
                  "label": "Minimum reads at a resistance position", "help": "Fewer reads sends the finding to review."},
    "min_freq": {"rule": "evid", "type": float, "min": 0.5, "max": 1.0, "unit": "fraction",
                 "label": "Minimum read fraction for a resistance call", "help": "Lower fractions (possible mixed infection) go to review."},
}
READ_ONLY = {"genome_bp": "Length of the M. tuberculosis H37Rv reference genome (NC_000962.3); a reference value, not a setting."}

DEFAULT_BASIS = "Initial project setting from the first draft (2026-10-26); not benchmarked against phenotypic DST."

_DEFAULT_THRESHOLDS = copy.deepcopy(THRESHOLDS)
_DEFAULT_RULES = copy.deepcopy(RULES)
_lock = threading.RLock()


def _path() -> Path:
    return Path(os.environ.get("TBAMR_RULES_FILE") or Path(__file__).resolve().parents[2] / "tbamr-rules.json")


def _default_meta() -> dict[str, dict[str, str]]:
    return {k: {"status": "provisional", "basis": DEFAULT_BASIS} for k in ("qc", "evid")}


def _read() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return {"thresholds": {}, "rules": {}, "meta": _default_meta(), "history": []}
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError) as e:  # never let a corrupt file stop the pipeline: fall back to defaults, loudly
        log.warning("could not read %s (%s); using default rule settings", p, e)
        return {"thresholds": {}, "rules": {}, "meta": _default_meta(), "history": []}
    d.setdefault("thresholds", {}); d.setdefault("rules", {}); d.setdefault("history", [])
    d["meta"] = {**_default_meta(), **(d.get("meta") or {})}
    return d


def _write(d: dict[str, Any]) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(p)  # atomic: a crash mid-write can't leave a half-written settings file


def apply() -> dict[str, Any]:
    """Load saved settings into the live THRESHOLDS / RULES (in place, so every importer sees them)."""
    with _lock:
        d = _read()
        THRESHOLDS.clear(); THRESHOLDS.update(_DEFAULT_THRESHOLDS)
        RULES.clear(); RULES.update(_DEFAULT_RULES)
        for k, v in d["thresholds"].items():
            if k in EDITABLE:
                THRESHOLDS[k] = EDITABLE[k]["type"](v)
        RULES.update({k: v for k, v in d["rules"].items() if k in RULES})
        return d


def current() -> dict[str, Any]:
    """Everything the Admin page shows."""
    with _lock:
        d = apply()
        return {"thresholds": dict(THRESHOLDS), "rules": dict(RULES), "meta": d["meta"], "history": d["history"][-50:][::-1],
                "editable": {k: {kk: (vv.__name__ if kk == "type" else vv) for kk, vv in v.items()} for k, v in EDITABLE.items()},
                "read_only": READ_ONLY, "defaults": _DEFAULT_THRESHOLDS}


def bump(version: str) -> str:
    """QC-v1.0 -> QC-v1.1; anything unexpected gets a .1 suffix."""
    m = re.match(r"^(.*-v)(\d+)\.(\d+)$", version)
    if m:
        return f"{m.group(1)}{m.group(2)}.{int(m.group(3)) + 1}"
    m = re.match(r"^(.*-v)(\d+)$", version)
    return f"{m.group(1)}{m.group(2)}.1" if m else f"{version}.1"


class RuleSettingError(ValueError):
    pass


def update(changes: dict[str, Any], rationale: str, person: str, role: str,
           status: dict[str, str] | None = None, basis: dict[str, str] | None = None) -> dict[str, Any]:
    """Validate and save threshold changes (and/or provenance), bump the affected rule versions, record history.

    Returns {"changed": {...}, "versions": {rule: (old, new)}}. Raises RuleSettingError on invalid input."""
    if role != "pi":
        raise RuleSettingError("Only the Principal Investigator can change pipeline rules.")
    if not (rationale or "").strip():
        raise RuleSettingError("Give a rationale for the change; it is recorded with the new rule version.")
    with _lock:
        d = apply()
        new = dict(THRESHOLDS)
        changed: dict[str, tuple[Any, Any]] = {}
        for k, v in (changes or {}).items():
            if k in READ_ONLY:
                raise RuleSettingError(f"{k} is a reference value and can't be changed.")
            spec = EDITABLE.get(k)
            if not spec:
                raise RuleSettingError(f"Unknown setting: {k}.")
            try:
                val = spec["type"](v)
            except (TypeError, ValueError):
                raise RuleSettingError(f"{spec['label']}: not a valid number.")
            if spec["type"] is int and float(v) != int(float(v)):
                raise RuleSettingError(f"{spec['label']}: must be a whole number.")
            if not spec["min"] <= val <= spec["max"]:
                raise RuleSettingError(f"{spec['label']}: must be between {spec['min']} and {spec['max']}.")
            if val != THRESHOLDS[k]:
                new[k] = val
                changed[k] = (THRESHOLDS[k], val)
        if new["border_cov"] >= new["min_cov"]:
            raise RuleSettingError("Borderline coverage must be lower than the minimum coverage.")
        meta_changes = {}
        for rule, st in (status or {}).items():
            if rule in d["meta"] and st in ("provisional", "validated") and st != d["meta"][rule]["status"]:
                meta_changes.setdefault(rule, {})["status"] = st
        for rule, b in (basis or {}).items():
            if rule in d["meta"] and (b or "").strip() and b.strip() != d["meta"][rule]["basis"]:
                meta_changes.setdefault(rule, {})["basis"] = b.strip()
        for rule, m in meta_changes.items():
            basis_after = m.get("basis") or d["meta"][rule]["basis"]
            if m.get("status") == "validated" and basis_after in ("", DEFAULT_BASIS):
                raise RuleSettingError("Marking a rule set validated needs a basis: the benchmark, data and date it rests on.")
        if not changed and not meta_changes:
            raise RuleSettingError("Nothing changed.")
        versions: dict[str, tuple[str, str]] = {}
        for rule in sorted({EDITABLE[k]["rule"] for k in changed} | set(meta_changes)):
            old = RULES[rule]
            versions[rule] = (old, bump(old))
        for k, (_, val) in changed.items():
            d["thresholds"][k] = val
        for rule, (_, newv) in versions.items():
            d["rules"][rule] = newv
        for rule, m in meta_changes.items():
            d["meta"][rule] = {**d["meta"][rule], **m}
        entry = {"ts": time.time(), "person": person or "unnamed", "role": role, "rationale": rationale.strip(),
                 "changes": {k: {"from": a, "to": b} for k, (a, b) in changed.items()},
                 "versions": {r: {"from": a, "to": b} for r, (a, b) in versions.items()}, "meta": meta_changes}
        d["history"].append(entry)
        _write(d)
        apply()
        log.info("pipeline rules changed by %s (%s): %s; versions %s; rationale: %s", entry["person"], role,
                 entry["changes"], entry["versions"], entry["rationale"])
        return {"changed": entry["changes"], "versions": entry["versions"], "meta": meta_changes}
