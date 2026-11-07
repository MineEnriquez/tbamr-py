"""Offline demo data. EVERYTHING here is simulated (accessions start with DEMO/PRJDEMO).

It mirrors the shapes returned by the real ENA, Europe PMC and TB-Profiler tools so the whole
pipeline can run without internet. Never mix these records with real results.

The runs form a scenario catalogue: each one exercises a decision branch the real system can
hit (eligibility rules, QC thresholds and their boundaries, TB-Profiler failures and file
formats, every evidence class, DST concordance and discordance). `SCENARIOS` documents what
each run is for and the outcome the pipeline should reach; tests/test_pipeline.py checks it.
"""
from __future__ import annotations

from typing import Any

from ..logutil import logged

GENOME = 4_411_532

# run, biosample, study, country, strategy, platform, layout, est. coverage (None = base_count missing), md5
_RUNS = [
    # --- original core set ---------------------------------------------------------------
    ("DEMO-R01", "SAMDEMO0001", "PRJDEMO-A", "Indonesia: Jakarta", "WGS", "ILLUMINA", "PAIRED", 96, True),
    ("DEMO-R02", "SAMDEMO0002", "PRJDEMO-A", "Indonesia: West Java", "WGS", "ILLUMINA", "PAIRED", 74, True),
    ("DEMO-R03", "SAMDEMO0003", "PRJDEMO-A", "Indonesia: East Java", "WGS", "ILLUMINA", "PAIRED", 68, True),
    ("DEMO-R04", "SAMDEMO0004", "PRJDEMO-B", "Indonesia: Central Java", "WGS", "ILLUMINA", "PAIRED", 27, True),
    ("DEMO-R05", "SAMDEMO0005", "PRJDEMO-B", "Indonesia: North Sumatra", "WGS", "ILLUMINA", "PAIRED", 58, False),
    ("DEMO-R06", "SAMDEMO0006", "PRJDEMO-B", "Viet Nam: Hanoi", "WGS", "ILLUMINA", "PAIRED", 80, True),
    ("DEMO-R07", "SAMDEMO0001", "PRJDEMO-A", "Indonesia: Jakarta", "WGS", "ILLUMINA", "PAIRED", 90, True),
    ("DEMO-R08", "SAMDEMO0008", "PRJDEMO-C", "Indonesia: Bandung", "AMPLICON", "ILLUMINA", "PAIRED", 0, True),
    ("DEMO-R09", "SAMDEMO0009", "PRJDEMO-C", "Indonesia: Papua", "WGS", "ILLUMINA", "PAIRED", 63, True),
    ("DEMO-R10", "SAMDEMO0010", "PRJDEMO-C", "Indonesia: South Sulawesi", "WGS", "ILLUMINA", "PAIRED", 85, True),
    ("DEMO-R11", "SAMDEMO0011", "PRJDEMO-C", "Indonesia: Bali", "WGS", "ILLUMINA", "PAIRED", 71, True),
    ("DEMO-R12", "SAMDEMO0012", "PRJDEMO-A", "Indonesia: Jakarta", "WGS", "ILLUMINA", "PAIRED", 77, True),
    ("DEMO-R13", "SAMDEMO0013", "PRJDEMO-B", "Indonesia: West Java", "WGS", "ILLUMINA", "PAIRED", 66, True),
    ("DEMO-R14", "SAMDEMO0014", "PRJDEMO-B", "Indonesia: Yogyakarta", "WGS", "ILLUMINA", "PAIRED", 44, True),
    ("DEMO-R15", "SAMDEMO0015", "PRJDEMO-C", "", "WGS", "ILLUMINA", "PAIRED", 59, True),
    ("DEMO-R16", "SAMDEMO0016", "PRJDEMO-D", "Indonesia: Makassar", "WGS", "ION_TORRENT", "PAIRED", 52, True),
    # --- Stage 2: eligibility edge cases ---------------------------------------------------
    ("DEMO-R17", "SAMDEMO0017", "PRJDEMO-E", "indonesia:Surabaya", "WGS", "ILLUMINA", "PAIRED", 64, True),
    ("DEMO-R18", "SAMDEMO0018", "PRJDEMO-E", "Indonesia: Medan", "RNA-Seq", "ILLUMINA", "PAIRED", 40, True),
    ("DEMO-R19", "SAMDEMO0019", "PRJDEMO-E", "Indonesia: Padang", "", "ILLUMINA", "PAIRED", 55, True),
    ("DEMO-R20", "SAMDEMO0020", "PRJDEMO-F", "Indonesia: Semarang", "WGS", "OXFORD_NANOPORE", "SINGLE", 120, True),
    ("DEMO-R21", "SAMDEMO0021", "PRJDEMO-F", "Indonesia: Malang", "WGS", "", "PAIRED", 61, True),
    ("DEMO-R22", "SAMDEMO0022", "PRJDEMO-E", "", "WGS", "ILLUMINA", "PAIRED", 70, True),
    ("DEMO-R23", "SAMDEMO0010", "PRJDEMO-E", "Indonesia: South Sulawesi", "WGS", "ILLUMINA", "PAIRED", 82, True),
    ("DEMO-R24", "SAMDEMO0024", "PRJDEMO-F", "Malaysia: Sabah", "WGS", "ILLUMINA", "PAIRED", 75, True),
    ("DEMO-R25", "SAMDEMO0025", "PRJDEMO-F", "Indonesia: Pontianak", "WGS", "ILLUMINA", "SINGLE", 45, True),
    # --- Stage 3: QC thresholds and boundaries ---------------------------------------------
    ("DEMO-R26", "SAMDEMO0026", "PRJDEMO-B", "Indonesia: Lampung", "WGS", "ILLUMINA", "PAIRED", 12, True),
    ("DEMO-R27", "SAMDEMO0027", "PRJDEMO-B", "Indonesia: Riau", "WGS", "ILLUMINA", "PAIRED", None, True),
    ("DEMO-R28", "SAMDEMO0028", "PRJDEMO-E", "Indonesia: Banten", "WGS", "ILLUMINA", "PAIRED", 30, True),
    ("DEMO-R29", "SAMDEMO0029", "PRJDEMO-E", "Indonesia: Jambi", "WGS", "ILLUMINA", "PAIRED", 25, True),
    # --- Stage 4: profiling states and result-file formats ---------------------------------
    ("DEMO-R30", "SAMDEMO0030", "PRJDEMO-A", "Indonesia: Bogor", "WGS", "ILLUMINA", "PAIRED", 66, True),
    ("DEMO-R31", "SAMDEMO0031", "PRJDEMO-B", "Indonesia: Palembang", "WGS", "ILLUMINA", "PAIRED", 58, True),
    ("DEMO-R32", "SAMDEMO0032", "PRJDEMO-C", "Indonesia: Manado", "WGS", "ILLUMINA", "PAIRED", 62, True),
    # --- Stage 5: evidence classes, boundaries and DST -------------------------------------
    ("DEMO-R33", "SAMDEMO0033", "PRJDEMO-A", "Indonesia: Jakarta", "WGS", "ILLUMINA", "PAIRED", 88, True),
    ("DEMO-R34", "SAMDEMO0034", "PRJDEMO-E", "Indonesia: Denpasar", "WGS", "ILLUMINA", "PAIRED", 72, True),
    ("DEMO-R35", "SAMDEMO0035", "PRJDEMO-C", "Indonesia: Kupang", "WGS", "ILLUMINA", "PAIRED", 69, True),
    ("DEMO-R36", "SAMDEMO0036", "PRJDEMO-B", "Indonesia: Bandar Lampung", "WGS", "ILLUMINA", "PAIRED", 64, True),
    ("DEMO-R37", "SAMDEMO0037", "PRJDEMO-E", "Indonesia: Balikpapan", "WGS", "ILLUMINA", "PAIRED", 33, True),
    ("DEMO-R38", "SAMDEMO0038", "PRJDEMO-A", "Indonesia: Depok", "WGS", "ILLUMINA", "PAIRED", 79, True),
    ("DEMO-R39", "SAMDEMO0039", "PRJDEMO-B", "Indonesia: Pekanbaru", "WGS", "ILLUMINA", "PAIRED", 57, True),
    ("DEMO-R40", "SAMDEMO0040", "PRJDEMO-C", "Indonesia: Ambon", "WGS", "ILLUMINA", "PAIRED", 91, True),
    ("DEMO-R41", "SAMDEMO0041", "PRJDEMO-F", "Indonesia: Mataram", "WGS", "ILLUMINA", "PAIRED", 76, True),
    ("DEMO-R42", "SAMDEMO0042", "PRJDEMO-E", "Indonesia: Tangerang", "WGS", "ILLUMINA", "PAIRED", 68, True),
    # --- subnational: location recorded as "city, province" ----------------------------------
    ("DEMO-R43", "SAMDEMO0043", "PRJDEMO-A", "Indonesia: Bandung, West Java", "WGS", "ILLUMINA", "PAIRED", 73, True),
]
# Runs a loosely-scoped archive search can return although their country is outside the scope.
_DECOYS = {"DEMO-R06", "DEMO-R24"}

