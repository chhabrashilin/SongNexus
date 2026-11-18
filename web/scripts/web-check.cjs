/**
 * Drives the connection web like a person would and saves what it sees
 * (visual review, not a test): hover an artist, select one, select a line,
 * filter by orbit, share the image.
 *
 *   node scripts/web-check.cjs <outDir> [artistId] [--mobile]
 */
const fs = require('node:fs');
const path = require('node:path');
const process = require('node:process');

const {chromium} = require('@playwright/test');

(async () => {
  const [outDir, artist = '10851cf2-c4db-507e-afb8-55cbcf92be0b'] = process.argv
    .slice(2)
    .filter(a => !a.startsWith('--'));
  const mobile = process.argv.includes('--mobile');
  fs.mkdirSync(outDir, {recursive: true});
  const shot = name =>
    page.screenshot({
      path: path.join(outDir, `${name}${mobile ? '-m' : ''}.png`),
    });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: mobile ? {width: 390, height: 844} : {width: 1440, height: 900},
    colorScheme: 'dark',
    acceptDownloads: true,
    hasTouch: mobile,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(120_000);
  const errors = [];
  page.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
  page.on('console', m => {
    if (m.type() === 'error' && !m.text().includes('401'))
      errors.push(`console: ${m.text()}`);
  });
  await page.goto(`http://127.0.0.1:5175/explore/${artist}`, {
    waitUntil: 'networkidle',
  });
  await page.waitForTimeout(8000);
  const canvas = page.locator('canvas[aria-label^="Connection web"]');
  const box = await canvas.boundingBox();

  // Find an artist and a line on the canvas by probing where the pointer turns.
  async function probe(want) {
    for (let r = 120; r < 260; r += 14)
      for (let a = 0; a < 360; a += 9) {
        const x = box.x + box.width / 2 + r * Math.cos((a * Math.PI) / 180);
        const y =
          box.y + box.height / 2 + 20 + r * Math.sin((a * Math.PI) / 180);
        await page.mouse.move(x, y);
        const tip = page.locator('.web__tip');
        if (!(await tip.isVisible())) continue;
        const text = (await tip.textContent()) ?? '';
        if (want(text)) return {x, y, text};
      }
    return null;
  }

  if (!mobile) {
    const node = await probe(t => t.includes('listeners'));
    process.stdout.write(`hover artist: ${node?.text}\n`);
    await page.waitForTimeout(500);
    await shot('1-hover');
    const line = await probe(t => t.includes('&'));
    process.stdout.write(`hover line: ${line?.text}\n`);
    await shot('2-hover-line');
    if (line) {
      await page.mouse.click(line.x, line.y);
      await page.waitForTimeout(2500);
      await shot('3-line-selected');
    }
    if (node) {
      await page.mouse.click(node.x, node.y);
      await page.waitForTimeout(2500);
      await shot('4-artist-selected');
    }
    await page.getByRole('button', {name: /^Features/}).click();
    await page.waitForTimeout(4000);
    await shot('5-features-only');
    await page.getByRole('button', {name: 'Everyone'}).click();
    await page.waitForTimeout(3000);
    const download = page
      .waitForEvent('download', {timeout: 20_000})
      .catch(() => null);
    await page.getByRole('button', {name: 'Share'}).click();
    const file = await download;
    if (file) {
      const target = path.join(outDir, 'story.png');
      await file.saveAs(target);
      process.stdout.write(`share image: ${target}\n`);
    } else process.stdout.write('share image: no download\n');
    await page.waitForTimeout(800);
    await shot('6-after-share');
  } else {
    await shot('1-phone');
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2 + 20);
    await page.waitForTimeout(2500);
    await shot('2-phone-center-tapped');
  }
  if (errors.length)
    process.stdout.write(`ERRORS\n${[...new Set(errors)].join('\n')}\n`);
  await browser.close();
})();
