"""Development only: a synthetic demo cohort so the social half of the app has content.

``songnexus seed-demo`` creates (or, re-run, recreates identically) about 350
synthetic listeners spread over 8 campuses (4 of them the fictional "(Demo)"
universities) and 6 cities, each campus with its own genre-coherent taste drawn
from real catalog artists, plus one demo account a person can sign in as
locally (``POST /v1/sessions:local`` with ``{"listener": "demo"}``) that has
listening, a campus, friends, shares and game scores.

Everything it writes is labeled: accounts carry ``users.synthetic_source =
"seed-demo"``, memberships ``synthetic``, so charts built from them say
``demoData``. Names are obviously fictional handles ("Velvet Heron (demo)"); no
emails exist. ``--reset`` removes exactly what it created. It refuses to run
outside development and never runs automatically. See docs/synthetic-data.md.

Charts are not written here: the caller builds them through the production
path (``community_job.compute``) at three points in time while the tallies are
rolled forward, so movement, rising and weekly movers have real history. The
privacy floors in ``core.community`` and ``core.leaderboard`` apply unchanged:
the smallest campus (8 members) stays locked and off the leaderboard on purpose.
"""

from __future__ import annotations

import math
import random
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from songnexus.core import leaderboard
from songnexus.storage import community_repository, demo_repository, social_repository
from songnexus.storage import models as m
from songnexus.storage.db import session_scope

SOURCE = "seed-demo"
DEMO_LISTENER = "demo"
DEMO_IDENTITY = f"local:{DEMO_LISTENER}"
PROVIDER = community_repository.SYNTHETIC_PROVIDER
# Stable IDs across runs, so a re-run recreates the same accounts (not security).
NAMESPACE = uuid.UUID("5f0c1d1e-8a43-4b7e-9d0a-5e6d656d6f00")
SEED = "songnexus-seed-demo-v1"

# Genre families. An artist belongs to a scene by the share of its genre votes here.
SCENES: Mapping[str, frozenset[str]] = {
    "hiphop": frozenset(
        {
            "hip hop",
            "trap",
            "pop rap",
            "gangsta rap",
            "boom bap",
            "conscious hip hop",
            "southern hip hop",
            "jazz rap",
            "g-funk",
            "hardcore hip hop",
            "east coast hip hop",
            "west coast hip hop",
            "drill",
        }
    ),
    "rnb": frozenset(
        {
            "soul",
            "contemporary r&b",
            "r&b",
            "neo soul",
            "funk",
            "new jack swing",
            "alternative r&b",
            "gospel",
            "disco",
            "motown",
        }
    ),
    "electronic": frozenset(
        {
            "electronic",
            "house",
            "electro",
            "deep house",
            "techno",
            "drum and bass",
            "dubstep",
            "uk garage",
            "downtempo",
            "trip hop",
            "ambient",
            "breaks",
            "tech house",
            "electro house",
            "progressive house",
            "idm",
            "breakbeat",
            "leftfield",
        }
    ),
    "rock": frozenset(
        {
            "rock",
            "alternative rock",
            "indie rock",
            "indie pop",
            "pop rock",
            "psychedelic rock",
            "folk rock",
            "soft rock",
            "punk",
            "grunge",
            "post-punk",
            "britpop",
            "art rock",
        }
    ),
    "pop": frozenset({"pop", "dance-pop", "synth-pop", "europop", "ballad", "dance", "electropop"}),
    "folk": frozenset({"folk", "country", "singer-songwriter", "blues", "americana", "bluegrass"}),
    "jazz": frozenset(
        {
            "jazz",
            "soul jazz",
            "contemporary jazz",
            "jazz-funk",
            "bebop",
            "hard bop",
            "fusion",
            "jazz fusion",
            "bossa nova",
        }
    ),
    "latin": frozenset(
        {
            "latin",
            "reggae",
            "reggaeton",
            "dancehall",
            "dub",
            "afrobeat",
            "latin pop",
            "salsa",
            "samba",
            "mpb",
            "afrobeats",
        }
    ),
}
MIN_SCENE_SHARE = 0.25
MIN_SCENE_ARTISTS = 12


