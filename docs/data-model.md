# Part 3: Data model

The authoritative DDL is generated from the ORM models: [schema.sql](schema.sql)
(`python scripts/generate_schema_sql.py`). This document explains the design.

## Three layers

```
raw_records ──(provenance FK)──┐
                               ▼
canonical entities ◀──── facts (credits, relationships, aliases, genres, links)
artists · tracks · albums · genres       every fact: source_id, raw_record_id, ingestion_run_id, confidence
          ▲
entity_source_mappings: which source record became which entity, how, and how sure we are
```

1. **Raw** (`raw_records`): source responses exactly as retrieved (JSONB), keyed by `(source_id, request_key)`,
   with URL, retrieval time and content hash. Never edited. This is what "show me the source" resolves to.
2. **Canonical entities**: one row per real-world thing, with deterministic UUIDv5 IDs.
3. **Facts**: relationships between entities. Each row carries full provenance.

The artist graph is **not stored**. It is projected from facts at load time (ADR-001), so there is exactly one
source of truth, and changing a weighting rule never requires a data migration.

## Entities

| Table | Key columns | Notes |
|---|---|---|
| `artists` | `id`, `name`, `normalized_name`, `artist_type`, `country`, `disambiguation`, `begin_date`, `hydrated` | `hydrated=false` means the artist is known only from credits (their own discography is not loaded) |
| `tracks` | `id`, `title` (base title), `normalized_title`, `length_ms`, `dedup_key` UNIQUE | One row per *song*, not per recording (see deduplication) |
| `albums` | `id`, `title`, `primary_type`, `first_release_date` | A MusicBrainz *release group* |
| `genres` | `id`, `name`, `normalized_name` UNIQUE | Source genre tags |

## Facts

| Table | Meaning | Uniqueness |
|---|---|---|
| `track_credits` | artist has `role` (primary, featured, producer, vocal, instrument, engineer, sampled, …) on a track, with `role_detail` (e.g. "drums", "co") and `credited_as` | `(track_id, artist_id, role, role_detail)` |
| `album_credits` | release-level credits (album producers, common on older records) | `(album_id, artist_id, role, role_detail)` |
| `album_artists`, `album_tracks` | album credit and tracklist | composite PKs |
| `artist_relationships` | directed: `(source) -member_of-> (target)`, `collaboration`, `is_person`, `subgroup`, `supporting_musician`, `teacher` | `(source, target, rel_type)` |
| `artist_aliases` | names, search hints, legal names, and every *credited-as* spelling seen on releases | `(artist_id, normalized_alias)` |
| `artist_genres` | genre tags with vote counts | `(artist_id, genre_id)` |
| `artist_links` | external IDs/URLs (Discogs, Wikidata, AllMusic…): the crosswalk for Phase 1 cross-source ER | `(artist_id, url)` |

Personal-life relations in the source (marriage, siblings) are deliberately **not** imported. They are not
musical connections, and surfacing them as graph edges is a product and privacy choice we decline. They are counted in
`ingestion_runs.stats.ignored_relation_types`.

## Provenance model

Every fact row has:

| Column | Answers |
|---|---|
| `source_id` → `data_sources` | Which source (name, homepage, license)? |
| `raw_record_id` → `raw_records` | Which exact API response asserted this? When was it retrieved, and from which URL? |
| `ingestion_run_id` → `ingestion_runs` | Which run, which pipeline version, from which snapshot hash? |
| `confidence` | How sure are we? 1.0 for exact source-ID links; lower for rule-based merges |

`entity_source_mappings` records resolution decisions per source record: `match_method`
(`musicbrainz_id`, `title_and_primary_artists`, and later `fuzzy_name` etc.), `confidence`, and `decision`
(`created`, `merged`, `review`). `GET /api/v1/provenance/edge?a=&b=` walks graph evidence → facts →
raw records → runs, so any link in the UI can be traced to the upstream JSON.

## Identifiers

