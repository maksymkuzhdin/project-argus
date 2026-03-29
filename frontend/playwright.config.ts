import { defineConfig, devices } from "@playwright/test";
import { MOCK_API_BASE } from "./e2e/mock-api-server";

/**
 * See https://playwright.dev/docs/test-configuration.
 *
 * E2E mock strategy
 * -----------------
 * A lightweight in-process HTTP server (e2e/mock-api-server.ts) is started
 * by globalSetup before the Next.js dev server launches.  Both
 * INTERNAL_API_URL (used by Next.js SSR) and NEXT_PUBLIC_API_URL are pointed
 * at this mock so all API calls resolve to deterministic fixture data
 * regardless of whether a real backend is available.
 *
 * When reuseExistingServer is true (non-CI), a manually started `npm run dev`
 * process is reused as-is; in that case the existing server's env takes
 * precedence.  Stop any running dev server before running `npm run e2e`
 * locally to ensure the mock is active.
 */
export default defineConfig({
  testDir: "./e2e",
  /* Global setup starts the mock API server; teardown stops it. */
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: "html",
  /* Shared settings for all the projects below. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: process.env.PLAYWRIGHT_TEST_BASE_URL || "http://localhost:3000",
    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: "on-first-retry",
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },

    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },

    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },

    /* Test against mobile viewports. */
    {
      name: "Mobile Chrome",
      use: { ...devices["Pixel 5"] },
    },
    {
      name: "Mobile Safari",
      use: { ...devices["iPhone 12"] },
    },
  ],

  /* Run your local dev server before starting the tests */
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    env: {
      /* Point SSR fetch calls at the mock API server started in globalSetup */
      INTERNAL_API_URL: MOCK_API_BASE,
      NEXT_PUBLIC_API_URL: MOCK_API_BASE,
    },
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
});
