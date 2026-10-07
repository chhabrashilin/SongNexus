# SongNexus

The people behind the music, and how they connect. A design and reference implementation for
**YouTube Music**: credits on the Now Playing screen, a daily connection game, and a map of how the artists you
listen to are linked. Every connection is backed by a cited credit.

UW–Madison CS 620 capstone with Google.

## Status

**Milestone M0: design review.** This branch (`v2`) is a clean rebuild. Code returns milestone by milestone, in
small reviewed changes.

| Milestone | State |
|---|---|
| M0 Design doc + engineering standards | ✍️ in review |
| M1 Data foundation | next |
| M2–M9 | see the [design doc §12](docs/design/design-doc.md#12-milestones-the-step-by-step-build) |

The earlier prototype is preserved at git tag `v0-prototype` (and on `main` until `v2` replaces it).

## Read first

- [Design doc](docs/design/design-doc.md): objective, user journeys, architecture, privacy, milestones, feature tracker
- [Engineering standards](docs/engineering-standards.md): the bar every change must meet

## What's in the repository today

```
data/
  samples/musicbrainz_snapshot.jsonl.gz   real MusicBrainz responses (CC0) for 28 seed artists
  seeds/                                  seed artists and the recorded name-resolution decisions
  eval/search_cases.json                  43 labeled search queries (quality regression set)
docs/
  design/design-doc.md
  engineering-standards.md
```

## Data and licensing

Catalog data comes from [MusicBrainz](https://musicbrainz.org), whose core data is CC0. The repository's own
license is an open question for the sponsor (design doc §14).
