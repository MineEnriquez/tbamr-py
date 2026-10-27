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
    """Runs TB-Profiler via Docker (staphb/tbprofiler image) when available, else the local tb-profiler
    binary. Docker is the recommended path on macOS: the image bundles snpEff and the WHO database at
    compatible versions, avoiding the host dependency hell."""

    DOCKER_IMAGE = "staphb/tbprofiler"

    def __init__(self, workdir: str | Path = "tbprofiler_runs", threads: int | None = None, db: str | None = None):
        self.workdir = Path(workdir).resolve()
        import os
        self.threads = threads if threads is not None else int(os.environ.get("TBAMR_PROFILER_THREADS", "4"))
        # Only used when running tb-profiler locally; the docker image uses its bundled DB.
        self.db = db if db is not None else os.environ.get("TBAMR_PROFILER_DB", "tbdb")
        # Backend selection: auto (docker if the image is pulled, else local), docker, local.
        self.backend = os.environ.get("TBAMR_PROFILER_BACKEND", "auto").lower()

    @staticmethod
    def _docker_ok() -> bool:
        """Docker daemon reachable AND the staphb/tbprofiler image is pulled."""
        if shutil.which("docker") is None:
            return False
        try:
            r = subprocess.run(["docker", "image", "inspect", TBProfilerRunner.DOCKER_IMAGE], capture_output=True, timeout=10)
            return r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def using_docker(self) -> bool:
        if self.backend == "docker":
            return True
        if self.backend == "local":
            return False
        return self._docker_ok()

    def available(self) -> dict[str, bool]:
        """Report what's usable. The UI's 'tb-profiler' row is true if either Docker or the local binary works."""
        return {
            "tb-profiler": self._docker_ok() or shutil.which("tb-profiler") is not None,
            "fasterq-dump": shutil.which("fasterq-dump") is not None,
            "docker": self._docker_ok(),
        }

    def run(self, run_accession: str, timeout: int = 7200) -> dict[str, Any]:
        avail = self.available()
        if not avail["fasterq-dump"]:
            return {"ok": False, "error": "Not installed: fasterq-dump (brew install sratoolkit)."}
        if not avail["tb-profiler"]:
            return {"ok": False, "error": f"Not available: tb-profiler. Either `docker pull {self.DOCKER_IMAGE}` or install tb-profiler locally."}
        out = self.workdir / run_accession
        out.mkdir(parents=True, exist_ok=True)
        result = out / "results" / f"{run_accession}.results.json"
        if result.exists():  # resume: finished sample already has its JSON
            try:
                data = json.loads(result.read_text())
                return {"ok": True, "cached": True, "result": parse_result(data, result.name), "raw": data}
            except (ValueError, OSError):
                pass
        t = str(max(1, int(self.threads)))
        r1, r2 = out / f"{run_accession}_1.fastq", out / f"{run_accession}_2.fastq"
        try:
            # resume: skip the multi-GB fasterq-dump re-download when both FASTQs are already on disk
            if not (r1.exists() and r2.exists() and r1.stat().st_size > 0 and r2.stat().st_size > 0):
                subprocess.run(["fasterq-dump", "--split-files", "-e", t, run_accession, "-O", str(out)], check=True, timeout=timeout, capture_output=True)
            if self.using_docker():
                # mount workdir as /data; paths inside the container become /data/<run>/...
                # --platform linux/amd64 so this works under Rosetta on Apple Silicon (the staphb image is amd64-only).
                cmd = ["docker", "run", "--rm", "--platform", "linux/amd64",
                       "-v", f"{self.workdir}:/data",
                       "-w", f"/data/{run_accession}",
                       self.DOCKER_IMAGE,
                       "tb-profiler", "profile",
                       "-1", f"/data/{run_accession}/{run_accession}_1.fastq",
                       "-2", f"/data/{run_accession}/{run_accession}_2.fastq",
                       "-p", run_accession, "--dir", f"/data/{run_accession}", "--threads", t]
            else:
                cmd = ["tb-profiler", "profile", "-1", str(r1), "-2", str(r2),
                       "-p", run_accession, "--dir", str(out), "--threads", t, "--db", self.db]
            p = subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "error": f"{type(e).__name__}: {getattr(e, 'stderr', b'')[-800:]!r}"}
        if not result.exists():
            tail = (p.stderr or b"")[-800:].decode(errors="replace")
            return {"ok": False, "error": f"TB-Profiler exited 0 but produced no result file. stderr tail: {tail}"}
        data = json.loads(result.read_text())
        return {"ok": True, "result": parse_result(data, result.name), "raw": data}
