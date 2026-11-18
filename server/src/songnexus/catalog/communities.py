"""The Around you directory: campuses and cities listeners can join, built from Wikidata.

``songnexus fetch-communities`` runs the queries below against the Wikidata Query
Service (CC0, already in the source registry) and writes ``communities.json``
next to this module. The file is checked in and loaded at startup; nothing
queries Wikidata at serving time.

What goes in:

* **Campuses**: the largest US universities by student count (P2196) that have a
  campus people live on, plus a short list of well-known universities abroad.
  Online-only and for-profit institutions, community colleges and university
  systems are left out (a reviewed exclusion list catches what the types miss).
* **Cities**: every campus's city, US cities over 100,000 people, and national
  capitals elsewhere.

A campus's city is the human settlement among its headquarters (P159),
located-in (P131) and location (P276) values, the most populous when several
apply. A few short names Wikidata lacks are filled from a reviewed table.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from songnexus.catalog.wikidata.fetch import WikidataClient, bindings
from songnexus.core.community import Community, Directory, Kind

log = logging.getLogger(__name__)

DIRECTORY_FILE = "communities.json"
DIRECTORY_PATH = Path(__file__).with_name(DIRECTORY_FILE)
FORMAT_VERSION = 1

US_CAMPUSES = 150
CANDIDATES = 320
MIN_CITY_POPULATION = 100_000
DETAIL_BATCH = 40

_ENTITY = "http://www.wikidata.org/entity/"

# University types the candidate query starts from: university, public, private,
# research, public research, and private not-for-profit institution.
UNIVERSITY_TYPES = ("Q3918", "Q875538", "Q902104", "Q15936437", "Q62078547", "Q23002054")
# Types that rule an institution out: for-profit institution, state university system,
# public company (a listed, so for-profit, operator).
EXCLUDED_TYPES = frozenset({"Q23002052", "Q1075106", "Q891723"})

# Reviewed exclusions the types miss (checked 2026-11-16), with the reason.
EXCLUDED: dict[str, str] = {
    "Q762266": "City University of New York: a system; its colleges are listed on their own",
    "Q7987876": "Western Governors University: online only",
    "Q3445256": "Southern New Hampshire University: mostly online",
    "Q14692455": "University of Maryland Global Campus: online",
    "Q620973": "University of the People: online only",
    "Q6099948": "Ivy Tech Community College: community college",
    "Q2075365": "University of Puerto Rico: a system of campuses",
    "Q3629946": "Austin Community College District: community college",
    "Q7568637": "South Texas College: two-year college",
    "Q5461608": "Florida State College at Jacksonville: two-year college",
    "Q1568237": "National University: mostly online",
    "Q7896695": "University of the Cumberlands: mostly online",
    "Q4805015": "University of Arizona Global Campus: online",
    "Q7622587": "Strayer University: for-profit, mostly online",
    "Q6383859": "Keiser University: for-profit",
    "Q4744166": "American InterContinental University: for-profit, mostly online",
    "Q5322728": "ECPI University: for-profit",
    "Q4570025": "Grand Canyon University: for-profit operator, mostly online",
    "Q1889100": "University of Phoenix: for-profit, mostly online",
    "Q7961486": "Walden University: for-profit, online",
    "Q572430": "Capella University: for-profit, online",
    "Q5148968": "Colorado Technical University: for-profit, mostly online",
    "Q5508130": "Full Sail University: for-profit",
}

# Well-known universities outside the US (Wikidata items, labels checked 2026-11-16).
INTERNATIONAL = (
    "Q180865",  # University of Toronto
    "Q201492",  # McGill University
    "Q391028",  # University of British Columbia
    "Q1049470",  # University of Waterloo
    "Q34433",  # University of Oxford
    "Q35794",  # University of Cambridge
    "Q189022",  # Imperial College London
    "Q245247",  # King's College London
    "Q160302",  # University of Edinburgh
    "Q214341",  # University of Amsterdam
    "Q11942",  # ETH Zurich
    "Q157808",  # Technical University of Munich
    "Q7842",  # University of Tokyo
    "Q39913",  # Seoul National University
    "Q738236",  # National University of Singapore
    "Q319078",  # University of Melbourne
    "Q487556",  # University of Sydney
    "Q222738",  # National Autonomous University of Mexico
    "Q835960",  # University of São Paulo
)

# Short names in common use that Wikidata lacks (P1813), reviewed.
SHORT_NAMES: dict[str, str] = {
    "Q838330": "UW–Madison",
    "Q457281": "UIUC",
    "Q739627": "Penn State",
    "Q143451": "UCF",
    "Q49212": "Texas A&M",
    "Q238101": "UMN",
    "Q309331": "Ohio State",
    "Q230492": "Michigan",
    "Q49210": "NYU",
    "Q501758": "UF",
    "Q4614": "USC",
    "Q1065809": "FIU",
    "Q500606": "USF",
    "Q503419": "UArizona",
    "Q270222": "Michigan State",
    "Q861548": "FSU",
    "Q1079140": "IU Bloomington",
    "Q622664": "UC San Diego",
    "Q49213": "UT Austin",
    "Q761534": "UGA",
    "Q129421": "UC Davis",
    "Q736674": "CU Boulder",
    "Q868421": "UC Irvine",
    "Q1132346": "NC State",
    "Q1521725": "LSU",
    "Q955764": "UIC",
    "Q235034": "Pitt",
    "Q15142": "UMass Amherst",
    "Q192334": "UNC Chapel Hill",
    "Q49110": "BU",
    "Q65379": "Virginia Tech",
    "Q49117": "Penn",
    "Q193727": "Johns Hopkins",
    "Q13371": "Harvard",
    "Q432637": "GW",
    "Q1433199": "IUPUI",
    "Q1781394": "UT Dallas",
    "Q34433": "Oxford",
    "Q35794": "Cambridge",
    "Q180865": "U of T",
    "Q391028": "UBC",
    "Q738236": "NUS",
    "Q222738": "UNAM",
    "Q835960": "USP",
    "Q157808": "TUM",
    "Q189022": "Imperial",
    "Q245247": "King's",
}


def campus_candidates_query(limit: int = CANDIDATES) -> str:
    """Returns the query for US universities, largest student body first."""
    types = " ".join(f"wd:{t}" for t in UNIVERSITY_TYPES)
    return (
        "SELECT ?item (MAX(?students) AS ?maxStudents) WHERE {\n"
        f"  VALUES ?type {{ {types} }}\n"
        "  ?item wdt:P31 ?type ; wdt:P17 wd:Q30 ; wdt:P2196 ?students .\n"
        "}\n"
        "GROUP BY ?item\n"
        "ORDER BY DESC(?maxStudents)\n"
        f"LIMIT {limit}"
    )


def campus_details_query(items: Iterable[str]) -> str:
    """Returns the query for labels, short names, websites, types and countries."""
    values = " ".join(f"wd:{q}" for q in sorted(items))
    return (
        "SELECT ?item ?label ?short ?website ?type ?country ?students WHERE {\n"
        f"  VALUES ?item {{ {values} }}\n"
        '  ?item rdfs:label ?label . FILTER(LANG(?label) = "en")\n'
        '  OPTIONAL { ?item wdt:P1813 ?short . FILTER(LANG(?short) = "en") }\n'
        "  OPTIONAL { ?item wdt:P856 ?website }\n"
        "  OPTIONAL { ?item wdt:P31 ?type }\n"
        "  OPTIONAL { ?item wdt:P17 ?c . ?c wdt:P297 ?country }\n"
        "  OPTIONAL { ?item wdt:P2196 ?students }\n"
        "}"
    )


def campus_places_query(items: Iterable[str]) -> str:
    """Returns the query for the places each campus is in, with types, population and region.

    Transitive paths time out on the public endpoint, so the region comes from at
    most two located-in hops, and settlements are told apart by type in Python.
    """
    values = " ".join(f"wd:{q}" for q in sorted(items))
    return (
        "SELECT ?item ?prop ?place ?placeLabel ?typeLabel ?population ?region ?region2 ?country "
        "WHERE {\n"
        f"  VALUES ?item {{ {values} }}\n"
        "  VALUES ?prop { wdt:P159 wdt:P131 wdt:P276 }\n"
        "  ?item ?prop ?place .\n"
        f"{_PLACE_FACTS}"
        "}"
    )


_PLACE_FACTS = (
    '  ?place rdfs:label ?placeLabel . FILTER(LANG(?placeLabel) = "en")\n'
    "  OPTIONAL { ?place wdt:P31 ?t . ?t rdfs:label ?typeLabel . "
    'FILTER(LANG(?typeLabel) = "en") }\n'
    "  OPTIONAL { ?place wdt:P1082 ?population }\n"
    "  OPTIONAL { ?place wdt:P131 ?a . ?a wdt:P300 ?region }\n"
    "  OPTIONAL { ?place wdt:P131 ?a2 . ?a2 wdt:P131 ?b . ?b wdt:P300 ?region2 }\n"
    "  OPTIONAL { ?place wdt:P17 ?c . ?c wdt:P297 ?country }\n"
)

# Type labels that make a place a city, town or similar settlement (and not a
# county, township, state or country).
_SETTLEMENT = re.compile(
    r"city|town|village|municipal|census-designated|capital|metropolis|settlement|borough|"
    r"commune|hamlet|unincorporated community",
    re.IGNORECASE,
)
# "city in the United States" is a settlement; "state of the United States" is not.
_NOT_SETTLEMENT = re.compile(
    r"township|county|\bstates? of\b|^state\b|province|\bcountry\b|sovereign", re.IGNORECASE
)


def is_settlement(type_labels: Iterable[str]) -> bool:
    """True when any type label names a settlement ("city of the United States")."""
    return any(_SETTLEMENT.search(t) and not _NOT_SETTLEMENT.search(t) for t in type_labels)


def us_cities_query(min_population: int = MIN_CITY_POPULATION) -> str:
    """Returns the query for US cities above a population."""
    return (
        "SELECT ?place ?placeLabel ?population ?region ?region2 WHERE {\n"
        "  ?place wdt:P31 wd:Q1093829 ; wdt:P1082 ?population .\n"
        f"  FILTER(?population > {min_population})\n"
        '  ?place rdfs:label ?placeLabel . FILTER(LANG(?placeLabel) = "en")\n'
        "  OPTIONAL { ?place wdt:P131 ?a . ?a wdt:P300 ?region }\n"
        "  OPTIONAL { ?place wdt:P131 ?a2 . ?a2 wdt:P131 ?b . ?b wdt:P300 ?region2 }\n"
        "}"
    )


CAPITALS_QUERY = """\
SELECT ?place ?placeLabel ?population ?country WHERE {
  ?state wdt:P31 wd:Q3624078 ; wdt:P36 ?place ; wdt:P297 ?country .
  FILTER NOT EXISTS { ?state wdt:P576 ?dissolved }
  FILTER(?country != "US")
  ?place rdfs:label ?placeLabel . FILTER(LANG(?placeLabel) = "en")
  OPTIONAL { ?place wdt:P1082 ?population }
}"""


def slugify(*parts: str) -> str:
    """Returns a lowercase ASCII slug ("University of Wisconsin–Madison" -> "university-of-...")."""
    text = re.sub(r"[\u2010-\u2015]", "-", " ".join(p for p in parts if p))
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower().replace("&", " and ")).strip("-")


def _qid(value: str) -> str:
    return value.removeprefix(_ENTITY)


def _number(value: str | None) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def domain(url: str) -> str:
    """Returns a website's domain without ``www.`` ("https://www.wisc.edu/" -> "wisc.edu")."""
    host = urlparse(url).hostname or ""
    return host.removeprefix("www.")


