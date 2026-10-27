"""Pipeline state: samples, findings, stages and human gates."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

ROLES = {
    "pi": "Principal Investigator",
    "deputy": "Deputy PI",
    "analyst": "Bioinformatics Analyst",
    "tbexpert": "TB Microbiologist",
}

STAGES = [
    {"n": 1, "key": "scope", "name": "Define & approve scope", "owner": "pi", "agents": ["scope_guardian"]},
    {"n": 2, "key": "discover", "name": "Discover & verify eligibility", "owner": "pi", "agents": ["discovery", "verification"]},
    {"n": 3, "key": "qc", "name": "Acquire & assess reads", "owner": "analyst", "agents": ["qc"]},
    {"n": 4, "key": "profile", "name": "Genomic profiling", "owner": "analyst", "agents": ["profiling"]},
    {"n": 5, "key": "evidence", "name": "Evaluate evidence & review", "owner": "tbexpert", "agents": ["evidence"]},
    {"n": 6, "key": "report", "name": "Assemble & deliver report", "owner": "pi", "agents": ["reporting"]},
]

# Human gates: who may pass each one
GATES = {
    "scope": ["pi", "deputy"],
    "cohort": ["pi", "deputy"],
    "profiling_batch": ["analyst"],
    "release": ["pi", "deputy"],
}

RULES = {
    "scope": "SCOPE-v2",
    "elig": "ELIG-v1.0",
    "cohort": "ELIG-v1.1",
    "qc": "QC-v1.0",
    "prof": "PROF-cfg-v1",
    "evid": "EVID-v1.0",
    "rpt": "RPT-v1.2",
}

THRESHOLDS = {"min_cov": 30.0, "border_cov": 25.0, "min_depth": 10, "min_freq": 0.9, "genome_bp": 4_411_532}


@dataclass
class Finding:
    fid: str
    sample_id: str
    drug: str
    gene: str
    change: str
    grade: int  # 0 not reported, 1, 2, 3, 5 (WHO catalogue groups)
    depth: float | None
    freq: float
    confidence: str = ""
    cls: str = "tech"  # tech | uncertain | other
    review: str = "Not required"  # Not required | Pending | Reviewed | Not supported | Needs more data
    reason: str = ""
    interpretation: str = ""  # Evidence Analyst's draft note (AI draft, never a decision)
    reviewer: str | None = None
    rationale: str = ""


@dataclass
class Sample:
    run: str
    biosample: str = ""
    study: str = ""
    country: str = ""
    library_strategy: str = ""
    platform: str = ""
    base_count: int | None = None
    md5: bool = False
    publication: str = ""
    # statuses (kept separate on purpose)
    eligibility: str | None = None  # Verified | Hold | Excluded
    eligibility_note: str = ""
    qc: str | None = None  # Pass | Escalated | Excluded
    qc_note: str = ""
    coverage: float | None = None
    profiling: str | None = None  # Awaiting results | Done | Failed
    profiling_note: str = ""
    lineage: str | None = None
    drtype: str | None = None
    in_cohort: bool = False
    findings: list[Finding] = field(default_factory=list)
    dst: dict[str, str] = field(default_factory=dict)
    profile_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def location(self) -> str:
        return self.country or "missing"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["location"] = self.location
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Sample":
        d = dict(d)
        d.pop("location", None)
        d["findings"] = [Finding(**f) for f in d.get("findings", [])]
        return Sample(**d)


@dataclass
class PipelineState:
    question: str = (
        "What patterns of drug resistance can we identify in Mycobacterium tuberculosis genomic samples, "
        "and which mutations are associated with resistance to rifampicin and isoniazid?"
    )
    country: str = ""  # empty = worldwide; set by the researcher at Stage 1 if they want to scope by country
    target_drugs: list[str] = field(default_factory=lambda: ["Rifampicin", "Isoniazid"])
    cohort_target: int = 8
    stage_status: dict[str, str] = field(
        default_factory=lambda: {"1": "ready", "2": "locked", "3": "locked", "4": "locked", "5": "locked", "6": "locked"}
    )
    gates: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
    cohort_checks: list[dict[str, Any]] = field(default_factory=list)
    samples: list[Sample] = field(default_factory=list)
    report: dict[str, Any] | None = None
    replans: int = 0

    def sample(self, run: str) -> Sample | None:
        return next((s for s in self.samples if s.run == run), None)

    def findings(self) -> list[Finding]:
        return [f for s in self.samples for f in s.findings]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["samples"] = [s.to_dict() for s in self.samples]
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PipelineState":
        d = dict(d)
        d["samples"] = [Sample.from_dict(s) for s in d.get("samples", [])]
        return PipelineState(**d)
