# ADR 0003: Separate CC0 and non-commercial MusicBrainz data

- **Status:** Accepted, 2026-10-07. Resolves the license check in plan §4 (M1-09).
- **Context:** MusicBrainz licenses its data in two parts
  ([Data License](https://musicbrainz.org/doc/About/Data_License),
  [Database](https://musicbrainz.org/doc/MusicBrainz_Database)):
  - **Core data, CC0:** artists, recordings, releases, release groups, labels, genres (the genre list), relationships, URLs.
  - **Supplementary data, CC BY-NC-SA 3.0:** "user submitted annotations, tags (including genre associations) and
    ratings, derived statistics, search indexes".

  We use two supplementary items: **artist–genre associations** (genre filters, comparisons) and **release-group
  ratings** (choosing which albums to fetch for each seed).
- **Decision:**
  1. Facts derived from supplementary data are attributed to a separate data source, `musicbrainz-supplementary`,
     whose license is recorded as CC BY-NC-SA 3.0. Today that's artist–genre associations.
  2. Album selection by ratings only influences *which* releases we fetch; it stores no rating data.
  3. Attribution ("Data from MusicBrainz") appears in the app's "About our data" page.
  4. Every snapshot and database derived from supplementary data is non-commercial and share-alike.
- **Consequences:** the capstone may use genres. A commercial integration (e.g. YouTube Music) must drop the
  `musicbrainz-supplementary` source and use its own genre data, which a single delete by `source_id` does.
  Album selection would switch to a CC0 signal (e.g. number of releases per group).
