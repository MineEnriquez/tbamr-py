"""Genomic Profiling & Execution Tasker (tool runner) — Stage 4.

Runs TB-Profiler when it is installed, or accepts imported TB-Profiler JSON results.
It records versions and provenance but never interprets results (that is Stage 5).
"""
from __future__ import annotations

from typing import Any

from ..core.decisions import Outcome
from ..core.models import RULES, Sample
from ..tools.tbprofiler import TBProfilerRunner
from .base import RuleAgent


class ProfilingTasker(RuleAgent):
    name = "profiling"
    title = "Genomic Profiling & Execution Tasker"
    description = "Queues QC-passed runs, runs TB-Profiler when installed or imports its result files, and records tool and database versions."

    def __init__(self, log, runner: TBProfilerRunner | None = None):
        super().__init__(log)
        self.runner = runner or TBProfilerRunner()

    def queue(self, samples: list[Sample]) -> int:
        n = 0
        for s in samples:
            if s.qc == "Pass" and not s.profiling:
                s.profiling, s.profiling_note = "Awaiting results", "Queued for TB-Profiler with config " + RULES["prof"] + "."
                n += 1
        self.decide("—", Outcome.INFO, RULES["prof"], f"{n} QC-passed run(s) queued for TB-Profiler. Tools on this machine: {self.runner.available()}.", stage=4)
        return n

    def apply_result(self, s: Sample, parsed: dict[str, Any], source: str) -> None:
        s.profiling = "Done"
        s.lineage, s.drtype, s.profile_meta = parsed.get("lineage"), parsed.get("drtype"), parsed.get("meta", {})
        s.profile_meta["mutations"] = parsed.get("mutations", [])
        s.findings = []
        other = parsed.get("other_variants") or 0
        s.profiling_note = (f"{s.profile_meta.get('tool')} · db {s.profile_meta.get('db')} · {len(s.profile_meta['mutations'])} resistance annotation(s)"
                            + (f" · {other} other variant(s) not counted" if other else "") + f" · {source}")
        self.decide(s.run, Outcome.PROCEED, RULES["prof"], "TB-Profiler result recorded: " + s.profiling_note,
                    f"file {s.profile_meta.get('file', '')}; median depth {s.profile_meta.get('median_depth')}", stage=4)

    def run_one(self, s: Sample) -> dict[str, Any]:
        res = self.runner.run(s.run)
        if res.get("ok"):
            self.apply_result(s, res["result"], "run locally")
        else:
            s.profiling, s.profiling_note = "Failed", res.get("error", "")
            self.decide(s.run, Outcome.ESCALATE, RULES["prof"], "TB-Profiler did not complete: " + s.profiling_note, stage=4)
        return res
