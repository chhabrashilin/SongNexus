/**
 * Listening-data formats (plan §15.5): detection by shape, parsing, aggregation.
 *
 * Everything here runs on the device (in a Web Worker); raw files are never
 * uploaded. Parsers return playlists (artists per track) or per-artist
 * aggregates of plays, never timestamps or full histories, so only what the
 * analysis needs can leave the device. Pure functions, unit-tested per format.
 */
import Papa from 'papaparse';

export interface PlaylistTrack {
  title: string;
  artists: string[];
}

export interface Playlist {
  name: string;
  tracks: PlaylistTrack[];
}

export interface ArtistListening {
  artist: string;
  plays: number;
  msPlayed: number;
}

export type FormatId =
  | 'spotify-playlists'
  | 'spotify-streaming-history'
  | 'spotify-extended-history'
  | 'spotify-library'
  | 'youtube-music-history'
  | 'listenbrainz'
  | 'csv-playlist'
  | 'csv-history';

export type Parsed =
  | {kind: 'playlists'; format: FormatId; playlists: Playlist[]}
  | {kind: 'listening'; format: FormatId; artists: ArtistListening[]};

/** Why a file can't be imported; the UI turns each into a localized message. */
export type RejectReason =
  | 'unsupportedType'
  | 'invalidJson'
  | 'notListening'
  | 'noArtistColumn'
  | 'damaged'
  | 'tooLarge'
  | 'importTooLarge'
  | 'zipEmpty'
  | 'zipDamaged';

export class UnsupportedFileError extends Error {
  override name = 'UnsupportedFileError';
  constructor(readonly reason: RejectReason) {
    super(reason);
  }
}

type Json = unknown;

function isObject(value: Json): value is Record<string, Json> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: Json): string {
  return typeof value === 'string' ? value.trim() : '';
}

/** Splits an artist cell: ";" always, "," only when not followed by a space ("Tyler, The Creator"). */
export function splitArtists(cell: string): string[] {
  return cell
    .split(/;|,(?! )/)
    .map(a => a.trim())
    .filter(Boolean);
}

/** Aggregates plays into per-artist totals, most listened first (ties by name). */
export function aggregate(
  plays: Iterable<{artist: string; ms: number}>,
): ArtistListening[] {
  const totals = new Map<string, ArtistListening>();
  for (const {artist, ms} of plays) {
    if (!artist) continue;
    const entry = totals.get(artist) ?? {artist, plays: 0, msPlayed: 0};
    entry.plays += 1;
    entry.msPlayed += Math.max(0, ms);
    totals.set(artist, entry);
  }
  return [...totals.values()].sort(
    (a, b) =>
      b.msPlayed - a.msPlayed ||
      b.plays - a.plays ||
      a.artist.localeCompare(b.artist),
  );
}

// ---------------------------------------------------------------------------
// JSON formats, detected by shape
// ---------------------------------------------------------------------------

function spotifyPlaylists(data: Json): Parsed | null {
  if (!isObject(data) || !Array.isArray(data.playlists)) return null;
  const playlists: Playlist[] = [];
  for (const raw of data.playlists) {
    if (!isObject(raw) || !Array.isArray(raw.items)) continue;
    const tracks: PlaylistTrack[] = [];
    for (const item of raw.items) {
      const track = isObject(item) ? item.track : null;
      if (!isObject(track)) continue; // podcast episodes and local files
      const artist = text(track.artistName);
      if (artist)
        tracks.push({title: text(track.trackName), artists: [artist]});
    }
    playlists.push({name: text(raw.name) || 'Untitled playlist', tracks});
  }
  return {kind: 'playlists', format: 'spotify-playlists', playlists};
}

function arrayOf(data: Json): Record<string, Json>[] | null {
  return Array.isArray(data) && data.length > 0 && data.every(isObject)
    ? data
    : null;
}

function spotifyStreamingHistory(data: Json): Parsed | null {
  const rows = arrayOf(data);
  if (!rows || !('artistName' in rows[0]!) || !('msPlayed' in rows[0]!))
    return null;
  return {
    kind: 'listening',
    format: 'spotify-streaming-history',
    artists: aggregate(
      rows.map(r => ({
        artist: text(r.artistName),
        ms: Number(r.msPlayed) || 0,
      })),
    ),
  };
}

function spotifyExtendedHistory(data: Json): Parsed | null {
  const rows = arrayOf(data);
  if (!rows || !('master_metadata_album_artist_name' in rows[0]!)) return null;
  // Podcast episodes have no artist and are skipped.
  return {
    kind: 'listening',
    format: 'spotify-extended-history',
    artists: aggregate(
      rows.map(r => ({
        artist: text(r.master_metadata_album_artist_name),
        ms: Number(r.ms_played) || 0,
      })),
    ),
  };
}

