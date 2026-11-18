"""Closed-loop load test of the read endpoints against a running API (plan §23, M8-01).

    uv run python scripts/load_test.py --base http://127.0.0.1:8790 --concurrency 8 --seconds 15

Prints one JSON object per scenario: requests, errors, p50/p95/p99 in milliseconds. Run the API
with SONGNEXUS_RATE_LIMIT_READ_PER_MINUTE and SONGNEXUS_RATE_LIMIT_ANALYZE_PER_MINUTE raised so the
limiter doesn't dominate the numbers, and run this script from another host when measuring a real
deployment.
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

QUERIES = [
    "bey",
    "beyonce",
    "the wee",
    "daft",
    "kendrik lamar",
    "radio",
    "drake",
    "flying lo",
    "ye",
    "taylor",
]
HTTP_ERROR = 400

Request = tuple[str, dict[str, str | int] | None]


async def discover(client: httpx.AsyncClient) -> list[str]:
    """Returns artist resource names found by searching a mix of queries."""
    names: set[str] = set()
    for query in QUERIES:
        response = await client.get("/v1/catalog:search", params={"query": query, "pageSize": 10})
        response.raise_for_status()
        names |= {r["name"] for r in response.json()["results"] if r["name"].startswith("artists/")}
    return sorted(names)


def scenarios(artists: list[str]) -> dict[str, Callable[[], Request]]:
    """Returns each scenario as a function producing one GET (path, params)."""
    rnd = random.Random(7)  # noqa: S311 - reproducible load, not security
    today = datetime.now(UTC).date().isoformat()

    def pair() -> tuple[str, str]:
        a, b = rnd.sample(artists, 2)
        return a, b

    def find_path() -> Request:
        a, b = pair()
        return f"/v1/{a}:findPath", {"target": b}

    def compare() -> Request:
        a, b = pair()
        return f"/v1/{a}:compare", {"other": b}

    return {
        "SearchCatalog": lambda: (
            "/v1/catalog:search",
            {"query": rnd.choice(QUERIES), "pageSize": 10},
        ),
        "GetArtist": lambda: (f"/v1/{rnd.choice(artists)}", None),
        "ListCollaborations": lambda: (f"/v1/{rnd.choice(artists)}/collaborations", None),
        "FindPath": find_path,
        "CompareArtists": compare,
        "GetPuzzle": lambda: (f"/v1/puzzles/{today}", None),
    }


async def worker(
    client: httpx.AsyncClient, make: Callable[[], Request], deadline: float, latencies: list[float]
) -> int:
    """Issues requests until the deadline, appending latencies (ms); returns the error count."""
    errors = 0
    while time.perf_counter() < deadline:
        path, params = make()
        start = time.perf_counter()
        try:
            response = await client.get(path, params=params)
            errors += response.status_code >= HTTP_ERROR
        except httpx.HTTPError:
            errors += 1
        latencies.append((time.perf_counter() - start) * 1000)
    return errors


async def run(base: str, concurrency: int, seconds: float) -> None:
    """Runs every scenario in turn and prints its summary."""
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        for name, make in scenarios(await discover(client)).items():
            latencies: list[float] = []
            deadline = time.perf_counter() + seconds
            errors = sum(
                await asyncio.gather(
                    *(worker(client, make, deadline, latencies) for _ in range(concurrency))
                )
            )
            latencies.sort()

            def percentile(p: float, values: list[float] = latencies) -> float:
                return values[min(len(values) - 1, int(p * len(values)))]

            print(
                json.dumps(
                    {
                        "scenario": name,
                        "requests": len(latencies),
                        "rps": round(len(latencies) / seconds, 1),
                        "errors": errors,
                        "p50_ms": round(statistics.median(latencies), 1),
                        "p95_ms": round(percentile(0.95), 1),
                        "p99_ms": round(percentile(0.99), 1),
                    }
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8790")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=15)
    args = parser.parse_args()
    asyncio.run(run(args.base, args.concurrency, args.seconds))
