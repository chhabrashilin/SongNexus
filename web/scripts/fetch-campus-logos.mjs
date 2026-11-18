#!/usr/bin/env node
/**
 * Builds src/community/campusLogos.json: the mark each campus is known by, from
 * Wikimedia Commons, found through Wikidata items, never by name.
 *
 *   node scripts/fetch-campus-logos.mjs
 *
 * 1. Candidates. For every campus in the Around you directory
 *    (server/src/songnexus/catalog/communities.json):
 *    - the current logos (P154) of its athletics program, the item that
 *      "represents" (P1268) the university: Wisconsin's motion W, Illinois's
 *      block I. Statements with an end date (P582) are retired marks and skipped;
 *    - the university's own small logo (P8972), logo (P154) and seal (P158).
 * 2. Files. Commons gives size, MIME type and license. Only SVG and PNG, and
 *    only public domain, CC0, CC BY and CC BY-SA files that are not marked
 *    non-free (the rule of ADR 0009).
 * 3. Looks. Each candidate's 330 px thumbnail is drawn in a headless browser:
 *    is the background transparent, and do its pixels stand out against the
 *    app's dark (#111) and light (#f6f6f6) card surfaces? A transparent mark
 *    that reads on a theme is shown bare there; one that would disappear gets
 *    a plate (white on dark, near-black on light).
 * 4. Choice, by score: an athletics mark over the university's own; the
 *    newest (preferred rank, latest start date); a compact mark over a wide
 *    wordmark; a transparent mark that reads on both themes over one that
 *    needs a plate.
 *
 * Generic User-Agent, no contact details; one Commons API request a second
 * and one thumbnail every 400 ms.
 */
/* global Image, document -- used inside page.evaluate, which runs in the browser */
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import {setTimeout as sleep} from 'node:timers/promises';
import {fileURLToPath, URLSearchParams} from 'node:url';

import {chromium} from '@playwright/test';

const {fetch} = globalThis;

const here = path.dirname(fileURLToPath(import.meta.url));
const DIRECTORY = path.resolve(
  here,
  '../../server/src/songnexus/catalog/communities.json',
);
const OUT = path.resolve(here, '../src/community/campusLogos.json');
const UA = 'SongNexus/0.2 (student capstone project)';
const WIDTH = 330;
/** Card surfaces in tokens.css (--md-surface-container-low). */
const SURFACE = {dark: [17, 17, 17], light: [246, 246, 246]};

async function getJson(url, init = {}) {
  for (let attempt = 0; attempt < 5; attempt++) {
    const res = await fetch(url, {
      ...init,
      headers: {'User-Agent': UA, Accept: 'application/json', ...init.headers},
    });
    if (res.ok) return res.json();
    if (res.status !== 429 && res.status < 500)
      throw new Error(`${res.status} ${url}`);
    await sleep(2000 * 2 ** attempt);
  }
  throw new Error(`gave up on ${url}`);
}

const sparql = query =>
  getJson('https://query.wikidata.org/sparql', {
    method: 'POST',
    headers: {
      Accept: 'application/sparql-results+json',
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: `query=${encodeURIComponent(query)}`,
  }).then(r => r.results.bindings);

const qid = uri => uri.split('/').pop();
const fileTitle = uri =>
  'File:' + decodeURIComponent(uri.split('/').pop()).replace(/_/g, ' ');

function isFreeLicense(name) {
  const n = name.trim().toLowerCase();
  if (/\b(nc|nd)\b|non-?commercial|no ?deriv/.test(n)) return false;
  return (
    n.startsWith('public domain') ||
    n.startsWith('pd') ||
    n === 'cc0' ||
    n.startsWith('cc0 ') ||
    /^cc[ -]by(-sa)?([ -]\d(\.\d)?)?/.test(n)
  );
}

function plainText(html) {
  return html
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^(.+?)\1$/, '$1'); // Commons sometimes repeats the text.
}

const directory = JSON.parse(fs.readFileSync(DIRECTORY, 'utf8'));
const campuses = directory.communities.filter(
  c => c.kind === 'CAMPUS' && /^Q\d+$/.test(c.wikidata ?? ''),
);
const values = campuses.map(c => `wd:${c.wikidata}`).join(' ');