@dataclass(frozen=True)
class CampusPlan:
    """A campus in the demo, its size, taste and city."""

    campus: str
    members: int
    taste: Mapping[str, float]
    city: str | None = None
    skill: float = 0.0  # shifts game results a little, so campuses differ


PLAN: tuple[CampusPlan, ...] = (
    CampusPlan(
        "demo-us-1", 46, {"hiphop": 0.5, "rnb": 0.3, "pop": 0.2}, "new-york-city-us-ny", 0.10
    ),
    CampusPlan(
        "demo-us-2",
        40,
        {"electronic": 0.6, "hiphop": 0.2, "rock": 0.2},
        "new-york-city-us-ny",
        0.05,
    ),
    CampusPlan("demo-ca-1", 42, {"rock": 0.5, "folk": 0.3, "electronic": 0.2}, "toronto-ca", 0.0),
    CampusPlan(
        "demo-mx-1", 40, {"latin": 0.5, "pop": 0.3, "electronic": 0.2}, "mexico-city-mx", -0.05
    ),
    # Deliberately below every floor: its chart stays locked and it never ranks.
    CampusPlan("demo-br-1", 8, {"latin": 0.4, "jazz": 0.4, "rnb": 0.2}, "sao-paulo-br", 0.15),
    CampusPlan(
        "university-of-wisconsin-madison", 50, {"rock": 0.4, "hiphop": 0.3, "folk": 0.3}, None, 0.08
    ),
    CampusPlan("university-of-toronto", 44, {"rnb": 0.45, "hiphop": 0.35, "pop": 0.2}, None, 0.02),
    CampusPlan(
        "university-of-illinois-urbana-champaign",
        40,
        {"electronic": 0.4, "rock": 0.3, "jazz": 0.3},
        None,
        -0.02,
    ),
)
DEMO_CAMPUS = "demo-us-1"
DEMO_CITY = "new-york-city-us-ny"
CITY_SHARE = 0.7  # members who also join their campus's city
OWN_SCENE_SHARE = 0.85  # picks from the campus's scenes; the rest from all popular artists
FAVORITES_PER_SCENE = 8
FAVORITE_BOOST = 4.0
BREAKOUTS = 3  # artists a campus picked up this week (they enter the chart)
BREAKOUT_SHARE = 0.45
ARTISTS_PER_MEMBER = (12, 28)
# When a member started on an artist, in days before now: most long ago, some
# in each of the last two weeks, so charts move between snapshots.
START_BANDS = ((0.70, 14.0, 150.0), (0.15, 7.0, 14.0), (0.15, 0.5, 7.0))
SNAPSHOT_AGES = (timedelta(days=14, hours=1), timedelta(days=7, hours=1), timedelta(0))
SCORE_DAYS = 7
PLAY_RATE = {leaderboard.Game.PUZZLE: 0.6, leaderboard.Game.TRIVIA: 0.5}
EXTRA_STEPS = (0, 1, 2, 3, 4)
EXTRA_WEIGHTS = (0.35, 0.3, 0.2, 0.1, 0.05)
TRIVIA_ACCURACY = 0.6
FRIENDS = (
    ("demo-us-1", 0),
    ("demo-us-1", 1),
    ("demo-us-2", 0),
    ("university-of-wisconsin-madison", 0),
    ("university-of-toronto", 0),
)
NOT_SHARING_FRIEND = 4  # the last friend keeps top-artist sharing off (shows that error)

