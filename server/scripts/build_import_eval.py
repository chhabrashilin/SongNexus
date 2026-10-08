"""Builds data/eval/import_match_cases.json, the labeled set behind the import precision gate.

Run from server/:  uv run python scripts/build_import_eval.py

Deterministic. Ground truth comes from the 107 seed artists, whose MusicBrainz
IDs were resolved or pinned and verified by a person (data/seeds). Rules:

- exact: the seed name as written.
- folded: lowercase, accents removed ("beyonce").
- typo: two adjacent letters swapped in the longest word (only words of 6+ letters).
- alias: up to one alias per seed in another script (MusicBrainz aliases).
- homonym: a name two or more catalog artists share (computed from the canonical
  catalog, exactly as ingested); must never be auto-matched.
- near_miss: real acts not in our catalog whose names are a letter or two from
  one that is ("The Beetles"); must never match. The hardest precision cases.
- absent: well-known artists not in our catalog, plus invented names; must never match.

It is generated, not sampled from real exports, so it tests the matcher's rules
rather than the distribution of real files. Extend it with labeled names from
real (consented) exports when available.
"""

from __future__ import annotations

import gzip
import json
import unicodedata
from collections import defaultdict
from pathlib import Path

from songnexus.catalog.canonicalize import build_batch
from songnexus.catalog.musicbrainz.snapshot import read_snapshot
from songnexus.core.text import normalize

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "data" / "seeds" / "seed_artists.lock.json"
SNAPSHOT = ROOT / "data" / "samples" / "musicbrainz_snapshot.jsonl.gz"
OUT = ROOT / "data" / "eval" / "import_match_cases.json"

# Real artists we deliberately did not fetch (checked against the snapshot below).
ABSENT_REAL = [
    "Sabrina Carpenter",
    "Chappell Roan",
    "Mitski",
    "Phoebe Bridgers",
    "Hozier",
    "Fred again..",
    "Peso Pluma",
    "Ateez",
    "Stray Kids",
    "Fujii Kaze",
    "Rema",
    "Ayra Starr",
    "Asake",
    "Arooj Aftab",
    "Rauw Alejandro",
    "Mon Laferte",
    "Clairo",
    "Boygenius",
    "Laufey",
    "Zach Bryan",
]
# Real acts one or two letters from a catalog artist (tribute bands, soundalikes).
NEAR_MISS = ["The Beetles", "Nirvanna", "Daft Punks", "The Weekend", "Bjork Guðmundsdóttir Band"]
INVENTED = [
    "The Velvet Nonexistents",
    "Moonlight Tractor Club",
    "Sapphire Lunch Society",
    "DJ Quietcorner",
    "Orbiting Teaspoons",
    "Cassette Weather",
    "Lilac Paper Planes",
    "Northbound Marmalade",
    "The Gentle Avalanches",
    "Neon Porcupine",
    "Kettle Drum Diaries",
    "Velvet Snowplow",
    "Midnight Cartographers",
    "Paper Lantern Riot",
    "Echo Pancake",
    "The Sleepy Lighthouses",
    "Granite Lullaby",
    "Saffron Satellite",
    "Hollow Harmonica Club",
    "Static Orchard",
]


def fold(text: str) -> str:
    """Lowercases and removes accents, as a person typing quickly might."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def typo(name: str) -> str | None:
    """Swaps two adjacent letters in the longest word (6+ letters), or returns None."""
    words = name.split()
    longest = max(range(len(words)), key=lambda i: (len(words[i]), -i))
    word = words[longest]
    if len(word) < 6 or not word.isalpha():  # noqa: PLR2004
        return None
    i = len(word) // 2 - 1
    swapped = word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    if swapped == word:
        return None
    words[longest] = swapped
    return " ".join(words)


def is_other_script(alias: str, name: str) -> bool:
    """True when the alias is written in a script the name doesn't use."""

    def script(text: str) -> set[str]:
        return {unicodedata.name(c, "?").split()[0] for c in text if c.isalpha()}

    return bool(script(alias)) and script(alias).isdisjoint(script(name))


def build_cases() -> list[dict[str, object]]:
    """Returns the labeled cases, in a stable order."""
    seeds = json.loads(SEEDS.read_text(encoding="utf-8"))["artists"]
    aliases: dict[str, list[str]] = defaultdict(list)
    with gzip.open(SNAPSHOT, "rt", encoding="utf-8") as fh:
        for line in fh:
            record = json.loads(line)
            body = record["body"]
            if record["kind"] in {"artist", "artist_profile"}:
                aliases[body["id"]].extend(a["name"] for a in body.get("aliases", []))

    # The canonical catalog, exactly as ingestion builds it: homonyms are decided
    # here, not from raw references (some of which ingestion deliberately drops).
    catalog: dict[str, list[str]] = defaultdict(list)
    for artist in build_batch(read_snapshot(SNAPSHOT)).artists.values():
        catalog[artist["normalized_name"]].append(artist["name"])

    cases: list[dict[str, object]] = []

    def add(query: str, category: str, mbid: str | None) -> None:
        if all(c["query"] != query for c in cases):
            cases.append({"query": query, "category": category, "mbid": mbid})

    for seed in seeds:
        name, mbid = seed["name"], seed["mbid"]
        homonym = len(catalog[normalize(name)]) > 1
        add(name, "homonym" if homonym else "exact", None if homonym else mbid)
        if fold(name) != name and not homonym:
            add(fold(name), "folded", mbid)
        if (variant := typo(name)) and not homonym:
            add(variant, "typo", mbid)
        other = [a for a in aliases[mbid] if is_other_script(a, name)]
        if other and not homonym:
            add(sorted(other)[0], "alias", mbid)
    for name, category in negative_names(catalog):
        add(name, category, None)
    return cases


def negative_names(catalog: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Returns (name, category) pairs that must never be matched automatically."""
    # Distinct catalog artists sharing a name: any automatic match could be wrong.
    negatives = [
        (catalog[key][0], "homonym")
        for key in sorted(k for k, names in catalog.items() if len(names) > 1)
    ]
    negatives += [(n, "near_miss") for n in NEAR_MISS if normalize(n) not in catalog]
    negatives += [(n, "absent") for n in ABSENT_REAL if normalize(n) not in catalog]
    negatives += [(n, "absent") for n in INVENTED]
    return negatives


def main() -> None:
    """Writes the labeled set and prints its composition."""
    cases = build_cases()
    OUT.write_text(
        json.dumps(
            {
                "description": (
                    "Labeled artist names for the import matcher (AC-10.2: precision >= 0.98). "
                    "Generated by server/scripts/build_import_eval.py from human-verified seed "
                    "MBIDs; mbid null means the name must not be matched automatically. "
                    "Rule-based, not sampled from real exports."
                ),
                "cases": cases,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    by_category: dict[str, int] = defaultdict(int)
    for case in cases:
        by_category[str(case["category"])] += 1
    print(len(cases), dict(by_category))


if __name__ == "__main__":
    main()
