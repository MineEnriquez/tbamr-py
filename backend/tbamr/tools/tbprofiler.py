"""TB-Profiler tool: run it if installed, or parse its JSON results.

Parsing is tolerant of the JSON layouts used by TB-Profiler 4.x-6.x (`dr_variants` with either
`drugs` or `annotation` lists). Check the output against your installed version.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

DRUG_ALIAS = {
    "rifampicin": "RIF", "rifampin": "RIF", "isoniazid": "INH", "ethambutol": "EMB", "pyrazinamide": "PZA",
    "levofloxacin": "FLQ", "moxifloxacin": "FLQ", "ofloxacin": "FLQ", "ciprofloxacin": "FLQ", "fluoroquinolones": "FLQ",
    "bedaquiline": "BDQ", "linezolid": "LZD", "delamanid": "DLM", "pretomanid": "DLM", "clofazimine": "CFZ",
    "amikacin": "AMK", "streptomycin": "STM", "ethionamide": "ETO", "kanamycin": "KAN", "capreomycin": "CAP",
    "para-aminosalicylic_acid": "PAS", "cycloserine": "CYC",
}
DRUG_NAMES = {
    "RIF": "Rifampicin", "INH": "Isoniazid", "EMB": "Ethambutol", "PZA": "Pyrazinamide", "FLQ": "Fluoroquinolones",
    "BDQ": "Bedaquiline", "LZD": "Linezolid", "DLM": "Delamanid", "CFZ": "Clofazimine", "AMK": "Amikacin",
    "STM": "Streptomycin", "ETO": "Ethionamide", "KAN": "Kanamycin", "CAP": "Capreomycin", "PAS": "Para-aminosalicylic acid",
    "CYC": "Cycloserine",
}


def drug_code(name: str) -> str:
    k = re.sub(r"\s+", "_", (name or "").strip().lower())
    return DRUG_ALIAS.get(k, (name or "?")[:3].upper())


def grade_of(confidence: str) -> int:
    c = (confidence or "").lower()
    if not c:
        return 0
    if "not assoc" in c:
        return 5
    if "interim" in c:
        return 2
    if "uncertain" in c:
        return 3
    if "assoc" in c:
        return 1
    return 0


def parse_result(data: dict[str, Any], filename: str = "") -> dict[str, Any]:
    sample_id = str(data.get("id") or data.get("sample_name") or re.sub(r"(\.results)?\.json$", "", Path(filename).name)).strip()
    mutations: list[dict[str, Any]] = []
    for v in data.get("dr_variants", []) or []:
        gene = v.get("gene_name") or v.get("gene") or v.get("locus_tag") or "?"
        change = v.get("change") or v.get("nucleotide_change") or "?"
        depth = v.get("depth")
        freq = float(v.get("freq", v.get("frequency", 1)) or 1)
        anns: list[tuple[str, str]] = []
        for d in v.get("drugs", []) or []:
            anns.append((d.get("drug") or d.get("name"), d.get("confidence") or d.get("who confidence") or ""))
        for a in v.get("annotation", []) or []:
            if not a.get("type") or "resist" in str(a.get("type")).lower():
                anns.append((a.get("drug"), a.get("confidence") or ""))
        seen: set[str] = set()
        for drug, conf in anns:
            if not drug:
                continue
            code = drug_code(drug)
            if code in seen:
                continue
            seen.add(code)
            mutations.append({"gene": gene, "change": change, "drug": code, "grade": grade_of(conf),
                              "depth": None if depth is None else float(depth), "freq": freq, "confidence": conf})
    lineage = data.get("sub_lineage") or data.get("sublin") or data.get("main_lineage") or data.get("main_lin")
    pipeline = data.get("pipeline") or {}
    raw_version = data.get("version")
    version = (
        pipeline.get("software_version")
        or data.get("tbprofiler_version")
        or (raw_version.get("name") if isinstance(raw_version, dict) else raw_version)
    )
    db = data.get("db_version") or pipeline.get("db_version") or {}
    db_name = (db.get("name") or db.get("commit")) if isinstance(db, dict) else db
    qc = data.get("qc") or {}
    return {
        "sample_id": sample_id,
        "mutations": mutations,
        "lineage": str(lineage).replace("lineage", "") if lineage else None,
        "drtype": data.get("drtype") or data.get("dr_type"),
        "other_variants": len(data.get("other_variants", []) or []),
        "meta": {"tool": f"TB-Profiler {version}" if version else "TB-Profiler (version not in file)", "db": db_name or "not in file",
                 "median_depth": qc.get("target_median_depth", qc.get("median_depth")), "file": Path(filename).name},
    }


def parse_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    return parse_result(json.loads(p.read_text()), p.name)


class TBProfilerRunner:
    """Runs TB-Profiler on a run accession when the command-line tools are installed."""

    def __init__(self, workdir: str | Path = "tbprofiler_runs"):
        self.workdir = Path(workdir)

    @staticmethod
    def available() -> dict[str, bool]:
        return {"tb-profiler": shutil.which("tb-profiler") is not None, "fasterq-dump": shutil.which("fasterq-dump") is not None}

    def run(self, run_accession: str, timeout: int = 7200) -> dict[str, Any]:
        avail = self.available()
        if not all(avail.values()):
            missing = [k for k, ok in avail.items() if not ok]
            return {"ok": False, "error": f"Not installed: {', '.join(missing)}. Run TB-Profiler yourself and import the JSON instead."}
        out = self.workdir / run_accession
        out.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(["fasterq-dump", "--split-files", run_accession, "-O", str(out)], check=True, timeout=timeout, capture_output=True)
            r1, r2 = out / f"{run_accession}_1.fastq", out / f"{run_accession}_2.fastq"
            subprocess.run(["tb-profiler", "profile", "-1", str(r1), "-2", str(r2), "-p", run_accession, "--dir", str(out)],
                           check=True, timeout=timeout, capture_output=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "error": f"{type(e).__name__}: {getattr(e, 'stderr', b'')[-500:]!r}"}
        result = out / "results" / f"{run_accession}.results.json"
        if not result.exists():
            return {"ok": False, "error": f"Expected {result} was not produced."}
        data = json.loads(result.read_text())
        return {"ok": True, "result": parse_result(data, result.name), "raw": data}
