"""Public data tools: ENA Portal API and Europe PMC.

These are the tools Claude-powered agents may call. Every function returns plain JSON-able
data and never raises on an empty result. Pass a custom httpx client for tests.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..logutil import logged
from ..stores.cache import cache

ENA = "https://www.ebi.ac.uk/ena/portal/api"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
RUN_FIELDS = "run_accession,sample_accession,study_accession,country,library_strategy,library_layout,instrument_platform,base_count,fastq_md5"
TB_TAXON = 1773  # Mycobacterium tuberculosis


class DataTools:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 30.0):
        self.http = client or httpx.Client(timeout=timeout, headers={"User-Agent": "tbamr-agentic-pipeline/0.1"})

    # ---- ENA --------------------------------------------------------------
    def ena_count(self, query: str) -> int:
        return cache.wrap("ena", {"m": "count", "q": query}, lambda: self._ena_count(query))

    @logged("tbamr.tools.ena")
    def _ena_count(self, query: str) -> int:
        r = self.http.get(f"{ENA}/count", params={"result": "read_run", "query": query})
        r.raise_for_status()
        txt = r.text.strip().splitlines()
        try:
            return int(txt[-1])
        except (ValueError, IndexError):
            return 0

    def ena_search_runs(self, country: str = "", extra_query: str = "", limit: int = 500, page_size: int = 200) -> dict[str, Any]:
        return cache.wrap(
            "ena",
            {"m": "search", "country": country, "extra": extra_query, "limit": limit, "page_size": page_size},
            lambda: self._ena_search_runs(country, extra_query, limit, page_size),
        )

    @logged("tbamr.tools.ena")
    def _ena_search_runs(self, country: str = "", extra_query: str = "", limit: int = 500, page_size: int = 200) -> dict[str, Any]:
        """Search M. tuberculosis read runs, optionally scoped by country. Empty, 'worldwide' or 'global'
        (case-insensitive) all mean no country filter.

        One request with the full limit: the ENA Portal API search endpoint rejects `offset` ("Unsupported
        param offset", HTTP 400), so paging with offsets made every search larger than one page fail outright.
        `page_size` is kept for interface compatibility and ignored."""
        query = f'tax_tree({TB_TAXON})'
        if country and country.strip().lower() not in ("worldwide", "global", "any"):
            query += f' AND country="{country}*"'
        if extra_query:
            query += f" AND {extra_query}"
        r = self.http.get(
            f"{ENA}/search",
            params={"result": "read_run", "query": query, "fields": RUN_FIELDS, "format": "json", "limit": max(0, int(limit))},
        )
        r.raise_for_status()
        rows: list[dict[str, Any]] = r.json() if r.text.strip() else []
        total = None
        try:
            total = self.ena_count(query)
        except httpx.HTTPError:
            pass
        return {"query": query, "returned": len(rows), "total_in_ena": total, "runs": rows}

    def ena_run(self, run_accession: str) -> dict[str, Any] | None:
        """One run's record (same fields as the search)."""
        return cache.wrap("ena", {"m": "run", "acc": run_accession}, lambda: self._ena_run(run_accession))

    @logged("tbamr.tools.ena")
    def _ena_run(self, run_accession: str) -> dict[str, Any] | None:
        r = self.http.get(f"{ENA}/search", params={"result": "read_run", "query": f'run_accession="{run_accession}"', "fields": RUN_FIELDS, "format": "json", "limit": 1})
        r.raise_for_status()
        rows = r.json() if r.text.strip() else []
        return rows[0] if rows else None

    def ena_study(self, study_accession: str) -> dict[str, Any]:
        return cache.wrap("ena", {"m": "study", "acc": study_accession}, lambda: self._ena_study(study_accession))

    @logged("tbamr.tools.ena")
    def _ena_study(self, study_accession: str) -> dict[str, Any]:
        r = self.http.get(
            f"{ENA}/search",
            params={"result": "study", "query": f'study_accession="{study_accession}"', "fields": "study_accession,study_title", "format": "json"},
        )
        r.raise_for_status()
        rows = r.json() if r.text.strip() else []
        return rows[0] if rows else {"study_accession": study_accession, "study_title": None}

    def ena_file_report(self, run_accession: str) -> dict[str, Any]:
        return cache.wrap("ena", {"m": "filereport", "acc": run_accession}, lambda: self._ena_file_report(run_accession))

    @logged("tbamr.tools.ena")
    def _ena_file_report(self, run_accession: str) -> dict[str, Any]:
        r = self.http.get(
            f"{ENA}/filereport",
            params={"accession": run_accession, "result": "read_run", "fields": "run_accession,fastq_ftp,fastq_md5,fastq_bytes", "format": "json"},
        )
        r.raise_for_status()
        rows = r.json() if r.text.strip() else []
        return rows[0] if rows else {"run_accession": run_accession}

    # ---- Europe PMC ---------------------------------------------------------
    def find_publications(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return cache.wrap("pmc", {"m": "find", "q": query, "limit": limit}, lambda: self._find_publications(query, limit))

    @logged("tbamr.tools.ena")
    def _find_publications(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        r = self.http.get(EPMC, params={"query": query, "format": "json", "resultType": "lite", "pageSize": limit})
        r.raise_for_status()
        res = r.json().get("resultList", {}).get("result", [])
        return [
            {k: x.get(k) for k in ("title", "authorString", "journalTitle", "pubYear", "pmid", "doi")} for x in res[:limit]
        ]