function spotifyLibrary(data: Json): Parsed | null {
  if (!isObject(data) || !Array.isArray(data.tracks)) return null;
  const tracks = data.tracks.filter(isObject);
  if (tracks.length && !('artist' in tracks[0]!)) return null;
  return {
    kind: 'listening',
    format: 'spotify-library',
    // A saved track counts as one "play" with no listening time.
    artists: aggregate(tracks.map(t => ({artist: text(t.artist), ms: 0}))),
  };
}

function youTubeMusicHistory(data: Json): Parsed | null {
  const rows = arrayOf(data);
  if (!rows || !rows.some(r => r.header === 'YouTube Music')) return null;
  const plays: {artist: string; ms: number}[] = [];
  for (const row of rows) {
    if (row.header !== 'YouTube Music' || !Array.isArray(row.subtitles))
      continue;
    const channel = isObject(row.subtitles[0])
      ? text(row.subtitles[0].name)
      : '';
    // Official audio comes from "<Artist> - Topic" channels; other uploads are skipped.
    if (channel.endsWith(' - Topic'))
      plays.push({artist: channel.slice(0, -' - Topic'.length), ms: 0});
  }
  return {
    kind: 'listening',
    format: 'youtube-music-history',
    artists: aggregate(plays),
  };
}

function listenBrainz(data: Json): Parsed | null {
  const rows = arrayOf(data);
  if (!rows || !isObject(rows[0]!.track_metadata)) return null;
  return {
    kind: 'listening',
    format: 'listenbrainz',
    artists: aggregate(
      rows.map(r => ({
        artist: isObject(r.track_metadata)
          ? text(r.track_metadata.artist_name)
          : '',
        ms: 0,
      })),
    ),
  };
}

const JSON_PARSERS = [
  spotifyPlaylists,
  spotifyLibrary,
  spotifyExtendedHistory,
  spotifyStreamingHistory,
  youTubeMusicHistory,
  listenBrainz,
];

/** Parses JSON or JSON Lines (ListenBrainz exports both). */
function parseJson(content: string): Json {
  const trimmed = content.trim();
  try {
    return JSON.parse(trimmed) as Json;
  } catch {
    const lines = trimmed.split(/\r?\n/).filter(Boolean);
    if (lines.length > 1) return lines.map(line => JSON.parse(line) as Json);
    throw new UnsupportedFileError('invalidJson');
  }
}

// ---------------------------------------------------------------------------
// CSV and TSV with a header row
// ---------------------------------------------------------------------------

const ARTIST_HEADERS = [
  'artist name(s)',
  'artist names',
  'artist name',
  'artists',
  'artist',
  'artist_name',
  'creator',
];
const TITLE_HEADERS = [
  'track name',
  'track_name',
  'track',
  'title',
  'song',
  'song name',
  'name',
];
const TIME_HEADERS = [
  'endtime',
  'ts',
  'played_at',
  'timestamp',
  'date played',
  'listened_at',
  'time',
];

function findColumn(
  headers: string[],
  candidates: string[],
): string | undefined {
  const lower = new Map(headers.map(h => [h.trim().toLowerCase(), h]));
  for (const candidate of candidates) {
    const match = lower.get(candidate);
    if (match !== undefined) return match;
  }
  return undefined;
}

function parseDelimited(content: string, fileName: string): Parsed {
  const result = Papa.parse<Record<string, string>>(content, {
    header: true,
    skipEmptyLines: 'greedy',
  });
  const headers = result.meta.fields ?? [];
  const artistColumn = findColumn(headers, ARTIST_HEADERS);
  if (!artistColumn) {
    throw new UnsupportedFileError('noArtistColumn');
  }
  const titleColumn = findColumn(headers, TITLE_HEADERS);
  if (findColumn(headers, TIME_HEADERS)) {
    return {
      kind: 'listening',
      format: 'csv-history',
      artists: aggregate(
        result.data.flatMap(row =>
          splitArtists(row[artistColumn] ?? '')
            .slice(0, 1)
            .map(artist => ({artist, ms: 0})),
        ),
      ),
    };
  }
  const tracks = result.data
    .map(row => ({
      title: titleColumn ? (row[titleColumn] ?? '').trim() : '',
      artists: splitArtists(row[artistColumn] ?? ''),
    }))
    .filter(t => t.artists.length > 0);
  return {
    kind: 'playlists',
    format: 'csv-playlist',
    playlists: [{name: fileName.replace(/\.(csv|tsv|txt)$/i, ''), tracks}],
  };
}

/** Detects a file's format from its content (not its name) and parses it. */
export function parseFile(fileName: string, content: string): Parsed {
  const lower = fileName.toLowerCase();
  if (/\.(csv|tsv|txt)$/.test(lower)) return parseDelimited(content, fileName);
  if (/\.(json|jsonl)$/.test(lower)) {
    const data = parseJson(content);
    for (const parser of JSON_PARSERS) {
      const parsed = parser(data);
      if (parsed) return parsed;
    }
    throw new UnsupportedFileError('notListening');
  }
  throw new UnsupportedFileError('unsupportedType');
}
