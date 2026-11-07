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

import re
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


def resolve_target(question: str | None, country_field: str | None) -> dict[str, Any]:
    """Decide the study's target population.

    Returns {"country": INSDC name | "Worldwide" | "", "source": "field" | "question" | "",
    "problem": None or a message telling the researcher exactly what to fix}.
    """
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
        return {"country": "", "source": "", "problem": f'The question names a region ({", ".join(regions)}) but archive records can only be filtered by country. Set the Country field to one country, or to "Worldwide".'}
    return {"country": "", "source": "", "problem": 'No target population: the question does not name a country and the Country field is empty. Enter a target country, or "Worldwide" to include all countries.'}
