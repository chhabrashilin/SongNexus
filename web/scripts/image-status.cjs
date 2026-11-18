/**
 * Lists every image response a route loads from a host, with its status, to
 * debug hot-linked images (not a test).
 *
 *   node scripts/image-status.cjs <route> [hostSubstring]
 *
 * Env: BASE (default http://127.0.0.1:5175), WAIT ms after load (default 8000).
 */
const process = require('node:process');

const {chromium} = require('@playwright/test');

(async () => {
  const [route = '/', host = 'wikimedia'] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({viewport: {width: 1440, height: 1600}});
  const seen = [];
  page.on('response', r => {
    if (r.url().includes(host))
      seen.push(`${r.status()} ${r.url().slice(0, 140)}`);
  });
  page.on('requestfailed', r => {
    if (r.url().includes(host))
      seen.push(`FAILED ${r.failure()?.errorText} ${r.url().slice(0, 140)}`);
  });
  const base = process.env.BASE || 'http://127.0.0.1:5175';
  await page.goto(base + route);
  await page.waitForTimeout(Number(process.env.WAIT || 8000));
  process.stdout.write(`${seen.join('\n')}\n`);
  await browser.close();
})();
