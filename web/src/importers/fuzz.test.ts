/**
 * Importer fuzzing (M8-04): malformed, truncated, mutated and adversarial files must each
 * produce an outcome (recognized or rejected with a reason), never an exception or a hang.
 * Seeded, so a failure reproduces; raise FUZZ_ROUNDS for a longer nightly run.
 */
import {readFileSync} from 'node:fs';

import {strToU8, zipSync} from 'fflate';
import {describe, expect, it} from 'vitest';

import {importFiles, type InputFile} from './importFiles';

const ROUNDS = Number(process.env.FUZZ_ROUNDS ?? 300);
const sample = readFileSync('e2e/fixtures/Playlist1.json', 'utf8');
const csv = 'Artist,Track,ms_played\nA,B,100\nC,D,200\n';
const plist =
  '<?xml version="1.0"?><plist version="1.0"><dict><key>Tracks</key><dict><key>1</key><dict><key>Track ID</key><integer>1</integer><key>Artist</key><string>A &amp; B</string><key>Play Count</key><integer>3</integer></dict></dict><key>Playlists</key><array><dict><key>Name</key><string>P</string><key>Playlist Items</key><array><dict><key>Track ID</key><integer>1</integer></dict></array></dict></array></dict></plist>';
const m3u = '#EXTM3U\n#EXTINF:1,A - B\nx.mp3\n#EXTART:Z\n/m/C - D.mp3\n';
const xspf =
  '<playlist xmlns="http://xspf.org/ns/0/"><title>T</title><trackList><track><creator>A</creator><title>B</title></track></trackList></playlist>';

/** Small deterministic PRNG (mulberry32). */
function rng(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function mutate(bytes: Uint8Array, next: () => number): Uint8Array {
  const out = Array.from(bytes);
  const kind = Math.floor(next() * 5);
  const at = Math.floor(next() * Math.max(1, out.length));
  if (kind === 0) return Uint8Array.from(out.slice(0, at)); // truncate
  if (kind === 1)
    out[at] = Math.floor(next() * 256); // flip a byte
  else if (kind === 2)
    out.splice(at, 0, ...[0, 0xff, 0x22, 0x7b, 0x5d]); // insert
  else if (kind === 3)
    out.splice(at, Math.floor(next() * 20)); // delete
  else out.push(...out.slice(0, at)); // duplicate a prefix
  return Uint8Array.from(out);
}

const file = (name: string, bytes: Uint8Array): InputFile => ({
  name,
  size: bytes.length,
  bytes: async () => bytes,
});

async function expectOutcomes(files: InputFile[]) {
  const started = performance.now();
  const outcomes = await importFiles(files, () => {});
  expect(outcomes.length).toBeGreaterThanOrEqual(files.length);
  for (const o of outcomes) expect(typeof o.ok).toBe('boolean');
  expect(performance.now() - started).toBeLessThan(5000);
  return outcomes;
}

// Hundreds of parses per test: allow for a busy machine (the 5 s default timed out
// while the server suite ran alongside). A hang still fails.
describe('importer fuzzing', {timeout: 30_000}, () => {
  it('survives mutated JSON, CSV and ZIP files', async () => {
    const next = rng(20261013);
    const zip = zipSync({
      'a/Playlist1.json': strToU8(sample),
      'b.csv': strToU8(csv),
    });
    const seeds: [string, Uint8Array][] = [
      ['p.json', strToU8(sample)],
      ['h.csv', strToU8(csv)],
      ['x.zip', zip],
      ['Library.xml', strToU8(plist)],
      ['p.m3u8', strToU8(m3u)],
      ['p.xspf', strToU8(xspf)],
    ];
    for (let i = 0; i < ROUNDS; i++) {
      const [name, bytes] = seeds[i % seeds.length]!;
      await expectOutcomes([file(name, mutate(bytes, next))]);
    }
  });

  it('survives random bytes under every accepted extension', async () => {
    const next = rng(7);
    for (const ext of [
      'json',
      'jsonl',
      'csv',
      'tsv',
      'txt',
      'xml',
      'm3u',
      'm3u8',
      'xspf',
      'zip',
      'bin',
    ]) {
      const bytes = Uint8Array.from({length: 4096}, () =>
        Math.floor(next() * 256),
      );
      await expectOutcomes([
        file(`noise.${ext}`, bytes),
        file(`empty.${ext}`, new Uint8Array()),
      ]);
    }
  });

  it('survives adversarial structure', async () => {
    const deep = '['.repeat(50_000) + ']'.repeat(50_000);
    const wide = JSON.stringify({
      playlists: [{items: Array.from({length: 20_000}, () => ({}))}],
    });
    const proto =
      '{"__proto__":{"polluted":true},"playlists":[{"items":[{"track":{"artistName":"A","trackName":"B"}}]}]}';
    const quotes = 'Artist,Track\n' + '"'.repeat(100_000);
    const bomb = zipSync({
      'big.csv': new Uint8Array(30 * 1024 * 1024).fill(0x41),
    });
    const traversal = zipSync({
      '../../etc/passwd.csv': strToU8(csv),
      '__MACOSX/x.csv': strToU8(csv),
    });
    const deepXml = '<dict>'.repeat(50_000);
    const unterminated = '<!--'.repeat(50_000) + '<![CDATA['.repeat(50_000);
    await expectOutcomes([
      file('deepdict.xml', strToU8(deepXml)),
      file('open.xml', strToU8(unterminated)),
      file('deep.json', strToU8(deep)),
      file('wide.json', strToU8(wide)),
      file('proto.json', strToU8(proto)),
      file('quotes.csv', strToU8(quotes)),
      file('bomb.zip', bomb),
      file('traversal.zip', traversal),
    ]);
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });
});
