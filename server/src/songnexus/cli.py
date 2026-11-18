"""Command-line entry point: ``songnexus <command>``.

Commands print a JSON result on stdout (logs go to stderr) and exit non-zero on
failure, so they compose in CI and scripts.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from songnexus.config import Settings, get_settings
from songnexus.logs import configure_logging

EXIT_OK = 0
EXIT_FAILED = 1


def _print(result: Any) -> None:
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def _cmd_migrate(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.storage import migrate
    from songnexus.storage.db import make_engine

    engine = make_engine(settings.database_url)
    if args.down:
        migrate.downgrade(engine, args.revision)
    else:
        migrate.upgrade(engine, args.revision)
    _print({"revision": migrate.current_revision(engine)})
    return EXIT_OK


def _cmd_fetch(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.catalog.musicbrainz.client import MusicBrainzClient
    from songnexus.catalog.musicbrainz.fetch import run_fetch

    client = MusicBrainzClient(
        base_url=settings.musicbrainz_base_url,
        cache_dir=settings.raw_cache_dir,
        contact=settings.musicbrainz_contact,
        min_interval_s=settings.musicbrainz_min_interval_s,
    )
    seeds_path: Path = args.seeds or settings.seeds_path
    result = run_fetch(
        client,
        seeds_path=seeds_path,
        snapshot_path=args.output or settings.snapshot_path,
        lock_path=seeds_path.with_suffix(".lock.json"),
        max_profiles=args.max_profiles,
    )
    _print(result)
    return EXIT_FAILED if result["unresolved"] else EXIT_OK


def _musicbrainz_batch(settings: Settings) -> Any:
    from songnexus.catalog.canonicalize import build_batch
    from songnexus.catalog.snapshot import read_snapshot

    return build_batch(read_snapshot(settings.snapshot_path))


def _cmd_fetch_wikidata(settings: Settings, _args: argparse.Namespace) -> int:
    from songnexus.catalog.wikidata.fetch import WikidataClient, run_fetch

    batch = _musicbrainz_batch(settings)
    mbids = [r["source_entity_id"] for r in batch.mappings.values() if r["entity_type"] == "artist"]
    client = WikidataClient(
        sparql_url=settings.wikidata_sparql_url,
        cache_dir=settings.raw_dir("wikidata"),
        contact=settings.wikidata_contact,
    )
    _print(
        run_fetch(
            client, musicbrainz_artist_ids=mbids, snapshot_path=settings.wikidata_snapshot_path
        )
    )
    return EXIT_OK


def _cmd_fetch_acousticbrainz(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.catalog.acousticbrainz import AcousticBrainzClient, run_fetch

    batch = _musicbrainz_batch(settings)
    mbids = [
        r["source_entity_id"] for r in batch.mappings.values() if r["entity_type"] == "recording"
    ]
    client = AcousticBrainzClient(
        base_url=settings.acousticbrainz_base_url,
        cache_dir=settings.raw_dir("acousticbrainz"),
        contact=settings.wikidata_contact,
    )
    _print(
        run_fetch(
            client,
            recording_ids=mbids,
            snapshot_path=settings.acousticbrainz_snapshot_path,
            cached_only=args.cached_only,
        )
    )
    return EXIT_OK


def _cmd_fetch_listenbrainz(settings: Settings, _args: argparse.Namespace) -> int:
    from songnexus.catalog.listenbrainz import ListenBrainzClient, run_fetch

    batch = _musicbrainz_batch(settings)
    artists = {
        r["source_entity_id"]: r["entity_id"]
        for r in batch.mappings.values()
        if r["entity_type"] == "artist"
    }
    # Co-listening for every artist with a page of its own (seeds and profiles).
    detailed = [
        mbid
        for mbid, artist_id in artists.items()
        if batch.artists[artist_id]["detail_level"] != "stub"
    ]
    cache = settings.raw_dir("listenbrainz")
    clients = [
        ListenBrainzClient(base_url=url, cache_dir=cache, contact=settings.wikidata_contact)
        for url in (settings.listenbrainz_api_url, settings.listenbrainz_labs_url)
    ]
    _print(
        run_fetch(
            *clients,
            artist_ids=artists,
            similar_for=detailed,
            snapshot_path=settings.listenbrainz_snapshot_path,
        )
    )
    return EXIT_OK


def _cmd_fetch_discogs(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.catalog.discogs.dump import fetch_masters_dump, run_extract
    from songnexus.catalog.enrich import discogs_links
    from songnexus.catalog.snapshot import read_snapshot

    links, _ambiguous = discogs_links(
        _musicbrainz_batch(settings), read_snapshot(settings.wikidata_snapshot_path)
    )
    dump_path, sha256 = fetch_masters_dump(
        settings.discogs_dumps_url,
        args.dump_date,
        settings.raw_dir("discogs"),
        contact=settings.wikidata_contact,
    )
    _print(
        run_extract(
            dump_path,
            sha256=sha256,
            dumps_url=settings.discogs_dumps_url,
            dump_date=args.dump_date,
            discogs_artist_ids=links,
            snapshot_path=settings.discogs_snapshot_path,
        )
    )
    return EXIT_OK


def _enrichment_inputs(settings: Settings, args: argparse.Namespace) -> Any:
    from songnexus.catalog.ingest import EnrichmentInputs

    # A custom snapshot (tests, experiments) is ingested on its own.
    if args.no_enrichment or (
        args.snapshot is not None and not getattr(args, "with_enrichment", False)
    ):
        return None
    paths = (
        settings.wikidata_snapshot_path,
        settings.discogs_snapshot_path,
        settings.acousticbrainz_snapshot_path,
        settings.listenbrainz_snapshot_path,
    )
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise SystemExit(
            f"missing enrichment snapshot(s): {', '.join(missing)}; "
            "run the fetch-* commands for them, or pass --no-enrichment"
        )
    return EnrichmentInputs(
        settings.wikidata_snapshot_path,
        settings.discogs_snapshot_path,
        settings.genre_map_path,
        settings.acousticbrainz_snapshot_path,
        settings.listenbrainz_snapshot_path,
    )


def _cmd_ingest(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.catalog.ingest import QualityGateError, ingest_snapshot
    from songnexus.storage import migrate
    from songnexus.storage.db import make_engine

    enrichment = _enrichment_inputs(settings, args)
    engine = make_engine(settings.database_url)
    migrate.upgrade(engine)
    try:
        _print(ingest_snapshot(engine, args.snapshot or settings.snapshot_path, enrichment))
    except QualityGateError as exc:
        # Nothing was written; the previous catalog keeps serving.
        print(f"Ingest rejected: {exc}. The previous catalog is unchanged.", file=sys.stderr)
        return EXIT_FAILED
    return EXIT_OK


def _cmd_serve(settings: Settings, args: argparse.Namespace) -> int:
    import uvicorn

    # In development, linked accounts sync on schedule with no setup: run the job
    # inside the API unless SONGNEXUS_SYNC_IN_PROCESS is set (environment or .env).
    # The server reads the environment itself (also in its --reload child process).
    # Overlapping syncs are safe: an account's plays are only ever counted once.
    if settings.environment == "development" and "sync_in_process" not in settings.model_fields_set:
        os.environ["SONGNEXUS_SYNC_IN_PROCESS"] = "true"
    # Local development only; deployments run uvicorn from the container's CMD.
    uvicorn.run(
        "songnexus.service.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        access_log=False,  # its log lines include query strings (QA review, privacy)
    )
    return EXIT_OK


def _cmd_quality(settings: Settings, _args: argparse.Namespace) -> int:
    from songnexus.catalog.quality import gate_passes, run_quality_checks
    from songnexus.storage.db import make_engine, session_scope

    with session_scope(make_engine(settings.database_url)) as session:
        results = run_quality_checks(session)
    passed = gate_passes(results)
    _print({"gatePassed": passed, "checks": [{**asdict(r), "passed": r.passed} for r in results]})
    return EXIT_OK if passed else EXIT_FAILED


def _cmd_purge(settings: Settings, _args: argparse.Namespace) -> int:
    from songnexus.jobs.purge import run_purge
    from songnexus.storage.db import make_engine

    _print(run_purge(make_engine(settings.database_url)))
    return EXIT_OK


MIN_SEARCH_MRR = 0.95
MIN_IMPORT_PRECISION = 0.98


def _cmd_sync_accounts(settings: Settings, _args: argparse.Namespace) -> int:
    import httpx

    from songnexus.service.readmodel import load_read_model
    from songnexus.service.sync_job import run_sync
    from songnexus.storage.db import make_engine

    engine = make_engine(settings.database_url)
    model = load_read_model(engine, settings.genre_sources)
    with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as http:
        _print(run_sync(engine, settings, model, http))
    return EXIT_OK


def _cmd_new_token_key(_settings: Settings, _args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from songnexus.accounts.crypto import new_key

    key_id = datetime.now(UTC).strftime("k%Y%m%d")
    # The key is the output; it is shown once and never logged.
    _print(
        {
            "SONGNEXUS_TOKEN_KEYS": json.dumps({key_id: new_key()}),
            "SONGNEXUS_TOKEN_KEY_ID": key_id,
            "note": "Store in Secret Manager. To rotate, add this key and switch the ID.",
        }
    )
    return EXIT_OK


def import_match_report(engine: Any, cases_path: Path) -> Any:
    """Resolves the labeled import names and scores them (shared with the golden test)."""
    from songnexus.core import ids
    from songnexus.core.resolution import evaluate_matches, resolve_batch
    from songnexus.service.readmodel import load_read_model

    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    model = load_read_model(engine)
    resolutions = resolve_batch(model.search, [c["query"] for c in cases])
    expected = [ids.artist_id(c["mbid"]) if c["mbid"] else None for c in cases]
    return evaluate_matches(resolutions, expected, [c["category"] for c in cases])


def _cmd_eval_import(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.storage.db import make_engine

    path = args.cases or settings.data_dir / "eval" / "import_match_cases.json"
    report = import_match_report(make_engine(settings.database_url), path)
    passed = report.precision >= MIN_IMPORT_PRECISION
    _print({"gatePassed": passed, "minPrecision": MIN_IMPORT_PRECISION, **asdict(report)})
    return EXIT_OK if passed else EXIT_FAILED


def _cmd_eval_songs(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.core.songs import Descriptors, genre_separation, weight_study
    from songnexus.service.readmodel import load_read_model
    from songnexus.storage import catalog_repository as repo
    from songnexus.storage.db import make_engine, session_scope

    engine = make_engine(settings.database_url)
    graph = load_read_model(engine, settings.genre_sources).graph
    with session_scope(engine) as session:
        rows = repo.descriptors_by_primary_artist(session)
    recordings = {}
    for recording_id, artist_id, fields in rows:
        node = graph.nodes.get(artist_id)
        if node is not None and node.genres:
            recordings[recording_id] = (
                Descriptors.from_fields(fields),
                artist_id,
                frozenset(g.genre_id for g in node.genres),
                node.genres[0].genre_id,
            )
    if args.fit_weights:
        _print(asdict(weight_study(recordings)))
        return EXIT_OK
    report = genre_separation(recordings)
    # No gate yet: this is the first measurement (plan R2-4); it is recorded in
    # docs/handoff/evaluations.md and a floor is set from it, never before it.
    _print({**asdict(report), "recordingsWithDescriptors": len(rows)})
    return EXIT_OK


def _cmd_eval_listening(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.catalog.listening_eval import lastfm_rows, listener_sets, listening_agreement
    from songnexus.catalog.snapshot import read_snapshot

    archive: Path = args.lastfm or settings.raw_dir("lastfm") / "lastfm-dataset-360K.tar.gz"
    colistened = {
        r.body["artist"]: [row["artist"] for row in r.body.get("similar", [])]
        for r in read_snapshot(settings.listenbrainz_snapshot_path)
    }
    catalog = {
        r["source_entity_id"]
        for r in _musicbrainz_batch(settings).mappings.values()
        if r["entity_type"] == "artist"
    }
    report = listening_agreement(colistened, listener_sets(lastfm_rows(archive), catalog))
    # Research data (registry tier EVALUATION): only this aggregate is reported.
    _print(asdict(report))
    return EXIT_OK


def _cmd_eval_genres(settings: Settings, _args: argparse.Namespace) -> int:
    from songnexus.catalog.canonicalize import SUPPLEMENTARY_SOURCE_ID
    from songnexus.catalog.enrich import DISCOGS_SOURCE_ID
    from songnexus.core.graph.genre_eval import genre_agreement
    from songnexus.service.readmodel import load_read_model
    from songnexus.storage.db import make_engine

    engine = make_engine(settings.database_url)
    musicbrainz = load_read_model(engine, [SUPPLEMENTARY_SOURCE_ID]).graph
    discogs = load_read_model(engine, [DISCOGS_SOURCE_ID]).graph
    report = genre_agreement(musicbrainz, discogs)
    # No gate yet: this is the first measurement (plan R2-1). It is recorded in
    # docs/handoff/evaluations.md and a gate is set from it, never before it.
    _print({"a": SUPPLEMENTARY_SOURCE_ID, "b": DISCOGS_SOURCE_ID, **asdict(report)})
    return EXIT_OK


MIN_COLLABORATION_RECALL = 0.95
COLLABORATION_EVAL_ARTISTS = 20


def _cmd_eval_collaborations(settings: Settings, _args: argparse.Namespace) -> int:
    from songnexus.catalog.collab_eval import collaboration_recall
    from songnexus.catalog.snapshot import read_snapshot
    from songnexus.service.readmodel import load_read_model
    from songnexus.storage.db import make_engine

    lock = json.loads(settings.seeds_path.with_suffix(".lock.json").read_text(encoding="utf-8"))
    seeds = [a["mbid"] for a in lock["artists"]][:COLLABORATION_EVAL_ARTISTS]
    graph = load_read_model(make_engine(settings.database_url)).graph
    report = collaboration_recall(graph, read_snapshot(settings.snapshot_path), seeds)
    passed = report.overall is not None and report.overall >= MIN_COLLABORATION_RECALL
    _print({"gatePassed": passed, "minRecall": MIN_COLLABORATION_RECALL, **asdict(report)})
    return EXIT_OK if passed else EXIT_FAILED


def _cmd_eval_search(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.core.search import EvalCase, evaluate
    from songnexus.service.readmodel import load_read_model
    from songnexus.storage.catalog_reader import canonical_ids_for_sources
    from songnexus.storage.db import make_engine, session_scope

    engine = make_engine(settings.database_url)
    raw_cases = json.loads(
        (args.cases or settings.data_dir / "eval" / "search_cases.json").read_text(encoding="utf-8")
    )["cases"]
    mbids = [r["mbid"] for c in raw_cases for r in c["relevant"]]
    with session_scope(engine) as session:
        canonical = canonical_ids_for_sources(session, mbids)
    unmapped = sorted({m for m in mbids if m not in canonical})
    cases = [
        EvalCase(
            c["query"],
            c["category"],
            frozenset(canonical[r["mbid"]] for r in c["relevant"] if r["mbid"] in canonical),
        )
        for c in raw_cases
    ]
    report = evaluate(load_read_model(engine).search, [c for c in cases if c.relevant])
    passed = report.mrr >= MIN_SEARCH_MRR and not unmapped
    _print(
        {
            "gatePassed": passed,
            "minMrr": MIN_SEARCH_MRR,
            "unmappedLabels": unmapped,
            **asdict(report),
        }
    )
    return EXIT_OK if passed else EXIT_FAILED


OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi.json"


def openapi_document() -> str:
    """Returns the API contract as canonical JSON (stable key order, trailing newline)."""
    from songnexus.service.app import create_app

    app = create_app(Settings(environment="production"), state=_contract_state())
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _contract_state() -> Any:
    """A state object sufficient to build routes; the contract never touches it."""
    from songnexus.identity.tokens import FirebaseIdTokenVerifier
    from songnexus.service.deps import AppState
    from songnexus.service.ratelimit import RateLimiter
    from songnexus.service.readmodel import ReadModelHolder
    from songnexus.storage.db import make_engine

    def no_model() -> Any:
        raise RuntimeError("not used when generating the contract")

    holder = ReadModelHolder(no_model, lambda: None)
    return AppState(
        Settings(), make_engine("sqlite://"), holder, RateLimiter(), FirebaseIdTokenVerifier("")
    )


def _write_generated(path: Path, document: str, *, command: str, check: bool) -> int:
    """Writes a generated file, or with ``check`` fails if the committed copy differs."""
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if check:
        in_sync = current == document
        if not in_sync:
            print(
                f"{path.name} is out of date; run `songnexus {command}` and review the diff.",
                file=sys.stderr,
            )
        return EXIT_OK if in_sync else EXIT_FAILED
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(document)
    _print({"written": str(path), "changed": current != document})
    return EXIT_OK


def _cmd_openapi(_settings: Settings, args: argparse.Namespace) -> int:
    return _write_generated(OPENAPI_PATH, openapi_document(), command="openapi", check=args.check)


RESOURCES_PATH = Path(__file__).resolve().parents[3] / "docs" / "resources.md"


def _cmd_resources(_settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.catalog.sources import render_markdown

    return _write_generated(
        RESOURCES_PATH, render_markdown(), command="resources", check=args.check
    )


# --- Artist photos (ADR 0009) -----------------------------------------------------------


def _cmd_fetch_images(settings: Settings, args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from songnexus.catalog.http import SourceRequestError
    from songnexus.catalog.wikidata.fetch import WikidataClient
    from songnexus.catalog.wikidata.images import CommonsClient, http_client, run_fetch_images
    from songnexus.storage.db import make_engine

    # Both clients get the generic User-Agent; no contact is ever sent (ADR 0009).
    wikidata = WikidataClient(
        sparql_url=settings.wikidata_sparql_url,
        cache_dir=settings.raw_dir("wikidata-images"),
        http=http_client("application/sparql-results+json"),
    )
    commons = CommonsClient(cache_dir=settings.raw_dir("commons"))
    try:
        result = run_fetch_images(
            make_engine(settings.database_url),
            wikidata,
            commons,
            now=datetime.now(UTC),
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except SourceRequestError as exc:
        print(f"fetch-images failed, nothing written: {exc}", file=sys.stderr)
        return EXIT_FAILED
    _print(result)
    return EXIT_OK


def _add_image_commands(commands: Any) -> None:
    images = commands.add_parser(
        "fetch-images",
        help="find freely licensed artist photos on Wikimedia Commons through Wikidata",
    )
    images.add_argument("--limit", type=int, help="only the first N artists (best-known first)")
    images.add_argument(
        "--dry-run", action="store_true", help="report coverage without writing to the database"
    )
    images.set_defaults(handler=_cmd_fetch_images)


# --- Around you (communities) ----------------------------------------------------------


def _cmd_fetch_communities(settings: Settings, _args: argparse.Namespace) -> int:
    from songnexus.catalog.communities import build_directory, write_directory
    from songnexus.catalog.wikidata.fetch import WikidataClient

    client = WikidataClient(
        sparql_url=settings.wikidata_sparql_url,
        cache_dir=settings.raw_dir("wikidata-communities"),
        contact=settings.wikidata_contact,
    )
    _print(write_directory(build_directory(client)))
    return EXIT_OK


def _cmd_community_charts(settings: Settings, _args: argparse.Namespace) -> int:
    from songnexus.service.community_job import run_community_charts
    from songnexus.service.readmodel import load_read_model
    from songnexus.storage.db import make_engine

    engine = make_engine(settings.database_url)
    model = load_read_model(engine, settings.genre_sources)
    _print(run_community_charts(engine, settings, model))
    return EXIT_OK


def _cmd_seed_community(settings: Settings, args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from songnexus.catalog.communities import load_directory
    from songnexus.core.community import Kind
    from songnexus.jobs.community_seed import SeedRefusedError, remove_synthetic, seed_community
    from songnexus.storage.db import make_engine, session_scope

    slug = args.campus or args.city
    kind = Kind.CAMPUS if args.campus else Kind.CITY
    try:
        engine = make_engine(settings.database_url)
        if args.remove:
            _print(remove_synthetic(engine, settings.environment, slug))
            return EXIT_OK
        community = load_directory().by_id.get(slug or "")
        if community is None or community.kind is not kind:
            raise SeedRefusedError(f"no {kind.value.lower()} with ID {slug!r} in the directory")
        if args.listeners is None:
            raise SeedRefusedError("--listeners is required")
        now = datetime.now(UTC)
        result = seed_community(engine, settings.environment, community, args.listeners, now)
    except SeedRefusedError as exc:
        print(f"seed-community refused: {exc}", file=sys.stderr)
        return EXIT_FAILED

    from songnexus.service.community_job import compute
    from songnexus.service.readmodel import load_read_model

    model = load_read_model(engine, settings.genre_sources)
    with session_scope(engine) as session:
        chart = compute(session, settings, model, community.id, now)
    _print({**result, "chartUnlocked": chart.unlocked, "chartArtists": len(chart.artists)})
    return EXIT_OK


def _add_community_commands(commands: Any) -> None:
    commands.add_parser(
        "fetch-communities",
        help="rebuild the Around you campus and city list from Wikidata (catalog/communities.json)",
    ).set_defaults(handler=_cmd_fetch_communities)
    commands.add_parser(
        "community-charts", help="recompute stale Around you charts (run hourly)"
    ).set_defaults(handler=_cmd_community_charts)
    seed = commands.add_parser(
        "seed-community",
        help="DEVELOPMENT ONLY: add (or --remove) synthetic members so a chart can be demoed",
    )
    target = seed.add_mutually_exclusive_group()
    target.add_argument("--campus", help="campus ID (slug) from the directory")
    target.add_argument("--city", help="city ID (slug) from the directory")
    seed.add_argument("--listeners", type=int, help="how many synthetic listeners to create")
    seed.add_argument(
        "--remove", action="store_true", help="delete synthetic members (of one community, or all)"
    )
    seed.set_defaults(handler=_cmd_seed_community)
    demo = commands.add_parser(
        "seed-demo",
        help="DEVELOPMENT ONLY: create (or --reset) the labeled synthetic demo cohort and the "
        "local demo account (docs/synthetic-data.md)",
    )
    demo.add_argument("--reset", action="store_true", help="remove everything seed-demo created")
    demo.set_defaults(handler=_cmd_seed_demo)


def _cmd_seed_demo(settings: Settings, args: argparse.Namespace) -> int:
    from datetime import UTC, date, datetime

    from songnexus.catalog.communities import load_directory
    from songnexus.core import game, trivia
    from songnexus.jobs.demo_seed import SeedRefusedError, preflight, reset_demo, seed_demo
    from songnexus.service.community_job import compute
    from songnexus.service.readmodel import EmptyCatalogError, load_read_model
    from songnexus.service.routes.discover import _label_facts
    from songnexus.service.routes.play import KINDS
    from songnexus.storage.db import make_engine, session_scope

    engine = make_engine(settings.database_url)
    now = datetime.now(UTC)
    try:
        if args.reset:
            _print(reset_demo(engine, settings.environment, now))
            return EXIT_OK
        preflight(engine, settings.environment)
        directory = load_directory()
        try:
            model = load_read_model(engine, settings.genre_sources)
        except EmptyCatalogError as exc:
            raise SeedRefusedError("the catalog is empty; run `songnexus ingest` first") from exc
        graph = model.graph
        pairs = game.candidate_pairs(
            graph.adjacency(KINDS), [n.id for n in graph.nodes.values() if n.detail_level == "full"]
        )
        index = trivia.build_index(graph)
        with session_scope(engine) as session:
            labels = _label_facts(session)

        def puzzle_par(day: date) -> int | None:
            try:
                return game.puzzle_for(day, pairs).par
            except ValueError:
                return None

        def trivia_total(day: date) -> int | None:
            try:
                return len(trivia.quiz_for(day, index, labels).questions)
            except ValueError:
                return None

        unlocked: dict[str, bool] = {}

        def build_charts(ids: list[str], at: datetime) -> None:
            for community_id in ids:
                with session_scope(engine) as session:
                    unlocked[community_id] = compute(
                        session, settings, model, community_id, at
                    ).unlocked

        def city_of(campus: str) -> str | None:
            found = directory.by_id.get(campus)
            return found.city_id if found else None

        result = seed_demo(
            engine,
            settings.environment,
            now,
            known_communities=lambda c: c in directory.by_id,
            city_of=city_of,
            build_charts=build_charts,
            puzzle_par=puzzle_par,
            trivia_total=trivia_total,
        )
    except SeedRefusedError as exc:
        print(f"seed-demo refused: {exc}", file=sys.stderr)
        return EXIT_FAILED
    _print({**result, "unlockedCharts": sorted(c for c, ok in unlocked.items() if ok)})
    return EXIT_OK


def _cmd_transfer(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.storage.db import make_engine
    from songnexus.storage.transfer import transfer

    url = os.environ.get(args.target_url_env)
    if not url:
        print(f"Set {args.target_url_env} securely to the destination URL", file=sys.stderr)
        return EXIT_FAILED
    source = make_engine(settings.database_url)
    target = make_engine(url)
    try:
        _print(transfer(source, target, apply=args.apply))
    finally:
        source.dispose()
        target.dispose()
    return EXIT_OK


def _cmd_merge(_settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.catalog.merge import merge_snapshots

    _print(merge_snapshots(args.inputs, args.output))
    return EXIT_OK


def _cmd_fetch_recordings(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.catalog.musicbrainz.client import MusicBrainzClient
    from songnexus.catalog.musicbrainz.recordings import fetch_recordings

    client = MusicBrainzClient(
        base_url=settings.musicbrainz_base_url,
        cache_dir=settings.raw_cache_dir,
        contact=settings.musicbrainz_contact,
        min_interval_s=settings.musicbrainz_min_interval_s,
    )
    _print(fetch_recordings(client, args.artist, args.output, limit=args.limit))
    return EXIT_OK


def _add_expansion_commands(commands: Any) -> None:
    recordings = commands.add_parser(
        "fetch-recordings", help="fetch singles and album recordings for an artist MBID"
    )
    recordings.add_argument(
        "--artist", required=True, action="append", help="artist MBID; repeat for several"
    )
    recordings.add_argument("--output", required=True, type=Path)
    recordings.add_argument("--limit", default=500, type=int, help="recordings per artist")
    recordings.set_defaults(handler=_cmd_fetch_recordings)
    transfer = commands.add_parser(
        "transfer-database", help="copy to an EMPTY database; dry run by default"
    )
    transfer.add_argument("--target-url-env", default="SONGNEXUS_TARGET_DATABASE_URL")
    transfer.add_argument(
        "--apply", action="store_true", help="migrate target and copy; stop source writers first"
    )
    transfer.set_defaults(handler=_cmd_transfer)
    merge = commands.add_parser(
        "merge-snapshots", help="union MusicBrainz snapshots; later input wins"
    )
    merge.add_argument("inputs", nargs="+", type=Path)
    merge.add_argument("--output", required=True, type=Path)
    merge.set_defaults(handler=_cmd_merge)


def build_parser() -> argparse.ArgumentParser:
    """Returns the argument parser (exposed for tests and documentation)."""
    parser = argparse.ArgumentParser(prog="songnexus", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    _add_expansion_commands(commands)

    migrate = commands.add_parser("migrate", help="apply database migrations")
    migrate.add_argument("revision", nargs="?", default="head")
    migrate.add_argument("--down", action="store_true", help="downgrade to the revision")
    migrate.set_defaults(handler=_cmd_migrate)

    fetch = commands.add_parser("fetch", help="fetch MusicBrainz data into a snapshot")
    fetch.add_argument("--seeds", type=Path, help="seed file (default: data/seeds)")
    fetch.add_argument("--output", type=Path, help="snapshot path (default: data/samples)")
    fetch.add_argument("--max-profiles", type=int, default=1500)
    fetch.set_defaults(handler=_cmd_fetch)

    serve = commands.add_parser("serve", help="run the API locally (default 127.0.0.1:8790)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8790)
    serve.add_argument("--reload", action="store_true", help="restart on code changes")
    serve.set_defaults(handler=_cmd_serve)

    discogs = commands.add_parser(
        "fetch-discogs", help="extract catalog artists' masters from a Discogs dump (~600 MB)"
    )
    discogs.add_argument("--dump-date", required=True, help="dump to use, YYYYMMDD (e.g. 20261001)")
    discogs.set_defaults(handler=_cmd_fetch_discogs)

    ingest = commands.add_parser(
        "ingest", help="ingest the committed snapshots (MusicBrainz and its enrichment sources)"
    )
    ingest.add_argument(
        "--snapshot", type=Path, help="ingest this MusicBrainz snapshot alone, without enrichment"
    )
    ingest.add_argument(
        "--no-enrichment",
        action="store_true",
        help="ingest MusicBrainz only, without the enrichment snapshots",
    )
    ingest.set_defaults(handler=_cmd_ingest)
    ingest.add_argument(
        "--with-enrichment",
        action="store_true",
        help="retain bundled enrichment with a custom merged snapshot",
    )

    eval_search = commands.add_parser(
        "eval-search", help=f"evaluate search on the labeled set (gate: MRR >= {MIN_SEARCH_MRR})"
    )
    eval_search.add_argument("--cases", type=Path)
    eval_search.set_defaults(handler=_cmd_eval_search)

    eval_import = commands.add_parser(
        "eval-import",
        help=f"evaluate import name matching (gate: precision >= {MIN_IMPORT_PRECISION})",
    )
    eval_import.add_argument("--cases", type=Path)
    eval_import.set_defaults(handler=_cmd_eval_import)

    # Commands without options.
    for name, help_text, handler in (
        (
            "fetch-wikidata",
            "fetch Discogs artist links and the genre hierarchy from Wikidata",
            _cmd_fetch_wikidata,
        ),
        (
            "fetch-listenbrainz",
            "fetch listener counts and co-listening for catalog artists",
            _cmd_fetch_listenbrainz,
        ),
        ("quality", "run data-quality checks (the gate)", _cmd_quality),
        (
            "eval-collaborations",
            f"collaborations recall vs raw MusicBrainz data (gate >= {MIN_COLLABORATION_RECALL})",
            _cmd_eval_collaborations,
        ),
        (
            "eval-genres",
            "measure genre coverage and MusicBrainz-Discogs agreement",
            _cmd_eval_genres,
        ),
        ("purge", "remove expired sessions and deleted accounts", _cmd_purge),
        (
            "sync-accounts",
            "sync linked listening accounts that are due (run every 15 minutes)",
            _cmd_sync_accounts,
        ),
        (
            "new-token-key",
            "print a new key for encrypting linked-account tokens",
            _cmd_new_token_key,
        ),
    ):
        commands.add_parser(name, help=help_text).set_defaults(handler=handler)
    _add_community_commands(commands)
    _add_image_commands(commands)

    acousticbrainz = commands.add_parser(
        "fetch-acousticbrainz", help="fetch audio descriptors for catalog recordings"
    )
    acousticbrainz.add_argument(
        "--cached-only", action="store_true", help="build the snapshot from the local cache only"
    )
    acousticbrainz.set_defaults(handler=_cmd_fetch_acousticbrainz)

    eval_songs = commands.add_parser(
        "eval-songs", help="song similarity vs genre agreement (AUC; 0.5 is chance)"
    )
    eval_songs.add_argument(
        "--fit-weights",
        action="store_true",
        help="refit the similarity weights on half the artists, measure on the other half",
    )
    eval_songs.set_defaults(handler=_cmd_eval_songs)

    eval_listening = commands.add_parser(
        "eval-listening",
        help="ListenBrainz co-listening vs Last.fm 360K listener overlap (AUC; offline)",
    )
    eval_listening.add_argument("--lastfm", type=Path, help="the 360K archive (default: data/raw)")
    eval_listening.set_defaults(handler=_cmd_eval_listening)

    openapi = commands.add_parser("openapi", help="write the API contract (server/openapi.json)")
    openapi.add_argument("--check", action="store_true", help="fail if the file is out of date")
    openapi.set_defaults(handler=_cmd_openapi)

    resources = commands.add_parser(
        "resources", help="write the data-source page (docs/resources.md) from the registry"
    )
    resources.add_argument("--check", action="store_true", help="fail if the file is out of date")
    resources.set_defaults(handler=_cmd_resources)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the CLI and returns the process exit code."""
    # Results are UTF-8 JSON on every platform (Windows consoles default to cp1252).
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    exit_code: int = args.handler(settings, args)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
