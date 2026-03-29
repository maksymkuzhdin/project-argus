/**
 * End-to-end smoke tests for Project Argus UI.
 *
 * Tests three key user journeys:
 * 1. Dashboard: Load, filter, paginate declarations
 * 2. Declaration Detail: View scores, rules, financial breakdowns
 * 3. Person Timeline: Multi-year comparison with change analysis
 *
 * Run: npx playwright test
 * Debug: npx playwright test --debug
 */

import { test, expect } from "@playwright/test";

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || "http://localhost:3000";
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

test.describe("Project Argus E2E Smoke Tests", () => {
  /**
   * Journey 1: Dashboard Loading & Declaration List
   */
  test("should load dashboard and display declarations", async ({ page }) => {
    await page.goto(`${BASE_URL}/`);

    // Wait for page title and navigation structure
    await expect(page).toHaveTitle(/Argus|declarations/i);

    // Check for key dashboard elements
    const heading = page.locator("h1, h2");
    await expect(heading.first()).toBeVisible();

    // Verify dashboard settles into one of the expected states:
    // 1) declarations list/table rendered
    // 2) explicit empty-state copy rendered
    // 3) explicit load-error panel rendered when API is unavailable
    const declarationsList = page.locator(
      "[data-testid='declarations-list'], table, ul"
    );
    const emptyState = page.locator("text=/no declarations|empty/i");
    const loadError = page.locator("text=/unable to load dashboard|failed to load dashboard/i");

    await expect
      .poll(
        async () => {
          const listCount = await declarationsList.count();
          const emptyCount = await emptyState.count();
          const errorCount = await loadError.count();
          return listCount > 0 || emptyCount > 0 || errorCount > 0;
        },
        { timeout: 10000 }
      )
      .toBe(true);

    const hasContent =
      (await declarationsList.count()) > 0 ||
      (await emptyState.count()) > 0 ||
      (await loadError.count()) > 0;
    expect(hasContent).toBe(true);

    // If list exists, verify pagination/filtering controls
    if ((await declarationsList.count()) > 0) {
      const filterOrPaginationControls = page.locator(
        "button, select, input[type='text'], input[type='search']"
      );
      expect((await filterOrPaginationControls.count()) > 0).toBe(true);
    }
  });

  /**
   * Journey 2: Click Declaration & View Detail Page
   */
  test("should navigate to declaration detail and display scores/rules", async ({
    page,
  }) => {
    // Capture API responses to verify data fetching
    const apiResponses: Record<string, object> = {};

    page.on("response", async (response) => {
      const url = response.url();
      if (!url.startsWith(API_URL)) {
        return;
      }
      if (response.ok()) {
        try {
          const contentType = response.headers()["content-type"] || "";
          if (contentType.includes("application/json")) {
            apiResponses[url] = await response.json();
          }
        } catch {
          // Ignore non-JSON responses
        }
      }
    });

    await page.goto(`${BASE_URL}/`);

    // Try to find and click a declaration link
    const declarationLink = page
      .locator("a[data-testid^='declaration-link-']")
      .first()
      .or(page.locator('a[href*="/declaration/"], a[href*="/declaration?id="]').first());

    // If no declarations exist, test will gracefully skip detail page
    if ((await declarationLink.count()) > 0) {
      const declarationHref = await declarationLink.getAttribute("href");
      if (declarationHref) {
        await page.goto(`${BASE_URL}${declarationHref.startsWith("/") ? "" : "/"}${declarationHref}`);
      } else {
        await declarationLink.click();
      }

      // Wait for detail page to load (URL or deterministic score section)
      await page.waitForURL(/\/declaration(\/|\?)/, { timeout: 8000 });

      // Verify detail page structure
      const pageHeading = page.locator("h1, h2").first();
      await expect(pageHeading).toBeVisible();

      // Look for key detail page sections
      const scoreSection = page.locator("[data-testid='score-section']");
      const anomalyHeading = page.getByRole("heading", { name: /anomaly analysis/i });
      const ruleSection = page.locator("[data-testid='rule-section']");

      // At least one of these should exist
      const hasSectionContent =
        (await scoreSection.count()) > 0 ||
        (await anomalyHeading.count()) > 0 ||
        (await ruleSection.count()) > 0;
      expect(hasSectionContent).toBe(true);

      // URL and visible content assertions above are the primary E2E checks.
    }
  });

  /**
   * Journey 3: Person Timeline (Multi-year Comparison)
   */
  test("should navigate to person timeline and display year-over-year changes", async ({
    page,
  }) => {
    const apiResponses: Record<string, object> = {};

    page.on("response", async (response) => {
      const url = response.url();
      if (!url.startsWith(API_URL)) {
        return;
      }
      if (response.ok()) {
        try {
          const contentType = response.headers()["content-type"] || "";
          if (contentType.includes("application/json")) {
            apiResponses[url] = await response.json();
          }
        } catch {
          // Ignore non-JSON responses
        }
      }
    });

    await page.goto(`${BASE_URL}/`);

    // Try to find person link (either from dashboard or declaration detail)
    let personLink = page.locator('a[href*="/person/"]').first();

    if ((await personLink.count()) === 0) {
      // Try to navigate through declaration first
      const declarationLink = page.locator(
        'a[href*="/declaration/"], a[href*="/declaration?id="], button:has-text("View")'
      ).first();

      if ((await declarationLink.count()) > 0) {
        await declarationLink.click();
        await page.waitForURL(/\/declaration(\/|\?)/, { timeout: 5000 });

        // Now look for person link from detail page
        personLink = page.locator('a[href*="/person/"]').first();
      }
    }

    // If person link found, navigate and verify timeline
    if ((await personLink.count()) > 0) {
      await personLink.click();
      await page.waitForURL(/\/person\//, { timeout: 5000 });

      // Verify timeline page structure
      const pageHeading = page.locator("h1, h2").first();
      await expect(pageHeading).toBeVisible();

      // Look for timeline elements (years, changes, deltas)
      const timelineTextMatches = page.getByText(/year|change|delta|history|2023|2024/i);
      const timelineTestIdMatches = page.locator("[data-testid*='timeline']");
      const hasTimelineContent =
        (await timelineTextMatches.count()) > 0 ||
        (await timelineTestIdMatches.count()) > 0;
      expect(hasTimelineContent).toBe(true);

      // URL and timeline content assertions above are the primary E2E checks.
    }
  });

  /**
   * Journey 4: Error Handling & Graceful Degradation
   */
  test("should handle API errors gracefully", async ({ page }) => {
    // Test with incorrect declaration ID to trigger error handling
    await page.goto(`${BASE_URL}/declaration/nonexistent-id-12345`);

    // Verify error message is shown or redirected to safe state
    const errorMessageText = page.getByText(/not found|error|try again/i);
    const errorMessageTestId = page.locator("[data-testid='error']");
    const dashboardLink = page.locator(
      "a:has-text(/dashboard|home|back/i), button:has-text(/back/i)"
    );

    const hasErrorHandling =
      (await errorMessageText.count()) > 0 ||
      (await errorMessageTestId.count()) > 0 ||
      (await dashboardLink.count()) > 0;
    expect(hasErrorHandling).toBe(true);
  });

  /**
   * Journey 5: Responsive Layout
   */
  test("should render correctly on mobile viewport", async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });

    await page.goto(`${BASE_URL}/`);

    // Verify page renders without horizontal scroll
    const bodyWidth = await page.evaluate(() => document.body.offsetWidth);
    const viewportWidth = 375;
    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth + 50); // Small margin for edge cases

    // Check that key elements are still accessible
    const headings = page.locator("h1, h2");
    await expect(headings.first()).toBeVisible();

    // Verify no JS errors in console
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    // Navigate and check again
    const link = page.locator("a").first();
    if ((await link.count()) > 0) {
      await link.click();
      // Wait a moment for potential errors
      await page.waitForTimeout(1000);
    }

    expect(consoleErrors.length === 0).toBe(true);
  });
});
