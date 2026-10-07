"""Command-line entry point: ``songnexus <command>``.

Commands print a JSON result on stdout (logs go to stderr) and exit non-zero on
failure, so they compose in CI and scripts.
"""

from __future__ import annotations

import argparse
import io
import json
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


def _cmd_ingest(settings: Settings, args: argparse.Namespace) -> int:
    from songnexus.catalog.ingest import ingest_snapshot
    from songnexus.storage import migrate
    from songnexus.storage.db import make_engine

    engine = make_engine(settings.database_url)
    migrate.upgrade(engine)
    _print(ingest_snapshot(engine, args.snapshot or settings.snapshot_path))
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


def _cmd_openapi(_settings: Settings, args: argparse.Namespace) -> int:
    document = openapi_document()
    current = OPENAPI_PATH.read_text(encoding="utf-8") if OPENAPI_PATH.exists() else ""
    if args.check:
        in_sync = current == document
        if not in_sync:
            print(
                f"{OPENAPI_PATH.name} is out of date; run `songnexus openapi` and review the diff.",
                file=sys.stderr,
            )
        return EXIT_OK if in_sync else EXIT_FAILED
    with OPENAPI_PATH.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(document)
    _print({"written": str(OPENAPI_PATH), "changed": current != document})
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Returns the argument parser (exposed for tests and documentation)."""
    parser = argparse.ArgumentParser(prog="songnexus", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    migrate = commands.add_parser("migrate", help="apply database migrations")
    migrate.add_argument("revision", nargs="?", default="head")
    migrate.add_argument("--down", action="store_true", help="downgrade to the revision")
    migrate.set_defaults(handler=_cmd_migrate)

    fetch = commands.add_parser("fetch", help="fetch MusicBrainz data into a snapshot")
    fetch.add_argument("--seeds", type=Path, help="seed file (default: data/seeds)")
    fetch.add_argument("--output", type=Path, help="snapshot path (default: data/samples)")
    fetch.add_argument("--max-profiles", type=int, default=1500)
    fetch.set_defaults(handler=_cmd_fetch)

    ingest = commands.add_parser("ingest", help="ingest a snapshot into the database")
    ingest.add_argument("--snapshot", type=Path)
    ingest.set_defaults(handler=_cmd_ingest)

    quality = commands.add_parser("quality", help="run data-quality checks (the gate)")
    quality.set_defaults(handler=_cmd_quality)

    eval_search = commands.add_parser(
        "eval-search", help=f"evaluate search on the labeled set (gate: MRR >= {MIN_SEARCH_MRR})"
    )
    eval_search.add_argument("--cases", type=Path)
    eval_search.set_defaults(handler=_cmd_eval_search)

    purge = commands.add_parser("purge", help="remove expired sessions and deleted accounts")
    purge.set_defaults(handler=_cmd_purge)

    openapi = commands.add_parser("openapi", help="write the API contract (server/openapi.json)")
    openapi.add_argument("--check", action="store_true", help="fail if the file is out of date")
    openapi.set_defaults(handler=_cmd_openapi)
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
