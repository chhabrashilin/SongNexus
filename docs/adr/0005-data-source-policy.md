# ADR 0005: One registry for every data source, with a license tier

- **Status:** Accepted, 2026-11-01 (R2-0). Extends [ADR 0003](0003-musicbrainz-licensing.md).
- **Context:** R2 adds sources beyond MusicBrainz: Discogs and Wikidata (genres), AcousticBrainz (audio descriptors),
  ListenBrainz (listening), Kaggle and research datasets (evaluation), and listeners' linked accounts. Each has its own
  terms. SongNexus is meant to become a YouTube Music feature, so every fact must be traceable to a source whose license
  allows that use, and a reviewer must be able to see the full list in one place.
- **Decision:**
  1. `server/src/songnexus/catalog/sources.py` is the only list of sources. Each entry records the license as the
     provider states it, the URL where it is stated, the date it was checked, what it feeds, and attribution text.
  2. Every source has a **tier**:
     - `PRODUCTION`: CC0 or equivalent; may ship in a commercial product.
     - `NON_COMMERCIAL`: may be served in the capstone build; a commercial launch deletes it by `source_id`
       (as ADR 0003 already does for MusicBrainz genres).
     - `EVALUATION`: offline evaluation only; never stored in the catalog, never served.
  3. A source is registered **before** code reads from it, with status `PLANNED`; it becomes `IN_USE` in the same
     change that wires it in. A dataset whose license is unstated is not used.
  4. Ingest refuses to store a fact from a source that is not an in-use, non-evaluation catalog source
     (`UnregisteredSourceError`), and a test checks that every stored fact traces to such a source.
  5. The registry is served as `ListDataSources` (`GET /v1/dataSources`), shown on the About page, and rendered to
     [docs/resources.md](../resources.md) by `songnexus resources`; CI fails when that page is stale.
  6. Datasets derived from another platform's API (for example Kaggle uploads of Spotify audio features) are
     `EVALUATION` even when the uploader labels them CC0: an uploader cannot relicense data they obtained under API terms.
- **Consequences:** adding a source is a reviewed change to one file, and the license review is visible in code review.
  The About page and docs can never disagree with what the pipeline accepts. The cost is a little ceremony per source,
  which is the point.
