"""Times batch name matching for a realistic 2,000-name playlist (plan §23, AnalyzePlaylist).

    SONGNEXUS_DATABASE_URL=sqlite:///path/to/catalog.db uv run python scripts/bench_resolve.py

The mix is 40 % exact catalog names, 25 % one-typo variants, 15 % names with a "the" or accent
change, and 20 % names absent from the catalog; it is seeded, so runs are comparable.
"""

import random
import time

from songnexus.config import Settings
from songnexus.core.resolution import Decision, resolve_batch
from songnexus.service.readmodel import load_read_model
from songnexus.storage.db import make_engine

COUNT = 2000
MIN_TYPO_LENGTH = 4
DELETE_SHARE = 0.5


def typo(name: str, rnd: random.Random) -> str:
    """Returns the name with one character deleted or two adjacent characters swapped."""
    if len(name) < MIN_TYPO_LENGTH:
        return name
    i = rnd.randrange(1, len(name) - 2)
    return (
        name[:i] + name[i + 1 :]
        if rnd.random() < DELETE_SHARE
        else name[:i] + name[i + 1] + name[i] + name[i + 2 :]
    )


def main() -> None:
    """Builds the mention set, resolves it, and prints timing and decision counts."""
    model = load_read_model(make_engine(Settings().database_url))
    rnd = random.Random(11)  # noqa: S311
    names = sorted({node.name for node in model.graph.nodes.values()})
    rnd.shuffle(names)
    mentions = names[: int(COUNT * 0.40)]
    mentions += [typo(n, rnd) for n in names[800:1300]]
    mentions += [f"the {n}" if not n.startswith("the ") else n[4:] for n in names[1300:1600]]
    mentions += [
        f"{rnd.choice(names)[:5]} {rnd.choice(['collective', 'orchestra', 'quartet', 'unit'])} {i}"
        for i in range(400)
    ]
    mentions = list(dict.fromkeys(mentions))[:COUNT]
    start = time.perf_counter()
    results = resolve_batch(model.search, mentions)
    elapsed = time.perf_counter() - start
    counts = {d.value: sum(r.decision is d for r in results) for d in Decision}
    each_ms = 1000 * elapsed / len(mentions)
    print(f"{len(mentions)} names in {elapsed:.2f} s ({each_ms:.2f} ms each); {counts}")
    print(
        "digest",
        hash(tuple((r.mention, r.decision.value, r.entity_id) for r in results)) & 0xFFFFFFFF,
    )


if __name__ == "__main__":
    main()
