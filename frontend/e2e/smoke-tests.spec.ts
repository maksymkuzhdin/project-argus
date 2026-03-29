/**
 * End-to-end smoke tests for Project Argus UI.
 *
 * Tests five key user journeys:
 * 1. Dashboard: Load, display declarations from fixture data
 * 2. Declaration Detail: Navigate from dashboard, verify scores/rules
 * 3. Person Timeline: Navigate directly to person page, verify yearly snapshots
 * 4. Error Handling: Unknown declaration ID shows error UI
 * 5. Responsive Layout: Dashboard renders on mobile viewport
 *
 * All journeys are deterministic — they rely on fixture data served by the
 * lightweight mock HTTP server defined in mock-api-server.ts.  No live
 * backend or pre-existing database state is required.
 *
 * Run: npx playwright test
 * Debug: npx playwright test --debug
 */

import { test, expect } from "@playwright/test";
import {
  FIXTURE_DECLARATION_ID,
  FIXTURE_USER_DECLARANT_ID,
} from "./mock-api-server";

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || "http://localhost:3000";

test.describe("Project Argus E2E Smoke Tests", () => {
  /**
   * Journey 1: Dashboard Loading & Declaration List
   *
   * With fixture data the dashboard always renders a non-empty declarations
   * table.  The test asserts the list is present and has at least one row.
   */
  test("should load dashboard and display declarations", async ({ page }) => {
    await page.goto(`${BASE_URL}/`);

    await expect(page).toHaveTitle(/Argus|declarations/i);

    const heading = page.locator("h1, h2");
    await expect(heading.first()).toBeVisible();

    // Fixture data guarantees the declarations list is rendered (not an empty
    // state or an error panel).
    const declarationsList = page.locator("[data-testid='declarations-list']");
    await expect(declarationsList).toBeVisible({ timeout: 10000 });

    // At least one declaration row should link to the fixture declaration.
    const declarationLink = page.locator(
      `a[data-testid='declaration-link-${FIXTURE_DECLARATION_ID}']`
    );
    await expect(declarationLink).toBeVisible();

    // Filtering and pagination controls are present.
    const filterInput = page.locator(
      "input[name='query'], input[type='text'], input[type='search']"
    );
    await expect(filterInput.first()).toBeVisible();
  });

  /**
   * Journey 2: Dashboard → Declaration Detail
   *
   * Clicks the fixture declaration link on the dashboard and verifies that
   * the detail page renders the anomaly-analysis section.  The skip branch
   * has been eliminated: fixture data guarantees the link is always present.
   */
  test("should navigate to declaration detail and display scores/rules", async ({
    page,
  }) => {
    await page.goto(`${BASE_URL}/`);

    // The fixture declaration link must always be present.
    const declarationLink = page.locator(
      `a[data-testid='declaration-link-${FIXTURE_DECLARATION_ID}']`
    );
    await expect(declarationLink).toBeVisible({ timeout: 8000 });

    const href = await declarationLink.getAttribute("href");
    if (href) {
      await page.goto(
        `${BASE_URL}${href.startsWith("/") ? "" : "/"}${href}`
      );
    } else {
      await declarationLink.click();
    }

    await page.waitForURL(/\/declaration(\/|\?)/, { timeout: 8000 });

    // Page heading (declarant name) must be visible.
    const pageHeading = page.locator("h1").first();
    await expect(pageHeading).toBeVisible();

    // The anomaly-analysis section with its data-testid must be present.
    const scoreSection = page.locator("[data-testid='score-section']");
    await expect(scoreSection).toBeVisible({ timeout: 8000 });

    // The fixture declaration has triggered rules, so the rule-section must
    // also be rendered inside the score section.
    const ruleSection = page.locator("[data-testid='rule-section']");
    await expect(ruleSection).toBeVisible();

    // The person-timeline link must be present (fixture has user_declarant_id).
    const timelineLink = page.locator(`a[href='/person/${FIXTURE_USER_DECLARANT_ID}']`);
    await expect(timelineLink).toBeVisible();
  });

  /**
   * Journey 3: Person Timeline (Multi-year Comparison)
   *
   * Navigates directly to the fixture person's timeline page and verifies
   * that the yearly-snapshots table and year-over-year changes section are
   * rendered.  The skip branch has been eliminated: the URL is constructed
   * from the deterministic FIXTURE_USER_DECLARANT_ID constant.
   */
  test("should navigate to person timeline and display year-over-year changes", async ({
    page,
  }) => {
    await page.goto(`${BASE_URL}/person/${FIXTURE_USER_DECLARANT_ID}`);
    await page.waitForURL(/\/person\//, { timeout: 8000 });

    // Page heading must show the fixture person's name.
    const pageHeading = page.locator("h1").first();
    await expect(pageHeading).toBeVisible();
    await expect(pageHeading).toContainText(/Fixture Person/i);

    // Yearly-snapshots section must be present.
    const timelineSection = page.locator("[data-testid='timeline']");
    await expect(timelineSection).toBeVisible({ timeout: 8000 });

    // The fixture timeline includes two yearly snapshots; both years must be
    // visible in the table.
    await expect(page.getByText("2023")).toBeVisible();
    await expect(page.getByText("2024")).toBeVisible();

    // Year-over-year changes section must be rendered (fixture has one change
    // record for the 2023 → 2024 period).
    const changesHeading = page.getByRole("heading", {
      name: /year-over-year changes/i,
    });
    await expect(changesHeading).toBeVisible();
  });

  /**
   * Journey 4: Error Handling & Graceful Degradation
   *
   * Navigating to a non-existent declaration ID triggers a 404 from the mock
   * server, which causes the detail page to render the error UI.
   */
  test("should handle API errors gracefully", async ({ page }) => {
    await page.goto(`${BASE_URL}/declaration/nonexistent-id-12345`);

    // The error container data-testid must be present.
    const errorContainer = page.locator("[data-testid='error']");
    await expect(errorContainer).toBeVisible({ timeout: 8000 });

    // A link back to the dashboard must be offered.
    const backLink = page.locator("a[href='/']");
    await expect(backLink.first()).toBeVisible();
  });

  /**
   * Journey 5: Responsive Layout
   *
   * Verifies the dashboard renders without horizontal overflow on a narrow
   * mobile viewport and that no console errors are produced.
   */
  test("should render correctly on mobile viewport", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto(`${BASE_URL}/`);

    const bodyWidth = await page.evaluate(() => document.body.offsetWidth);
    expect(bodyWidth).toBeLessThanOrEqual(375 + 50); // small rounding margin

    const headings = page.locator("h1, h2");
    await expect(headings.first()).toBeVisible();

    // Navigate to declaration detail to exercise a second page on mobile.
    const declarationLink = page.locator(
      `a[data-testid='declaration-link-${FIXTURE_DECLARATION_ID}']`
    );
    await expect(declarationLink).toBeVisible();
    const href = await declarationLink.getAttribute("href");
    if (href) {
      await page.goto(`${BASE_URL}${href.startsWith("/") ? "" : "/"}${href}`);
      await page.waitForURL(/\/declaration(\/|\?)/, { timeout: 8000 });
    }

    expect(consoleErrors.length === 0).toBe(true);
  });
});
