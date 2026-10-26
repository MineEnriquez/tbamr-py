"""Offline demo data. EVERYTHING here is simulated (accessions start with DEMO/PRJDEMO).

It mirrors the shapes returned by the real ENA, Europe PMC and TB-Profiler tools so the whole
pipeline can run without internet. Never mix these records with real results.
"""
from __future__ import annotations

from typing import Any

GENOME = 4_411_532

# run, biosample, study, country, strategy, platform, est. coverage, md5
_RUNS = [
    ("DEMO-R01", "SAMDEMO0001", "PRJDEMO-A", "Indonesia: Jakarta", "WGS", "ILLUMINA", 96, True),
    ("DEMO-R02", "SAMDEMO0002", "PRJDEMO-A", "Indonesia: West Java", "WGS", "ILLUMINA", 74, True),
    ("DEMO-R03", "SAMDEMO0003", "PRJDEMO-A", "Indonesia: East Java", "WGS", "ILLUMINA", 68, True),
    ("DEMO-R04", "SAMDEMO0004", "PRJDEMO-B", "Indonesia: Central Java", "WGS", "ILLUMINA", 27, True),
    ("DEMO-R05", "SAMDEMO0005", "PRJDEMO-B", "Indonesia: North Sumatra", "WGS", "ILLUMINA", 58, False),
    ("DEMO-R06", "SAMDEMO0006", "PRJDEMO-B", "Viet Nam: Hanoi", "WGS", "ILLUMINA", 80, True),
    ("DEMO-R07", "SAMDEMO0001", "PRJDEMO-A", "Indonesia: Jakarta", "WGS", "ILLUMINA", 90, True),
    ("DEMO-R08", "SAMDEMO0008", "PRJDEMO-C", "Indonesia: Bandung", "AMPLICON", "ILLUMINA", 0, True),
    ("DEMO-R09", "SAMDEMO0009", "PRJDEMO-C", "Indonesia: Papua", "WGS", "ILLUMINA", 63, True),
    ("DEMO-R10", "SAMDEMO0010", "PRJDEMO-C", "Indonesia: South Sulawesi", "WGS", "ILLUMINA", 85, True),
    ("DEMO-R11", "SAMDEMO0011", "PRJDEMO-C", "Indonesia: Bali", "WGS", "ILLUMINA", 71, True),
    ("DEMO-R12", "SAMDEMO0012", "PRJDEMO-A", "Indonesia: Jakarta", "WGS", "ILLUMINA", 77, True),
    ("DEMO-R13", "SAMDEMO0013", "PRJDEMO-B", "Indonesia: West Java", "WGS", "ILLUMINA", 66, True),
    ("DEMO-R14", "SAMDEMO0014", "PRJDEMO-B", "Indonesia: Yogyakarta", "WGS", "ILLUMINA", 44, True),
    ("DEMO-R15", "SAMDEMO0015", "PRJDEMO-C", "", "WGS", "ILLUMINA", 59, True),
    ("DEMO-R16", "SAMDEMO0016", "PRJDEMO-D", "Indonesia: Makassar", "WGS", "ION_TORRENT", 52, True),
]
_STUDIES = {
    "PRJDEMO-A": "DEMO study A — Jakarta and Java isolates (simulated)",
    "PRJDEMO-B": "DEMO study B — Sumatra and Java surveillance (simulated)",
    "PRJDEMO-C": "DEMO study C — Eastern Indonesia isolates (simulated)",
    "PRJDEMO-D": "DEMO study D — Ion Torrent pilot (simulated)",
}
_PUBS = {
    "PRJDEMO-C": [{"title": "DEMO publication: genomes from Eastern Indonesia including East Nusa Tenggara (simulated record)",
                    "authorString": "Demo A, Demo B", "journalTitle": "Demo Journal", "pubYear": "2024", "pmid": None, "doi": None}],
}
# simulated TB-Profiler outputs: run -> (lineage, drtype, [(gene, change, drug, confidence, depth, freq)])
_PROFILES = {
    "DEMO-R01": ("lineage2.2.1", "MDR-TB", [("rpoB", "p.Ser450Leu", "rifampicin", "Assoc w R", 81, 1.0), ("katG", "p.Ser315Thr", "isoniazid", "Assoc w R", 77, 1.0)]),
    "DEMO-R02": ("lineage1.1.2", "Sensitive", []),
    "DEMO-R03": ("lineage4.1.2", "HR-TB", [("fabG1", "c.-15C>T", "isoniazid", "Assoc w R", 60, 1.0)]),
    "DEMO-R05": ("lineage1.2.1", "Sensitive", []),
    "DEMO-R09": ("lineage1.1.1", "RR-TB", [("rpoB", "p.Leu430Pro", "rifampicin", "Assoc w R - Interim", 55, 1.0)]),
    "DEMO-R10": ("lineage2.2.1", "Pre-XDR-TB", [("rpoB", "p.Ser450Leu", "rifampicin", "Assoc w R", 79, 1.0), ("katG", "p.Ser315Thr", "isoniazid", "Assoc w R", 80, 1.0),
                                                 ("gyrA", "p.Asp94Gly", "moxifloxacin", "Assoc w R", 74, 1.0), ("embB", "p.Met306Val", "ethambutol", "Assoc w R", 69, 1.0)]),
    "DEMO-R11": ("lineage4.5", "HR-TB", [("katG", "p.Ser315Thr", "isoniazid", "Assoc w R", 66, 0.62)]),
    "DEMO-R12": ("lineage2.2.1", "MDR-TB", [("rpoB", "p.Ser450Leu", "rifampicin", "Assoc w R", 70, 1.0), ("katG", "p.Ser315Thr", "isoniazid", "Assoc w R", 73, 1.0),
                                             ("Rv0678", "c.192dupG", "bedaquiline", "Uncertain significance", 61, 1.0)]),
    "DEMO-R13": ("lineage4.1.1", "Sensitive", [("katG", "p.Arg463Leu", "isoniazid", "Not assoc w R", 64, 1.0)]),
    "DEMO-R14": ("lineage2.2.1", "RR-TB", [("rpoB", "p.Ser450Leu", "rifampicin", "Assoc w R", 6, 1.0)]),
}
DST = {"DEMO-R01": {"RIF": "R", "INH": "R"}, "DEMO-R05": {"RIF": "S", "INH": "S"}, "DEMO-R09": {"RIF": "S", "INH": "S"},
       "DEMO-R10": {"RIF": "R", "INH": "R"}, "DEMO-R12": {"RIF": "R"}, "DEMO-R13": {"INH": "S"}, "DEMO-R03": {"INH": "R"}}


