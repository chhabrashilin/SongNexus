"""MusicBrainz adapter (https://musicbrainz.org/doc/MusicBrainz_API).

MusicBrainz core data is CC0, which is why it is the primary source for the
vertical slice. Access is split into three layers:

* ``client``   - HTTP with rate limiting, retries, and a raw response cache.
* ``snapshot`` - an immutable, versionable set of raw responses (JSONL.gz).
* ``parsers``  - validation of raw JSON into typed source records.
"""
