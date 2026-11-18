/**
 * Screenshots of routes for visual review (not a test).
 *
 *   node scripts/screens.cjs <outDir> <route[::name]>... [--mobile] [--light] [--full]
 *
 * Env: BASE (default http://127.0.0.1:5175), WAIT ms after load (default 2500),
 * CLICK a CSS selector to click before the shot, HOVER "x,y" to point at.
 */
const fs = require('node:fs');
const path = require('node:path');
const process = require('node:process');

const {chromium} = require('@playwright/test');

(async () => {
  const args = process.argv.slice(2);
  const flags = new Set(args.filter(a => a.startsWith('--')));
  const rest = args.filter(a => !a.startsWith('--'));
  const outDir = rest[0];
  fs.mkdirSync(outDir, {recursive: true});
  const mobile = flags.has('--mobile');
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: mobile ? {width: 390, height: 844} : {width: 1440, height: 900},
    colorScheme: flags.has('--light') ? 'light' : 'dark',
  });
  const page = await context.newPage();
  page.setDefaultTimeout(120_000);
  const errors = [];
  page.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
  page.on('console', m => {
    if (m.type() === 'error') errors.push(`console: ${m.text()}`);
  });
  const base = process.env.BASE || 'http://127.0.0.1:5175';
  for (const spec of rest.slice(1)) {
    const [route, name] = spec.split('::');
    const file = path.join(
      outDir,
      `${name || route.replace(/[^a-z0-9]+/gi, '_') || 'home'}${mobile ? '-m' : ''}.png`,
    );
    await page.goto(base + route, {waitUntil: 'networkidle'});
    await page.waitForTimeout(Number(process.env.WAIT || 2500));
    if (process.env.HOVER) {
      const [x, y] = process.env.HOVER.split(',').map(Number);
      await page.mouse.move(x, y);
      await page.waitForTimeout(600);
    }
    if (process.env.CLICK) {
      await page.locator(process.env.CLICK).first().click();
      await page.waitForTimeout(1200);
    }
    await page.screenshot({path: file, fullPage: flags.has('--full')});
    process.stdout.write(`saved ${file}\n`);
  }
  const unique = [...new Set(errors)].filter(e => !e.includes('401'));
  if (unique.length) process.stdout.write(`ERRORS\n${unique.join('\n')}\n`);
  await browser.close();
})();