def _pick_region(regions: Iterable[str], country: str) -> str:
    """The subdivision code: for the US the state; elsewhere only when there is exactly one."""
    codes = sorted({r for r in regions if r.startswith(f"{country}-")})
    if country == "US":
        states = [c for c in codes if len(c) == len("US-WI")]
        return states[0] if states else ""
    return codes[0] if len(codes) == 1 else ""


def city_id(name: str, country: str, region: str) -> str:
    """Returns a city's community ID: ``madison-us-wi`` in the US, ``london-gb`` elsewhere."""
    if country == "US" and region:
        return slugify(name, region)
    return slugify(name, country)


class _Place:
    def __init__(self, qid: str, name: str) -> None:
        self.qid = qid
        self.name = name
        self.population = 0
        self.regions: set[str] = set()
        self.country = ""
        self.types: set[str] = set()


def _places(rows: Iterable[dict[str, str]], key: str = "place") -> dict[str, _Place]:
    places: dict[str, _Place] = {}
    for row in rows:
        qid = _qid(row[key])
        place = places.setdefault(qid, _Place(qid, row.get(f"{key}Label", "")))
        place.population = max(place.population, _number(row.get("population")))
        for key_name in ("region", "region2"):
            if row.get(key_name):
                place.regions.add(row[key_name])
        if row.get("country"):
            place.country = row["country"]
        if row.get("typeLabel"):
            place.types.add(row["typeLabel"])
    return places


