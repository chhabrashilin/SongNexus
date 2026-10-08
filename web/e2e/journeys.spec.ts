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
