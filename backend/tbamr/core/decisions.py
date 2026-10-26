"""Shared decision contract used by every agent.

Every agent, rule-based or Claude-powered, reports work as Decision records with one
of five outcomes. Guardrails validate each decision before it is accepted, so no agent
can bypass the playbook's safeguards.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Outcome(str, Enum):
    PROCEED = "Proceed"
    HOLD = "Hold"
    EXCLUDE = "Exclude"
    RETRY = "Retry"
    ESCALATE = "Escalate"
    # human-only outcomes
    APPROVE = "Approve"
    OVERRIDE = "Override"
    INFO = "Info"


AGENT_OUTCOMES = {Outcome.PROCEED, Outcome.HOLD, Outcome.EXCLUDE, Outcome.RETRY, Outcome.ESCALATE, Outcome.INFO}


@dataclass
class Decision:
    sample_id: str
    outcome: Outcome
    rule_version: str
    rationale: str
    actor: str  # e.g. "agent:verification" or "human:pi"
    evidence: str = ""
    stage: int = 0
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        return d


class GuardrailViolation(Exception):
    """Raised when an agent tries to make a decision it is not allowed to make."""


def check_agent_decision(d: Decision) -> Decision:
    """Validate a decision proposed by an agent.

    - Agents may only use the five shared outcomes (plus Info).
    - Every decision needs a sample id, rule version and a non-empty rationale.
    """
    if not d.actor.startswith("agent:"):
        return d
    if d.outcome not in AGENT_OUTCOMES:
        raise GuardrailViolation(f"{d.actor} may not record '{d.outcome.value}'; that outcome is reserved for humans.")
    if not d.sample_id or not d.rule_version or not d.rationale.strip():
        raise GuardrailViolation(f"{d.actor} produced an incomplete decision record.")
    return d


class DecisionLog:
    """Append-only decision log backed by SQLite. Overrides never delete history."""

    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()  # FastAPI serves requests from several threads
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, ts REAL, stage INT, sample_id TEXT, outcome TEXT,"
            " rule_version TEXT, actor TEXT, rationale TEXT, evidence TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS trace (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, agent TEXT, kind TEXT, payload TEXT)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
        self.db.commit()

    # decisions -------------------------------------------------------------
    def add(self, d: Decision) -> Decision:
        with self._lock:
            check_agent_decision(d)
            self.db.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?)",
                (d.id, d.ts, d.stage, d.sample_id, d.outcome.value, d.rule_version, d.actor, d.rationale, d.evidence),
            )
            self.db.commit()
            return d

    def all(self, limit: int = 2000) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.db.execute(
                "SELECT id, ts, stage, sample_id, outcome, rule_version, actor, rationale, evidence FROM decisions ORDER BY ts DESC, rowid DESC LIMIT ?",
                (limit,),
            )
            keys = ["id", "ts", "stage", "sample_id", "outcome", "rule_version", "actor", "rationale", "evidence"]
            return [dict(zip(keys, r)) for r in cur.fetchall()]

    def for_sample(self, sample_id: str) -> list[dict[str, Any]]:
        return [d for d in self.all() if d["sample_id"] == sample_id]

    # agent trace ------------------------------------------------------------
    def trace(self, agent: str, kind: str, payload: Any) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO trace (ts, agent, kind, payload) VALUES (?,?,?,?)",
                (time.time(), agent, kind, json.dumps(payload, default=str)[:20000]),
            )
            self.db.commit()

    def traces(self, agent: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            q = "SELECT id, ts, agent, kind, payload FROM trace"
            args: tuple = ()
            if agent:
                q += " WHERE agent = ?"
                args = (agent,)
            q += " ORDER BY id DESC LIMIT ?"
            cur = self.db.execute(q, args + (limit,))
            return [
                {"id": r[0], "ts": r[1], "agent": r[2], "kind": r[3], "payload": json.loads(r[4])} for r in cur.fetchall()
            ]

    # small key/value store for pipeline state --------------------------------
    def put(self, k: str, v: Any) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v, default=str)))
            self.db.commit()

    def get(self, k: str, default: Any = None) -> Any:
        with self._lock:
            r = self.db.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
            return json.loads(r[0]) if r else default
