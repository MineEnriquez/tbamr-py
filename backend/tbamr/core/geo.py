"""Target-population resolution: which country (or explicitly worldwide) a study is about.

The pipeline only searches with a clear target. Rules (SCOPE-v2, applied before any agent):
  1. Country field set → it must be a recognised country, or an explicit worldwide word.
  2. Country field empty → the question must name exactly one country, or say worldwide/global.
  3. Anything else (nothing stated, a region only, several countries, an unrecognised name, or a
     field that contradicts the question) blocks the scope until the researcher fixes it.
Worldwide is never a default: it has to be asked for.

Country names are canonicalised to the INSDC /country vocabulary that ENA records use
(e.g. "Vietnam" → "Viet Nam", "United States" → "USA"), so the scope matches archive records.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

WORLDWIDE = "Worldwide"
# Shown whenever the scope resolves to worldwide, so the researcher knows the cost before starting.
WORLDWIDE_NOTICE = ("Worldwide scope: no country filter is applied. Discovery retrieves up to 500 candidate runs from the archive, "
                    "and every run that passes QC must be downloaded and profiled with TB-Profiler. At this scale, profiling (Stage 4) "
                    "can take several hours, depending on network bandwidth and available CPU cores. For a first analysis, "
                    "a single-country scope is usually faster and easier to interpret.")

# INSDC /country vocabulary (the values ENA's country field starts with).
INSDC_COUNTRIES = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda", "Argentina", "Armenia", "Australia", "Austria",
    "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus", "Belgium", "Belize", "Benin", "Bhutan", "Bolivia",
    "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria", "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia",
    "Cameroon", "Canada", "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros", "Costa Rica",
    "Cote d'Ivoire", "Croatia", "Cuba", "Cyprus", "Czechia", "Democratic Republic of the Congo", "Denmark", "Djibouti", "Dominica",
    "Dominican Republic", "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini", "Ethiopia",
    "Fiji", "Finland", "France", "French Guiana", "Gabon", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Greenland", "Grenada",
    "Guatemala", "Guinea", "Guinea-Bissau", "Guyana", "Haiti", "Honduras", "Hong Kong", "Hungary", "Iceland", "India", "Indonesia",
    "Iran", "Iraq", "Ireland", "Israel", "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati", "Kosovo", "Kuwait",
    "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania", "Luxembourg", "Macau",
    "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Marshall Islands", "Mauritania", "Mauritius", "Mexico",
    "Micronesia, Federated States of", "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia",
    "Nauru", "Nepal", "Netherlands", "New Caledonia", "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", "North Macedonia",
    "Norway", "Oman", "Pakistan", "Palau", "Palestine", "Panama", "Papua New Guinea", "Paraguay", "Peru", "Philippines", "Poland",
    "Portugal", "Puerto Rico", "Qatar", "Republic of the Congo", "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis",
    "Saint Lucia", "Saint Vincent and the Grenadines", "Samoa", "San Marino", "Sao Tome and Principe", "Saudi Arabia", "Senegal",
    "Serbia", "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia", "Solomon Islands", "Somalia", "South Africa",
    "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname", "Sweden", "Switzerland", "Syria", "Taiwan", "Tajikistan",
    "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga", "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Tuvalu",
    "Uganda", "Ukraine", "United Arab Emirates", "United Kingdom", "Uruguay", "USA", "Uzbekistan", "Vanuatu", "Venezuela", "Viet Nam",
    "Yemen", "Zambia", "Zimbabwe",
]
# Common alternative names and demonyms → INSDC name. Demonyms only where they are unambiguous in TB research text.
ALIASES = {
    "vietnam": "Viet Nam", "vietnamese": "Viet Nam", "united states": "USA", "united states of america": "USA", "us": "USA", "u.s.": "USA",
    "uk": "United Kingdom", "great britain": "United Kingdom", "britain": "United Kingdom", "england": "United Kingdom",
    "scotland": "United Kingdom", "wales": "United Kingdom", "russian federation": "Russia", "korea": "South Korea",
    "republic of korea": "South Korea", "drc": "Democratic Republic of the Congo", "dr congo": "Democratic Republic of the Congo",
    "congo-kinshasa": "Democratic Republic of the Congo", "congo-brazzaville": "Republic of the Congo", "ivory coast": "Cote d'Ivoire",
    "côte d'ivoire": "Cote d'Ivoire", "czech republic": "Czechia", "swaziland": "Eswatini", "burma": "Myanmar", "türkiye": "Turkey",
    "turkiye": "Turkey", "east timor": "Timor-Leste", "lao pdr": "Laos", "macedonia": "North Macedonia", "cape verde": "Cabo Verde",
    "holland": "Netherlands", "the netherlands": "Netherlands", "the gambia": "Gambia", "persia": "Iran",
    "indonesian": "Indonesia", "kenyan": "Kenya", "nigerian": "Nigeria", "south african": "South Africa", "filipino": "Philippines",
    "philippine": "Philippines", "pakistani": "Pakistan", "bangladeshi": "Bangladesh", "chinese": "China", "burmese": "Myanmar",
    "thai": "Thailand", "peruvian": "Peru", "brazilian": "Brazil", "mexican": "Mexico", "ethiopian": "Ethiopia", "tanzanian": "Tanzania",
    "ugandan": "Uganda", "mozambican": "Mozambique", "ukrainian": "Ukraine", "zambian": "Zambia", "zimbabwean": "Zimbabwe",
    "cambodian": "Cambodia", "nepali": "Nepal", "nepalese": "Nepal", "malawian": "Malawi", "georgian": "Georgia", "moldovan": "Moldova",
    "kazakh": "Kazakhstan", "uzbek": "Uzbekistan", "tajik": "Tajikistan", "kyrgyz": "Kyrgyzstan", "mongolian": "Mongolia",
}
WORLDWIDE_WORDS = ("worldwide", "global", "globally", "all countries", "any country", "every country", "world-wide", "international")
# Regions are not usable as an archive filter on their own; the researcher must pick a country or say worldwide.
REGIONS = ("africa", "sub-saharan africa", "sub-saharan", "asia", "south-east asia", "southeast asia", "europe", "latin america", "south america",
           "north america", "middle east", "oceania", "pacific", "caribbean", "balkans", "eastern europe", "central asia")

_NAMES = {c.lower(): c for c in INSDC_COUNTRIES} | ALIASES
# longest names first, so "Papua New Guinea" wins over "Guinea" and "Nigeria" over "Niger"
_ORDER = sorted(_NAMES, key=len, reverse=True)
# aliases that are also everyday words in lowercase text: only matched in their capitalised/upper form
_CASE_SENSITIVE = {"us": "US", "u.s.": "U.S.", "uk": "UK", "drc": "DRC", "chad": "Chad", "georgia": "Georgia", "jordan": "Jordan",
                   "turkey": "Turkey", "guinea": "Guinea", "niger": "Niger"}


def is_worldwide(country: str | None) -> bool:
    return (country or "").strip().lower() in {w.lower() for w in WORLDWIDE_WORDS} | {"any", "all"}


def search_country(country: str | None) -> str:
    """The country filter to pass to archive searches: '' for worldwide, else the country."""
    return "" if is_worldwide(country) else (country or "").strip()


def canonical_country(name: str | None) -> str | None:
    """INSDC name for a country name or alias, or None when not recognised."""
    k = re.sub(r"\s+", " ", (name or "").strip().lower())
    return _NAMES.get(k)


def countries_in(text: str | None) -> list[str]:
    """INSDC countries named in free text, in order of first mention, without overlaps."""
    t = text or ""
    low, taken, found = t.lower(), [False] * len(t), []
    for name in _ORDER:
        pat = re.escape(_CASE_SENSITIVE[name]) if name in _CASE_SENSITIVE else re.escape(name)
        src = t if name in _CASE_SENSITIVE else low
        for m in re.finditer(r"(?<![A-Za-z])" + pat + r"(?![A-Za-z])", src):
            if any(taken[m.start():m.end()]):
                continue
            taken[m.start():m.end()] = [True] * (m.end() - m.start())
            found.append((m.start(), _NAMES[name]))
    out: list[str] = []
    for _, c in sorted(found):
        if c not in out:
            out.append(c)
    return out


def _says_worldwide(text: str) -> bool:
    low = text.lower()
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) for w in WORLDWIDE_WORDS)


def _regions_in(text: str) -> list[str]:
    low = text.lower()
    hits = [r for r in REGIONS if re.search(r"(?<![a-z])" + re.escape(r) + r"(?![a-z])", low)]
    return [r for r in hits if not any(r != o and r in o for o in hits)]  # "africa" is part of "sub-saharan africa"


def _resolve_country(question: str | None, country_field: str | None) -> dict[str, Any]:
    """Country part of the target: INSDC name, "Worldwide", or a problem."""
    q, field = question or "", (country_field or "").strip()
    named = countries_in(q)
    if field:
        if is_worldwide(field):
            if named:
                return {"country": "", "source": "", "problem": f'The Country field says worldwide but the question names {", ".join(named)}. Clear one of them.'}
            return {"country": WORLDWIDE, "source": "field", "problem": None, "notice": WORLDWIDE_NOTICE}
        c = canonical_country(field)
        if not c:
            return {"country": "", "source": "", "problem": f'"{field}" is not a recognised country. Use the country name as the archive records it (e.g. "Indonesia", "Viet Nam") or "Worldwide".'}
        others = [n for n in named if n != c]
        if others:
            return {"country": "", "source": "", "problem": f'The Country field says {c} but the question names {", ".join(others)}. Make them agree.'}
        return {"country": c, "source": "field", "problem": None}
    if len(named) == 1:
        if _says_worldwide(q):
            return {"country": "", "source": "", "problem": f'The question names {named[0]} and also says worldwide. Set the Country field to the one you mean.'}
        return {"country": named[0], "source": "question", "problem": None}
    if len(named) > 1:
        return {"country": "", "source": "", "problem": f'The question names several countries ({", ".join(named)}). The pipeline studies one country at a time: set the Country field to one, or to "Worldwide".'}
    if _says_worldwide(q):
        return {"country": WORLDWIDE, "source": "question", "problem": None, "notice": WORLDWIDE_NOTICE}
    regions = _regions_in(q)
    if regions:
        return {"country": "", "source": "", "problem": f'The question names a multi-country region ({", ".join(regions)}). Set the Country field to one country (optionally with a Region inside it), or to "Worldwide".'}
    return {"country": "", "source": "", "problem": 'No target population: the question does not name a country and the Country field is empty. Enter a target country, or "Worldwide" to include all countries.'}


# ---------------------------------------------------------------------------------------------
# Subnational regions. ENA stores location as "Country: free text" (e.g. "Indonesia: West Java",
# "Indonesia: Bandung, West Java"). There is no controlled vocabulary below country level, so a
# region is matched as a normalised phrase inside the free text, never by guessing geography.
_REGION_NOISE = {"province", "provinsi", "prov", "state", "region", "district", "regency", "kabupaten", "city", "kota",
                 "county", "prefecture", "oblast", "governorate", "department", "municipality"}
_REGION_IN_Q = re.compile(r"(?:\b(?:province|state|region|district|governorate|oblast|prefecture) of\s+([A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*){0,3}))"
                          r"|(?:\b([A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*){0,3})\s+(?:[Pp]rovince|[Ss]tate|[Rr]egion|[Dd]istrict|[Gg]overnorate|[Oo]blast|[Pp]refecture)\b)")


_LEAD_WORDS = {"the", "in", "of", "from", "and", "or", "compare", "comparing", "resistance", "patterns", "what", "which", "how",
               "are", "is", "do", "does", "among", "across", "between", "within", "for", "to", "tb", "mdr", "mdr-tb", "drug"}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm_region(text: str | None) -> str:
    """Lower-case, accent-free, punctuation-free, without administrative words ("Hà Nội City" -> "ha noi")."""
    words = re.sub(r"[^\w\s]", " ", _fold(text or "").lower()).split()
    return " ".join(w for w in words if w not in _REGION_NOISE)


# ---- catalogue: WHO high-burden countries and their first-level regions (tbamr/data/subnational.json,
# generated by scripts/build_subnational.py from the WHO lists and ISO 3166-2).
@lru_cache(maxsize=1)
def catalogue() -> dict[str, Any]:
    return json.loads((Path(__file__).resolve().parents[1] / "data" / "subnational.json").read_text())


def country_catalogue() -> dict[str, Any]:
    """Country options for the scope form: WHO high-burden list, watchlist, then every other INSDC country."""
    c = catalogue()
    listed = set(c["high_burden"]) | set(c["watchlist"])
    return {"high_burden": c["high_burden"], "watchlist": c["watchlist"],
            "other": [n for n in INSDC_COUNTRIES if n not in listed], "sources": c["sources"], "notes": c["notes"]}


def regions_for(country: str | None) -> list[dict[str, Any]]:
    """First-level regions for a catalogued country (name + aliases), or [] when the country has none on file."""
    entry = catalogue()["countries"].get(canonical_country(country) or country or "")
    return entry["regions"] if entry else []


def _region_entry(country: str | None, region: str | None) -> dict[str, Any] | None:
    n = norm_region(region)
    if not n:
        return None
    return next((r for r in regions_for(country) if n in {norm_region(x) for x in [r["name"], *r["aliases"]]}), None)


def canonical_region(country: str | None, region: str | None) -> str:
    """The catalogue name for a region typed in any known form ("jawa barat" -> "West Java"); unchanged if unknown."""
    e = _region_entry(country, region)
    return e["name"] if e else (region or "").strip()


def _region_names(country: str | None, region: str | None) -> list[str]:
    e = _region_entry(country, region)
    return [e["name"], *e["aliases"]] if e else [region or ""]


def _phrase_in(needle: str, hay: str) -> bool:
    """Whole-phrase match; also accepts a spaced name written as one word ("ha noi" in "hanoi")."""
    return bool(needle and hay) and (f" {needle} " in f" {hay} " or needle.replace(" ", "") in hay.split())


def region_of(location: str | None) -> str:
    """The subnational part of an ENA location ("Indonesia: West Java" -> "West Java"), or ''."""
    loc = location or ""
    return loc.split(":", 1)[1].strip() if ":" in loc else ""


def country_of(location: str | None) -> str:
    return (location or "").split(":", 1)[0].strip()


def region_matches(target_region: str | None, location: str | None, country: str | None = None) -> bool:
    """True when the location's subnational text names the target region in any known form (catalogue name or
    alias; case-, accent- and punctuation-insensitive, whole words)."""
    hay = norm_region(region_of(location))
    return any(_phrase_in(norm_region(n), hay) for n in _region_names(country or country_of(location), target_region))


# Catalogue names too generic to detect in free text without an administrative word ("Central", "Northern"...).
_GENERIC_REGION = {"central", "eastern", "northern", "southern", "western", "north western", "north west", "coast", "gulf",
                   "delta", "plateau", "plateaux", "river", "lake", "capital", "centre", "center", "pool", "zaire", "mon", "chin",
                   "shan", "georgia", "maryland", "sangha", "ouham", "niger", "punjab"}


def regions_in_question(question: str | None, country: str = "") -> list[str]:
    """Subnational regions named in the question: with an administrative word ("West Java province", "the state of
    Lagos"), or as a catalogued region of the target country written as a proper name ("in West Java")."""
    out: list[str] = []
    q = question or ""
    for r in regions_for(country):
        for n in [r["name"], *r["aliases"]]:
            if len(n) < 4 or norm_region(n) in _GENERIC_REGION or canonical_country(n):
                continue
            if re.search(r"(?<![\w])" + re.escape(n) + r"(?![\w])", q) and r["name"] not in out:
                out.append(r["name"])
                break
    for m in _REGION_IN_Q.finditer(question or ""):
        name = (m.group(1) or m.group(2) or "").strip()
        words = name.split()
        while words and words[0].lower() in _LEAD_WORDS:  # sentence words captured by the capitalised-phrase pattern
            words.pop(0)
        name = " ".join(words)
        name = canonical_region(country, name) if name else name
        if name and canonical_country(name) is None and name.lower() != (country or "").lower() and name not in out:
            out.append(name)
    return out


def resolve_target(question: str | None, country_field: str | None, region_field: str | None = None) -> dict[str, Any]:
    """Decide the study's target population: a country, optionally a region inside it, or worldwide.

    Returns {"country": INSDC name | "Worldwide" | "", "region": free text | "", "source": "field" | "question" | "",
    "region_source": "field" | "question" | "", "problem": None or a message saying exactly what to fix,
    "notice": optional run-time notice}.
    """
    field, region = (country_field or "").strip(), (region_field or "").strip()
    if ":" in field:  # ENA's own format typed into the Country field: "Indonesia: West Java"
        field, inline = field.split(":", 1)
        field, inline = field.strip(), inline.strip()
        if region and inline and norm_region(region) != norm_region(inline):
            return {"country": "", "region": "", "source": "", "region_source": "", "problem": f'The Country field names region "{inline}" but the Region field says "{region}". Keep one.'}
        region = region or inline
    t = _resolve_country(question, field)
    t.setdefault("notice", None)
    t["region"], t["region_source"] = "", ""
    asked = regions_in_question(question, t["country"])
    if t["problem"]:
        if not field and (region or asked) and t["problem"].startswith("No target population"):
            where = region or ", ".join(asked)
            t["problem"] = f'The scope names {where} but no country. Set the Country field to the country it belongs to.'
        return t
    if region:
        region = canonical_region(t["country"], region)
        if t["country"] == WORLDWIDE:
            return {**t, "country": "", "source": "", "notice": None, "problem": f'Region "{region}" needs a single country. Set the Country field to the country it belongs to.'}
        others = [a for a in asked if norm_region(a) != norm_region(region)]
        if others:
            return {**t, "country": "", "source": "", "problem": f'The Region field says "{region}" but the question names {", ".join(others)}. Make them agree.'}
        return {**t, "region": region, "region_source": "field"}
    if asked:
        if t["country"] == WORLDWIDE:
            return {**t, "country": "", "source": "", "notice": None, "problem": f'The question names {", ".join(asked)} but the scope is worldwide. Set the Country field to the country it belongs to.'}
        if len(asked) > 1:  # a within-country comparison: target the whole country, the report breaks down by region
            return {**t, "regions_named": asked,
                    "note": f'Targeting all of {t["country"]}. The question names several regions ({", ".join(asked)}); the report breaks results down by region so they can be compared.'}
        return {**t, "region": asked[0], "region_source": "question"}
    return t


def place_label(location: str | None, country: str | None = None) -> str:
    """Region label for reporting: the catalogue region the location names, else the location's own text."""
    raw = region_of(location)
    if not raw:
        return ""
    hay = norm_region(raw)
    for r in regions_for(country or country_of(location)):
        if any(_phrase_in(norm_region(n), hay) for n in [r["name"], *r["aliases"]]):
            return r["name"]
    return raw
