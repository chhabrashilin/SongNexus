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
  | 'csv-history'
  | 'apple-music-library'
  | 'm3u-playlist'
  | 'xspf-playlist';

export type Parsed =
  | {kind: 'playlists'; format: FormatId; playlists: Playlist[]}
  | {
      kind: 'listening';
      format: FormatId;
      artists: ArtistListening[];
      /** Playlists that came in the same file (Apple Music libraries); absent otherwise. */
      playlists?: Playlist[];
    };

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

// ---------------------------------------------------------------------------
// XML formats: Apple Music / iTunes library, XSPF. A small scanner instead of
// DOMParser, which Web Workers don't have.
// ---------------------------------------------------------------------------

const ENTITIES: Record<string, string> = {
  amp: '&',
  lt: '<',
  gt: '>',
  quot: '"',
  apos: "'",
};

function decodeEntities(value: string): string {
  if (!value.includes('&')) return value;
  return value.replace(
    /&(#x[0-9a-f]+|#\d+|[a-z]+);/gi,
    (match, body: string) => {
      if (body.startsWith('#')) {
        const code =
          body[1] === 'x' || body[1] === 'X'
            ? parseInt(body.slice(2), 16)
            : parseInt(body.slice(1), 10);
        return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : '';
      }
      return ENTITIES[body.toLowerCase()] ?? match;
    },
  );
}

interface XmlHandler {
  open(name: string): void;
  close(name: string): void;
  text(value: string): void;
}

const MAX_XML_DEPTH = 64;

/** Linear-time tag scanner: skips comments, processing instructions and DOCTYPE. */
function scanXml(content: string, handler: XmlHandler): void {
  let pos = 0;
  let depth = 0;
  while (pos < content.length) {
    const lt = content.indexOf('<', pos);
    if (lt === -1) {
      handler.text(decodeEntities(content.slice(pos)));
      return;
    }
    if (lt > pos) handler.text(decodeEntities(content.slice(pos, lt)));
    let end: number;
    if (content.startsWith('<!--', lt)) {
      end = content.indexOf('-->', lt + 4);
      pos = end === -1 ? content.length : end + 3;
    } else if (content.startsWith('<![CDATA[', lt)) {
      end = content.indexOf(']]>', lt + 9);
      handler.text(content.slice(lt + 9, end === -1 ? content.length : end));
      pos = end === -1 ? content.length : end + 3;
    } else if (content.startsWith('<?', lt)) {
      end = content.indexOf('?>', lt + 2);
      pos = end === -1 ? content.length : end + 2;
    } else if (content.startsWith('<!', lt)) {
      end = content.indexOf('>', lt + 2);
      const bracket = content.indexOf('[', lt + 2);
      if (end !== -1 && bracket !== -1 && bracket < end)
        end = content.indexOf(']>', bracket);
      pos = end === -1 ? content.length : end + 1;
    } else {
      end = content.indexOf('>', lt + 1);
      if (end === -1) return;
      const tag = content.slice(lt + 1, end);
      pos = end + 1;
      const match = /^(\/?)([A-Za-z_][^\s/>]*)/.exec(tag);
      if (!match) continue;
      const name = (match[2] ?? '').replace(/^.*:/, '');
      if (match[1]) {
        depth = Math.max(0, depth - 1);
        handler.close(name);
      } else if (tag.endsWith('/')) {
        handler.open(name);
        handler.close(name);
      } else {
        if (++depth > MAX_XML_DEPTH) throw new UnsupportedFileError('damaged');
        handler.open(name);
      }
    }
  }
}

type Plist = string | boolean | Plist[] | Map<string, Plist>;
type PlistDict = Map<string, Plist>;

function plistValue(name: string, buffer: string): Plist | undefined {
  switch (name) {
    case 'string':
    case 'integer':
    case 'real':
    case 'date':
    case 'data':
      return buffer;
    case 'true':
      return true;
    case 'false':
      return false;
    default:
      return undefined;
  }
}

/** Parses an XML property list into maps, arrays, strings and booleans. */
function parsePlist(content: string): Plist | undefined {
  type Frame =
    | {type: 'dict'; map: PlistDict; key: string}
    | {type: 'array'; items: Plist[]};
  const stack: Frame[] = [];
  let root: Plist | undefined;
  let buffer = '';

  const attach = (value: Plist) => {
    const top = stack[stack.length - 1];
    if (!top) root ??= value;
    else if (top.type === 'array') top.items.push(value);
    else top.map.set(top.key, value);
  };

  scanXml(content, {
    open(name) {
      if (name === 'dict') stack.push({type: 'dict', map: new Map(), key: ''});
      else if (name === 'array') stack.push({type: 'array', items: []});
      buffer = '';
    },
    text(value) {
      buffer += value;
    },
    close(name) {
      if (name === 'dict' || name === 'array') {
        const frame = stack.pop();
        if (frame) attach(frame.type === 'dict' ? frame.map : frame.items);
      } else if (name === 'key') {
        const top = stack[stack.length - 1];
        if (top?.type === 'dict') top.key = buffer.trim();
      } else {
        const value = plistValue(name, buffer);
        if (value !== undefined) attach(value);
      }
      buffer = '';
    },
  });
  return root;
}

function plistText(value: Plist | undefined): string {
  return typeof value === 'string' ? value.trim() : '';
}

function plistDict(value: Plist | undefined): PlistDict | undefined {
  return value instanceof Map ? value : undefined;
}

/** False for podcasts, videos, audiobooks and other non-music items in a library. */
function isMusicTrack(track: PlistDict): boolean {
  for (const key of [
    'Podcast',
    'Has Video',
    'Audiobook',
    'Movie',
    'TV Show',
    'Music Video',
  ])
    if (track.get(key) === true) return false;
  return !/video|podcast|audiobook|book|pdf/i.test(
    plistText(track.get('Kind')),
  );
}

interface LibrarySong {
  title: string;
  artist: string;
  plays: number;
  ms: number;
}

function appleMusicLibrary(content: string): Parsed | null {
  if (!content.includes('<plist')) return null;
  const root = plistDict(parsePlist(content));
  const library = plistDict(root?.get('Tracks'));
  if (!root || !library) return null;

  const songs = new Map<string, LibrarySong>();
  for (const [id, raw] of library) {
    const track = plistDict(raw);
    if (!track || !isMusicTrack(track)) continue;
    // Album Artist stands in only when a track has no Artist of its own.
    const artist =
      plistText(track.get('Artist')) || plistText(track.get('Album Artist'));
    if (!artist) continue;
    songs.set(id, {
      title: plistText(track.get('Name')),
      artist,
      plays: Math.max(
        0,
        Math.floor(Number(plistText(track.get('Play Count'))) || 0),
      ),
      ms: Math.max(0, Number(plistText(track.get('Total Time'))) || 0),
    });
  }

  const playlists: Playlist[] = [];
  let hasMaster = false;
  const rawPlaylists = root.get('Playlists');
  for (const raw of Array.isArray(rawPlaylists) ? rawPlaylists : []) {
    const playlist = plistDict(raw);
    if (!playlist) continue;
    const master = playlist.get('Master') === true;
    if (master) hasMaster = true;
    // System playlists (Library, Music, Downloaded...) and folders are not the listener's own.
    if (
      master ||
      playlist.has('Distinguished Kind') ||
      playlist.get('Folder') === true
    )
      continue;
    const tracks: PlaylistTrack[] = [];
    const items = playlist.get('Playlist Items');
    for (const item of Array.isArray(items) ? items : []) {
      const song = songs.get(plistText(plistDict(item)?.get('Track ID')));
      if (song) tracks.push({title: song.title, artists: [song.artist]});
    }
    playlists.push({
      name: plistText(playlist.get('Name')) || 'Untitled playlist',
      tracks,
    });
  }

  // A single exported playlist (no Master) is a playlist, even if its tracks were played.
  if (!hasMaster && playlists.length > 0)
    return {kind: 'playlists', format: 'apple-music-library', playlists};

  // Without any play counts, each library track counts as one "play" with no listening time.
  const counted = [...songs.values()].some(s => s.plays > 0);
  const totals = new Map<string, ArtistListening>();
  for (const song of songs.values()) {
    const plays = counted ? song.plays : 1;
    if (plays === 0) continue;
    const entry = totals.get(song.artist) ?? {
      artist: song.artist,
      plays: 0,
      msPlayed: 0,
    };
    entry.plays += plays;
    entry.msPlayed += counted ? plays * song.ms : 0;
    totals.set(song.artist, entry);
  }
  const artists = [...totals.values()].sort(
    (a, b) =>
      b.msPlayed - a.msPlayed ||
      b.plays - a.plays ||
      a.artist.localeCompare(b.artist),
  );
  return {
    kind: 'listening',
    format: 'apple-music-library',
    artists,
    ...(playlists.length > 0 ? {playlists} : {}),
  };
}

function xspfPlaylist(content: string, fileName: string): Parsed | null {
  if (!/<(\w+:)?playlist[\s>]/.test(content) || !content.includes('trackList'))
    return null;
  const tracks: PlaylistTrack[] = [];
  const path: string[] = [];
  let title = '';
  let creator = '';
  let name = '';
  scanXml(content, {
    open(tag) {
      path.push(tag);
      if (tag === 'track') {
        title = '';
        creator = '';
      }
    },
    text(value) {
      const tag = path[path.length - 1];
      const parent = path[path.length - 2];
      if (parent === 'track' && tag === 'title') title += value;
      else if (parent === 'track' && tag === 'creator') creator += value;
      else if (parent === 'playlist' && tag === 'title') name += value;
    },
    close(tag) {
      if (tag === 'track') {
        const artists = splitArtists(creator.trim());
        if (artists.length > 0) tracks.push({title: title.trim(), artists});
      }
      path.pop();
    },
  });
  return {
    kind: 'playlists',
    format: 'xspf-playlist',
    playlists: [
      {name: name.trim() || fileName.replace(/\.(xspf|xml)$/i, ''), tracks},
    ],
  };
}

// ---------------------------------------------------------------------------
// M3U / M3U8 playlists
// ---------------------------------------------------------------------------

/** "Artist - Title" from a display string or a file name; null when it has no such shape. */
function splitArtistTitle(label: string): PlaylistTrack | null {
  const at = label.indexOf(' - ');
  if (at <= 0) return null;
  const artists = splitArtists(label.slice(0, at));
  const title = label.slice(at + 3).trim();
  return artists.length > 0 && title ? {title, artists} : null;
}

function fromPath(path: string): PlaylistTrack | null {
  let file = path.split(/[\\/]/).pop() ?? '';
  try {
    file = decodeURIComponent(file);
  } catch {
    // Not percent-encoded after all.
  }
  file = file.replace(/\.[A-Za-z0-9]{2,5}$/, '').trim();
  // "01 - Artist - Title": drop the track number when what remains has the shape.
  const unnumbered = file.replace(/^\d{1,3}\s*[-.)]\s*/, '');
  return splitArtistTitle(unnumbered) ?? splitArtistTitle(file);
}