// 1. Candidates: athletics marks, then the university's own.
const candidates = new Map(campuses.map(c => [c.wikidata, []]));
for (const b of await sparql(`SELECT ?u ?team ?teamLabel ?logo ?rank ?start ?end WHERE {
  VALUES ?u { ${values} }
  ?team wdt:P1268 ?u ; p:P154 ?st .
  ?st ps:P154 ?logo ; wikibase:rank ?rank .
  OPTIONAL { ?st pq:P580 ?start }
  OPTIONAL { ?st pq:P582 ?end }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}`)) {
  if (b.end || b.rank.value.endsWith('DeprecatedRank')) continue;
  candidates.get(qid(b.u.value))?.push({
    source: 'athletics',
    team: b.teamLabel?.value ?? '',
    title: fileTitle(b.logo.value),
    preferred: b.rank.value.endsWith('PreferredRank'),
    start: b.start ? Number(b.start.value.slice(0, 4)) : null,
  });
}
for (const b of await sparql(`SELECT ?u ?prop ?logo ?rank WHERE {
  VALUES ?u { ${values} }
  VALUES ?prop { p:P8972 p:P154 p:P158 }
  ?u ?prop ?st . ?st ?ps ?logo ; wikibase:rank ?rank .
  FILTER(STRSTARTS(STR(?ps), "http://www.wikidata.org/prop/statement/P"))
  FILTER(STRSTARTS(STR(?logo), "http://commons.wikimedia.org/"))
  FILTER NOT EXISTS { ?st pq:P582 [] }
}`)) {
  if (b.rank.value.endsWith('DeprecatedRank')) continue;
  const prop = qid(b.prop.value);
  candidates.get(qid(b.u.value))?.push({
    source: prop === 'P158' ? 'seal' : 'logo',
    team: '',
    title: fileTitle(b.logo.value),
    preferred: b.rank.value.endsWith('PreferredRank'),
    start: null,
    small: prop === 'P8972',
  });
}

// 2. Files: size, MIME, license and thumbnail from the Commons API.
const titles = [...new Set([...candidates.values()].flat().map(c => c.title))];
const info = new Map();
for (let i = 0; i < titles.length; i += 50) {
  const batch = titles.slice(i, i + 50);
  const params = new URLSearchParams({
    action: 'query',
    format: 'json',
    formatversion: '2',
    prop: 'imageinfo',
    iiprop: 'url|size|mime|extmetadata',
    iiurlwidth: String(WIDTH),
    iiextmetadatafilter:
      'LicenseShortName|LicenseUrl|Artist|NonFree|AttributionRequired',
    titles: batch.join('|'),
  });
  // Big batches come back in parts: follow `continue` until every page is in.
  const alias = new Map();
  const pages = new Map();
  let cont = {};
  for (;;) {
    const res = await getJson(
      `https://commons.wikimedia.org/w/api.php?${params}&${new URLSearchParams(cont)}`,
    );
    for (const n of res.query.normalized ?? []) alias.set(n.from, n.to);
    for (const r of res.query.redirects ?? []) alias.set(r.from, r.to);
    for (const p of res.query.pages)
      if (p.imageinfo?.[0] && !pages.has(p.title)) pages.set(p.title, p);
    if (!res.continue) break;
    cont = res.continue;
    await sleep(1000);
  }
  for (const t of batch) {
    let key = t;
    for (let hop = 0; hop < 3 && alias.has(key); hop++) key = alias.get(key);
    const page = pages.get(key);
    if (page) info.set(t, page.imageinfo[0]);
  }
  await sleep(1000);
}

const skipped = {notSvgOrPng: 0, license: {}, failedToLoad: 0};
function usable(c) {
  const ii = info.get(c.title);
  if (!ii) return false;
  if (!['image/svg+xml', 'image/png'].includes(ii.mime)) {
    skipped.notSvgOrPng++;
    return false;
  }
  const meta = ii.extmetadata ?? {};
  const license = meta.LicenseShortName?.value ?? '';
  if (meta.NonFree?.value || !isFreeLicense(license)) {
    skipped.license[license || '(none)'] =
      (skipped.license[license || '(none)'] ?? 0) + 1;
    return false;
  }
  return /^https:\/\/(upload|thumb)\.wikimedia\.org\//.test(ii.thumburl ?? '');
}
for (const [q, list] of candidates)
  candidates.set(
    q,
    list.filter(c => usable(c)).map(c => ({...c, ii: info.get(c.title)})),
  );

