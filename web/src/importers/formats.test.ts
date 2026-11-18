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

const dictOf = (id: number, fields: Record<string, string>) =>
  `<key>${id}</key><dict><key>Track ID</key><integer>${id}</integer>${Object.entries(
    fields,
  )
    .map(([k, v]) => `<key>${k}</key>${v}`)
    .join('')}</dict>`;

const LIBRARY_XML = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Major Version</key><integer>1</integer>
  <key>Tracks</key>
  <dict>
    ${dictOf(101, {Name: '<string>HUMBLE.</string>', Artist: '<string>Kendrick Lamar</string>', 'Album Artist': '<string>Kendrick Lamar</string>', 'Play Count': '<integer>10</integer>', 'Total Time': '<integer>177000</integer>', 'Play Date UTC': '<date>2026-01-01T10:00:00Z</date>'})}
    ${dictOf(102, {Name: '<string>Snooze</string>', 'Album Artist': '<string>SZA</string>', 'Play Count': '<integer>4</integer>', 'Total Time': '<integer>201000</integer>'})}
    ${dictOf(103, {Name: '<string>Tyler &amp; Co</string>', Artist: '<string>Tyler, The Creator</string>', 'Total Time': '<integer>100000</integer>'})}
    ${dictOf(104, {Name: '<string>Some Episode</string>', Artist: '<string>A Podcaster</string>', Podcast: '<true/>', 'Play Count': '<integer>50</integer>'})}
    ${dictOf(105, {Name: '<string>A Film</string>', Artist: '<string>Studio</string>', Kind: '<string>MPEG-4 video file</string>', 'Has Video': '<true/>', 'Play Count': '<integer>9</integer>'})}
  </dict>
  <key>Playlists</key>
  <array>
    <dict>
      <key>Name</key><string>Library</string>
      <key>Master</key><true/>
      <key>Playlist Items</key>
      <array><dict><key>Track ID</key><integer>101</integer></dict><dict><key>Track ID</key><integer>104</integer></dict></array>
    </dict>
    <dict>
      <key>Name</key><string>Recently Added</string>
      <key>Distinguished Kind</key><integer>2</integer>
      <key>Playlist Items</key>
      <array><dict><key>Track ID</key><integer>101</integer></dict></array>
    </dict>
    <dict>
      <key>Name</key><string>Gym</string>
      <key>Playlist Items</key>
      <array>
        <dict><key>Track ID</key><integer>101</integer></dict>
        <dict><key>Track ID</key><integer>104</integer></dict>
        <dict><key>Track ID</key><integer>102</integer></dict>
        <dict><key>Track ID</key><integer>999</integer></dict>
      </array>
    </dict>
  </array>
</dict>
</plist>`;

describe('parseFile: Apple Music library', () => {
  it('reads play counts as listening and exposes playlists, skipping non-music and system items', () => {
    expect(parseFile('Library.xml', LIBRARY_XML)).toEqual({
      kind: 'listening',
      format: 'apple-music-library',
      artists: [
        {artist: 'Kendrick Lamar', plays: 10, msPlayed: 1_770_000},
        {artist: 'SZA', plays: 4, msPlayed: 804_000},
      ],
      playlists: [
        {
          name: 'Gym',
          tracks: [
            {title: 'HUMBLE.', artists: ['Kendrick Lamar']},
            {title: 'Snooze', artists: ['SZA']},
          ],
        },
      ],
    });
  });

  it('counts each track once when the library has no play counts', () => {
    const xml = `<plist version="1.0"><dict><key>Tracks</key><dict>
      ${dictOf(1, {Artist: '<string>SZA</string>'})}
      ${dictOf(2, {Artist: '<string>SZA</string>'})}
      ${dictOf(3, {'Album Artist': '<string>Jai Paul</string>'})}
    </dict></dict></plist>`;
    expect(parseFile('Library.xml', xml)).toEqual({
      kind: 'listening',
      format: 'apple-music-library',
      artists: [
        {artist: 'SZA', plays: 2, msPlayed: 0},
        {artist: 'Jai Paul', plays: 1, msPlayed: 0},
      ],
    });
  });

  it('reads a single exported playlist as a playlist', () => {
    const xml = `<plist version="1.0"><dict><key>Tracks</key><dict>
      ${dictOf(7, {Name: '<string>Snooze</string>', Artist: '<string>SZA</string>', 'Play Count': '<integer>3</integer>'})}
    </dict><key>Playlists</key><array><dict>
      <key>Name</key><string>Chill &amp; Late</string>
      <key>Playlist Items</key><array><dict><key>Track ID</key><integer>7</integer></dict></array>
    </dict></array></dict></plist>`;
    expect(parseFile('Chill.xml', xml)).toEqual({
      kind: 'playlists',
      format: 'apple-music-library',
      playlists: [
        {name: 'Chill & Late', tracks: [{title: 'Snooze', artists: ['SZA']}]},
      ],
    });
  });

  it('rejects other XML, truncated files and deep nesting', () => {
    expect(() => parseFile('x.xml', '<plist><dict></dict></plist>')).toThrow(
      'notListening',
    );
    expect(() => parseFile('x.xml', '<note>hi</note>')).toThrow('notListening');
    expect(() =>
      parseFile('x.xml', LIBRARY_XML.slice(0, LIBRARY_XML.length / 2)),
    ).toThrow(UnsupportedFileError);
    expect(() => parseFile('x.xml', '<plist>' + '<dict>'.repeat(500))).toThrow(
      'damaged',
    );
  });
});

describe('parseFile: M3U', () => {
  const M3U8 = `\uFEFF#EXTM3U
