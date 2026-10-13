/**
 * The production Content-Security-Policy (firebase.json) must not break any screen (M8-04).
 * `vite preview` doesn't apply Firebase Hosting headers, so the test adds the real policy
 * to document responses and fails on any violation.
 */
import {readFileSync} from 'node:fs';

import {expect, test} from '@playwright/test';

const hosting = JSON.parse(
  readFileSync(new URL('../../firebase.json', import.meta.url), 'utf8'),
) as {
  hosting: {
    headers: {source: string; headers: {key: string; value: string}[]}[];
  };
};
const csp = hosting.hosting.headers
  .find(h => h.source === '**')!
  .headers.find(h => h.key === 'Content-Security-Policy')!.value;

const ROUTES = [
  '/',
  '/explore',
  '/six-degrees',
  '/compare',
  '/play',
  '/library',
  '/you',
  '/about',
  '/privacy',
];

test('no screen violates the production CSP', async ({page}) => {
  const violations: string[] = [];
  await page.exposeFunction('reportViolation', (v: string) =>
    violations.push(v),
  );
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', e =>
      (
        window as unknown as {reportViolation: (v: string) => void}
      ).reportViolation(`${e.violatedDirective} ${e.blockedURI}`),
    );
  });
  await page.route('**/*', async route => {
    if (route.request().resourceType() !== 'document') return route.continue();
    const response = await route.fetch();
    await route.fulfill({
      response,
      headers: {...response.headers(), 'content-security-policy': csp},
    });
  });
  for (const path of ROUTES) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
  }
  await page.goto('/');
  await page
    .getByRole('combobox', {name: 'Search artists and songs'})
    .fill('drake');
  await expect(page.getByRole('option').first()).toBeVisible();
  expect(violations).toEqual([]);
});
