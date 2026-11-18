/**
 * Screenshots right after a click, to see what a click does frame by frame
 * (a debugging aid, not a test).
 *
 *   node scripts/click-frames.cjs <outDir> <route> <selector> [--mobile]
 *
 * Saves <outDir>/frame-<ms>.png at 0, 60, 150, 300, 600 and 1200 ms after the
 * click. Env: BASE (default http://127.0.0.1:5175), WAIT before the click.
 */
const fs = require('node:fs');
const path = require('node:path');
const process = require('node:process');

const {chromium} = require('@playwright/test');

(async () => {
  const [outDir, route, selector] = process.argv.slice(2);
  fs.mkdirSync(outDir, {recursive: true});
  const mobile = process.argv.includes('--mobile');
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: mobile ? {width: 390, height: 844} : {width: 1440, height: 900},
    colorScheme: 'dark',
  });
  const base = process.env.BASE || 'http://127.0.0.1:5175';
  await page.goto(base + route);
  await page.waitForTimeout(Number(process.env.WAIT || 3000));
  const target = page.locator(selector).first();
  await target.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await target.click();
  let last = 0;
  for (const ms of [0, 60, 150, 300, 600, 1200]) {
    await page.waitForTimeout(ms - last);
    last = ms;
    await page.screenshot({path: path.join(outDir, `frame-${ms}.png`)});
  }
  await browser.close();
  process.stdout.write(`saved frames in ${outDir}\n`);
})();
