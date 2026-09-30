-- Generated from backend/songnexus/db/models.py for PostgreSQL 16.
-- Regenerate rather than edit: python scripts/generate_schema_sql.py

CREATE TABLE data_sources (
	id VARCHAR(32) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	homepage VARCHAR(256) NOT NULL, 
	license VARCHAR(128) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE genres (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	normalized_name VARCHAR(128) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (normalized_name)
);

CREATE TABLE ingestion_runs (
	id SERIAL NOT NULL, 
	source_id VARCHAR(32) NOT NULL, 
	pipeline_version VARCHAR(32) NOT NULL, 
	snapshot_sha256 VARCHAR(64) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(16) NOT NULL, 
	stats JSONB NOT NULL, 
	error TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES data_sources (id)
);

CREATE TABLE albums (
	id VARCHAR(36) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	normalized_title VARCHAR(512) NOT NULL, 
	primary_type VARCHAR(32), 
	first_release_date VARCHAR(10), 
	ingestion_run_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_albums_normalized_title ON albums (normalized_title);

CREATE TABLE artists (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(512) NOT NULL, 
	sort_name VARCHAR(512), 
	normalized_name VARCHAR(512) NOT NULL, 
	artist_type VARCHAR(32), 
	country VARCHAR(8), 
	disambiguation VARCHAR(512), 
	begin_date VARCHAR(10), 
	end_date VARCHAR(10), 
	hydrated BOOLEAN NOT NULL, 
	ingestion_run_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_artists_normalized_name ON artists (normalized_name);

CREATE TABLE entity_source_mappings (
	id VARCHAR(36) NOT NULL, 
	entity_type VARCHAR(16) NOT NULL, 
	entity_id VARCHAR(36) NOT NULL, 
	source_id VARCHAR(32) NOT NULL, 
	source_entity_id VARCHAR(128) NOT NULL, 
	match_method VARCHAR(64) NOT NULL, 
	confidence FLOAT NOT NULL, 
	decision VARCHAR(16) NOT NULL, 
	ingestion_run_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_source_entity UNIQUE (source_id, entity_type, source_entity_id), 
	FOREIGN KEY(source_id) REFERENCES data_sources (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_mapping_entity ON entity_source_mappings (entity_type, entity_id);

CREATE TABLE raw_records (
	id SERIAL NOT NULL, 
	source_id VARCHAR(32) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	request_key VARCHAR(512) NOT NULL, 
	url VARCHAR(1024) NOT NULL, 
	retrieved_at VARCHAR(32) NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	payload JSONB NOT NULL, 
	last_seen_run_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_raw_source_key UNIQUE (source_id, request_key), 
	FOREIGN KEY(source_id) REFERENCES data_sources (id), 
	FOREIGN KEY(last_seen_run_id) REFERENCES ingestion_runs (id)
);

CREATE TABLE tracks (
	id VARCHAR(36) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	normalized_title VARCHAR(512) NOT NULL, 
	length_ms INTEGER, 
	first_release_date VARCHAR(10), 
	dedup_key VARCHAR(1024) NOT NULL, 
	ingestion_run_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (dedup_key), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_tracks_normalized_title ON tracks (normalized_title);

CREATE TABLE album_artists (
	album_id VARCHAR(36) NOT NULL, 
	artist_id VARCHAR(36) NOT NULL, 
	position INTEGER NOT NULL, 
	credited_as VARCHAR(512) NOT NULL, 
	source_id VARCHAR(32) NOT NULL, 
	raw_record_id INTEGER, 
	ingestion_run_id INTEGER NOT NULL, 
	confidence FLOAT NOT NULL, 
	PRIMARY KEY (album_id, artist_id), 
	FOREIGN KEY(album_id) REFERENCES albums (id) ON DELETE CASCADE, 
	FOREIGN KEY(artist_id) REFERENCES artists (id), 
	FOREIGN KEY(source_id) REFERENCES data_sources (id), 
	FOREIGN KEY(raw_record_id) REFERENCES raw_records (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_album_artists_artist_id ON album_artists (artist_id);

CREATE TABLE album_credits (
	id VARCHAR(36) NOT NULL, 
	album_id VARCHAR(36) NOT NULL, 
	artist_id VARCHAR(36) NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	role_detail VARCHAR(256) NOT NULL, 
	source_id VARCHAR(32) NOT NULL, 
	raw_record_id INTEGER, 
	ingestion_run_id INTEGER NOT NULL, 
	confidence FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_album_credit UNIQUE (album_id, artist_id, role, role_detail), 
	FOREIGN KEY(album_id) REFERENCES albums (id) ON DELETE CASCADE, 
	FOREIGN KEY(artist_id) REFERENCES artists (id), 
	FOREIGN KEY(source_id) REFERENCES data_sources (id), 
	FOREIGN KEY(raw_record_id) REFERENCES raw_records (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_album_credits_album_id ON album_credits (album_id);
CREATE INDEX ix_album_credits_artist_role ON album_credits (artist_id, role);

CREATE TABLE album_tracks (
	album_id VARCHAR(36) NOT NULL, 
	disc_number INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	track_id VARCHAR(36) NOT NULL, 
	source_id VARCHAR(32) NOT NULL, 
	raw_record_id INTEGER, 
	ingestion_run_id INTEGER NOT NULL, 
	confidence FLOAT NOT NULL, 
	PRIMARY KEY (album_id, disc_number, position), 
	FOREIGN KEY(album_id) REFERENCES albums (id) ON DELETE CASCADE, 
	FOREIGN KEY(track_id) REFERENCES tracks (id), 
	FOREIGN KEY(source_id) REFERENCES data_sources (id), 
	FOREIGN KEY(raw_record_id) REFERENCES raw_records (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_album_tracks_track_id ON album_tracks (track_id);

CREATE TABLE artist_aliases (
	id VARCHAR(36) NOT NULL, 
	artist_id VARCHAR(36) NOT NULL, 
	alias VARCHAR(512) NOT NULL, 
	normalized_alias VARCHAR(512) NOT NULL, 
	alias_type VARCHAR(32) NOT NULL, 
	locale VARCHAR(16), 
	source_id VARCHAR(32) NOT NULL, 
	raw_record_id INTEGER, 
	ingestion_run_id INTEGER NOT NULL, 
	confidence FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_alias UNIQUE (artist_id, normalized_alias), 
	FOREIGN KEY(artist_id) REFERENCES artists (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_id) REFERENCES data_sources (id), 
	FOREIGN KEY(raw_record_id) REFERENCES raw_records (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_artist_aliases_artist_id ON artist_aliases (artist_id);
CREATE INDEX ix_artist_aliases_normalized_alias ON artist_aliases (normalized_alias);

CREATE TABLE artist_genres (
	artist_id VARCHAR(36) NOT NULL, 
	genre_id VARCHAR(36) NOT NULL, 
	votes INTEGER NOT NULL, 
	source_id VARCHAR(32) NOT NULL, 
	raw_record_id INTEGER, 
	ingestion_run_id INTEGER NOT NULL, 
	confidence FLOAT NOT NULL, 
	PRIMARY KEY (artist_id, genre_id), 
	FOREIGN KEY(artist_id) REFERENCES artists (id) ON DELETE CASCADE, 
	FOREIGN KEY(genre_id) REFERENCES genres (id), 
	FOREIGN KEY(source_id) REFERENCES data_sources (id), 
	FOREIGN KEY(raw_record_id) REFERENCES raw_records (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_artist_genres_genre_id ON artist_genres (genre_id);

CREATE TABLE artist_links (
	id VARCHAR(36) NOT NULL, 
	artist_id VARCHAR(36) NOT NULL, 
	link_type VARCHAR(64) NOT NULL, 
	url VARCHAR(1024) NOT NULL, 
	source_id VARCHAR(32) NOT NULL, 
	raw_record_id INTEGER, 
	ingestion_run_id INTEGER NOT NULL, 
	confidence FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_artist_link UNIQUE (artist_id, url), 
	FOREIGN KEY(artist_id) REFERENCES artists (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_id) REFERENCES data_sources (id), 
	FOREIGN KEY(raw_record_id) REFERENCES raw_records (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_artist_links_artist_id ON artist_links (artist_id);

CREATE TABLE artist_relationships (
	id VARCHAR(36) NOT NULL, 
	source_artist_id VARCHAR(36) NOT NULL, 
	target_artist_id VARCHAR(36) NOT NULL, 
	rel_type VARCHAR(32) NOT NULL, 
	attributes JSONB NOT NULL, 
	begin_date VARCHAR(10), 
	end_date VARCHAR(10), 
	source_id VARCHAR(32) NOT NULL, 
	raw_record_id INTEGER, 
	ingestion_run_id INTEGER NOT NULL, 
	confidence FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_artist_rel UNIQUE (source_artist_id, target_artist_id, rel_type), 
	FOREIGN KEY(source_artist_id) REFERENCES artists (id), 
	FOREIGN KEY(target_artist_id) REFERENCES artists (id), 
	FOREIGN KEY(source_id) REFERENCES data_sources (id), 
	FOREIGN KEY(raw_record_id) REFERENCES raw_records (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_artist_relationships_source_artist_id ON artist_relationships (source_artist_id);
CREATE INDEX ix_artist_relationships_target_artist_id ON artist_relationships (target_artist_id);

CREATE TABLE track_credits (
	id VARCHAR(36) NOT NULL, 
	track_id VARCHAR(36) NOT NULL, 
	artist_id VARCHAR(36) NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	role_detail VARCHAR(256) NOT NULL, 
	credited_as VARCHAR(512), 
	source_id VARCHAR(32) NOT NULL, 
	raw_record_id INTEGER, 
	ingestion_run_id INTEGER NOT NULL, 
	confidence FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_track_credit UNIQUE (track_id, artist_id, role, role_detail), 
	FOREIGN KEY(track_id) REFERENCES tracks (id) ON DELETE CASCADE, 
	FOREIGN KEY(artist_id) REFERENCES artists (id), 
	FOREIGN KEY(source_id) REFERENCES data_sources (id), 
	FOREIGN KEY(raw_record_id) REFERENCES raw_records (id), 
	FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs (id)
);
CREATE INDEX ix_track_credits_artist_role ON track_credits (artist_id, role);
CREATE INDEX ix_track_credits_track_id ON track_credits (track_id);