_STUDIES = {
    "PRJDEMO-A": "DEMO study A — Jakarta and Java isolates (simulated)",
    "PRJDEMO-B": "DEMO study B — Sumatra and Java surveillance (simulated)",
    "PRJDEMO-C": "DEMO study C — Eastern Indonesia isolates (simulated)",
    "PRJDEMO-D": "DEMO study D — Ion Torrent pilot (simulated)",
    "PRJDEMO-E": "DEMO study E — multi-site resubmission with sparse metadata (simulated)",
    "PRJDEMO-F": None,  # study with no title in the archive
}
_PUBS = {
    "PRJDEMO-C": [{"title": "DEMO publication: genomes from Eastern Indonesia including East Nusa Tenggara (simulated record)",
                    "authorString": "Demo A, Demo B", "journalTitle": "Demo Journal", "pubYear": "2024", "pmid": None, "doi": None}],
}

# Simulated TB-Profiler 6-style outputs: run -> (lineage, drtype, [(gene, change, drug, confidence, depth, freq)]).
# depth None = field absent from the file; confidence "" = grading absent from the file.
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
    "DEMO-R17": ("lineage2.2.1", "Sensitive", []),
    "DEMO-R28": ("lineage4.3.3", "Sensitive", []),
    "DEMO-R32": ("lineage1.2.2", "RR-TB", [("rpoB", "p.His445Tyr", "rifampicin", "", None, 1.0)]),
    "DEMO-R33": ("lineage2.2.1", "XDR-TB", [("rpoB", "p.Ser450Leu", "rifampicin", "Assoc w R", 84, 1.0), ("katG", "p.Ser315Thr", "isoniazid", "Assoc w R", 82, 1.0),
                                             ("gyrA", "p.Asp94Gly", "levofloxacin", "Assoc w R", 80, 1.0), ("rplC", "p.Cys154Arg", "linezolid", "Assoc w R", 77, 1.0),
                                             ("Rv0678", "c.141_142insC", "bedaquiline", "Assoc w R - Interim", 71, 1.0)]),
    "DEMO-R34": ("lineage1.1.3", "RR-TB", [("rpoB", "p.His445Asn", "rifampicin", "Assoc w R - Interim", 62, 1.0)]),
    "DEMO-R35": ("lineage2.2.1;lineage4.3.4.2", "HR-TB", [("katG", "p.Ser315Thr", "isoniazid", "Assoc w R", 65, 1.0),
                                                           ("gyrA", "p.Ala90Val", "moxifloxacin", "Assoc w R", 58, 0.35)]),
    "DEMO-R36": ("lineage4.1.2", "HR-TB", [("inhA", "c.-777C>T", "isoniazid", "Assoc w R", 61, 0.88)]),
    "DEMO-R37": ("lineage4.5", "RR-TB", [("rpoB", "p.Asp435Val", "rifampicin", "Assoc w R", 10, 1.0)]),
    "DEMO-R38": ("lineage4.1.1", "Sensitive", []),
    "DEMO-R40": ("lineage2.2.1", "MDR-TB", [("rpoB", "p.Ser450Leu", "rifampicin", "Assoc w R", 88, 1.0), ("katG", "p.Ser315Thr", "isoniazid", "Assoc w R", 86, 1.0),
                                             ("pncA", "p.Gln10Pro", "pyrazinamide", "Assoc w R", 83, 1.0), ("embB", "p.Gly406Ala", "ethambutol", "Assoc w R", 80, 1.0),
                                             ("rpsL", "p.Lys43Arg", "streptomycin", "Assoc w R", 85, 1.0), ("rrs", "n.1401A>G", "amikacin", "Assoc w R", 79, 1.0)]),
    "DEMO-R41": ("La1.8.BCG", "Other", [("pncA", "p.His57Asp", "pyrazinamide", "Assoc w R", 74, 1.0)]),
    "DEMO-R43": ("lineage2.2.1", "HR-TB", [("katG", "p.Ser315Thr", "isoniazid", "Assoc w R", 70, 1.0)]),
    "DEMO-R42": ("lineage1.1.1", "Sensitive", [("gyrA", "p.Glu21Gln", "moxifloxacin", "Not assoc w R", 66, 1.0),
                                                ("rpoB", "p.Ala1075Ala", "rifampicin", "Not assoc w R", 70, 1.0)]),
}
# TB-Profiler 4.x layout: `drugs` list per variant, `version` key, no db_version, `main_lin`/`sublin`.
_PROFILES_V4 = {
    "DEMO-R31": {"id": "DEMO-R31", "main_lin": "lineage4", "sublin": "lineage4.3.4.1", "drtype": "MDR", "tbprofiler_version": "4.4.0",
                 "qc": {"median_depth": 52},
                 "dr_variants": [{"gene": "rpoB", "change": "p.Ser450Leu", "depth": 49, "freq": 1.0, "drugs": [{"drug": "rifampicin", "confidence": "Assoc w R"}]},
                                 {"gene": "katG", "change": "p.Ser315Thr", "depth": 51, "freq": 1.0, "drugs": [{"drug": "isoniazid", "confidence": "Assoc w R"}]}],
                 "other_variants": [{"gene": "Rv2752c", "change": "p.Asn30Ser"}]},
    # one variant annotated for two drugs (inhA promoter: isoniazid + ethionamide)
    "DEMO-R39": {"id": "DEMO-R39", "sub_lineage": "lineage4.1.2.1", "drtype": "HR-TB", "pipeline": {"software_version": "6.2.0"},
                 "db_version": {"name": "tbdb", "commit": "demo1234"}, "qc": {"target_median_depth": 55},
                 "dr_variants": [{"gene_name": "fabG1", "change": "c.-15C>T", "depth": 53, "freq": 1.0,
                                  "annotation": [{"type": "drug_resistance", "drug": "isoniazid", "confidence": "Assoc w R"},
                                                 {"type": "drug_resistance", "drug": "ethionamide", "confidence": "Assoc w R"}]}],
                 "other_variants": []},
}
# TB-Profiler runs that fail (the real runner returns an error string the pipeline records).
_FAILURES = {"DEMO-R25": "TB-Profiler did not start: only one FASTQ file (single-end library); the approved config expects paired reads."}

