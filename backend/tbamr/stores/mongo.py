"""Thin Mongo accessor. Lazy connection, graceful degradation.

If pymongo is not installed, or MONGO_URL points at a server that's down, every public call here
returns None and sets `last_error`. Callers (cache + results) treat None as "store unavailable" and
fall back cleanly — the app still works, caching is just a no-op and the result archive is skipped.

Env:
  MONGO_URL    e.g. mongodb://localhost:27017/tbamr (default: mongodb://localhost:27017)
  MONGO_DB     database name (default: tbamr)
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

log = logging.getLogger("tbamr.mongo")

_DEFAULT_URL = "mongodb://localhost:27017"
_DEFAULT_DB = "tbamr"
_CONNECT_TIMEOUT_MS = 1500  # keep startup fast even when Mongo is down

_lock = threading.Lock()
_state: dict[str, Any] = {
    "client": None,
    "db": None,
    "url": None,
    "last_error": None,
    "available": None,  # tri-state: None=untried, True=ok, False=down
}


def _try_connect() -> None:
    """Attempt to open a connection and ping. Sets _state in place. Idempotent-safe under _lock."""
    try:
        from pymongo import MongoClient  # type: ignore
        from pymongo.errors import PyMongoError  # type: ignore
    except ImportError as e:
        _state["available"] = False
        _state["last_error"] = f"pymongo not installed: {e}"
        return

    url = os.environ.get("MONGO_URL", _DEFAULT_URL)
    dbname = os.environ.get("MONGO_DB", _DEFAULT_DB)
    try:
        client = MongoClient(url, serverSelectionTimeoutMS=_CONNECT_TIMEOUT_MS, connectTimeoutMS=_CONNECT_TIMEOUT_MS)
        client.admin.command("ping")  # forces an actual round-trip, not just a lazy handle
        _state["client"] = client
        _state["db"] = client[dbname]
        _state["url"] = url
        _state["available"] = True
        _state["last_error"] = None
        log.info("Mongo connected: %s/%s", url, dbname)
    except PyMongoError as e:
        _state["available"] = False
        _state["last_error"] = str(e)
        log.warning("Mongo unavailable (%s); caching and result archive disabled", e)


def mongo():
    """Return the live database handle, or None if Mongo isn't reachable. Never raises."""
    with _lock:
        if _state["available"] is None:
            _try_connect()
        return _state["db"] if _state["available"] else None


def is_connected() -> bool:
    """True if the last connection attempt succeeded. Does not re-probe."""
    with _lock:
        if _state["available"] is None:
            _try_connect()
        return bool(_state["available"])


def reconnect() -> dict[str, Any]:
    """Force a fresh connection attempt. Called by the admin page when the user restarts Mongo."""
    with _lock:
        _state["available"] = None
        _state["client"] = None
        _state["db"] = None
        _try_connect()
        return status()


def status() -> dict[str, Any]:
    """Snapshot for the admin UI: connected?, url, db name, last error."""
    with _lock:
        if _state["available"] is None:
            _try_connect()
        return {
            "connected": bool(_state["available"]),
            "url": _state["url"] or os.environ.get("MONGO_URL", _DEFAULT_URL),
            "db": os.environ.get("MONGO_DB", _DEFAULT_DB),
            "last_error": _state["last_error"],
        }