#PLAYLIST:Road trip
#EXTINF:215,Kendrick Lamar - HUMBLE.
/music/kendrick/humble.mp3
#EXTALB:Some Album
#EXTART:SZA
#EXTINF:201,Snooze
C:\\Music\\snooze.flac
#EXTINF:-1 tvg-id="x",Daft Punk; Pharrell Williams - Get Lucky
http://example.com/stream
/music/Tyler, The Creator - EARFQUAKE.mp3
D:\\Music\\03 - Rihanna - Diamonds.m4a
/music/untitled recording.mp3
https://example.com/Some%20Band%20-%20A%20Song.ogg
#EXT-X-JUNK:1
`;

  it('reads EXTINF, EXTART, file names and ignores junk', () => {
    expect(parseFile('trip.m3u8', M3U8)).toEqual({
      kind: 'playlists',
      format: 'm3u-playlist',
      playlists: [
        {
          name: 'Road trip',
          tracks: [
            {title: 'HUMBLE.', artists: ['Kendrick Lamar']},
            {title: 'Snooze', artists: ['SZA']},
            {title: 'Get Lucky', artists: ['Daft Punk', 'Pharrell Williams']},
            {title: 'EARFQUAKE', artists: ['Tyler, The Creator']},
            {title: 'Diamonds', artists: ['Rihanna']},
            {title: 'A Song', artists: ['Some Band']},
          ],
        },
      ],
    });
  });

  it('names the playlist after the file and accepts a header-less list', () => {
    expect(
      parseFile('Mix.m3u', 'SZA - Saturn.mp3\r\nnonsense\r\n\r\n'),
    ).toEqual({
      kind: 'playlists',
      format: 'm3u-playlist',
      playlists: [{name: 'Mix', tracks: [{title: 'Saturn', artists: ['SZA']}]}],
    });
  });

  it('copes with empty files', () => {
    expect(parseFile('e.m3u', '')).toMatchObject({
      playlists: [{name: 'e', tracks: []}],
    });
  });
});

describe('parseFile: XSPF', () => {
  const XSPF = `<?xml version="1.0" encoding="UTF-8"?>
<playlist version="1" xmlns="http://xspf.org/ns/0/">
  <title>Evening &amp; chill</title>
  <creator>someone</creator>
  <trackList>
    <track><location>file:///a.mp3</location><creator>Kendrick Lamar</creator><title>HUMBLE.</title><album>DAMN.</album></track>
    <track><creator><![CDATA[Tyler, The Creator]]></creator><title>EARFQUAKE</title></track>
    <track><title>No creator</title></track>
    <!-- <track><creator>Hidden</creator></track> -->
    <track><creator>SZA</creator><title>Snooze &#38; more</title></track>
  </trackList>
</playlist>`;

  it('reads creator and title per track', () => {
    expect(parseFile('evening.xspf', XSPF)).toEqual({
      kind: 'playlists',
      format: 'xspf-playlist',
      playlists: [
        {
          name: 'Evening & chill',
          tracks: [
            {title: 'HUMBLE.', artists: ['Kendrick Lamar']},
            {title: 'EARFQUAKE', artists: ['Tyler, The Creator']},
            {title: 'Snooze & more', artists: ['SZA']},
          ],
        },
      ],
    });
  });

  it('is detected by content under an .xml name too', () => {
    expect(parseFile('p.xml', XSPF)).toMatchObject({format: 'xspf-playlist'});
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

  it('imports the new playlist and library formats from a ZIP', async () => {
    const zip = zipSync({
      'Library.xml': strToU8(LIBRARY_XML),
      'a/mix.m3u8': strToU8('#EXTM3U\n#EXTINF:1,SZA - Saturn\nx.mp3\n'),
    });
    const outcomes = await importFiles([input('apple.zip', zip)], () => {});
    expect(outcomes.map(o => o.ok && o.parsed.format)).toEqual([
      'm3u-playlist',
      'apple-music-library',
    ]);
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
