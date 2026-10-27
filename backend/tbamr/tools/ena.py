"""Public data tools: ENA Portal API and Europe PMC.

These are the tools Claude-powered agents may call. Every function returns plain JSON-able
data and never raises on an empty result. Pass a custom httpx client for tests.
"""
from __future__ import annotations

from typing import Any

import httpx

ENA = "https://www.ebi.ac.uk/ena/portal/api"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
RUN_FIELDS = "run_accession,sample_accession,study_accession,country,library_strategy,library_layout,instrument_platform,base_count,fastq_md5"
TB_TAXON = 1773  # Mycobacterium tuberculosis


class DataTools:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 30.0):
        self.http = client or httpx.Client(timeout=timeout, headers={"User-Agent": "tbamr-agentic-pipeline/0.1"})

    # ---- ENA --------------------------------------------------------------
    def ena_count(self, query: str) -> int:
        r = self.http.get(f"{ENA}/count", params={"result": "read_run", "query": query})
        r.raise_for_status()
        txt = r.text.strip().splitlines()
        try:
            return int(txt[-1])
        except (ValueError, IndexError):
            return 0

    def ena_search_runs(self, country: str = "", extra_query: str = "", limit: int = 500, page_size: int = 200) -> dict[str, Any]:
        """Search M. tuberculosis read runs, optionally scoped by country (empty = worldwide), paging past the first batch."""
        query = f'tax_tree({TB_TAXON})'
        if country:
            query += f' AND country="{country}*"'
        if extra_query:
            query += f" AND {extra_query}"
        rows: list[dict[str, Any]] = []
        offset = 0
        while len(rows) < limit:
            size = min(page_size, limit - len(rows))
            r = self.http.get(
                f"{ENA}/search",
                params={"result": "read_run", "query": query, "fields": RUN_FIELDS, "format": "json", "limit": size, "offset": offset},
            )
            r.raise_for_status()
            batch = r.json() if r.text.strip() else []
            rows.extend(batch)
            if len(batch) < size:
                break
            offset += size
        total = None
        try:
            total = self.ena_count(query)
        except httpx.HTTPError:
            pass
        return {"query": query, "returned": len(rows), "total_in_ena": total, "runs": rows}

    def ena_run(self, run_accession: str) -> dict[str, Any] | None:
        """One run's record (same fields as the search)."""
        r = self.http.get(f"{ENA}/search", params={"result": "read_run", "query": f'run_accession="{run_accession}"', "fields": RUN_FIELDS, "format": "json", "limit": 1})
        r.raise_for_status()
        rows = r.json() if r.text.strip() else []
        return rows[0] if rows else None

    def ena_study(self, study_accession: str) -> dict[str, Any]:
        r = self.http.get(
            f"{ENA}/search",
            params={"result": "study", "query": f'study_accession="{study_accession}"', "fields": "study_accession,study_title", "format": "json"},
        )
        r.raise_for_status()
        rows = r.json() if r.text.strip() else []
        return rows[0] if rows else {"study_accession": study_accession, "study_title": None}

    def ena_file_report(self, run_accession: str) -> dict[str, Any]:
        r = self.http.get(
            f"{ENA}/filereport",
            params={"accession": run_accession, "result": "read_run", "fields": "run_accession,fastq_ftp,fastq_md5,fastq_bytes", "format": "json"},
        )
        r.raise_for_status()
        rows = r.json() if r.text.strip() else []
        return rows[0] if rows else {"run_accession": run_accession}

    # ---- Europe PMC ---------------------------------------------------------
    def find_publications(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        r = self.http.get(EPMC, params={"query": query, "format": "json", "resultType": "lite", "pageSize": limit})
        r.raise_for_status()
        res = r.json().get("resultList", {}).get("result", [])
        return [
            {k: x.get(k) for k in ("title", "authorString", "journalTitle", "pubYear", "pmid", "doi")} for x in res[:limit]
        ]