function m3uPlaylist(content: string, fileName: string): Parsed | null {
  const lines = content.split(/\r\n|\n|\r/).map(line => line.trim());
  const hasHeader = lines.find(Boolean)?.toUpperCase().startsWith('#EXTM3U');
  if (!hasHeader && !/\.m3u8?$/i.test(fileName)) return null;
  const tracks: PlaylistTrack[] = [];
  let name = '';
  let info: PlaylistTrack | null = null;
  let infoLabel = '';
  let extArtist = '';
  for (const line of lines) {
    if (!line) continue;
    if (line.startsWith('#')) {
      const upper = line.toUpperCase();
      if (upper.startsWith('#EXTINF:')) {
        // "#EXTINF:215,Artist - Title"; attributes may precede the comma.
        infoLabel = line.includes(',')
          ? line.slice(line.indexOf(',') + 1).trim()
          : '';
        info = splitArtistTitle(infoLabel);
      } else if (upper.startsWith('#EXTART:'))
        extArtist = line.slice('#EXTART:'.length).trim();
      else if (upper.startsWith('#PLAYLIST:'))
        name = line.slice('#PLAYLIST:'.length).trim();
      continue;
    }
    // An entry line (a path or URL): combine with the info lines before it.
    let track = info;
    if (!track && extArtist && infoLabel) {
      const artists = splitArtists(extArtist);
      if (artists.length > 0) track = {title: infoLabel, artists};
    }
    track ??= fromPath(line);
    if (track) tracks.push(track);
    info = null;
    infoLabel = '';
    extArtist = '';
  }
  return {
    kind: 'playlists',
    format: 'm3u-playlist',
    playlists: [{name: name || fileName.replace(/\.m3u8?$/i, ''), tracks}],
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
  if (/\.(m3u|m3u8)$/.test(lower)) {
    const parsed = m3uPlaylist(content.trim(), fileName);
    if (parsed) return parsed;
    throw new UnsupportedFileError('notListening');
  }
  if (/\.(xml|xspf)$/.test(lower)) {
    const parsed =
      appleMusicLibrary(content) ?? xspfPlaylist(content, fileName);
    if (parsed) return parsed;
    throw new UnsupportedFileError('notListening');
  }
  throw new UnsupportedFileError('unsupportedType');
}
