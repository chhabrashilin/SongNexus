/**
 * Renders the app icons in public/icons from the SongNexus mark.
 * Run from web/: `node scripts/make-icons.mjs` (uses the Playwright browser the
 * end-to-end tests already install). Commit the PNGs it writes.
 *
 * - icon-192 / icon-512: the red disc on a transparent square.
 * - maskable-512: the mark inside the 80% safe zone on the app's near-black,
 *   so any launcher mask (circle, squircle) keeps the whole mark.
 * - apple-touch-icon: 180px, opaque (iOS ignores transparency).
 */
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import {chromium} from '@playwright/test';

const MARK = `
  <circle cx="14" cy="14" r="14" fill="#ff0000"/>
  <circle cx="14" cy="14" r="9.4" fill="none" stroke="#fff" stroke-opacity="0.38" stroke-width="1"/>
  <path d="M11 8.9 11 19.1 19.6 14Z" fill="none" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/>
  <circle cx="11" cy="8.9" r="2.3" fill="#fff"/>
  <circle cx="11" cy="19.1" r="2.3" fill="#fff"/>
  <circle cx="19.6" cy="14" r="2.3" fill="#fff"/>`;

/** The mark scaled to `inset` of the square (1 = edge to edge), on `background`. */
function svg(size, inset, background) {
  const scale = (size * inset) / 28;
  const offset = (size * (1 - inset)) / 2;
  const fill = background
    ? `<rect width="${size}" height="${size}" fill="${background}"/>`
    : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${fill}<g transform="translate(${offset} ${offset}) scale(${scale})">${MARK}</g></svg>`;
}

const ICONS = [
  {file: 'icon-192.png', size: 192, inset: 0.94, background: null},
  {file: 'icon-512.png', size: 512, inset: 0.94, background: null},
  {file: 'maskable-512.png', size: 512, inset: 0.62, background: '#030303'},
  {file: 'apple-touch-icon.png', size: 180, inset: 0.7, background: '#030303'},
];

const out = path.join(import.meta.dirname, '..', 'public', 'icons');
{
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch();
  for (const icon of ICONS) {
    const page = await browser.newPage({
      viewport: {width: icon.size, height: icon.size},
      deviceScaleFactor: 1,
    });
    await page.setContent(
      `<body style="margin:0;background:transparent">${svg(icon.size, icon.inset, icon.background)}</body>`,
    );
    await page.screenshot({
      path: path.join(out, icon.file),
      omitBackground: icon.background === null,
    });
    await page.close();
    process.stdout.write(`wrote ${icon.file}
`);
  }
  await browser.close();
}
