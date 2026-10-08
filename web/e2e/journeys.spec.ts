/**
 * End-to-end journeys for the committed screens (M5-07), each with an axe scan:
 * zero serious or critical accessibility issues (plan §10).
 *
 * Needs the API on :8790 with the reference catalog and `vite preview` (e2e/README.md).
 */
import AxeBuilder from '@axe-core/playwright';
import {expect, test, type Page} from '@playwright/test';

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({page})
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
    .analyze();
  const serious = results.violations.filter(
    v => v.impact === 'serious' || v.impact === 'critical',
  );
  expect(
    serious.map(
      v => `${v.id}: ${v.nodes.map(n => n.target.join(' ')).join(', ')}`,
    ),
  ).toEqual([]);
}

async function openArtist(page: Page, query: string, name: string) {
  await page.goto('/');
  const search = page.getByRole('combobox', {name: 'Search artists and songs'});
  await search.fill(query);
  await page
    .getByRole('option', {name: new RegExp(`^${name}`)})
    .first()
    .click();
  await expect(page.getByRole('heading', {level: 1, name})).toBeVisible();
}

test('home is accessible and explains the product', async ({page}) => {
  await page.goto('/');
  await expect(page.getByRole('heading', {level: 1})).toHaveText(
    'Discover who made the music you love',
  );
  await expectAccessible(page);
});

test('search finds artists in any script', async ({page}) => {
  await page.goto('/');
  const search = page.getByRole('combobox', {name: 'Search artists and songs'});
  await search.fill('방탄소년단');
  await expect(page.getByRole('option').first()).toContainText('BTS');
  await search.fill('beyonce');
  await expect(page.getByRole('option').first()).toContainText('Beyoncé');
});

test('artist page shows collaborations with evidence and sources', async ({
  page,
}) => {
  await openArtist(page, 'Kendrick Lamar', 'Kendrick Lamar');
  await expect(page.getByRole('tab', {name: /Features/})).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await page.getByRole('tab', {name: /Features/}).press('ArrowRight');
  await expect(page.getByRole('tab', {name: /Production/})).toBeFocused();
  await page.getByRole('tab', {name: /Features/}).click();
  await page
    .getByRole('button', {name: /^Show credits with/})
    .first()
    .click();
  const sheet = page.getByRole('dialog');
  await expect(
    sheet.getByRole('link', {name: /Source: musicbrainz.org/}).first(),
  ).toBeVisible();
  await expectAccessible(page);
  await page.keyboard.press('Escape');
  await expect(sheet).toBeHidden();
});

test('six degrees connects two artists and the link is shareable', async ({
  page,
}) => {
  await page.goto('/six-degrees');
  await page.getByRole('combobox', {name: 'From'}).fill('Kendrick Lamar');
  await page
    .getByRole('option', {name: /^Kendrick Lamar/})
    .first()
    .click();
  await page.getByRole('combobox', {name: 'To'}).fill('Daft Punk');
  await page
    .getByRole('option', {name: /^Daft Punk/})
    .first()
    .click();
  await expect(page.getByRole('heading', {name: /steps? apart/})).toBeVisible();
  await page
    .getByRole('button', {name: 'Skip animation'})
    .click({timeout: 2000})
    .catch(() => undefined);
  const chain = await page.getByRole('list').first().innerText();
  await expectAccessible(page);

  // AC-3.4: the same link shows the same chain.
  const url = page.url();
  const other = await page.context().newPage();
  await other.goto(url);
  await expect(
    other.getByRole('heading', {name: /steps? apart/}),
  ).toBeVisible();
  await other
    .getByRole('button', {name: 'Skip animation'})
    .click({timeout: 2000})
    .catch(() => undefined);
  await expect
    .poll(() => other.getByRole('list').first().innerText())
    .toBe(chain);
});

test('explore has a list view equivalent to the web', async ({page}) => {
  await openArtist(page, 'Thundercat', 'Thundercat');
  await page.getByRole('link', {name: 'Explore connections'}).click();
  await expect(
    page.getByRole('img', {name: /Connection web of Thundercat/}),
  ).toBeVisible();
  await page.getByRole('button', {name: 'List'}).click();
  const first = page.getByRole('button', {expanded: false}).first();
  await first.click();
  await expect(
    page.getByRole('button', {expanded: true}).first(),
  ).toBeVisible();
  await expectAccessible(page);
});

test('signed-out users see how to sign in', async ({page}) => {
  await page.goto('/you');
  await expect(
    page.getByRole('button', {name: 'Sign in with Google'}),
  ).toBeVisible();
  await expectAccessible(page);
});