def _row(r) -> dict[str, Any]:
    run, bs, study, country, strat, plat, cov, md5 = r
    return {"run_accession": run, "sample_accession": bs, "study_accession": study, "country": country, "library_strategy": strat,
            "library_layout": "PAIRED", "instrument_platform": plat, "base_count": str(int(cov * GENOME)), "fastq_md5": "demo1;demo2" if md5 else ""}


class DemoDataTools:
    """Same interface as tools.ena.DataTools, backed by simulated records."""

    is_demo = True

    def ena_count(self, query: str) -> int:
        return len(self._match(query))

    def _match(self, query: str) -> list[dict[str, Any]]:
        rows = [_row(r) for r in _RUNS]
        if 'country="Indonesia' in query:
            rows = [r for r in rows if r["country"].startswith("Indonesia") or not r["country"] or r["run_accession"] == "DEMO-R06"]
        for part in query.split(" AND "):
            if "study_accession!=" in part:
                acc = part.split("!=")[1].strip('" ')
                rows = [r for r in rows if r["study_accession"] != acc]
        return rows

    def ena_search_runs(self, country: str = "Indonesia", extra_query: str = "", limit: int = 500, page_size: int = 200) -> dict[str, Any]:
        q = f'tax_tree(1773) AND country="{country}*"' + (f" AND {extra_query}" if extra_query else "")
        rows = self._match(q)[:limit]
        return {"query": q, "returned": len(rows), "total_in_ena": len(rows), "runs": rows, "demo": True}

    def ena_run(self, run_accession: str) -> dict[str, Any] | None:
        return next((_row(r) for r in _RUNS if r[0] == run_accession), None)

    def ena_study(self, study_accession: str) -> dict[str, Any]:
        return {"study_accession": study_accession, "study_title": _STUDIES.get(study_accession), "demo": True}

    def ena_file_report(self, run_accession: str) -> dict[str, Any]:
        return {"run_accession": run_accession, "fastq_ftp": "", "fastq_md5": "demo1;demo2", "demo": True}

    def find_publications(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        for acc, pubs in _PUBS.items():
            if acc in query:
                return pubs[:limit]
        return []


def demo_tbprofiler_json(run: str) -> dict[str, Any] | None:
    """A simulated TB-Profiler 6-style result for a demo run, or None if not profiled."""
    p = _PROFILES.get(run)
    if not p:
        return None
    lin, drtype, variants = p
    return {"id": run, "sub_lineage": lin, "drtype": drtype, "pipeline": {"software_version": "demo (simulated)"},
            "db_version": {"name": "demo-db (simulated)"}, "qc": {"target_median_depth": 60},
            "dr_variants": [{"gene_name": g, "change": c, "depth": d, "freq": f, "annotation": [{"type": "drug_resistance", "drug": drug, "confidence": conf}]}
                            for g, c, drug, conf, d, f in variants],
            "other_variants": []}
