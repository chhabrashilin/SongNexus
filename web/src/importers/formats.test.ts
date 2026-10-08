/** AC-8.1: each supported export format yields exactly the expected aggregates. */
import {strToU8, zipSync} from 'fflate';
import {describe, expect, it} from 'vitest';

import {
  aggregate,
  parseFile,
  splitArtists,
  UnsupportedFileError,
} from './formats';
import {importFiles, MAX_FILE_BYTES, type InputFile} from './importFiles';

const json = (value: unknown) => JSON.stringify(value);

describe('splitArtists', () => {
  it('splits on semicolons and on commas without a following space', () => {
    expect(splitArtists('Kendrick Lamar,SZA')).toEqual([
      'Kendrick Lamar',
      'SZA',
    ]);
    expect(splitArtists('Daft Punk; Pharrell Williams')).toEqual([
      'Daft Punk',
      'Pharrell Williams',
    ]);
    expect(splitArtists('Tyler, The Creator')).toEqual(['Tyler, The Creator']);
    expect(splitArtists('  ')).toEqual([]);
  });
});

describe('aggregate', () => {
  it('sums plays and time per artist, most listened first', () => {
    expect(
      aggregate([
        {artist: 'B', ms: 1000},
        {artist: 'A', ms: 3000},
        {artist: 'B', ms: 2500},
        {artist: '', ms: 9999},
      ]),
    ).toEqual([
      {artist: 'B', plays: 2, msPlayed: 3500},
      {artist: 'A', plays: 1, msPlayed: 3000},
    ]);
  });
});

describe('parseFile', () => {
  it('reads Spotify playlists, skipping episodes and local files', () => {
    const file = json({
      playlists: [
        {
          name: 'Road trip',
          items: [
            {
              track: {
                trackName: 'HUMBLE.',
                artistName: 'Kendrick Lamar',
                albumName: 'DAMN.',
              },
            },
            {track: null, episode: {episodeName: 'A podcast'}},
            {track: {trackName: 'Kill Bill', artistName: 'SZA'}},
          ],
        },
      ],
    });
    expect(parseFile('Playlist1.json', file)).toEqual({
      kind: 'playlists',
      format: 'spotify-playlists',
      playlists: [
        {
          name: 'Road trip',
          tracks: [
            {title: 'HUMBLE.', artists: ['Kendrick Lamar']},
            {title: 'Kill Bill', artists: ['SZA']},
          ],
        },
      ],
    });
  });

  it('reads Spotify streaming history', () => {
    const file = json([
      {
        endTime: '2026-01-01 10:00',
        artistName: 'SZA',
        trackName: 'Snooze',
        msPlayed: 200000,
      },
      {
        endTime: '2026-01-01 10:04',
        artistName: 'Drake',
        trackName: 'X',
        msPlayed: 1000,
      },
      {
        endTime: '2026-01-01 10:05',
        artistName: 'SZA',
        trackName: 'Kill Bill',
        msPlayed: 150000,
      },
    ]);
    expect(parseFile('StreamingHistory_music_0.json', file)).toEqual({
      kind: 'listening',
      format: 'spotify-streaming-history',
      artists: [
        {artist: 'SZA', plays: 2, msPlayed: 350000},
        {artist: 'Drake', plays: 1, msPlayed: 1000},
      ],
    });
  });

  it('reads extended Spotify history and skips podcasts', () => {
    const file = json([
      {
        ts: '2026-01-01T10:00:00Z',
        ms_played: 1000,
        master_metadata_album_artist_name: 'Björk',
        master_metadata_track_name: 'Joga',
      },
      {
        ts: '2026-01-01T11:00:00Z',
        ms_played: 5000,
        master_metadata_album_artist_name: null,
        episode_name: 'News',
      },
    ]);
    expect(parseFile('Streaming_History_Audio_2026.json', file)).toEqual({
      kind: 'listening',
      format: 'spotify-extended-history',
      artists: [{artist: 'Björk', plays: 1, msPlayed: 1000}],
    });
  });

  it('reads the Spotify library', () => {
    const file = json({
      tracks: [
        {artist: 'BTS', track: 'Dynamite'},
        {artist: 'BTS', track: 'Butter'},
      ],
      albums: [],
    });
    expect(parseFile('YourLibrary.json', file)).toEqual({
      kind: 'listening',
      format: 'spotify-library',
      artists: [{artist: 'BTS', plays: 2, msPlayed: 0}],
    });
  });

  it('reads YouTube Music history from "- Topic" channels only', () => {
    const file = json([
      {
        header: 'YouTube Music',
        title: 'Watched Dynamite',
        subtitles: [{name: 'BTS - Topic'}],
      },
      {
        header: 'YouTube Music',
        title: 'Watched a vlog',
        subtitles: [{name: 'Some Vlogger'}],
      },
      {
        header: 'YouTube',
        title: 'Watched cats',
        subtitles: [{name: 'Cats - Topic'}],
      },
      {
        header: 'YouTube Music',
        title: 'Watched Butter',
        subtitles: [{name: 'BTS - Topic'}],
      },
    ]);
    expect(parseFile('watch-history.json', file)).toEqual({
      kind: 'listening',
      format: 'youtube-music-history',
      artists: [{artist: 'BTS', plays: 2, msPlayed: 0}],
    });
  });

  it('reads ListenBrainz JSON Lines', () => {
    const lines = [
      json({
        listened_at: 1,
        track_metadata: {artist_name: 'Radiohead', track_name: 'Reckoner'},
      }),
      json({
        listened_at: 2,
        track_metadata: {artist_name: 'Radiohead', track_name: 'Nude'},
      }),
    ].join('\n');
    expect(parseFile('listens.jsonl', lines)).toEqual({
      kind: 'listening',
      format: 'listenbrainz',
      artists: [{artist: 'Radiohead', plays: 2, msPlayed: 0}],
    });
  });

  it('reads CSV playlists (Exportify) with header detection', () => {
    const csv =
      'Track Name,Artist Name(s),Album Name\nmoney trees,"Kendrick Lamar,Jay Rock",good kid\nEARFQUAKE,"Tyler, The Creator",IGOR\n';
    expect(parseFile('My Mix.csv', csv)).toEqual({
      kind: 'playlists',
      format: 'csv-playlist',
      playlists: [
        {
          name: 'My Mix',
          tracks: [
            {title: 'money trees', artists: ['Kendrick Lamar', 'Jay Rock']},
            {title: 'EARFQUAKE', artists: ['Tyler, The Creator']},
          ],
        },
      ],
    });
  });

  it('treats CSV with a time column as listening history', () => {
    const tsv =
      'artist\ttrack\tplayed_at\nSZA\tSnooze\t2026-01-01\nSZA\tSaturn\t2026-01-02\n';
    expect(parseFile('history.tsv', tsv)).toEqual({
      kind: 'listening',
      format: 'csv-history',
      artists: [{artist: 'SZA', plays: 2, msPlayed: 0}],
    });
  });

  it('explains what is wrong with unsupported files', () => {
    expect(() => parseFile('notes.pdf', 'x')).toThrow(UnsupportedFileError);
    expect(() => parseFile('data.json', json({hello: 'world'}))).toThrow(
      'notListening',
    );
    expect(() => parseFile('data.json', '{broken')).toThrow('invalidJson');
    expect(() => parseFile('people.csv', 'name,email\nA,a@x\n')).toThrow(
      'noArtistColumn',
    );
  });
});