test('unknown pages say so', async ({page}) => {
  await page.goto('/no-such-page');
  await expect(page.getByText('Page not found')).toBeVisible();
});

test('pseudo-locales render (long text and right-to-left)', async ({page}) => {
  await page.goto('/?locale=ar-XB');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await page.goto('/?locale=en-XA');
  await expect(page.getByRole('heading', {level: 1})).toContainText('⟦');
});

test('navigation moves focus to the new page (QA Q17)', async ({page}) => {
  await page.goto('/');
  await page.getByRole('link', {name: 'About our data'}).click();
  await expect(
    page.getByRole('heading', {level: 1, name: 'About our data'}),
  ).toBeFocused();
});

test('a playlist export is mapped on the device, sending only artist names (US-10)', async ({
  page,
}) => {
  await page.goto('/library');
  await expect(
    page.getByRole('heading', {name: 'Your files stay on this device'}),
  ).toBeVisible();
  await page
    .locator('input[type=file]')
    .setInputFiles('e2e/fixtures/Playlist1.json');
  await expect(page.getByText('1 playlist')).toBeVisible();

  const request = page.waitForRequest(r =>
    r.url().includes('/v1/playlists:analyze'),
  );
  await page.getByRole('button', {name: 'Map this playlist'}).click();
  const sent = (await request).postDataJSON() as {
    tracks: {artists: string[]}[];
  };
  // AC-10.1: only artist names leave the device; no titles, albums or IDs.
  expect(sent).toEqual({
    tracks: [
      {artists: ['Thundercat']},
      {artists: ['Flying Lotus']},
      {artists: ['SZA']},
      {artists: ['Kendrick Lamar']},
      {artists: ['Nobody In Our Catalog Zq']},
    ],
  });
  expect(JSON.stringify(sent)).not.toContain('Private Track Title Zq');

  await expect(page.getByText(/Cohesion \d+%/)).toBeVisible();
  await expect(
    page.getByText('4 of 5 artists found in our data'),
  ).toBeVisible();
  await expect(
    page.getByText(/Not in our data yet: Nobody In Our Catalog Zq/),
  ).toBeVisible();
  await expectAccessible(page);
});

test('unsupported files are listed with a reason (AC-10.3)', async ({page}) => {
  await page.goto('/library');
  await page.locator('input[type=file]').setInputFiles({
    name: 'notes.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4'),
  });
  await expect(
    page.getByText(
      'Unsupported file type. Use the JSON, CSV or ZIP from your export.',
    ),
  ).toBeVisible();
});

function localDate(): string {
  return '2026-10-08';
}

async function name(page: Page, artist: string) {
  const search = page.getByRole('combobox', {name: /Who worked with/});
  await search.fill(artist);
  await page.getByRole('option').filter({hasText: artist}).first().click();
}

test('the daily puzzle: a wrong move reveals nothing; solving shares no spoilers (US-04)', async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date(2026, 9, 8, 12));
  const puzzle = await (
    await page.request.get(`/v1/puzzles/${localDate()}`)
  ).json();
  const route = await (
    await page.request.get(`/v1/puzzles/${localDate()}:reveal`)
  ).json();
  await page.goto('/play');
  await page.evaluate(() => localStorage.removeItem('songnexus.play.v2'));
  await page.reload();
  await expect(
    page.getByRole('heading', {level: 1, name: 'Daily puzzle'}),
  ).toBeVisible();

  // The target is never directly connected to the start (par >= 3).
  await name(page, puzzle.target.displayName);
  await expect(page.getByText(/isn’t directly connected/)).toBeVisible();
  await expect(page.getByText(/steps? to go/).first()).toHaveText(
    new RegExp(`${puzzle.par} steps to go`),
  );

  for (const step of route.steps) await name(page, step.toArtist.displayName);
  await expect(
    page.getByRole('heading', {
      name: new RegExp(`Solved in ${puzzle.par} steps`),
    }),
  ).toBeVisible();
  const card = await page.locator('pre').innerText();
  expect(card).toContain(
    `${puzzle.start.displayName} → ${puzzle.target.displayName}`,
  );
  for (const step of route.steps.slice(0, -1))
    expect(card).not.toContain(step.toArtist.displayName);
  await expectAccessible(page);

  // Progress survives a reload.
  await page.reload();
  await expect(page.getByRole('heading', {name: /Solved in/})).toBeVisible();
  await page.emulateMedia({colorScheme: 'dark'});
  await expectAccessible(page);
  await page.screenshot({
    path: `test-results/daily-${test.info().project.name}.png`,
    fullPage: true,
  });
});