`canonical_id(entity_type, key) = uuid5(namespace, f"{entity_type}:{key}")`, where the key names the source that
first introduced the entity (`musicbrainz:<mbid>`) or, for tracks, the deduplication key. Consequences:
re-ingesting the same snapshot produces identical IDs (idempotent upserts, stable URLs). Later sources attach
via mappings and never re-key an entity.

## Track deduplication

MusicBrainz models *recordings*; the same song appears as several recordings (album vs. remaster vs. explicit).
Counting each would inflate collaboration strength. A canonical track is keyed by
`normalize(base_title(title)) | sorted(primary artist ids)`, where `base_title` strips *feat.*, *remaster*,
*explicit/clean* and *album version* decorations but **keeps** *remix*, *live* and *acoustic* (different works,
different credits). The first recording creates the track (confidence 1.0); later ones are `merged`
(confidence 0.9). The sample merged 17 recordings.

## Indexes

| Index | Serves |
|---|---|
| `artists(normalized_name)`, `artist_aliases(normalized_alias)` | exact-name candidate generation for entity resolution |
| `track_credits(artist_id, role)`, `track_credits(track_id)` | artist credit lists; provenance lookups per track |
| `album_credits(artist_id, role)`, `album_credits(album_id)`, `album_tracks(track_id)` | album views; track → album |
| `artist_relationships(source_artist_id)`, `(target_artist_id)` | relationship lookups both directions |
| `entity_source_mappings(entity_type, entity_id)` + unique `(source_id, entity_type, source_entity_id)` | entity → sources; idempotent upserts |
| `raw_records` unique `(source_id, request_key)` | raw-record dedup |

**Planned (Phase 4, PostgreSQL only):** `CREATE EXTENSION pg_trgm;` with GIN trigram indexes on
`artists.normalized_name` and `artist_aliases.normalized_alias`, to move fuzzy candidate generation into SQL
once the catalog outgrows the in-memory index; `pgvector` HNSW index on an `entity_embeddings` table for
semantic retrieval.

## Planned tables (not in code yet)

These are listed so the design is visible. They are intentionally absent from the models until a phase implements them.

```sql
-- Phase 3: audio features (source TBD: AcousticBrainz dumps, CC0; Spotify only if terms allow)
CREATE TABLE audio_features (
  track_id VARCHAR(36) PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
  danceability REAL, energy REAL, valence REAL, tempo_bpm REAL, acousticness REAL,
  source_id VARCHAR(32) NOT NULL REFERENCES data_sources(id),
  raw_record_id INTEGER REFERENCES raw_records(id),
  ingestion_run_id INTEGER NOT NULL REFERENCES ingestion_runs(id),
  confidence REAL NOT NULL DEFAULT 1.0,
  CHECK (danceability BETWEEN 0 AND 1 AND energy BETWEEN 0 AND 1 AND valence BETWEEN 0 AND 1)
);

-- Phase 1: human review queue for ambiguous cross-source matches
CREATE TABLE resolution_reviews (
  id VARCHAR(36) PRIMARY KEY,
  source_id VARCHAR(32) NOT NULL, source_entity_id VARCHAR(128) NOT NULL,
  candidate_ids JSONB NOT NULL, scores JSONB NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'open',   -- open | accepted | rejected
  decided_entity_id VARCHAR(36), decided_by VARCHAR(64), decided_at TIMESTAMPTZ
);

-- Phase 3: community detection results, versioned with the graph
CREATE TABLE artist_communities (
  graph_version VARCHAR(64) NOT NULL, artist_id VARCHAR(36) NOT NULL REFERENCES artists(id),
  community_id INTEGER NOT NULL, algorithm VARCHAR(32) NOT NULL, resolution REAL NOT NULL,
  PRIMARY KEY (graph_version, algorithm, artist_id)
);
```

## Portability

The same models run on PostgreSQL (JSON → JSONB) and SQLite (tests, zero-setup development). Verified: the
committed snapshot ingests idempotently with all quality checks passing on both (PostgreSQL 16.2 via an embedded
server during development). `tests/integration/test_postgres.py` repeats the check against CI's PostgreSQL
service container. Schema migrations move to Alembic in Phase 1. Until then
`create_all` is used, which is acceptable only because every database can be rebuilt from snapshots.
