"""MusicBrainz adapter (https://musicbrainz.org/doc/MusicBrainz_API).

MusicBrainz core data is CC0, which is why it is the primary source for the
vertical slice. Access is split into three layers:

* ``client``  - the shared polite HTTP client (``catalog.http``) with MusicBrainz's conventions.
* ``fetch``   - what to request for a seed list; writes a snapshot (``catalog.snapshot``).
* ``parsers`` - validation of raw JSON into typed source records.
"""
