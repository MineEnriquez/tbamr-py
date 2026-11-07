"""Build tbamr/data/subnational.json: TB high-burden countries and their first-level regions.

Run with pycountry available (it is NOT a runtime dependency; the app only reads the JSON):

    python -m venv /tmp/geo && /tmp/geo/bin/pip install pycountry
    /tmp/geo/bin/python scripts/build_subnational.py

Sources
- Country lists: WHO global lists of high burden countries for TB, 2021-2025 (30 countries), and the
  WHO global TB watchlist (countries that transitioned out of the list in 2021).
  https://www.who.int/news/item/17-06-2021-who-releases-new-global-lists-of-high-burden-countries-for-tb-hiv-associated-tb-and-drug-resistant-tb
- Regions: ISO 3166-2 first-level subdivisions as packaged by pycountry. ISO names are often in the
  local language; where ENA submitters commonly use an English name, that name is shown and the ISO
  name is kept as an alias so both match archive records.

Known gaps (stated in the file's "notes"): ISO 3166-2 can lag administrative reforms (e.g. Viet Nam's
2025 provincial merger is not reflected). Archive records mostly predate such reforms, so the older
names are the useful ones for matching.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pycountry

# INSDC country name (what ENA records) -> ISO alpha-2
HIGH_BURDEN = {
    "Angola": "AO", "Bangladesh": "BD", "Brazil": "BR", "Central African Republic": "CF", "China": "CN",
    "Republic of the Congo": "CG", "North Korea": "KP", "Democratic Republic of the Congo": "CD", "Ethiopia": "ET",
    "Gabon": "GA", "India": "IN", "Indonesia": "ID", "Kenya": "KE", "Lesotho": "LS", "Liberia": "LR", "Mongolia": "MN",
    "Mozambique": "MZ", "Myanmar": "MM", "Namibia": "NA", "Nigeria": "NG", "Pakistan": "PK", "Papua New Guinea": "PG",
    "Philippines": "PH", "Sierra Leone": "SL", "South Africa": "ZA", "Thailand": "TH", "Uganda": "UG", "Tanzania": "TZ",
    "Viet Nam": "VN", "Zambia": "ZM",
}
WATCHLIST = {"Cambodia": "KH", "Russia": "RU", "Zimbabwe": "ZW"}

# Countries whose ISO top level is a geographic grouping: use the level below instead.
USE_CHILD_LEVEL = {"ID", "UG"}
# Countries whose ISO names carry diacritics that English-language records usually drop.
ASCII_DISPLAY = {"IN", "MN"}

# Display-name overrides (ISO code -> English name commonly used in records). The ISO name becomes an alias.
ENGLISH = {
    # Indonesia
    "ID-JB": "West Java", "ID-JT": "Central Java", "ID-JI": "East Java", "ID-JK": "Jakarta", "ID-YO": "Yogyakarta",
    "ID-KB": "West Kalimantan", "ID-KT": "Central Kalimantan", "ID-KS": "South Kalimantan", "ID-KI": "East Kalimantan",
    "ID-KU": "North Kalimantan", "ID-SA": "North Sulawesi", "ID-ST": "Central Sulawesi", "ID-SN": "South Sulawesi",
    "ID-SG": "Southeast Sulawesi", "ID-SR": "West Sulawesi", "ID-SU": "North Sumatra", "ID-SB": "West Sumatra",
    "ID-SS": "South Sumatra", "ID-NB": "West Nusa Tenggara", "ID-NT": "East Nusa Tenggara", "ID-MU": "North Maluku",
    "ID-PB": "West Papua", "ID-PD": "Southwest Papua", "ID-PE": "Highland Papua", "ID-PS": "South Papua",
    "ID-PT": "Central Papua", "ID-BB": "Bangka Belitung Islands", "ID-KR": "Riau Islands",
    # China (autonomous regions and SARs; other provinces just lose the Sheng/Shi suffix)
    "CN-GX": "Guangxi", "CN-NM": "Inner Mongolia", "CN-NX": "Ningxia", "CN-XJ": "Xinjiang", "CN-XZ": "Tibet",
    "CN-HK": "Hong Kong", "CN-MO": "Macau",
    # Ethiopia
    "ET-AM": "Amhara", "ET-TI": "Tigray", "ET-BE": "Benishangul-Gumuz", "ET-GA": "Gambela", "ET-HA": "Harari",
    "ET-SN": "Southern Nations, Nationalities and Peoples (SNNPR)", "ET-SW": "South West Ethiopia Peoples",
    # Mozambique: ISO has two "Maputo" entries
    "MZ-MPM": "Maputo (city)", "MZ-L": "Maputo (province)",
    # Namibia, South Africa, Thailand, North Korea
    "NA-KA": "ǁKaras", "ZA-KZN": "KwaZulu-Natal", "TH-10": "Bangkok", "KP-01": "Pyongyang",
    # Philippines (current name of the former ARMM)
    "PH-14": "Bangsamoro (BARMM)",
    # Cambodia: ISO romanisation differs from the usual English spellings
    "KH-2": "Battambang", "KH-1": "Banteay Meanchey", "KH-3": "Kampong Cham", "KH-5": "Kampong Speu",
    "KH-6": "Kampong Thom", "KH-8": "Kandal", "KH-9": "Koh Kong", "KH-10": "Kratie", "KH-11": "Mondulkiri",
    "KH-22": "Oddar Meanchey", "KH-15": "Pursat", "KH-14": "Prey Veng", "KH-16": "Ratanakiri", "KH-17": "Siem Reap",
    "KH-19": "Stung Treng", "KH-20": "Svay Rieng", "KH-21": "Takeo", "KH-25": "Tboung Khmum", "KH-23": "Kep",
    "KH-18": "Preah Sihanouk",
    # Russia (watchlist): the two federal cities by their English names; others keep ISO transliteration
    "RU-MOW": "Moscow", "RU-SPE": "Saint Petersburg",
}
# Extra aliases (ISO code -> other names seen in records)
ALIASES = {
    "ID-JK": ["DKI Jakarta", "Jakarta Raya"], "ID-YO": ["DI Yogyakarta", "Jogjakarta"], "ID-AC": ["Nanggroe Aceh Darussalam"],
    "VN-HN": ["Hanoi"], "VN-SG": ["Ho Chi Minh City", "Saigon"], "VN-HP": ["Haiphong"], "VN-DN": ["Da Nang", "Danang"],
    "IN-DL": ["New Delhi", "NCT of Delhi"], "IN-OD": ["Orissa"], "IN-UK": ["Uttaranchal"],
    "ET-AA": ["Addis Abeba"], "ET-SN": ["SNNPR", "SNNP"], "PH-00": ["Metro Manila", "NCR"], "PH-14": ["ARMM", "Bangsamoro"],
    "MM-06": ["Rangoon"], "MM-07": ["Irrawaddy"], "MM-18": ["Naypyidaw", "Nay Pyi Taw"],
    "KE-30": ["Nairobi"], "TH-10": ["Krung Thep", "Bangkok Metropolis"], "NA-KA": ["Karas"],
    "BD-C": ["Dacca"], "BD-B": ["Chittagong"], "BD-A": ["Barisal"],
}
# First-level units created after the ISO data was last updated (name, aliases).
EXTRA = {
    "ET": [("South Ethiopia", ["South Ethiopia Regional State"]), ("Central Ethiopia", ["Central Ethiopia Regional State"])],
}
CN_SUFFIXES = (" Sheng", " Shi", " Zizhiqu", " Huizu", " Zhuangzu", " Weiwu'er", " Tebiexingzhengqu")


def ascii_fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def regions_for(alpha2: str) -> list[dict]:
    subs = list(pycountry.subdivisions.get(country_code=alpha2) or [])
    level = [s for s in subs if (s.parent_code is not None) == (alpha2 in USE_CHILD_LEVEL)]
    if alpha2 in USE_CHILD_LEVEL:  # keep only direct children of the top level
        top = {s.code for s in subs if s.parent_code is None}
        level = [s for s in level if s.parent_code in top]
    out = []
    for s in level:
        iso = s.name
        name = ENGLISH.get(s.code)
        if not name:
            name = iso
            if alpha2 == "CN":
                for suf in CN_SUFFIXES:
                    name = name.replace(suf, "")
            if alpha2 in ASCII_DISPLAY:
                name = ascii_fold(name)
        aliases = [a for a in [iso, ascii_fold(iso), *ALIASES.get(s.code, [])] if a and a != name]
        out.append({"name": name, "code": s.code, "type": s.type, "aliases": sorted(set(aliases))})
    for name, al in EXTRA.get(alpha2, []):
        out.append({"name": name, "code": None, "type": "Region", "aliases": al, "note": "Created after the ISO 3166-2 data was last updated."})
    out.sort(key=lambda r: ascii_fold(r["name"]).lower())
    return out


def main() -> None:
    countries = {}
    for name, a2 in {**HIGH_BURDEN, **WATCHLIST}.items():
        countries[name] = {"iso": a2, "regions": regions_for(a2)}
    data = {
        "high_burden": sorted(HIGH_BURDEN),
        "watchlist": sorted(WATCHLIST),
        "countries": countries,
        "sources": {
            "lists": "WHO global lists of high burden countries for TB, 2021-2025, and the global TB watchlist "
                     "(https://www.who.int/news/item/17-06-2021-who-releases-new-global-lists-of-high-burden-countries-for-tb-hiv-associated-tb-and-drug-resistant-tb)",
            "regions": f"ISO 3166-2 first-level subdivisions via pycountry {pycountry.__version__ if hasattr(pycountry, '__version__') else ''}".strip(),
        },
        "notes": [
            "Region display names use the English form common in archive records where it differs from ISO; ISO names are kept as aliases.",
            "ISO 3166-2 can lag administrative reforms (e.g. Viet Nam's 2025 provincial merger is not reflected); older names are the ones archive records use.",
            "WHO publishes new high-burden lists every five years; update HIGH_BURDEN when the list after 2021-2025 is released.",
        ],
    }
    out = Path(__file__).resolve().parents[1] / "tbamr" / "data" / "subnational.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {out} · {len(countries)} countries · {sum(len(c['regions']) for c in countries.values())} regions")


if __name__ == "__main__":
    main()
