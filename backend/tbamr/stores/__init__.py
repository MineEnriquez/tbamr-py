"""NoSQL (MongoDB) stores: pipeline-result archive + request/response cache for upstream data.

Why Mongo lives next to SQLite: the SQLite DecisionLog is the authoritative *audit* trail (every
decision + who-saw-what receipt), it must stay durable and local. Mongo is a *performance* and
*archive* layer — if it is down, the app still runs and still logs every decision; only cache lookups
miss and nothing is persisted to the result archive.

Submodules (prefer qualified imports so submodule names aren't shadowed by their contents):
  from tbamr.stores import mongo, cache, results
  mongo.status()                 # Mongo health
  cache.cache.get(...)           # the singleton cache
  results.save_release(...)
"""
from . import cache, mongo, results  # noqa: F401 (register submodules on the package)
