/* global window, document, location, scrollY, performance, PerformanceObserver -- page.evaluate callbacks run in the browser */
/**
 * Clicks through the controls on each route and reports what moves that
 * should not (a check for "glitches on click", not a test):
 *
 * - layout shifts in the 1.2 s after the click (with the elements that moved),
 * - entrance animations that replay on content that was already showing,
 * - scroll jumps when the click did not navigate,
 * - a page that empties out (blank flash) 50 ms after the click,
 * - console errors.
 *
 *   node scripts/click-probe.cjs [route ...] [--max N] [--mobile]
 *
 * Env: BASE (default http://127.0.0.1:5175). Defaults to the main routes.
 */
const process = require('node:process');
const {URL} = require('node:url');

const {chromium} = require('@playwright/test');

const args = process.argv.slice(2);
const flag = name => args.includes(name);
const maxAt = args.indexOf('--max');
const MAX = maxAt >= 0 ? Number(args[maxAt + 1]) : 14;
const routes = args.filter(
  (a, i) => !a.startsWith('--') && (maxAt < 0 || i !== maxAt + 1),
);
const BASE = process.env.BASE || 'http://127.0.0.1:5175';
const ROUTES = routes.length
  ? routes
  : [
      '/',
      '/explore',
      '/play',
      '/stories',
      '/friends',
      '/library',
      '/around-you',
      '/around-you?c=madison-us-wi',
    ];

const SETUP = () => {
  window.__shifts = [];
  new PerformanceObserver(list => {
    for (const e of list.getEntries())
      window.__shifts.push({
        t: e.startTime,
        value: e.value,
        nodes: (e.sources || [])
          .map(s => {
            const n = s.node;
            if (!n || n.nodeType !== 1) return n ? n.nodeName : '?';
            const cls =
              typeof n.className === 'string'
                ? n.className.split(' ').filter(Boolean).slice(0, 2).join('.')
                : '';
            return `${n.tagName.toLowerCase()}${cls ? '.' + cls : ''}`;
          })
          .slice(0, 4),
      });
  }).observe({type: 'layout-shift', buffered: false});
};

/** Visible, clickable controls that stay inside the app. */
const CANDIDATES = () => {
  const seen = new Set();
  const out = [];
  const els = document.querySelectorAll(
    'main button, main summary, main [role="tab"], main a[href^="/"], main label[for]',
  );
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    if (el.closest('[aria-hidden="true"]')) continue;
    if (el.matches(':disabled')) continue;
    const text = (el.innerText || el.getAttribute('aria-label') || '')
      .trim()
      .replace(/\s+/g, ' ')
      .slice(0, 40);
    if (
      /sign in|share|copy|log ?out|delete|leave|disconnect|choose files/i.test(
        text,
      )
    )
      continue;
    const key = `${el.tagName}|${text}|${el.getAttribute('href') || ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    el.setAttribute('data-probe', String(out.length));
    out.push({
      i: out.length,
      tag: el.tagName.toLowerCase(),
      text,
      href: el.getAttribute('href'),
    });
  }
  return out;
};

(async () => {
  const browser = await chromium.launch();
  const mobile = flag('--mobile');
  const context = await browser.newContext({
    viewport: mobile ? {width: 390, height: 844} : {width: 1440, height: 900},
    colorScheme: 'dark',
  });
  await context.addInitScript(SETUP);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
  page.on('console', m => {
    if (m.type() === 'error') errors.push(`console: ${m.text().slice(0, 160)}`);
  });
  const findings = [];
  for (const route of ROUTES) {
    await page.goto(BASE + route);
    await page.waitForTimeout(2500);
    const controls = (await page.evaluate(CANDIDATES)).slice(0, MAX);
    for (const c of controls) {
      await page.goto(BASE + route);
      await page.waitForTimeout(1800);
      await page.evaluate(CANDIDATES);
      const el = page.locator(`[data-probe="${c.i}"]`);
      if (!(await el.count())) continue;
      await el.scrollIntoViewIfNeeded().catch(() => {});
      await page.waitForTimeout(250);
      const before = await page.evaluate(() => ({
        url: location.href,
        y: scrollY,
        text: document.querySelector('main')?.innerText.length ?? 0,
        t: performance.now(),
        shown: [...document.querySelectorAll('.stagger > *')].length,
      }));
      await page.evaluate(() => (window.__shifts = []));
      try {
        await el.click({timeout: 3000});
      } catch {
        continue;
      }
      await page.waitForTimeout(50);
      const flash = await page.evaluate(
        () => document.querySelector('main')?.innerText.length ?? 0,
      );
      await page.waitForTimeout(1150);
      const after = await page.evaluate(t0 => {
        const replays = document
          .getAnimations()
          .filter(a => a.animationName === 'rise-in' && a.startTime !== null)
          .filter(a => a.startTime >= t0).length;
        return {
          url: location.href,
          y: scrollY,
          text: document.querySelector('main')?.innerText.length ?? 0,
          shifts: window.__shifts,
          replays,
        };
      }, before.t);
      const navigated = after.url !== before.url;
      const shift = after.shifts.reduce((s, e) => s + e.value, 0);
      const issues = [];
      if (shift > 0.02)
        issues.push(
          `layout shift ${shift.toFixed(3)} [${[...new Set(after.shifts.flatMap(s => s.nodes))].slice(0, 5).join(', ')}]`,
        );
      if (!navigated && after.replays > 0 && before.shown > 0)
        issues.push(`${after.replays} entrance animations replayed in place`);
      if (!navigated && Math.abs(after.y - before.y) > 40)
        issues.push(`scroll jumped ${before.y} -> ${after.y}`);
      if (before.text > 200 && flash < before.text * 0.25)
        issues.push(`blank flash (${before.text} -> ${flash} chars at 50 ms)`);
      if (issues.length)
        findings.push(
          `${route} :: ${c.tag} "${c.text}"${navigated ? ` -> ${new URL(after.url).pathname}` : ''}\n    ${issues.join('\n    ')}`,
        );
    }
  }
  process.stdout.write(
    `${findings.length} findings\n${findings.join('\n')}\n` +
      (errors.length ? `\nerrors:\n${[...new Set(errors)].join('\n')}\n` : ''),
  );
  await browser.close();
})();