DST = {"DEMO-R01": {"RIF": "R", "INH": "R"}, "DEMO-R05": {"RIF": "S", "INH": "S"}, "DEMO-R09": {"RIF": "S", "INH": "S"},
       "DEMO-R10": {"RIF": "R", "INH": "R"}, "DEMO-R12": {"RIF": "R"}, "DEMO-R13": {"INH": "S"}, "DEMO-R03": {"INH": "R"},
       "DEMO-R33": {"RIF": "R", "INH": "R", "FLQ": "R"}, "DEMO-R38": {"RIF": "R", "INH": "S"}, "DEMO-R39": {"INH": "R"},
       "DEMO-R40": {"RIF": "R", "INH": "R", "PZA": "R"}}

# What each run is for, and where the pipeline should land. Keys of `expect`:
#   elig = Verified/Hold/Excluded · qc = Pass/Escalated/Excluded · prof = Done/Failed/Awaiting results
#   review = {"gene change": "Pending" | "Not required"} for findings that must be (or must not be) routed to review
SCENARIOS: dict[str, dict[str, Any]] = {
    "DEMO-R01": {"what": "Clean MDR-TB, catalogue grade 1, DST concordant", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"rpoB p.Ser450Leu": "Not required"}}},
    "DEMO-R02": {"what": "Pan-susceptible, no resistance variants", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R03": {"what": "Isoniazid-only (HR-TB) via fabG1 promoter, DST concordant", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R04": {"what": "Borderline coverage 27× → QC escalation", "expect": {"elig": "Verified", "qc": "Escalated"}},
    "DEMO-R05": {"what": "No archive checksum (integrity not verifiable), otherwise clean", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R06": {"what": "Country outside the approved scope (Viet Nam)", "expect": {"elig": "Excluded"}},
    "DEMO-R07": {"what": "Repeated isolate: BioSample shared with R01 in the same study", "expect": {"elig": "Excluded"}},
    "DEMO-R08": {"what": "Amplicon library, not WGS", "expect": {"elig": "Excluded"}},
    "DEMO-R09": {"what": "Interim (group 2) rpoB call, DST susceptible → discordance", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"rpoB p.Leu430Pro": "Pending"}}},
    "DEMO-R10": {"what": "Pre-XDR-TB: RIF + INH + fluoroquinolone + ethambutol", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R11": {"what": "Minor variant at 62% of reads (heteroresistance)", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"katG p.Ser315Thr": "Pending"}}},
    "DEMO-R12": {"what": "Bedaquiline variant of uncertain significance (group 3)", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"Rv0678 c.192dupG": "Pending"}}},
    "DEMO-R13": {"what": "Only a 'not associated' lineage marker → not counted", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"katG p.Arg463Leu": "Not required"}}},
    "DEMO-R14": {"what": "Resistance call at 6 reads (below the depth minimum)", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"rpoB p.Ser450Leu": "Pending"}}},
    "DEMO-R15": {"what": "Country missing; a linked publication suggests Indonesia → human confirms", "expect": {"elig": "Hold"}},
    "DEMO-R16": {"what": "Non-Illumina platform (Ion Torrent)", "expect": {"elig": "Hold"}},
    "DEMO-R17": {"what": "Country written in a non-standard form ('indonesia:Surabaya') still matches", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R18": {"what": "RNA-Seq library, not WGS", "expect": {"elig": "Excluded"}},
    "DEMO-R19": {"what": "Library strategy missing from the archive record", "expect": {"elig": "Excluded"}},
    "DEMO-R20": {"what": "Oxford Nanopore long reads", "expect": {"elig": "Hold"}},
    "DEMO-R21": {"what": "Platform missing from the archive record", "expect": {"elig": "Hold"}},
    "DEMO-R22": {"what": "Country missing and no publication evidence found", "expect": {"elig": "Hold"}},
    "DEMO-R23": {"what": "Same BioSample as R10 resubmitted under another study", "expect": {"elig": "Excluded"}},
    "DEMO-R24": {"what": "Neighbouring country (Malaysia: Sabah) returned by a loose search", "expect": {"elig": "Excluded"}},
    "DEMO-R25": {"what": "Single-end library: passes QC, TB-Profiler fails", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Failed"}},
    "DEMO-R26": {"what": "Coverage 12×, below the exclusion line", "expect": {"elig": "Verified", "qc": "Excluded"}},
    "DEMO-R27": {"what": "Base count missing → coverage cannot be estimated", "expect": {"elig": "Verified", "qc": "Escalated"}},
    "DEMO-R28": {"what": "Coverage exactly 30× (pass boundary)", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R29": {"what": "Coverage exactly 25× (bottom of the borderline zone)", "expect": {"elig": "Verified", "qc": "Escalated"}},
    "DEMO-R30": {"what": "QC passed but no TB-Profiler result yet (analyst must run or import it)", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Awaiting results"}},
    "DEMO-R31": {"what": "Older TB-Profiler 4.x result layout (drugs list, no database version)", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R32": {"what": "Result file without catalogue grading or depth", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"rpoB p.His445Tyr": "Not required"}}},
    "DEMO-R33": {"what": "XDR-TB: RIF + INH + FLQ + linezolid + bedaquiline (interim), DST concordant", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"Rv0678 c.141_142insC": "Pending"}}},
    "DEMO-R34": {"what": "Interim grading alone, no DST → agent adds caution", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"rpoB p.His445Asn": "Pending"}}},
    "DEMO-R35": {"what": "Mixed-lineage sample with a 35% fluoroquinolone variant", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"gyrA p.Ala90Val": "Pending", "katG p.Ser315Thr": "Not required"}}},
    "DEMO-R36": {"what": "Read fraction 88%, just under the 90% minimum", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"inhA c.-777C>T": "Pending"}}},
    "DEMO-R37": {"what": "Depth exactly 10 reads (depth boundary, passes)", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"rpoB p.Asp435Val": "Not required"}}},
    "DEMO-R38": {"what": "Phenotypically RIF-resistant, no resistance variant found (missed by genotype)", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R39": {"what": "One variant annotated for two drugs (INH + ethionamide)", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R40": {"what": "MDR-TB plus pyrazinamide, ethambutol, streptomycin, amikacin", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R41": {"what": "M. bovis BCG lineage (likely contamination); intrinsic pncA", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R43": {"what": "Location 'Bandung, West Java' (city + province) still matches a West Java region target", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done"}},
    "DEMO-R42": {"what": "Only lineage markers ('not associated') → nothing counted", "expect": {"elig": "Verified", "qc": "Pass", "prof": "Done", "review": {"gyrA p.Glu21Gln": "Not required"}}},
}


def _row(r) -> dict[str, Any]:
    run, bs, study, country, strat, plat, layout, cov, md5 = r
    return {"run_accession": run, "sample_accession": bs, "study_accession": study, "country": country, "library_strategy": strat,
            "library_layout": layout, "instrument_platform": plat, "base_count": "" if cov is None else str(int(cov * GENOME)),
            "fastq_md5": "demo1;demo2" if md5 else ""}


class DemoDataTools:
    """Same interface as tools.ena.DataTools, backed by simulated records."""

    is_demo = True

    @logged("tbamr.tools.demo")
    def ena_count(self, query: str) -> int:
        return len(self._match(query))

    def _match(self, query: str) -> list[dict[str, Any]]:
        rows = [_row(r) for r in _RUNS]
        if 'country="' in query:
            prefix = query.split('country="', 1)[1].split('"', 1)[0].rstrip("*").strip().lower()
            if prefix and prefix not in ("worldwide", "global", "any"):  # scoped search: prefix match (case-insensitive, like ENA), plus records with no country and loose-search decoys
                rows = [r for r in rows if r["country"].lower().startswith(prefix) or not r["country"] or r["run_accession"] in _DECOYS]
        for part in query.split(" AND "):
            if "study_accession!=" in part:
                acc = part.split("!=")[1].strip('" ')
                rows = [r for r in rows if r["study_accession"] != acc]
        return rows

    @logged("tbamr.tools.demo")
    def ena_search_runs(self, country: str = "Indonesia", extra_query: str = "", limit: int = 500, page_size: int = 200) -> dict[str, Any]:
        q = f'tax_tree(1773) AND country="{country}*"' + (f" AND {extra_query}" if extra_query else "")
        matches = self._match(q)
        rows = matches[:limit]
        return {"query": q, "returned": len(rows), "total_in_ena": len(matches), "runs": rows, "demo": True}

    @logged("tbamr.tools.demo")
    def ena_run(self, run_accession: str) -> dict[str, Any] | None:
        return next((_row(r) for r in _RUNS if r[0] == run_accession), None)

    @logged("tbamr.tools.demo")
    def ena_study(self, study_accession: str) -> dict[str, Any]:
        return {"study_accession": study_accession, "study_title": _STUDIES.get(study_accession), "demo": True}

    @logged("tbamr.tools.demo")
    def ena_file_report(self, run_accession: str) -> dict[str, Any]:
        r = self.ena_run(run_accession) or {}
        files = 1 if r.get("library_layout") == "SINGLE" else 2
        return {"run_accession": run_accession, "fastq_ftp": "", "fastq_md5": ";".join(f"demo{i + 1}" for i in range(files)) if r.get("fastq_md5") else "", "demo": True}

    @logged("tbamr.tools.demo")
    def find_publications(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        for acc, pubs in _PUBS.items():
            if acc in query:
                return pubs[:limit]
        return []


def demo_tbprofiler_json(run: str) -> dict[str, Any] | None:
    """A simulated TB-Profiler result for a demo run, or None if not profiled."""
    if run in _PROFILES_V4:
        return _PROFILES_V4[run]
    p = _PROFILES.get(run)
    if not p:
        return None
    lin, drtype, variants = p

    def variant(g, c, drug, conf, d, f):
        v = {"gene_name": g, "change": c, "freq": f, "annotation": [{"type": "drug_resistance", "drug": drug, **({"confidence": conf} if conf else {})}]}
        if d is not None:
            v["depth"] = d
        return v

    return {"id": run, "sub_lineage": lin, "drtype": drtype, "pipeline": {"software_version": "demo (simulated)"},
            "db_version": {"name": "demo-db (simulated)"}, "qc": {"target_median_depth": 60},
            "dr_variants": [variant(*v) for v in variants], "other_variants": []}


def demo_tbprofiler_failure(run: str) -> str | None:
    """The error a simulated TB-Profiler run returns, or None if it would not fail."""
    return _FAILURES.get(run)
