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
        # raw source data (ENA records, TB-Profiler JSON, agent tool outputs) kept verbatim for human inspection
        self.db.execute("CREATE TABLE IF NOT EXISTS raw (kind TEXT, key TEXT, ts REAL, data TEXT, PRIMARY KEY (kind, key))")
        # receipts: who opened which raw data, and when (gates require them)
        self.db.execute("CREATE TABLE IF NOT EXISTS views (person TEXT, role TEXT, kind TEXT, key TEXT, ts REAL)")
        # pipeline runs: one row per cycle of work on the pipeline. A run is "active" while ended_at IS NULL;
        # /api/reset closes the active run (sets ended_at + label from the current scope) and opens a new one.
        # Executions keep their run_id across resets, so the Logs tab can look back at previous runs' logs.
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at REAL, ended_at REAL, label TEXT)"
        )
        # executions: one row per discrete user-triggered unit of work (stage run, gate, profiling batch, etc).
        # log_text holds the captured stdout/stderr/logging output for that unit — scoped, not continuous.
        # result_json holds the structured return value of the wrapped action (what Stage 2 found, the
        # outcome of a TB-Profiler batch, …) so the Logs tab can show what happened, not just what was said.
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS executions (id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT, start_ts REAL,"
            " end_ts REAL, status TEXT, log_text TEXT, error TEXT)"
        )
        # Migrate older DBs that pre-date later columns: add anything missing. SQLite ALTER TABLE ADD COLUMN
        # is safe on existing rows (they get NULL). Order matters only if we read these columns elsewhere.
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(executions)").fetchall()}
        if "run_id" not in cols:
            self.db.execute("ALTER TABLE executions ADD COLUMN run_id INTEGER")
        if "result_json" not in cols:
            self.db.execute("ALTER TABLE executions ADD COLUMN result_json TEXT")
        self.db.commit()
        self._adopt_orphan_executions()
        self._ensure_active_run()

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
    def trace(self, agent: str, kind: str, payload: Any) -> int:
        text = json.dumps(payload, default=str)
        if len(text) > 20000:  # never store invalid (cut) JSON; the full value lives in the raw table
            text = json.dumps({"truncated": True, "preview": text[:4000]})
        with self._lock:
            cur = self.db.execute("INSERT INTO trace (ts, agent, kind, payload) VALUES (?,?,?,?)", (time.time(), agent, kind, text))
            self.db.commit()
            return int(cur.lastrowid)

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

    # raw data + view receipts ---------------------------------------------------
    def put_raw(self, kind: str, key: str, data: Any) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO raw VALUES (?,?,?,?)", (kind, key, time.time(), json.dumps(data, default=str)))
            self.db.commit()

    def get_raw(self, kind: str, key: str) -> Any:
        with self._lock:
            r = self.db.execute("SELECT data FROM raw WHERE kind = ? AND key = ?", (kind, key)).fetchone()
            return json.loads(r[0]) if r else None

    def record_view(self, person: str, role: str, kind: str, key: str) -> float:
        ts = time.time()
        with self._lock:
            self.db.execute("INSERT INTO views VALUES (?,?,?,?,?)", (person, role, kind, key, ts))
            self.db.commit()
        return ts

    def viewed_at(self, person: str, kind: str, key: str) -> float | None:
        with self._lock:
            r = self.db.execute("SELECT MAX(ts) FROM views WHERE person = ? AND kind = ? AND key = ?", (person, kind, key)).fetchone()
            return r[0] if r and r[0] else None

    def receipts(self, person: str) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.db.execute("SELECT kind, key, MAX(ts) FROM views WHERE person = ? GROUP BY kind, key", (person,))
            return [{"kind": k, "key": key, "ts": ts} for k, key, ts in cur.fetchall()]

    # pipeline runs -------------------------------------------------------
    def _ensure_active_run(self) -> int:
        """Return the id of the open run; create one if none is open."""
        with self._lock:
            r = self.db.execute("SELECT id FROM runs WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
            if r:
                return int(r[0])
            cur = self.db.execute("INSERT INTO runs (started_at, ended_at, label) VALUES (?, NULL, NULL)", (time.time(),))
            self.db.commit()
            return int(cur.lastrowid)

    def _adopt_orphan_executions(self) -> None:
        """Older DBs have executions with run_id=NULL. Fold them into one 'Legacy executions' run so they
        remain visible after the runs feature ships."""
        with self._lock:
            orphans = self.db.execute("SELECT MIN(start_ts), MAX(end_ts) FROM executions WHERE run_id IS NULL").fetchone()
            if not orphans or orphans[0] is None:
                return
            start_ts, end_ts = orphans
            cur = self.db.execute(
                "INSERT INTO runs (started_at, ended_at, label) VALUES (?, ?, ?)",
                (start_ts, end_ts or start_ts, "Legacy executions"),
            )
            self.db.execute("UPDATE executions SET run_id = ? WHERE run_id IS NULL", (int(cur.lastrowid),))
            self.db.commit()

    def active_run_id(self) -> int:
        return self._ensure_active_run()

    def close_active_run(self, label: str = "") -> int | None:
        """Close the open run with an ended_at timestamp (and optional label). Returns the closed run id."""
        with self._lock:
            r = self.db.execute("SELECT id FROM runs WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
            if not r:
                return None
            rid = int(r[0])
            self.db.execute("UPDATE runs SET ended_at = ?, label = COALESCE(NULLIF(?, ''), label) WHERE id = ?",
                            (time.time(), label.strip(), rid))
            self.db.commit()
            return rid

    def start_run(self) -> int:
        """Open a new run. Used by /api/reset after closing the previous one."""
        with self._lock:
            cur = self.db.execute("INSERT INTO runs (started_at, ended_at, label) VALUES (?, NULL, NULL)", (time.time(),))
            self.db.commit()
            return int(cur.lastrowid)

    def list_runs(self) -> list[dict[str, Any]]:
        """Runs newest-first, each with its execution count. The active run is the one with ended_at = None."""
        with self._lock:
            cur = self.db.execute(
                "SELECT r.id, r.started_at, r.ended_at, r.label, "
                " (SELECT COUNT(*) FROM executions e WHERE e.run_id = r.id) AS n_executions "
                " FROM runs r ORDER BY r.id DESC"
            )
            return [{"id": r[0], "started_at": r[1], "ended_at": r[2], "label": r[3], "active": r[2] is None,
                     "n_executions": r[4]} for r in cur.fetchall()]

    # execution log --------------------------------------------------------
    def add_execution(self, trigger: str, start_ts: float, end_ts: float, status: str, log_text: str,
                      error: str = "", result: Any = None) -> int:
        with self._lock:
            run_id = self._ensure_active_run()
            result_json = _serialize_result(result)
            cur = self.db.execute(
                "INSERT INTO executions (trigger, start_ts, end_ts, status, log_text, error, run_id, result_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (trigger, start_ts, end_ts, status, log_text, error, run_id, result_json),
            )
            self.db.commit()
            return int(cur.lastrowid)

    def list_executions(self, limit: int = 100, run_id: int | None = None) -> list[dict[str, Any]]:
        """List executions newest-first. If run_id is None, defaults to the active run.
        has_result is a boolean the UI uses to badge rows that carry structured output."""
        with self._lock:
            if run_id is None:
                run_id = self._ensure_active_run()
            cur = self.db.execute(
                "SELECT id, trigger, start_ts, end_ts, status, length(log_text), error, run_id,"
                " CASE WHEN result_json IS NULL THEN 0 ELSE 1 END FROM executions"
                " WHERE run_id = ? ORDER BY id DESC LIMIT ?",
                (run_id, limit),
            )
            return [{"id": r[0], "trigger": r[1], "start_ts": r[2], "end_ts": r[3], "status": r[4],
                     "log_bytes": r[5], "error": r[6], "run_id": r[7], "has_result": bool(r[8])}
                    for r in cur.fetchall()]

    def get_execution(self, execution_id: int) -> dict[str, Any] | None:
        with self._lock:
            r = self.db.execute(
                "SELECT id, trigger, start_ts, end_ts, status, log_text, error, run_id, result_json"
                " FROM executions WHERE id = ?",
                (execution_id,),
            ).fetchone()
            if not r:
                return None
            try:
                result = json.loads(r[8]) if r[8] else None
            except (ValueError, TypeError):
                result = {"_parse_error": "result_json was not valid JSON", "_raw": r[8]}
            return {"id": r[0], "trigger": r[1], "start_ts": r[2], "end_ts": r[3], "status": r[4],
                    "log_text": r[5], "error": r[6], "run_id": r[7], "result": result}


def _serialize_result(result: Any) -> str | None:
    """Serialize a Python value to JSON for storage. Returns None if the value is None, or a safe
    error-marker JSON if serialization fails — never raises, so a bad return value can't lose the log."""
    if result is None:
        return None
    try:
        text = json.dumps(result, default=str)
    except (TypeError, ValueError) as e:
        return json.dumps({"_serialize_error": f"{type(e).__name__}: {e}"})
    # Keep executions reasonably small: a 200 KB JSON blob dropped into the Logs tab is already more
    # than anyone will read. Preserve the shape (first element preview) so the UI still shows something.
    if len(text) > 200_000:
        return json.dumps({"_truncated": True, "_original_bytes": len(text), "_preview": text[:4000]})
    return text
