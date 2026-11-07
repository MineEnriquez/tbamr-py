"""Content-addressed cache for upstream data (ENA, Europe PMC, TB-Profiler, Claude).

Design decisions:
- One collection per namespace (`cache_ena`, `cache_pmc`, `cache_tbprofiler`, `cache_claude`).
  Separate collections make it easy to clear or disable one source without touching the others,
  and keep per-source stats cheap (`collection.estimated_document_count()`).
- Keys are SHA-256 hashes of the normalised request payload. We don't try to be clever about
  "equivalent" requests — same bytes in, same key out.
- Per-namespace enable flag lives in a `cache_settings` collection, so admin toggles survive restarts.
- Hit / miss counters live in memory for cheap reads from the admin UI and are also mirrored to
  `cache_stats` so they survive restarts (eventually consistent — not transactional).
- Graceful degradation: if `mongo()` returns None, `get()` returns None, `set()` is a no-op, and
  `is_enabled()` falls back to the in-memory default (enabled). The caller re-runs the live request.

Usage:
    from tbamr.stores.cache import cache
    hit = cache.get("ena", {"method": "search", "country": "Peru", "limit": 500})
    if hit is not None:
        return hit
    live = run_the_request()
    cache.set("ena", {"method": "search", "country": "Peru", "limit": 500}, live)
    return live

A `cache.wrap(ns, key_payload, fn)` helper collapses the three lines above into one call.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Callable

from .mongo import mongo

log = logging.getLogger("tbamr.cache")

CACHE_NAMESPACES = ("ena", "pmc", "tbprofiler", "claude")

_SETTINGS_COLL = "cache_settings"
_STATS_COLL = "cache_stats"


def _hash_key(payload: Any) -> str:
    """Stable SHA-256 of the payload. Dicts are sorted so insertion order doesn't change the key."""
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _Cache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # In-memory enable + stats so hot paths don't hit Mongo on every call.
        self._enabled: dict[str, bool] = {ns: True for ns in CACHE_NAMESPACES}
        self._hits: dict[str, int] = {ns: 0 for ns in CACHE_NAMESPACES}
        self._misses: dict[str, int] = {ns: 0 for ns in CACHE_NAMESPACES}
        self._bootstrapped = False

    def _bootstrap(self) -> None:
        """Load persisted enable/disable flags once, lazily, on first use. Safe when Mongo is down."""
        if self._bootstrapped:
            return
        self._bootstrapped = True
        db = mongo()
        if db is None:
            return
        try:
            for ns in CACHE_NAMESPACES:
                doc = db[_SETTINGS_COLL].find_one({"_id": ns})
                if doc is not None and "enabled" in doc:
                    self._enabled[ns] = bool(doc["enabled"])
                stats = db[_STATS_COLL].find_one({"_id": ns})
                if stats is not None:
                    self._hits[ns] = int(stats.get("hits", 0))
                    self._misses[ns] = int(stats.get("misses", 0))
        except Exception as e:  # Mongo blipped mid-bootstrap — fine, we keep in-memory defaults
            log.warning("cache bootstrap partial failure: %s", e)

    # -------- enable / disable ------------------------------------------------
    def is_enabled(self, ns: str) -> bool:
        with self._lock:
            self._bootstrap()
            return self._enabled.get(ns, True)

    def set_enabled(self, ns: str, enabled: bool) -> None:
        if ns not in CACHE_NAMESPACES:
            raise ValueError(f"unknown cache namespace: {ns!r}")
        with self._lock:
            self._bootstrap()
            self._enabled[ns] = bool(enabled)
            db = mongo()
            if db is not None:
                try:
                    db[_SETTINGS_COLL].update_one(
                        {"_id": ns}, {"$set": {"enabled": bool(enabled)}}, upsert=True
                    )
                except Exception as e:
                    log.warning("could not persist cache toggle for %s: %s", ns, e)

    # -------- get / set / wrap ------------------------------------------------
    def get(self, ns: str, payload: Any) -> Any | None:
        if not self.is_enabled(ns):
            return None
        db = mongo()
        if db is None:
            return None
        try:
            doc = db[f"cache_{ns}"].find_one({"_id": _hash_key(payload)})
        except Exception as e:
            log.warning("cache.get(%s) failed: %s", ns, e)
            return None
        if doc is None:
            self._bump("misses", ns)
            return None
        self._bump("hits", ns)
        return doc.get("value")

    def set(self, ns: str, payload: Any, value: Any) -> None:
        if not self.is_enabled(ns):
            return
        db = mongo()
        if db is None:
            return
        try:
            db[f"cache_{ns}"].update_one(
                {"_id": _hash_key(payload)},
                {"$set": {"value": value, "payload": payload, "stored_at": time.time()}},
                upsert=True,
            )
        except Exception as e:
            log.warning("cache.set(%s) failed: %s", ns, e)

    def wrap(self, ns: str, payload: Any, fn: Callable[[], Any]) -> Any:
        """get-or-compute idiom. If the namespace is disabled or Mongo is down, just computes fn()."""
        hit = self.get(ns, payload)
        if hit is not None:
            return hit
        value = fn()
        if value is not None:
            self.set(ns, payload, value)
        return value

    # -------- admin: stats / clear --------------------------------------------
    def stats(self) -> list[dict[str, Any]]:
        """One row per namespace for the admin page. `entries` is None if Mongo is down."""
        with self._lock:
            self._bootstrap()
            db = mongo()
            rows = []
            for ns in CACHE_NAMESPACES:
                entries: int | None
                if db is None:
                    entries = None
                else:
                    try:
                        entries = db[f"cache_{ns}"].estimated_document_count()
                    except Exception:
                        entries = None
                rows.append({
                    "namespace": ns, "enabled": self._enabled.get(ns, True),
                    "hits": self._hits.get(ns, 0), "misses": self._misses.get(ns, 0), "entries": entries,
                })
            return rows

    def clear(self, ns: str) -> int:
        """Drop every cached entry for one namespace. Resets hit/miss counters too."""
        if ns not in CACHE_NAMESPACES:
            raise ValueError(f"unknown cache namespace: {ns!r}")
        db = mongo()
        n = 0
        if db is not None:
            try:
                r = db[f"cache_{ns}"].delete_many({})
                n = int(r.deleted_count)
            except Exception as e:
                log.warning("cache.clear(%s) failed: %s", ns, e)
        with self._lock:
            self._hits[ns] = 0
            self._misses[ns] = 0
            if db is not None:
                try:
                    db[_STATS_COLL].update_one({"_id": ns}, {"$set": {"hits": 0, "misses": 0}}, upsert=True)
                except Exception:
                    pass
        return n

    def clear_all(self) -> dict[str, int]:
        return {ns: self.clear(ns) for ns in CACHE_NAMESPACES}

    # -------- internal --------------------------------------------------------
    def _bump(self, which: str, ns: str) -> None:
        target = self._hits if which == "hits" else self._misses
        with self._lock:
            target[ns] = target.get(ns, 0) + 1
            db = mongo()
            if db is not None:
                try:
                    db[_STATS_COLL].update_one({"_id": ns}, {"$inc": {which: 1}}, upsert=True)
                except Exception:
                    pass  # stat bump is best-effort; cache correctness doesn't depend on it


cache = _Cache()
