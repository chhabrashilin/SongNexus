# songnexus (server)

Core library, catalog pipeline and HTTP API for SongNexus. See the repository
[design doc](../docs/design/design-doc.md) for what and why.

## Develop

```bash
uv sync                      # create .venv with Python 3.12 and all dependencies
uv run pytest                # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run lint-imports          # layering contracts
```

## Layout

| Package | Responsibility | May depend on |
|---|---|---|
| `songnexus.core` | Pure domain logic: text, model, graph, search, resolution, game, filters | standard library only |
| `songnexus.storage` | Database models, sessions, repositories, migrations | `core` |
| `songnexus.catalog` | Catalog sources (MusicBrainz) and the ingestion pipeline | `core`, `storage` |
| `songnexus.identity` | Sign-in token verification, sessions, authorization policies | `core`, `storage` |
| `songnexus.jobs` | Batch jobs (purge, rebuilds) | `core`, `storage` |
| `songnexus.service` | HTTP API | everything above |

The layering is enforced by `lint-imports` in CI.
