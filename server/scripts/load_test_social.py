"""Closed-loop load test of the signed-in R2 endpoints (R2-8): friends, inbox, linked accounts.

Development only: it signs in through ``POST /v1/sessions:local``, so the API must run with
``SONGNEXUS_ENVIRONMENT=development`` and no Firebase project, on a scratch database copy,
with ``SONGNEXUS_RATE_LIMIT_READ_PER_MINUTE`` and ``SONGNEXUS_RATE_LIMIT_WRITE_PER_MINUTE``
raised and ``SONGNEXUS_ALLOWED_ORIGINS`` set to the API's own origin:

    uv run uvicorn songnexus.service.app:create_app --factory --port 8791
    uv run python scripts/load_test_social.py --base http://127.0.0.1:8791 --seconds 8

Seeds ``--users`` listeners in pairs of friends, each pair with ``--shares`` shares (at most
20: the hourly send limit), then prints one JSON line per scenario like ``load_test.py``. The
session cookie is Secure, so it is carried by hand over plain HTTP to localhost.
"""

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import httpx

HTTP_ERROR = 400


@dataclass
class Listener:
    """A signed-in development listener."""

    user: str
    headers: dict[str, str]


async def sign_in(client: httpx.AsyncClient, origin: str, name: str) -> Listener:
    """Creates a local session and picks a display name."""
    response = await client.post(
        "/v1/sessions:local",
        json={"listener": name, "ageConfirmed": True},
        headers={"Origin": origin},
    )
    response.raise_for_status()
    body = response.json()
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    headers = {"Origin": origin, "X-CSRF-Token": body["csrfToken"], "Cookie": cookie}
    named = await client.patch(
        "/v1/users/me/socialProfile", json={"displayName": name}, headers=headers
    )
    named.raise_for_status()
    return Listener(body["user"], headers)


async def seed(
    client: httpx.AsyncClient, origin: str, users: int, shares: int
) -> tuple[list[Listener], list[str]]:
    """Signs in listeners, befriends neighbours, and fills inboxes."""
    found = await client.get("/v1/catalog:search", params={"query": "kendrick", "pageSize": 10})
    found.raise_for_status()
    artists = [r["name"] for r in found.json()["results"] if r["name"].startswith("artists/")]
    run = uuid.uuid4().hex[:6]
    people = [await sign_in(client, origin, f"load-{run}-{i}") for i in range(users)]
    for a, b in zip(people[::2], people[1::2], strict=False):
        invite = await client.post("/v1/users/me/friendInvites", headers=a.headers)
        invite.raise_for_status()
        code = invite.json()["code"]
        accepted = await client.post(f"/v1/friendInvites/{code}:accept", headers=b.headers)
        accepted.raise_for_status()
        for i in range(shares):
            sent = await client.post(
                "/v1/shares",
                json={
                    "recipient": b.user,
                    "kind": "ARTIST",
                    "subjects": [artists[i % len(artists)]],
                    "note": f"try this one ({i})",
                },
                headers=a.headers,
            )
            sent.raise_for_status()
    return people, artists


Request = tuple[str, str, dict[str, str]]


def scenarios(people: list[Listener]) -> dict[str, Callable[[], Request]]:
    """Each scenario returns (method, path, headers) for one request."""
    rnd = random.Random(7)  # noqa: S311 - reproducible load, not security
    recipients = people[1::2]

    def pick(group: list[Listener]) -> Listener:
        return group[rnd.randrange(len(group))]

    return {
        "ListInbox (20 shares)": lambda: ("GET", "/v1/users/me/inbox", pick(recipients).headers),
        "ListFriends": lambda: ("GET", "/v1/users/me/friends", pick(people).headers),
        "ListLinkedAccounts": lambda: ("GET", "/v1/users/me/linkedAccounts", pick(people).headers),
        "ListListening": lambda: ("GET", "/v1/users/me/listening", pick(people).headers),
        "GetSocialProfile": lambda: ("GET", "/v1/users/me/socialProfile", pick(people).headers),
        "MarkInboxRead (write)": lambda: (
            "POST",
            "/v1/users/me/inbox:markRead",
            pick(recipients).headers,
        ),
    }


async def worker(
    client: httpx.AsyncClient,
    make: Callable[[], Request],
    deadline: float,
    latencies: list[float],
) -> int:
    """Sends requests until the deadline; returns the error count."""
    errors = 0
    while time.perf_counter() < deadline:
        method, path, headers = make()
        start = time.perf_counter()
        response = await client.request(method, path, headers=headers)
        latencies.append((time.perf_counter() - start) * 1000)
        errors += response.status_code >= HTTP_ERROR
    return errors


async def run(base: str, concurrency: int, seconds: float, users: int, shares: int) -> None:
    """Seeds, then runs every scenario in turn and prints its summary."""
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        people, _ = await seed(client, base, users, shares)
        for name, make in scenarios(people).items():
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
    parser.add_argument("--base", default="http://127.0.0.1:8791")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--shares", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(run(args.base, args.concurrency, args.seconds, args.users, args.shares))