def build_directory(  # noqa: PLR0912, PLR0915 - one linear pipeline, read top to bottom
    client: WikidataClient, *, us_campuses: int = US_CAMPUSES
) -> dict[str, Any]:
    """Runs the queries and returns the directory document (see the module docstring).

    Raises:
        WikidataError: A query failed permanently.
    """
    ranked = [
        (_qid(r["item"]), _number(r.get("maxStudents")))
        for r in bindings(client.sparql(campus_candidates_query()))
    ]
    students = dict(ranked)
    wanted = [q for q, _ in ranked if q not in EXCLUDED] + list(INTERNATIONAL)

    details: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"types": set(), "short": set(), "website": set(), "students": 0}
    )
    places_of: dict[str, list[tuple[str, str]]] = defaultdict(list)
    place_rows: list[dict[str, str]] = []
    for start in range(0, len(wanted), DETAIL_BATCH):
        batch = wanted[start : start + DETAIL_BATCH]
        for row in bindings(client.sparql(campus_details_query(batch))):
            entry = details[_qid(row["item"])]
            entry["label"] = row["label"]
            entry["country"] = row.get("country", entry.get("country", ""))
            entry["students"] = max(entry["students"], _number(row.get("students")))
            for field_name, key in (("type", "types"), ("short", "short"), ("website", "website")):
                if row.get(field_name):
                    entry[key].add(_qid(row[field_name]))
        for row in bindings(client.sparql(campus_places_query(batch))):
            prop = row["prop"].rsplit("/", 1)[-1]  # wdt:P159 -> P159
            places_of[_qid(row["item"])].append((prop, _qid(row["place"])))
            place_rows.append(row)
    places = _places(place_rows)

    def campus_city(qid: str) -> _Place | None:
        # Headquarters and located-in first, the most populous; "location" last, as it
        # is sometimes a branch campus abroad.
        for props in (("P159", "P131"), ("P276",)):
            options = [
                places[p]
                for kind, p in places_of[qid]
                if kind in props and is_settlement(places[p].types)
            ]
            if options:
                return max(options, key=lambda p: (p.population, p.name))
        return None

    cities: dict[str, dict[str, Any]] = {}

    def add_city(place: _Place, country: str) -> str:
        region = _pick_region(place.regions, country)
        cid = city_id(place.name, country, region)
        if cid in cities and cities[cid]["wikidata"] != place.qid:
            cid = f"{cid}-{place.qid.lower()}"
        cities.setdefault(
            cid,
            {
                "id": cid,
                "kind": Kind.CITY.value,
                "name": place.name,
                "shortName": place.name,
                "city": place.name,
                "region": region,
                "country": country,
                "website": "",
                "wikidata": place.qid,
                "size": place.population,
            },
        )
        return cid

    campuses: list[dict[str, Any]] = []
    us_count = 0
    for qid in wanted:
        info: dict[str, Any] | None = details.get(qid)
        if info is None or "label" not in info or info["types"] & EXCLUDED_TYPES:
            continue
        name = str(info["label"])
        if re.search(r"community college|college district", name, re.IGNORECASE):
            continue
        international = qid in INTERNATIONAL
        country = str(info.get("country") or "")
        if not international and (country != "US" or us_count >= us_campuses):
            continue
        place = campus_city(qid)
        if place is None or not country:
            log.info("campus skipped: no city", extra={"item": qid})
            continue
        if not international:
            us_count += 1
        short = SHORT_NAMES.get(qid) or min(info["short"], key=len, default="") or name
        # The home domain: .edu in the US, then https, then the shortest.
        websites = sorted(
            info["website"],
            key=lambda u: (
                country == "US" and not domain(u).endswith(".edu"),
                not u.startswith("https"),
                len(u),
                u,
            ),
        )
        cid = add_city(place, country)
        campuses.append(
            {
                "id": slugify(name),
                "kind": Kind.CAMPUS.value,
                "name": name,
                "shortName": short,
                "city": place.name,
                "region": cities[cid]["region"],
                "country": country,
                "website": domain(websites[0]) if websites else "",
                "wikidata": qid,
                "cityId": cid,
                "size": students.get(qid) or info["students"],
            }
        )

    us = _places(bindings(client.sparql(us_cities_query())))
    for place in us.values():
        add_city(place, "US")
    capitals = _places(bindings(client.sparql(CAPITALS_QUERY)))
    for place in capitals.values():
        if place.country:
            add_city(place, place.country)

    seen: set[str] = set()
    for campus in campuses:  # slugs must be unique; the larger campus keeps the plain one
        if campus["id"] in seen:
            campus["id"] = f"{campus['id']}-{campus['wikidata'].lower()}"
        seen.add(campus["id"])
    entries = sorted(campuses, key=lambda c: c["id"]) + sorted(
        cities.values(), key=lambda c: c["id"]
    )
    return {
        "formatVersion": FORMAT_VERSION,
        "generatedAt": datetime.now(UTC).date().isoformat(),
        "source": "wikidata",
        "license": "CC0-1.0",
        "sample": False,
        "communities": entries,
    }


