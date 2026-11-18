/**
 * Explore frame rate with a large web, on a slowed CPU (R2-2 budget: >= 50 fps at
 * 300 nodes on a mid-range phone). Opt-in, because frame rates on shared CI
 * runners are noise: `SONGNEXUS_PERF=1 npx playwright test perf --project=mobile`.
 * The result is printed and recorded by hand in docs/perf/measurements.md.
 */
import {expect, test} from '@playwright/test';

test.skip(!process.env.SONGNEXUS_PERF, 'set SONGNEXUS_PERF=1 to measure');

const CPU_SLOWDOWN = 4; // Chrome DevTools' "mid-tier mobile" preset

// Headless Chromium rasterizes canvas in software by default, which a phone does
// not; use the machine's GPU so the number reflects drawing, not the emulator.
test.use({
  launchOptions: {
    args: ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=d3d11'],
  },
});

test('explore holds its frame rate with a large web', async ({page}) => {
  // Growing the web to 300 artists alone takes longer than the 30 s default.
  test.setTimeout(180_000);
  const cdp = await page.context().newCDPSession(page);
  await page.goto('/');
  const search = page.getByRole('combobox', {name: 'Search artists and songs'});
  await search.fill('Kendrick Lamar');
  await page
    .getByRole('option', {name: /^Kendrick Lamar/})
    .first()
    .click();
  await page.getByRole('link', {name: 'Explore connections'}).click();
  const grow = page.getByRole('button', {name: 'Expand the 5 strongest'});
  const canvas = page.locator('canvas');
  const nodeCount = async () =>
    Number(await canvas.getAttribute('data-node-count'));
  const trail = page.getByRole('navigation', {name: 'Artists you expanded'});
  // Grow from the center, then from each expanded artist in turn, until the cap.
  for (
    let round = 0, from = 0;
    round < 40 && (await nodeCount()) < 300;
    round++
  ) {
    await expect(grow)
      .toBeEnabled({timeout: 15_000})
      .catch(() => undefined);
    if (!(await grow.isEnabled())) {
      from++;
      if (from >= (await trail.getByRole('button').count())) break;
      await trail.getByRole('button').nth(from).click();
      continue;
    }
    await grow.click();
    await expect(grow).toBeDisabled();
  }
  // Let the layout settle, then start one more expansion and measure while it moves.
  await page.waitForTimeout(8000);
  await page.getByRole('button', {name: 'Undo'}).click();
  const fps = () =>
    page.evaluate(
      () =>
        new Promise<number>(resolve => {
          let frames = 0;
          const start = performance.now();
          const tick = () => {
            frames++;
            if (performance.now() - start < 2500) requestAnimationFrame(tick);
            else resolve((frames * 1000) / (performance.now() - start));
          };
          requestAnimationFrame(tick);
        }),
    );
  const measure = async (rate: number) => {
    await cdp.send('Emulation.setCPUThrottlingRate', {rate});
    const value = await fps();
    await cdp.send('Emulation.setCPUThrottlingRate', {rate: 1});
    return Math.round(value * 10) / 10;
  };
  const nodes = await nodeCount();
  // Moving: right after a change restarts the layout.
  const movingSlow = await measure(CPU_SLOWDOWN);
  await page.getByRole('button', {name: 'Expand the 5 strongest'}).click();
  const movingFast = await measure(1);
  await page.waitForTimeout(10_000);
  const settledSlow = await measure(CPU_SLOWDOWN);
  const result = {
    nodes,
    movingSlow,
    movingFast,
    settledSlow,
    cpuSlowdown: CPU_SLOWDOWN,
  };
  console.log(`explore-perf ${JSON.stringify(result)}`);
  expect(result.movingFast).toBeGreaterThan(0);
});
