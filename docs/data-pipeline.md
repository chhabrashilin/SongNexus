# Data pipeline

```
seeds.json ─▶ [0 fetch] ─▶ snapshot.jsonl.gz ─▶ [1 validate] ─▶ [2 normalize] ─▶ [3 resolve]
   (network, rate-limited,        (the reproducibility        ─▶ [4 canonical rows] ─▶ [5 write] ─▶ [6 run record]
    cached, resumable)             boundary; committed)          (pure function)          (one transaction)
                                                                                           ─▶ quality checks ─▶ read-model rebuild
```

## Stage 0: fetch (`songnexus fetch`)

The only stage that touches the network.

1. **Seed resolution.** Each seed name is searched (`artist:"X" OR alias:"X"`, so renamed artists such as
   *Kanye West → Ye* are found) and resolved with the entity-resolution matcher. An *ambiguous* or
   *no-match* decision **fails** the seed with the candidate list. A human pins the MBID in
   `data/seeds/seed_artists.json` together with a mandatory `pin_reason`. Resolution outcomes are written to
   `seed_artists.lock.json`.
2. **Album selection** per artist: studio albums only (primary type *Album*, no secondary types), ranked by
   MusicBrainz rating votes (a transparent, source-provided popularity proxy), top N (default 4).
3. **Release selection** per album: official releases; avoid *clean/edited* versions (they often use different
   recordings with sparser credits); then earliest date, preferred country, fewest tracks (standard edition), then ID.
4. **Release lookup** with recordings, artist credits and recording-level artist relationships (producer, vocal,
   instrument, engineer, samples).

Etiquette and resilience: ≥ 1.1 s between requests, a descriptive User-Agent (the contact is configurable via
`SONGNEXUS_MUSICBRAINZ_CONTACT`), retries with exponential backoff that honor `Retry-After` on 429/5xx, an
on-disk cache per request (atomic writes), and resumption from the cache after interruption. The snapshot contains
only the records requested for the *current* seed list, sorted and gzip-timestamped deterministically.

The committed sample has 285 records (28 artists, 102 albums) and was fetched with 315 requests over the 3 iterations
it took to pin the ambiguous seeds.

## Stages 1–4: canonicalize (pure, `pipelines/canonicalize.py`)

- **Validate:** Pydantic models accept only the fields used. A record that fails validation is *rejected and
  counted*; the rest of the batch continues (partial-failure tolerance).
- **Normalize:** one `normalize()` for ingestion, matching and search (Unicode folding, typographic
  hyphen/quote folding, `&`→`and`, `$`→`s`, punctuation removal).
- **Resolve:** artists by MBID (exact, confidence 1.0); fuller *lookup* data wins over *credit stubs*; tracks by
  the deduplication key ([data-model.md](data-model.md#track-deduplication)).
- **Interpret credits:** artist-credit join phrases give primary vs. featured (anything after *feat./ft./with* is
  featured). Relationship types map to roles via an explicit table. Unmapped types are counted, never guessed.
- Artist relationship direction follows MusicBrainz `direction` relative to the looked-up artist, so
  `(member) -member_of-> (band)` comes out the same whether it was seen from the member's or the band's lookup.

Because this is a pure function, it is unit-tested on synthetic records, including determinism under input
reordering.

## Stages 5–6: write (`pipelines/ingest.py`)

- Run bookkeeping in its **own** transactions, so a failed run is recorded as `failed` with its error.
- All data in **one** transaction:
  - raw records upserted by `(source, request_key)`;
  - entities **upserted** by deterministic ID and never deleted (another source may reference them);
  - facts **synced per source**: after the run, the facts attributed to MusicBrainz are exactly those in the
    snapshot. Stale rows are deleted, so the database is a function of its snapshots.
- Stats: per-table inserted/updated/deleted, rejected records, ignored relation types, records per second.

Idempotency is tested: ingesting the same snapshot twice yields zero inserts and zero deletes (SQLite and
PostgreSQL), and removing a record from the snapshot deletes exactly the facts only it asserted.

## Quality checks (`songnexus quality`)

18 invariants, including: referential integrity of credits and relationships; no self-relationships; provenance
populated on every fact; confidence within [0, 1]; every track has a primary artist; every entity maps to a source
record; every album has tracks; plausible track lengths; well-formed dates; no two fully loaded artists sharing a
normalized name. All pass on the sample; CI enforces this on every change.

## Incremental ingestion (planned)

`raw_records.content_hash` already allows skipping unchanged records. When ingestion time matters (Phase 1+),
canonicalization can be restricted to changed records and their dependents.
