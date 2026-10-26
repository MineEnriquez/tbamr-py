"""Sequencing Quality Assessment Analyst (rule agent) — Stage 3.

Deterministic coverage gate (QC-v1.0): estimated coverage = base_count / genome length.
Proceed ≥ minimum; Escalate in the borderline zone; Exclude below it. Records checksum availability.
"""
from __future__ import annotations

from ..core.decisions import Outcome
from ..core.models import RULES, THRESHOLDS, Sample
from .base import RuleAgent


class QCAnalyst(RuleAgent):
    name = "qc"
    title = "Sequencing Quality Assessment Analyst"
    description = "Applies the approved coverage gate to every verified run and records checksum availability. It never changes thresholds."

    def assess(self, samples: list[Sample], min_cov: float | None = None) -> dict[str, int]:
        min_cov = min_cov or THRESHOLDS["min_cov"]
        border = THRESHOLDS["border_cov"]
        counts = {"pass": 0, "escalated": 0, "excluded": 0}
        for s in samples:
            if not s.in_cohort or s.qc:
                continue
            if not s.base_count:
                s.qc, s.qc_note = "Escalated", "No base count in ENA; coverage cannot be estimated."
                self.decide(s.run, Outcome.ESCALATE, RULES["qc"], s.qc_note, stage=3)
                counts["escalated"] += 1
                continue
            s.coverage = round(s.base_count / THRESHOLDS["genome_bp"], 1)
            md5 = "MD5 listed in ENA" if s.md5 else "no archive checksum (integrity not verifiable)"
            if s.coverage < border:
                s.qc, s.qc_note = "Excluded", f"Estimated coverage {s.coverage}× is below {border:g}×; {md5}."
                outcome = Outcome.EXCLUDE
                counts["excluded"] += 1
            elif s.coverage < min_cov:
                s.qc, s.qc_note = "Escalated", f"Estimated coverage {s.coverage}× is in the borderline zone ({border:g}–{min_cov:g}×); {md5}."
                outcome = Outcome.ESCALATE
                counts["escalated"] += 1
            else:
                s.qc, s.qc_note = "Pass", f"Estimated coverage {s.coverage}× (≥{min_cov:g}×); {md5}."
                outcome = Outcome.PROCEED
                counts["pass"] += 1
            self.decide(s.run, outcome, RULES["qc"], s.qc_note, f"base_count {s.base_count}", stage=3)
        return counts