function input(
  name: string,
  content: string | Uint8Array,
  size?: number,
): InputFile {
  const bytes = typeof content === 'string' ? strToU8(content) : content;
  return {
    name,
    size: size ?? bytes.length,
    bytes: () => Promise.resolve(bytes),
  };
}

describe('importFiles', () => {
  const history = json([
    {endTime: 'x', artistName: 'SZA', trackName: 'Snooze', msPlayed: 1},
  ]);

  it('opens ZIP exports and ignores non-listening entries', async () => {
    const zip = zipSync({
      'Spotify Account Data/StreamingHistory_music_0.json': strToU8(history),
      'Spotify Account Data/ReadMeFirst.pdf': strToU8('pdf'),
      '__MACOSX/._StreamingHistory_music_0.json': strToU8('junk'),
    });
    const outcomes = await importFiles(
      [input('my_spotify_data.zip', zip)],
      () => undefined,
    );
    expect(outcomes.map(o => [o.file, o.ok])).toEqual([
      [
        'my_spotify_data.zip › Spotify Account Data/StreamingHistory_music_0.json',
        true,
      ],
    ]);
  });

  it('reports every rejected file with a reason (no silent drops)', async () => {
    const outcomes = await importFiles(
      [
        input('a.json', history),
        input('huge.json', history, MAX_FILE_BYTES + 1),
        input('photo.png', 'png'),
        input('empty.zip', zipSync({'readme.pdf': strToU8('x')})),
      ],
      () => undefined,
    );
    expect(outcomes.map(o => (o.ok ? 'ok' : o.reason))).toEqual([
      'ok',
      'tooLarge',
      'unsupportedType',
      'zipEmpty',
    ]);
  });

  it('reads CSVs saved by Excel (UTF-8 byte-order mark before the header)', async () => {
    const csv = '\uFEFFArtist,Title\nSZA,Snooze\n';
    const [outcome] = await importFiles(
      [input('excel.csv', csv)],
      () => undefined,
    );
    expect(outcome).toMatchObject({ok: true, parsed: {kind: 'playlists'}});
  });

  it('reads JSON that starts with a byte-order mark', async () => {
    const history = JSON.stringify([
      {endTime: 'x', artistName: 'SZA', trackName: 'S', msPlayed: 1},
    ]);
    const [outcome] = await importFiles(
      [input('h.json', '\uFEFF' + history)],
      () => undefined,
    );
    expect(outcome).toMatchObject({ok: true, parsed: {kind: 'listening'}});
  });

  it('reports progress and can be cancelled', async () => {
    const seen: number[] = [];
    await importFiles([input('a.json', history), input('b.json', history)], p =>
      seen.push(p.done),
    );
    expect(seen).toEqual([0, 1, 2]);
    const controller = new AbortController();
    controller.abort();
    await expect(
      importFiles(
        [input('a.json', history)],
        () => undefined,
        controller.signal,
      ),
    ).rejects.toThrow();
  });
});
