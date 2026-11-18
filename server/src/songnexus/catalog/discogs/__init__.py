"""Discogs adapter: the monthly CC0 data dumps (https://data.discogs.com).

Only the masters dump is read: per master release, its main artists, year,
genres and styles. Artists are joined through MusicBrainz and Wikidata links,
never by name. API-only "Restricted Data" (images, marketplace) is not used.
"""