ADJECTIVES = (
    "Velvet",
    "Neon",
    "Quiet",
    "Golden",
    "Static",
    "Paper",
    "Cobalt",
    "Amber",
    "Lunar",
    "Echo",
    "Copper",
    "Silver",
    "Midnight",
    "Analog",
    "Crystal",
    "Rusty",
    "Hollow",
    "Bright",
    "Sleepy",
    "Electric",
    "Indigo",
    "Coral",
    "Misty",
    "Solar",
    "Vinyl",
    "Cosmic",
    "Tidal",
    "Woven",
    "Frosted",
    "Ember",
)
NOUNS = (
    "Heron",
    "Fox",
    "Otter",
    "Lynx",
    "Comet",
    "Falcon",
    "Maple",
    "Harbor",
    "Lantern",
    "Beacon",
    "Sparrow",
    "Badger",
    "Cedar",
    "Meadow",
    "Raven",
    "Willow",
    "Bison",
    "Quokka",
    "Pelican",
    "Marten",
    "Ferret",
    "Kestrel",
    "Juniper",
    "Puffin",
    "Wombat",
    "Gecko",
    "Orca",
    "Panda",
    "Tapir",
    "Yak",
)
SHARE_NOTES = (
    "This one is all over our campus chart",
    "How are these two connected?",
    "",
    "Put this on your Friday playlist",
    "Didn't know they worked together",
)


class SeedRefusedError(RuntimeError):
    """Seeding is not allowed here (environment, a real account in the way, catalog)."""


def check_environment(environment: str) -> None:
    """Refuses anything but development (production above all).

    Raises:
        SeedRefusedError: Not development.
    """
    if environment != "development":
        raise SeedRefusedError(
            f"seed-demo only runs in development (SONGNEXUS_ENVIRONMENT is {environment!r})"
        )


def preflight(engine: Engine, environment: str) -> None:
    """Checks the environment and that no real account signs in as the demo listener.

    Raises:
        SeedRefusedError: Not development, or a real ``local:demo`` account exists.
    """
    check_environment(environment)
    with session_scope(engine) as session:
        existing = demo_repository.find_by_identity(session, DEMO_IDENTITY)
        if existing is not None and existing.synthetic_source != SOURCE:
            raise SeedRefusedError(
                f"a real account already signs in as {DEMO_LISTENER!r}; delete it first"
            )


def _id(kind: str, *parts: object) -> str:
    return str(uuid.uuid5(NAMESPACE, ":".join([kind, *map(str, parts)])))


