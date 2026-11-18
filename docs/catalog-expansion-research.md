# SongNexus expansion research

Checked 2026-11-16. Prioritized survey; not an exhaustive inventory of every dataset. No dumps imported or hosted accounts provisioned.

## Best route to more songs

Full MusicBrainz core dumps, followed by Discogs release track lists, offer the strongest expansion beyond this project's seed snapshots. MusicBrainz currently reports 40,996,530 recordings and 59,059,474 release tracks. These overlap and are not counts of unique compositions or licensed audio files. [Statistics](https://musicbrainz.org/statistics).

| Source | Contribution and access | Recommendation / limits |
|---|---|---|
| [MusicBrainz](https://musicbrainz.org/doc/MusicBrainz_Database/Download) | Full PostgreSQL catalog dumps: recordings, works, credits, releases, identifiers | First priority; core CC0, supplementary fields have different [licenses](https://musicbrainz.org/doc/About/Data_License) |
| [Discogs](https://data.discogs.com/) | Releases, track lists, labels, credits, genres | Expand current genre-only use. Existing registry identifies CC0 dump fields; site returned 403, so recheck availability/terms before ingest |
| Wikidata | Aliases, cross-source IDs, composers, geography | Existing CC0 integration; enrichment rather than comprehensive recording inventory |
| [ListenBrainz](https://listenbrainz.org/terms-of-service/) | CC0 listening data | Discovery and aggregate popularity; resolve listens to canonical recordings |
| [AcoustID](https://acoustid.org/database) | Daily fingerprint database updates | MusicBrainz mappings CC0; other data CC BY-SA 3.0. Helps deduplication, not a standalone song catalog |
| [AcousticBrainz](https://acousticbrainz.org/) | CC0 tempo/key/mood descriptors | Already integrated; collection stopped in 2022, so historical enrichment only |
| [Jamendo](https://developer.jamendo.com/v3.0) | Official API advertises hundreds of thousands of indie tracks | Review API plan and track-specific audio licenses; no blanket redistribution permission |
| [FMA](https://github.com/mdeff/fma) | 106,574-track music-analysis corpus | Separate metadata terms from per-track audio licenses; evaluation or cleared subsets |
| [MTG-Jamendo](https://mtg.github.io/mtg-jamendo-dataset/) | 55,701 tracks and music tags | Research/evaluation first; review noncommercial and track-specific restrictions |
| [Million Song Dataset](https://millionsongdataset.com/) | Historical features and metadata, not one million audio files | Site unavailable during research; access and terms need follow-up |
| [Spotify](https://developer.spotify.com/terms) | Catalog resolution, linked accounts | Official API integration, not unrestricted bulk dataset; provider storage/use limits apply |
| [Apple Music](https://developer.apple.com/musickit/) | Catalog lookup and subscriber playback | Credentials/platform terms; not an open export |
| [YouTube](https://developers.google.com/youtube/data/determine_quota_cost) | Video search and playback destinations | Quotas and policies; video IDs are not canonical recording IDs |
| User listening exports | Long-tail songs and personal collections | Consent-based discovery; retain unmatched entries without inventing credits |
| Existing Kaggle Spotify / Last.fm datasets | Similarity and listening benchmarks | Retain evaluation-only policy; uploader labels do not establish upstream rights |

Further candidates requiring individual research: DDEX partner feeds, ISRC registry access, MusicStory, Gracenote, Musixmatch, 7digital, Deezer, SoundCloud, Audius, Internet Archive collections, Musopen, IMSLP, OpenScore, Music4All, DALI, Lakh MIDI, MagnaTagATune and AudioSet. These include commercial feeds, scores, MIDI, clips and research corpora. None is approved here as an unrestricted production catalog.

### Import plan

1. Stage versioned dumps with URL, checksum, retrieval date and license version. Preserve the working catalog until quality gates pass.
2. Keep works, recordings and release tracks distinct. Match explicit source IDs first; ISRC is evidence, not a universally unique key. Use artist/title/duration only with confidence thresholds and review queues. Preserve live/remix/remaster versions.
3. Store source provenance per assertion. Report net-new recordings after deduplication, orphan-credit rate, reviewed match precision and regional/language coverage.
4. Implement resumable bulk loads, indexes and atomic version promotion. Benchmark search and in-memory graph usage before expansion.
5. Separate the large catalog/search deployment from account storage as a subsequent architecture change. Tens of millions of recordings cannot be assumed to fit a 500 MB free database or the current in-memory graph.

## Searchable worldwide universities

Use [ROR CC0 dumps](https://ror.readme.io/docs/data-dump) as the open base. Import current v2 JSON, educational organizations, names/aliases, locations, domains, persistent IDs and status. ROR is a research-organization registry: it is neither comprehensive accreditation evidence nor a list of every university.

[IAU/UNESCO WHED](https://www.whed.net/) is a candidate for recognition checks. Its site blocked this research browser; confirm coverage criteria and bulk/API licensing directly. Public search does not imply permission to scrape or redistribute. Supplement with national ministry/accreditation sources: US NCES/IPEDS and Department of Education, UK recognized bodies/Office for Students, Australian TEQSA, Indian UGC/AISHE. These are follow-up candidates; the [NCES endpoint](https://nces.ed.gov/ipeds/use-the-data) timed out during this run.

Proposed implementation: versioned ROR importer, institution table, normalized name/alias index, country/city filters and source links/last-checked dates in search responses. Crosswalk existing Wikidata campus IDs explicitly; preserve memberships during merges. Maintain an unmatched-institution review queue.

Distinguish registry listing, official recognition, email-domain control and current enrollment. Alumni/staff email access does not prove student status. [SheerID](https://www.sheerid.com/faq/) checks authoritative sources and has [document fallback](https://verify.sheerid.com/student-faq-b/?locale=en_US&pid=6048fe44d4ea450065f5853b). It is not a free downloadable universal student directory. Use a provider or institutional SSO/enrollment integration for eligibility; retain result, institution and expiry rather than raw documents when possible.

## Free login/database recommendation

Preserve Firebase Authentication and use managed PostgreSQL. Existing code already verifies Firebase tokens and stores accounts through SQLAlchemy/Alembic/psycopg. MongoDB requires a persistence rewrite and does not remove network latency.

| Option | Fit and limitation |
|---|---|
| [Firebase Auth](https://firebase.google.com/pricing) + [Supabase PostgreSQL](https://supabase.com/pricing) | Compatible database; free tier currently 500 MB, shared resources, pauses after one week inactive |
| Firebase Auth + [Neon](https://neon.com/pricing) | Compatible free-entry PostgreSQL; evaluate compute allowances and cold-start behavior |
| [MongoDB Atlas Free](https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/) | Shared resources and connection/storage/region limits; SQL persistence rewrite needed |
| Current SQLite | Free and fast locally; not a managed multi-instance deployment |

No provider guarantees lag-free operation. Co-locate API/database, pool connections, index session/user lookups and measure cold/warm p50/p95. The free account database must not be mistaken for global catalog hosting.

### Setup using existing integration

1. Create PostgreSQL in the API region. Put its connection string securely into server/.env as SONGNEXUS_DATABASE_URL, using postgresql+psycopg and TLS according to provider instructions. Do not commit credentials or paste them in chat. Use a direct/session connection compatible with migrations; check transaction-pooler driver requirements separately.
2. From server/, run `uv run songnexus migrate`. This creates schema; it does not transfer SQLite users. Back up and plan an explicit data migration before cutover.
3. Configure SONGNEXUS_FIREBASE_PROJECT_ID; enable Google sign-in and authorized domains in Firebase; populate existing VITE_FIREBASE_* variables in web/.env.local and rebuild.
4. Test sign-in, session restoration, sign-out, CSRF, deletion and unauthorized requests against the hosted database.
5. Current SONGNEXUS_DATABASE_URL covers both users and catalog. Use only the bundled demo snapshot if it fits; splitting stores requires additional implementation before full-catalog ingestion.

Activation remains pending provider project configuration and credentials. No hosted connection or migration was performed. University search/import implementation and full-catalog import remain future work; this document establishes sources and the integration approach.