def write_directory(document: dict[str, Any], path: Path = DIRECTORY_PATH) -> dict[str, Any]:
    """Writes the directory as stable, reviewable JSON and returns counts."""
    text = json.dumps(document, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    kinds: dict[str, int] = defaultdict(int)
    for entry in document["communities"]:
        kinds[entry["kind"]] += 1
    return {"written": str(path), "bytes": len(text.encode()), **dict(kinds)}


def parse_directory(document: dict[str, Any]) -> Directory:
    """Builds the in-memory directory from a document."""
    communities = tuple(
        Community(
            id=e["id"],
            kind=Kind(e["kind"]),
            name=e["name"],
            short_name=e.get("shortName") or e["name"],
            city=e.get("city", ""),
            region=e.get("region", ""),
            country=e.get("country", ""),
            website=e.get("website", ""),
            wikidata=e.get("wikidata", ""),
            city_id=e.get("cityId"),
            size=int(e.get("size", 0)),
            synthetic=bool(e.get("synthetic", False)),
        )
        for e in document["communities"]
    )
    digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()[:12]
    return Directory(communities, version=digest)


@lru_cache(maxsize=1)
def load_directory() -> Directory:
    """Returns the checked-in directory (read once per process)."""
    text = resources.files("songnexus.catalog").joinpath(DIRECTORY_FILE).read_text("utf-8")
    document = json.loads(text)
    demo = resources.files("songnexus.catalog").joinpath("universities.synthetic.json")
    document["communities"].extend(json.loads(demo.read_text("utf-8"))["communities"])
    return parse_directory(document)


def campus_ids(directory: Directory) -> Sequence[str]:
    """Returns every campus ID (for help text and tests)."""
    return [c.id for c in directory.communities if c.kind is Kind.CAMPUS]