def handle(index: int) -> str:
    """The obviously fictional display name of demo member ``index``."""
    adjective = ADJECTIVES[index % len(ADJECTIVES)]
    noun = NOUNS[(index // len(ADJECTIVES)) % len(NOUNS)]
    return f"{adjective} {noun} (demo)"


def scene_pools(
    artists: Sequence[tuple[str, int, Mapping[str, int]]],
) -> dict[str, list[tuple[str, float]]]:
    """Each scene's artists with a draw weight (scene share x audience), strongest first."""
    pools: dict[str, list[tuple[str, float]]] = {s: [] for s in SCENES}
    for artist_id, audience, genres in artists:
        total = sum(genres.values()) or 1
        for scene, names in SCENES.items():
            share = sum(v for g, v in genres.items() if g.casefold() in names) / total
            if share >= MIN_SCENE_SHARE:
                pools[scene].append((artist_id, share * math.sqrt(audience + 50)))
    for pool in pools.values():
        pool.sort(key=lambda p: (-p[1], p[0]))
    return pools


@dataclass
class Listening:
    """One member's synthetic history: per artist (started days ago, last days ago, rate)."""

    picks: dict[str, tuple[float, float, float]] = field(default_factory=dict)

    def at(self, age_days: float, now: datetime, user_id: str) -> list[m.ListeningTally]:
        """The member's tallies as they stood ``age_days`` before ``now``."""
        rows = []
        for artist_id, (start, last, rate) in self.picks.items():
            if start <= age_days:
                continue
            last_seen = max(last, age_days)
            plays = max(1, round(rate * (start - last_seen)))
            rows.append(
                m.ListeningTally(
                    user_id=user_id,
                    provider=PROVIDER,
                    artist_id=artist_id,
                    plays=plays,
                    last_played_at=now - timedelta(days=last_seen),
                )
            )
        return rows


def _start(rng: random.Random) -> float:
    roll = rng.random()
    for share, low, high in START_BANDS:
        if roll < share:
            return rng.uniform(low, high)
        roll -= share
    return rng.uniform(START_BANDS[0][1], START_BANDS[0][2])


def _listening(
    rng: random.Random,
    plan: CampusPlan,
    *,
    pools: Mapping[str, list[tuple[str, float]]],
    popular: list[tuple[str, float]],
    favorites: Mapping[str, set[str]],
    breakouts: Sequence[str],
) -> Listening:
    history = Listening()
    scenes = [s for s in plan.taste if pools.get(s)]
    want = rng.randint(*ARTISTS_PER_MEMBER)
    for _ in range(want * 3):
        if len(history.picks) >= want:
            break
        if scenes and rng.random() < OWN_SCENE_SHARE:
            scene = rng.choices(scenes, weights=[plan.taste[s] for s in scenes])[0]
            pool = pools[scene]
            boost = favorites.get(scene, set())
            weights = [w * (FAVORITE_BOOST if a in boost else 1.0) for a, w in pool]
            artist_id = rng.choices([a for a, _ in pool], weights=weights)[0]
        else:
            artist_id = rng.choices([a for a, _ in popular], weights=[w for _, w in popular])[0]
        if artist_id in breakouts or artist_id in history.picks:
            continue
        start = _start(rng)
        history.picks[artist_id] = (start, rng.uniform(0, min(start, 30.0)), rng.uniform(0.2, 3.0))
    for artist_id in breakouts:
        if rng.random() < BREAKOUT_SHARE:
            start = rng.uniform(0.5, 6.5)
            history.picks[artist_id] = (start, rng.uniform(0, start), rng.uniform(1.0, 5.0))
    return history


@dataclass
class Member:
    """A synthetic account to write."""

    user_id: str
    name: str
    campus: str
    city: str | None
    listening: Listening
    skill: float
    identity: str | None = None


def _cohort(
    rng: random.Random,
    pools: Mapping[str, list[tuple[str, float]]],
    city_of: Callable[[str], str | None],
) -> tuple[list[Member], Member]:
    popular = sorted(
        {a: w for pool in pools.values() for a, w in pool[:60]}.items(), key=lambda p: (-p[1], p[0])
    )[:200]
    members: list[Member] = []
    demo: Member | None = None
    index = 0
    for plan in PLAN:
        favorites = {
            s: set(
                rng.sample([a for a, _ in pools[s][:40]], min(FAVORITES_PER_SCENE, len(pools[s])))
            )
            for s in plan.taste
            if pools.get(s)
        }
        main = max(plan.taste, key=lambda s: plan.taste[s])
        candidates = [a for a, _ in pools.get(main, [])[15:45]]
        breakouts = rng.sample(candidates, min(BREAKOUTS, len(candidates)))
        city = plan.city or city_of(plan.campus)
        for i in range(plan.members):
            members.append(
                Member(
                    _id("member", plan.campus, i),
                    handle(index),
                    plan.campus,
                    city if city and rng.random() < CITY_SHARE else None,
                    _listening(
                        rng,
                        plan,
                        pools=pools,
                        popular=popular,
                        favorites=favorites,
                        breakouts=breakouts,
                    ),
                    plan.skill + rng.uniform(-0.1, 0.1),
                )
            )
            index += 1
        if plan.campus == DEMO_CAMPUS:
            demo = Member(
                _id("demo-account"),
                "Demo Listener (you)",
                DEMO_CAMPUS,
                DEMO_CITY,
                _listening(
                    rng,
                    plan,
                    pools=pools,
                    popular=popular,
                    favorites=favorites,
                    breakouts=breakouts,
                ),
                plan.skill,
                identity=DEMO_IDENTITY,
            )
    assert demo is not None
    return members, demo


def _scores(
    rng: random.Random,
    member: Member,
    *,
    today: date,
    now: datetime,
    puzzle_par: Callable[[date], int | None],
    trivia_total: Callable[[date], int | None],
    include_today: bool,
) -> list[m.GameScore]:
    rows = []
    for back in range(SCORE_DAYS):
        if back == 0 and not include_today:
            continue
        day = today - timedelta(days=back)
        for game, rate in PLAY_RATE.items():
            if rng.random() >= rate + member.skill / 2:
                continue
            if game is leaderboard.Game.PUZZLE:
                par = puzzle_par(day)
                if par is None:
                    continue
                shift = max(0.0, 1 - member.skill * 3)
                extra = rng.choices(
                    EXTRA_STEPS,
                    weights=[w if i == 0 else w * shift for i, w in enumerate(EXTRA_WEIGHTS)],
                )[0]
                points = leaderboard.puzzle_points(par + extra, par)
                detail = {"steps": par + extra, "par": par}
            else:
                total = trivia_total(day)
                if not total:
                    continue
                accuracy = min(0.95, max(0.2, TRIVIA_ACCURACY + member.skill))
                correct = sum(rng.random() < accuracy for _ in range(total))
                points = leaderboard.trivia_points(correct, total)
                detail = {"correct": correct, "total": total}
            rows.append(
                m.GameScore(
                    user_id=member.user_id,
                    game=game.value,
                    day=day.isoformat(),
                    points=points,
                    detail=detail,
                    campus_id=member.campus,
                    submitted_at=min(now, datetime.combine(day, now.timetz()).replace(hour=20)),
                )
            )
    return rows


def _remove(engine: Engine, now: datetime) -> dict[str, int]:
    with session_scope(engine) as session:
        ids = demo_repository.synthetic_user_ids(session, SOURCE)
        removed = demo_repository.remove_users(session, ids, now)
        # Every demo chart, including city charts reached through a campus's city.
        charts = demo_repository.delete_demo_charts(session)
    return {"removedAccounts": removed, "removedCharts": charts}


def plan_communities(city_of: Callable[[str], str | None] | None = None) -> list[str]:
    """Every community the demo writes members to."""
    ids = {p.campus for p in PLAN} | {p.city for p in PLAN if p.city} | {DEMO_CITY}
    if city_of is not None:
        ids |= {c for p in PLAN if (c := city_of(p.campus))}
    return sorted(ids)


def reset_demo(engine: Engine, environment: str, now: datetime) -> dict[str, int]:
    """Removes every account ``seed-demo`` created, with all their data and demo charts.

    Raises:
        SeedRefusedError: Outside development.
    """
    check_environment(environment)
    return _remove(engine, now)


def seed_demo(
    engine: Engine,
    environment: str,
    now: datetime,
    *,
    known_communities: Callable[[str], bool],
    city_of: Callable[[str], str | None],
    build_charts: Callable[[list[str], datetime], None],
    puzzle_par: Callable[[date], int | None],
    trivia_total: Callable[[date], int | None],
) -> dict[str, int | str]:
    """Creates (or recreates identically) the demo cohort and the demo account.

    Args:
        engine: The development database.
        environment: ``Settings.environment``; anything but development is refused.
        now: The seed's "now"; scores cover the 7 days up to it.
        known_communities: Whether a community ID is in the directory.
        city_of: A campus's city in the directory, if any.
        build_charts: Builds and stores the charts of these communities as of a
            time, through the production chart path.
        puzzle_par: The day's puzzle par (None: no puzzle).
        trivia_total: The day's Credit check question count (None: none).

    Raises:
        SeedRefusedError: Outside development, an unknown community, a real
            account using the demo sign-in, or a catalog too small to draw from.
    """
    check_environment(environment)
    communities = plan_communities(city_of)
    missing = [c for c in communities if not known_communities(c)]
    if missing:
        raise SeedRefusedError(f"communities missing from the directory: {missing}")
    preflight(engine, environment)
    with session_scope(engine) as session:
        pools = scene_pools(demo_repository.catalog_artist_genres(session))
    thin = [s for p in PLAN for s in p.taste if len(pools[s]) < MIN_SCENE_ARTISTS]
    if thin:
        raise SeedRefusedError(f"the catalog is too thin for scenes {sorted(set(thin))}")

    rng = random.Random(SEED)  # noqa: S311 - reproducible demo data, not security
    members, demo = _cohort(rng, pools, city_of)
    everyone = [*members, demo]
    removed = _remove(engine, now)

    with session_scope(engine) as session:
        for person in everyone:
            demo_repository.add_user(session, person.user_id, person.identity, SOURCE, now)
        session.flush()
        for person in everyone:
            social_repository.set_display_name(session, person.user_id, person.name, now)
            session.add(
                m.CommunityMembership(
                    user_id=person.user_id,
                    kind="CAMPUS",
                    community_id=person.campus,
                    joined_at=now - timedelta(days=30),
                    synthetic=True,
                )
            )
            if person.city:
                session.add(
                    m.CommunityMembership(
                        user_id=person.user_id,
                        kind="CITY",
                        community_id=person.city,
                        joined_at=now - timedelta(days=30),
                        synthetic=True,
                    )
                )

    ids = [p.user_id for p in everyone]
    for age in SNAPSHOT_AGES:
        at = now - age
        days = age.total_seconds() / 86400
        with session_scope(engine) as session:
            demo_repository.replace_tallies(
                session, ids, (t for p in everyone for t in p.listening.at(days, now, p.user_id))
            )
        build_charts(communities, at)

    friends = [_friend(members, campus, n) for campus, n in FRIENDS]
    shares = 0
    scores = 0
    with session_scope(engine) as session:
        for i, friend in enumerate(friends):
            social_repository.befriend(
                session, demo.user_id, friend.user_id, now - timedelta(days=10 - i)
            )
            if i != NOT_SHARING_FRIEND:
                social_repository.set_share_top_artists(session, friend.user_id, True, now)
        social_repository.set_share_top_artists(session, demo.user_id, True, now)
        shares = _shares(session, rng, demo, friends, now)
        today = now.date()
        for person in members:
            rows = _scores(
                rng,
                person,
                today=today,
                now=now,
                puzzle_par=puzzle_par,
                trivia_total=trivia_total,
                include_today=True,
            )
            session.add_all(rows)
            scores += len(rows)
        rows = _scores(
            rng,
            demo,
            today=today,
            now=now,
            puzzle_par=puzzle_par,
            trivia_total=trivia_total,
            include_today=False,
        )
        session.add_all(rows)
        scores += len(rows)

    return {
        "source": SOURCE,
        "signInAs": DEMO_LISTENER,
        "demoAccount": f"users/{demo.user_id}",
        "syntheticListeners": len(members),
        "communities": len(communities),
        "listeningTallies": sum(len(p.listening.at(0, now, p.user_id)) for p in everyone),
        "friends": len(friends),
        "shares": shares,
        "gameScores": scores,
        "chartSnapshots": len(SNAPSHOT_AGES),
        **removed,
    }


def _friend(members: list[Member], campus: str, n: int) -> Member:
    return [p for p in members if p.campus == campus][n]


def _shares(
    session: Session, rng: random.Random, demo: Member, friends: list[Member], now: datetime
) -> int:
    """Sends the demo account a few shares from its demo friends; returns how many."""
    recordings = demo_repository.recordings_by(
        session, [a for f in friends for a in f.listening.picks]
    )
    count = 0
    for i, friend in enumerate(friends):
        theirs = sorted(friend.listening.picks, key=lambda a: -friend.listening.picks[a][0])
        mine = sorted(demo.listening.picks)
        kind_index = i % 4
        if kind_index == 0:
            kind, subjects = "ARTIST", [f"artists/{theirs[0]}"]
        elif kind_index == 1:
            other = rng.choice([a for a in mine if a != theirs[0]])
            kind, subjects = "PATH", [f"artists/{theirs[0]}", f"artists/{other}"]
        elif kind_index == 2:  # noqa: PLR2004 - share kinds take turns
            kind, subjects = "ARTIST_COMPARISON", [f"artists/{theirs[0]}", f"artists/{theirs[1]}"]
        else:
            recording = next((recordings[a] for a in theirs if a in recordings), None)
            if recording is None:
                kind, subjects = "ARTIST", [f"artists/{theirs[1]}"]
            else:
                kind, subjects = "RECORDING", [f"recordings/{recording}"]
        row = social_repository.add_share(
            session,
            sender_id=friend.user_id,
            recipient_id=demo.user_id,
            kind=kind,
            subjects=subjects,
            note=SHARE_NOTES[i % len(SHARE_NOTES)],
            now=now - timedelta(hours=3 * (i + 1)),
        )
        if i >= 3:  # noqa: PLR2004 - the two oldest are read, the rest unread
            social_repository.mark_read(session, row, now)
        count += 1
    return count