test('giving up shows a shortest route with sources', async ({page}) => {
  await page.clock.setFixedTime(new Date(2026, 9, 8, 12));
  await page.goto('/play');
  await page.evaluate(() => localStorage.removeItem('songnexus.play.v2'));
  await page.reload();
  await page.getByRole('button', {name: 'Show the answer'}).click();
  await expect(
    page.getByRole('heading', {name: 'Here’s a shortest route:'}),
  ).toBeVisible();
  await expect(
    page.getByRole('link', {name: /Source: musicbrainz.org/}).first(),
  ).toBeVisible();
});

test('archive navigation preserves progress, browser history and dated share links', async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date(2026, 9, 8, 12));
  await page.goto('/?play=2026-10-07');
  await expect(page).toHaveURL(/\/play\?date=2026-10-07$/);
  await expect(page.getByRole('button', {name: 'Previous day'})).toBeDisabled();
  const route = await (
    await page.request.get('/v1/puzzles/2026-10-07:reveal')
  ).json();
  for (const step of route.steps) await name(page, step.toArtist.displayName);
  await expect(page.getByRole('heading', {name: /Solved in/})).toBeVisible();
  await expect(page.locator('pre')).toContainText('/play?date=2026-10-07');
  const stats = page.getByRole('region', {name: 'Your stats'});
  await expect(
    stats
      .locator('div')
      .filter({has: page.getByText('Played', {exact: true})})
      .locator('dd'),
  ).toHaveText('1');
  await expect(
    stats
      .locator('div')
      .filter({has: page.getByText('Current streak', {exact: true})})
      .locator('dd'),
  ).toHaveText('0');
  await page.getByRole('button', {name: 'Next day'}).click();
  await expect(
    page.getByRole('button', {name: 'Show the answer'}),
  ).toBeVisible();
  await expect(page.getByRole('button', {name: 'Next day'})).toBeDisabled();
  await page.goBack();
  await expect(page.getByRole('heading', {name: /Solved in/})).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', {name: /Solved in/})).toBeVisible();
  await expectAccessible(page);
});

test('changing puzzle during a pending move never carries the move into another day', async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date(2026, 9, 8, 12));
  const solution = await (
    await page.request.get('/v1/puzzles/2026-10-07:reveal')
  ).json();
  let release!: () => void;
  const pending = new Promise<void>(resolve => {
    release = resolve;
  });
  await page.route('**/v1/puzzles/2026-10-07:checkMove', async route => {
    const response = await route.fetch();
    await pending;
    await route.fulfill({response});
  });
  await page.goto('/play?date=2026-10-07');
  const request = page.waitForRequest('**/v1/puzzles/2026-10-07:checkMove');
  await name(page, solution.steps[0].toArtist.displayName);
  await request;
  await expect(
    page.getByRole('combobox', {name: /Who worked with/}),
  ).toBeDisabled();
  await page.getByRole('button', {name: 'Next day'}).click();
  await expect(page.getByLabel('Puzzle date')).toHaveValue('2026-10-08');
  await expect(
    page.getByRole('button', {name: 'Go back a step'}),
  ).toBeDisabled();
  const response = page.waitForResponse('**/v1/puzzles/2026-10-07:checkMove');
  release();
  await response;
  await expect(
    page.getByRole('button', {name: 'Go back a step'}),
  ).toBeDisabled();
  await page.reload();
  await expect(
    page.getByRole('button', {name: 'Go back a step'}),
  ).toBeDisabled();
});

test('only completed shares are reported, and telemetry failure does not block copying', async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date(2026, 9, 8, 12));
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      configurable: true,
    });
    Object.defineProperty(navigator, 'clipboard', {
      value: {writeText: async () => {}},
      configurable: true,
    });
  });
  let shares = 0;
  await page.route('**/v1/puzzles:share', async route => {
    shares++;
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{}',
    });
  });
  await page.goto('/play');
  await page.getByRole('button', {name: 'Show the answer'}).click();
  await page.getByRole('button', {name: 'Share result'}).click();
  await expect(page.getByText('Result copied', {exact: true})).toBeVisible();
  await expect.poll(() => shares).toBe(1);
  await page.evaluate(() =>
    Object.defineProperty(navigator, 'share', {
      value: async () => {
        throw new DOMException('Cancelled', 'AbortError');
      },
      configurable: true,
    }),
  );
  await page.getByRole('button', {name: 'Share result'}).click();
  await page.getByRole('button', {name: 'Previous day'}).click();
  await expect(page.getByLabel('Puzzle date')).toHaveValue('2026-10-07');
  expect(shares).toBe(1);
});
