# Resources: data sources and licenses

<!-- Generated from server/src/songnexus/catalog/sources.py by `songnexus resources`. Do not edit by hand; CI fails when this file is out of date. -->

Every fact SongNexus shows carries the ID of the source that asserted it. This page lists every source we use or evaluate, what it feeds, its license, and when the license was checked. The policy behind the tiers is [ADR 0005](adr/0005-data-source-policy.md); the same list is served by `ListDataSources` (`GET /v1/dataSources`) and shown on the app's About page.

Status **Planned** means the source is approved but no code reads from it yet; the plan milestone that wires it in is in [plans/r2-plan.md](plans/r2-plan.md).

## Summary

| Source | License | Tier | Status | Feeds |
|---|---|---|---|---|
| [MusicBrainz](https://musicbrainz.org) | CC0-1.0 | Production-safe | In Use | artists, recordings, releases and labels; credits and artist relationships (every connection); collaborations, six degrees, compare, the daily puzzle |
| [MusicBrainz genres](https://musicbrainz.org/doc/Genre) | CC-BY-NC-SA-3.0 | Non-commercial | In Use | artist genres; genre filters and shared genres in compare |
| [Discogs data dumps](https://data.discogs.com) | CC0-1.0 | Production-safe | In Use | artist genres (commercial-safe); genre filters and shared genres in compare |
| [Wikidata](https://www.wikidata.org) | CC0-1.0 | Production-safe | In Use | genre hierarchy (subgenres); links from MusicBrainz artists to Discogs; Around you: the campuses and cities listeners can join; artist photos: which Commons file shows an artist |
| [Wikimedia Commons](https://commons.wikimedia.org) | Per file: public domain, CC0, CC BY or CC BY-SA | Production-safe | In Use | artist photos; Around you: campus athletics marks, logos and seals; the ListenBrainz and Libre.fm logos in connected services |
| [Simple Icons](https://simpleicons.org) | CC0-1.0 (the icons stay their brands' trademarks) | Production-safe | In Use | the YouTube Music, Spotify, Apple Music, Last.fm and Deezer marks in connected services, the import guide and every 'Listen on YouTube Music' button |
| [AcousticBrainz](https://acousticbrainz.org) | CC0-1.0 | Production-safe | In Use | song comparison: tempo, key, loudness, mood and other audio descriptors |
| [ListenBrainz](https://listenbrainz.org) | CC0-1.0 | Production-safe | In Use | listener overlap in artist comparison; 'often played with' on artist pages |
| [Spotify Tracks Dataset (Kaggle, maharshipandya)](https://www.kaggle.com/datasets/maharshipandya/-spotify-tracks-dataset) | CC0-1.0 (as stated by the uploader) | Evaluation only | Planned | evaluating song similarity against genre labels |
| [Last.fm 360K and 1K users (Celma, 2010)](https://zenodo.org/records/6090214) | Non-commercial research use, with permission of Last.fm | Evaluation only | In Use | evaluating listener overlap against an independent population |
| Your listening history | The listener's own data | Production-safe | In Use | Library: your artists and playlist analysis; Around you: campus and city charts, from listeners who opt in |

## Production-safe

CC0 or equivalent. Usable in a commercial YouTube Music feature.

### MusicBrainz

- **ID:** `musicbrainz`
- **Obtained via:** its API
- **License:** [CC0-1.0](https://musicbrainz.org/doc/About/Data_License) (checked 2026-10-07)
- **Feeds:** artists, recordings, releases and labels; credits and artist relationships (every connection); collaborations, six degrees, compare, the daily puzzle
- **Attribution:** “Data from MusicBrainz”
- **Notes:** Core data only. Fetched at no more than one request per 1.1 s with an identifying User-Agent, as MusicBrainz asks.

### Discogs data dumps

- **ID:** `discogs`
- **Obtained via:** published data dumps
- **License:** [CC0-1.0](https://support.discogs.com/hc/en-us/articles/360009334593) (checked 2026-11-01)
- **Feeds:** artist genres (commercial-safe); genre filters and shared genres in compare
- **Attribution:** “Data from Discogs”
- **Notes:** Monthly XML dumps of artists, labels, masters and releases are CC0; we read the masters dump (main artists, genres, styles). API-only 'Restricted Data' (images, marketplace) is not used. Artists are joined through MusicBrainz and Wikidata links, never by name; styles map onto the MusicBrainz genre list by name or a reviewed table.

### Wikidata

- **ID:** `wikidata`
- **Obtained via:** its API
- **License:** [CC0-1.0](https://www.wikidata.org/wiki/Wikidata:Licensing) (checked 2026-11-16)
- **Feeds:** genre hierarchy (subgenres); links from MusicBrainz artists to Discogs; Around you: the campuses and cities listeners can join; artist photos: which Commons file shows an artist
- **Attribution:** “Data from Wikidata”
- **Notes:** Structured data is CC0. Used for 'subclass of' (P279) links between items carrying MusicBrainz genre IDs (P8052), and for items carrying both a MusicBrainz artist ID (P434) and a Discogs artist ID (P1953). The Around you list is the largest US universities by student count (P2196) plus a few abroad, their cities, US cities over 100,000 people and national capitals, rebuilt with `songnexus fetch-communities`.

### Wikimedia Commons

- **ID:** `wikimedia-commons`
- **Obtained via:** its API
- **License:** [Per file: public domain, CC0, CC BY or CC BY-SA](https://commons.wikimedia.org/wiki/Commons:Licensing) (checked 2026-11-16)
- **Feeds:** artist photos; Around you: campus athletics marks, logos and seals; the ListenBrainz and Libre.fm logos in connected services
- **Attribution:** “Each photo and logo is credited with its author, license and file page”
- **Notes:** Found through the image (P18) on the artist's Wikidata item, matched by MusicBrainz ID (P434); fetched with `songnexus fetch-images` (ADR 0009). Each file carries its own license: only public domain, CC0, CC BY and CC BY-SA raster images are kept; non-free, unlicensed and non-commercial files are skipped. Images are hot-linked from Wikimedia's media hosts (upload.wikimedia.org, thumb.wikimedia.org), never copied, and the API returns the author, license and file page with every photo. Campus marks are the current logo (P154, no end date) of the athletics program that represents (P1268) the campus, else the campus's small logo (P8972), logo (P154) or seal (P158), SVG or PNG under the same license rule, chosen and hot-linked by `web/scripts/fetch-campus-logos.mjs` into `web/src/community/campusLogos.json`; the campus page links each logo's Commons file. The ListenBrainz (CC BY-SA 4.0, MetaBrainz Foundation) and Libre.fm (CC BY-SA 3.0) logo files are served unmodified from `web/public/brands`.

### Simple Icons

- **ID:** `simple-icons`
- **Obtained via:** published data dumps
- **License:** [CC0-1.0 (the icons stay their brands' trademarks)](https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md) (checked 2026-11-17)
- **Feeds:** the YouTube Music, Spotify, Apple Music, Last.fm and Deezer marks in connected services, the import guide and every 'Listen on YouTube Music' button
- **Notes:** SVG paths from simple-icons 16.38 copied into `web/src/components/BrandMark.tsx` with each brand's published color. The paths are CC0, but the marks are trademarks: they are used only to name the service a listener links or listens on, as the brands' guidelines allow, never altered or combined with the SongNexus mark (see the Simple Icons disclaimer).

### AcousticBrainz

- **ID:** `acousticbrainz`
- **Obtained via:** its API
- **License:** [CC0-1.0](https://acousticbrainz.org/download) (checked 2026-11-01)
- **Feeds:** song comparison: tempo, key, loudness, mood and other audio descriptors
- **Attribution:** “Audio data from AcousticBrainz”
- **Notes:** Data collection stopped in 2022; the API still serves the final dataset. Coverage is partial and keyed by MusicBrainz recording ID; songs without data say so. The voice-gender and genre classifiers are not used.

### ListenBrainz

- **ID:** `listenbrainz`
- **Obtained via:** its API
- **License:** [CC0-1.0](https://listenbrainz.org/terms-of-service/) (checked 2026-11-01)
- **Feeds:** listener overlap in artist comparison; 'often played with' on artist pages
- **Attribution:** “Listening data from ListenBrainz”
- **Notes:** Public listens are CC0. Only aggregates are fetched: listener and listen counts per artist, and the session-based similar-artists ranking. Overlap is shown only when both artists have at least 50 listeners, always with the counts.

### Your listening history

- **ID:** `user-listening`
- **Obtained via:** the listener's own files or linked accounts
- **License:** The listener's own data (checked 2026-10-07)
- **Feeds:** Library: your artists and playlist analysis; Around you: campus and city charts, from listeners who opt in
- **Notes:** Imported files are parsed on the device; only artist names reach the server. Linked accounts (R2-6) add each provider under its own API terms. Around you charts use only members who opted in, and only once 10 have listening data; an artist needs 3 listeners and counts are shown as ranges.

## Non-commercial

Served in the capstone build only. A commercial launch removes these facts by source ID.

### MusicBrainz genres

- **ID:** `musicbrainz-supplementary`
- **Obtained via:** its API
- **License:** [CC-BY-NC-SA-3.0](https://musicbrainz.org/doc/About/Data_License) (checked 2026-10-07)
- **Feeds:** artist genres; genre filters and shared genres in compare
- **Attribution:** “Genre data from MusicBrainz (CC BY-NC-SA 3.0)”
- **Notes:** Tag-derived genre associations. Kept apart from core data (ADR 0003); replaced by Discogs and Wikidata genres for commercial use.

## Evaluation only

Used offline to check our results against an independent signal. Never stored in the catalog, never shown to listeners.

### Spotify Tracks Dataset (Kaggle, maharshipandya)

- **ID:** `kaggle-spotify-tracks`
- **Obtained via:** a published dataset
- **License:** [CC0-1.0 (as stated by the uploader)](https://www.kaggle.com/datasets/maharshipandya/-spotify-tracks-dataset) (checked 2026-11-01)
- **Feeds:** evaluating song similarity against genre labels
- **Notes:** About 114,000 tracks across 125 genres with audio features. The uploader states CC0, but the values come from the Spotify Web API, whose terms the uploader cannot waive. Treated as evaluation-only. Not used yet: downloading needs a Kaggle account, so song similarity is evaluated against genre agreement instead (eval-songs).

### Last.fm 360K and 1K users (Celma, 2010)

- **ID:** `lastfm-360k`
- **Obtained via:** a published dataset
- **License:** [Non-commercial research use, with permission of Last.fm](https://zenodo.org/records/6090214) (checked 2026-11-01)
- **Feeds:** evaluating listener overlap against an independent population
- **Attribution:** “Last.fm dataset, Ò. Celma (2010)”
- **Notes:** Per-user artist play counts with MusicBrainz artist IDs; collected 2008-2009, so it measures agreement, not current overlap. Also mirrored on Kaggle.

## Adding a source

1. Read the provider's license or terms; record the SPDX ID (or the terms' name), the URL and today's date.
2. Add a `DataSource` to `sources.py` with status `PLANNED` and the right tier. Unclear or unstated license: do not add it.
3. Run `uv run songnexus resources` and commit the regenerated page with the code that first reads the source, switching its status to `IN_USE`.
