"""Command-line entry points: `songnexus <command>`.

fetch         Stage 0 (network): seeds -> raw MusicBrainz snapshot
init-db       Create database tables
ingest        Stages 1-6 (offline): snapshot -> canonical DB
quality       Run data-quality checks against the database
eval-search   Run the search evaluation harness
eval-agent    Run the agent evaluation harness
bench         Run graph-algorithm benchmarks
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from songnexus.core.config import REPO_ROOT, get_settings
from songnexus.core.logging import configure_logging


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_fetch(args: argparse.Namespace) -> int:
    from songnexus.integrations.musicbrainz.client import MusicBrainzClient
    from songnexus.pipelines.fetch_musicbrainz import run_fetch

    settings = get_settings()
    client = MusicBrainzClient(
        base_url=settings.musicbrainz_base_url,
        cache_dir=settings.raw_cache_dir,
        contact=settings.musicbrainz_contact,
        min_interval_s=settings.musicbrainz_min_interval_s,
    )
    seeds_path = Path(args.seeds) if args.seeds else settings.seeds_path
    result = run_fetch(
        client,
        seeds_path=seeds_path,
        snapshot_path=Path(args.out) if args.out else settings.sample_snapshot_path,
        lock_path=seeds_path.with_suffix(".lock.json"),
    )
    _print(result)
    return 1 if result["unresolved"] else 0


def cmd_init_db(_: argparse.Namespace) -> int:
    from songnexus.db.session import create_all, get_engine

    create_all(get_engine())
    _print({"status": "ok"})
    return 0


def cmd_bootstrap(_: argparse.Namespace) -> int:
    """Idempotent container start-up step: never re-ingests a loaded database."""
    from sqlalchemy import func, select

    from songnexus.db.models import IngestionRun
    from songnexus.db.session import create_all, get_engine, session_scope
    from songnexus.pipelines.ingest import ingest_snapshot

    engine = get_engine()
    create_all(engine)
    with session_scope(engine) as session:
        loaded = session.scalar(
            select(func.count()).select_from(IngestionRun).where(IngestionRun.status == "succeeded")
        )
    if loaded:
        _print({"status": "already loaded", "succeeded_runs": loaded})
        return 0
    _print(ingest_snapshot(engine, get_settings().sample_snapshot_path))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from songnexus.db.session import create_all, get_engine
    from songnexus.pipelines.ingest import ingest_snapshot

    settings = get_settings()
    engine = get_engine()
    create_all(engine)
    stats = ingest_snapshot(engine, Path(args.snapshot) if args.snapshot else settings.sample_snapshot_path)
    _print(stats)
    return 0


def cmd_quality(_: argparse.Namespace) -> int:
    from songnexus.db.session import get_engine, session_scope
    from songnexus.pipelines.quality import run_quality_checks

    with session_scope(get_engine()) as session:
        results = run_quality_checks(session)
    _print([r.__dict__ for r in results])
    return 0 if all(r.passed for r in results) else 1


def cmd_eval_search(args: argparse.Namespace) -> int:
    from songnexus.evaluation.search_eval import run_search_eval

    _print(run_search_eval(Path(args.cases), k=args.k))
    return 0


def cmd_eval_agent(args: argparse.Namespace) -> int:
    from songnexus.evaluation.agent_eval import run_agent_eval

    _print(run_agent_eval(Path(args.cases), mode=args.mode))
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    from songnexus.evaluation.benchmarks import run_path_benchmarks

    _print(run_path_benchmarks(pairs=args.pairs, seed=args.seed))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="songnexus")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch raw MusicBrainz data into a snapshot (network)")
    fetch.add_argument("--seeds")
    fetch.add_argument("--out")
    fetch.set_defaults(func=cmd_fetch)

    sub.add_parser("init-db", help="create tables").set_defaults(func=cmd_init_db)
    sub.add_parser("bootstrap", help="create tables and load the sample if empty").set_defaults(func=cmd_bootstrap)

    ingest = sub.add_parser("ingest", help="ingest a snapshot into the database (offline)")
    ingest.add_argument("--snapshot")
    ingest.set_defaults(func=cmd_ingest)

    sub.add_parser("quality", help="run data-quality checks").set_defaults(func=cmd_quality)

    eval_search = sub.add_parser("eval-search", help="evaluate search quality")
    eval_search.add_argument("--cases", default=str(REPO_ROOT / "evaluation" / "search_cases.json"))
    eval_search.add_argument("--k", type=int, default=5)
    eval_search.set_defaults(func=cmd_eval_search)

    eval_agent = sub.add_parser("eval-agent", help="evaluate the discovery agent")
    eval_agent.add_argument("--cases", default=str(REPO_ROOT / "evaluation" / "agent_cases.json"))
    eval_agent.add_argument("--mode", choices=["deterministic", "llm"], default="deterministic")
    eval_agent.set_defaults(func=cmd_eval_agent)

    bench = sub.add_parser("bench", help="benchmark path algorithms on the loaded graph")
    bench.add_argument("--pairs", type=int, default=300)
    bench.add_argument("--seed", type=int, default=7)
    bench.set_defaults(func=cmd_bench)
    return parser


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=False)
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
