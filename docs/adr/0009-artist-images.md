# ADR 0009: Artist photos from Wikimedia Commons

- **Status:** Accepted, 2026-11-16.
- **Context:** Every artist was drawn as a generated gradient with a letter, because SongNexus holds no artwork
  rights: cover art and press photos from labels or streaming services cannot be served. Wikimedia Commons holds
  freely licensed photos of many musicians, and Wikidata items name the photo for an artist (property P18) and carry
  the MusicBrainz artist ID (P434) that every catalog artist already has. The catch is licensing: Commons files are
  under many licenses, most of which require credit, and some files are not free at all.

- **Decision:**
  1. **Find photos through identifiers, never names.** `songnexus fetch-images` (`catalog/wikidata/images.py`)
     reads catalog artists' MusicBrainz IDs from `entity_source_mappings` and asks the Wikidata SPARQL endpoint, 400
     IDs a query, for `?item wdt:P434 ?mbid` and the item's `wdt:P18` image. A MusicBrainz ID found on more than one
     item gets no photo: a picture of the wrong person is worse than none. With several P18 files, the first
     acceptable one in title order is used.
  2. **Ask Commons for size, URLs and license.** `action=query&prop=imageinfo` with
     `iiprop=url|size|mime|extmetadata`, 50 titles a request, once with `iiurlwidth=330` (the thumbnail used in lists)
     and once with `iiurlwidth=960` (the large photo). Both are standard Commons thumbnail widths. Redirects and
     title normalization are followed.
  3. **Licensing rules.** A file is kept only when all hold:
     - `LicenseShortName` is public domain, CC0, CC BY or CC BY-SA (any version or national port), and `NonFree` is
       not set. NC and ND variants, GFDL-only, "Attribution", FAL, government licenses, fair use and anything
       unrecognized are skipped and counted by name, so the list can be widened deliberately later.
     - The MIME type is JPEG, PNG or WebP (SVG, TIFF and GIF are skipped).
     - Both URLs are HTTPS on a Wikimedia media host (`upload.wikimedia.org` for originals and files narrower than the
       requested width, `thumb.wikimedia.org` for scaled thumbnails).
  4. **Attribution travels with the image.** Table `artist_images` (migration 0009, one row per artist) stores the
     Commons file, both URLs, the original size, the file page, the author (HTML stripped to text), the license short
     name and URL, and whether attribution is required. Every artist summary in the API gains `imageUrl` (330 px, or
     null); `GetArtist` gains `image` with `url`, `thumbnailUrl`, `width`, `height`, `pageUrl`, `author`, `license`
     and `licenseUrl`. A client that shows a photo shows its author and license, linked to the file page, on the
     artist page. Images are hot-linked, never copied or modified, so CC BY-SA's share-alike terms are not triggered
     by our own pages. Wikimedia Commons is in the source registry (`docs/resources.md`) at tier Production: these
     licenses allow commercial use with credit.
  5. **Politeness and privacy.** Requests go through the shared `PoliteClient` (one request a second, retries with
     backoff, responses cached under `data/raw/wikidata-images` and `data/raw/commons`). The User-Agent is the generic
     `SongNexus/0.2 (student capstone project)`; no contact, name or address is ever sent, whatever
     `SONGNEXUS_WIKIDATA_CONTACT` says (tests assert the headers).
  6. **Idempotent, and safe to re-run after a re-ingest.** A run computes the answer for each artist and writes only
     differences: new rows are inserted, changed rows updated, rows of artists whose photo is gone or no longer
     acceptable deleted; unchanged rows keep their `fetched_at`. `--limit N` processes the N best-known artists
     (seeds, then profiles, then stubs) and leaves the rest untouched; `--dry-run` reports coverage without writing.
     Rows reference `artists.id` with `ON DELETE CASCADE`.
  7. **Serving cost and caching.** Photos are loaded once into the read model (`ArtistGraph.images`), so no request
     adds a query. The served version is the catalog run plus a stamp of the photo table (`…+run3.img<hash>`), so a
     fetch that changes photos reloads the read model on the next refresh and changes every response-cache key and
     ETag; a no-op re-run changes nothing. The web Content-Security-Policy (`firebase.json`) allows images from the
     two Wikimedia media hosts in `img-src` only.

- **Consequences:**
  - Coverage is bounded by Wikidata: on the 2026-11-16 development catalog, 1,517 of 5,854 artists got a photo
    (2,748 have a Wikidata item, 1,545 an image on it; 16 were skipped for license, 7 for TIFF files, 5 as ambiguous).
    Artists without one keep the generated gradient, which stays the honest default.
  - Cached responses make re-runs free but also stale: to pick up relicensed or replaced files, delete the two cache
    directories and run the command again.
  - Commons URLs include Wikimedia's own `utm_*` parameters as returned; they are kept verbatim rather than rewritten.
  - The web app must render the attribution before photos ship to people. That UI work is outside this change.
  - YouTube Music integration: production would use licensed artist imagery; the `imageUrl` and `image` contract,
    including attribution fields, carries over.
