import {defineConfig, devices} from '@playwright/test';

// E2E runs against a production build served by `vite preview` with the API
// proxied to a locally running server (see e2e/README.md).
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: process.env.SONGNEXUS_WEB ?? 'http://127.0.0.1:4273',
    trace: 'retain-on-failure',
  },
  projects: [
    {name: 'mobile', use: {...devices['Pixel 7']}},
    {
      name: 'desktop',
      use: {...devices['Desktop Chrome'], viewport: {width: 1440, height: 900}},
    },
  ],
});