// 3. Looks: transparency and contrast against both card surfaces.
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent('<canvas></canvas>');
const looks = new Map();
for (const src of new Set(
  [...candidates.values()].flat().map(c => c.ii.thumburl),
)) {
  const result = await page.evaluate(
    async ({src, surface}) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.src = src;
      try {
        await img.decode();
      } catch {
        return null;
      }
      const scale = 160 / Math.max(img.naturalWidth, img.naturalHeight);
      const w = Math.max(1, Math.round(img.naturalWidth * scale));
      const h = Math.max(1, Math.round(img.naturalHeight * scale));
      const canvas = document.querySelector('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d', {willReadFrequently: true});
      ctx.clearRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0, w, h);
      const {data} = ctx.getImageData(0, 0, w, h);
      const lin = v => {
        const c = v / 255;
        return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      };
      const lum = (r, g, b) =>
        0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
      const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      const dark = lum(...surface.dark);
      const light = lum(...surface.light);
      let clear = 0;
      let ink = 0;
      let onDark = 0;
      let onLight = 0;
      for (let i = 0; i < data.length; i += 4) {
        const a = data[i + 3] / 255;
        if (a < 0.05) {
          clear++;
          continue;
        }
        if (a < 0.5) continue;
        ink++;
        const l = lum(data[i], data[i + 1], data[i + 2]);
        if (ratio(l, dark) >= 2.2) onDark++;
        if (ratio(l, light) >= 2.2) onLight++;
      }
      return {
        // Tight crops put ink in the corners, so count clear pixels instead:
        // a mark with its own background has next to none.
        transparent: clear / (w * h) > 0.04,
        onDark: ink > 0 && onDark / ink >= 0.6,
        onLight: ink > 0 && onLight / ink >= 0.6,
      };
    },
    {src, surface: SURFACE},
  );
  if (!result) skipped.failedToLoad++;
  looks.set(src, result);
  await sleep(400);
}
await browser.close();

// 4. Choice.
const isWordmark = c => /wordmark|text ?logo|logotype|script/i.test(c.title);
function score(c) {
  const look = looks.get(c.ii.thumburl);
  const aspect = c.ii.width / Math.max(1, c.ii.height);
  let s = 0;
  if (c.source === 'athletics') s += 100;
  if (c.small) s += 30;
  if (c.source === 'seal') s -= 5;
  if (c.preferred) s += 15;
  if (c.start) s += (c.start - 2000) * 0.5;
  if (aspect <= 1.8) s += 12;
  else if (aspect > 3) s -= 8;
  if (isWordmark(c)) s -= 6;
  if (look?.transparent) s += 6;
  if (look?.transparent && look.onDark && look.onLight) s += 8;
  else if (look?.transparent && look.onDark) s += 4;
  return s;
}

const logos = {};
for (const campus of campuses) {
  const ranked = candidates
    .get(campus.wikidata)
    .filter(c => looks.get(c.ii.thumburl))
    .map(c => ({c, s: score(c)}))
    .sort((a, b) => b.s - a.s || a.c.title.localeCompare(b.c.title));
  if (!ranked.length) continue;
  const {c} = ranked[0];
  const look = looks.get(c.ii.thumburl);
  const meta = c.ii.extmetadata ?? {};
  logos[campus.id] = {
    src: c.ii.thumburl,
    aspect: Math.round((c.ii.width / Math.max(1, c.ii.height)) * 100) / 100,
    kind: c.source,
    ...(c.team ? {team: c.team} : {}),
    // A plate behind the mark on that theme: it has no background of its own
    // and would not read on the bare card.
    plate: {
      dark: look.transparent && !look.onDark,
      light: look.transparent && !look.onLight,
    },
    page: c.ii.descriptionurl,
    author: plainText(meta.Artist?.value ?? ''),
    license: meta.LicenseShortName?.value ?? '',
    licenseUrl: meta.LicenseUrl?.value ?? '',
  };
}

const sorted = Object.fromEntries(
  Object.entries(logos).sort(([a], [b]) => a.localeCompare(b)),
);
fs.writeFileSync(
  OUT,
  JSON.stringify(
    {
      source:
        'Wikidata (athletics program P154 via P1268; university P8972, P154, P158) and Wikimedia Commons',
      generatedAt: new Date().toISOString().slice(0, 10),
      logos: sorted,
    },
    null,
    2,
  ) + '\n',
);
const kinds = {};
for (const l of Object.values(sorted)) kinds[l.kind] = (kinds[l.kind] ?? 0) + 1;
process.stdout.write(
  `${Object.keys(sorted).length} of ${campuses.length} campuses have a mark ` +
    `${JSON.stringify(kinds)} ${JSON.stringify(skipped)}\n`,
);
