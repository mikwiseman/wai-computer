import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

/**
 * Print stylesheet smoke test.
 *
 * Drives Chromium with `emulateMedia({ media: "print" })` against the three
 * pages that ship a print rule: /privacy, /terms, and /share/[token]. We
 * confirm:
 *
 *  - body background renders as white (the print reset),
 *  - body color renders as black,
 *  - landing nav / locale switcher / share download / share CTA / legal
 *    back-link, when present, are visually hidden under print,
 *  - font-family is a serif fallback (so legal copy reads like a printed
 *    document, not the sans-serif UI font).
 *
 * The screenshot is saved alongside the audit artifacts for visual review.
 * Heavy assertions stay in DOM/CSS land — pixel comparison is intentionally
 * left to humans inspecting the PNGs in `tests/e2e/snapshots/`.
 *
 * This file is not part of the CI loop yet (see AGENTS.md → e2e is skipped
 * in CI for now). It runs locally with `pnpm test:e2e`.
 */

const SNAPSHOT_DIR = path.resolve(__dirname, "snapshots");
const AUDIT_SHARE_TOKEN =
  process.env.AUDIT_SHARE_TOKEN ?? "LCxhDCuT9r0QUGlrDTx8dyBBan1X3bn1";

function rgb(value: string): [number, number, number] {
  const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!match) return [-1, -1, -1];
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function isWhiteish([r, g, b]: [number, number, number]): boolean {
  return r >= 245 && g >= 245 && b >= 245;
}

function isBlackish([r, g, b]: [number, number, number]): boolean {
  return r <= 30 && g <= 30 && b <= 30;
}

async function assertPrintReset(page: Page) {
  const styles = await page.evaluate(() => {
    const body = getComputedStyle(document.body);
    return {
      background: body.backgroundColor,
      color: body.color,
      fontFamily: body.fontFamily,
    };
  });

  expect(isWhiteish(rgb(styles.background)), `body background under print: ${styles.background}`).toBe(true);
  expect(isBlackish(rgb(styles.color)), `body color under print: ${styles.color}`).toBe(true);
  expect(styles.fontFamily.toLowerCase()).toMatch(/times|serif|georgia/);
}

async function assertHiddenIfPresent(page: Page, selector: string) {
  const handle = await page.$(selector);
  if (!handle) return;
  const display = await handle.evaluate((el) => getComputedStyle(el).display);
  expect(display, `${selector} should be hidden in print`).toBe("none");
}

test.describe("print stylesheet", () => {
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ media: "print" });
  });

  test("/privacy renders cleanly under print media", async ({ page }) => {
    const response = await page.goto("/privacy", { waitUntil: "domcontentloaded" });
    expect(response?.ok(), "GET /privacy should be 2xx").toBe(true);

    await assertPrintReset(page);
    await assertHiddenIfPresent(page, ".locale-switcher");
    // legal pages use a CSS-module "backLink" class — confirm it's hidden.
    await assertHiddenIfPresent(page, '[class*="backLink"]');

    await page.screenshot({
      path: path.join(SNAPSHOT_DIR, "print-privacy.png"),
      fullPage: true,
    });
  });

  test("/terms renders cleanly under print media", async ({ page }) => {
    const response = await page.goto("/terms", { waitUntil: "domcontentloaded" });
    expect(response?.ok(), "GET /terms should be 2xx").toBe(true);

    await assertPrintReset(page);
    await assertHiddenIfPresent(page, ".locale-switcher");
    await assertHiddenIfPresent(page, '[class*="backLink"]');

    await page.screenshot({
      path: path.join(SNAPSHOT_DIR, "print-terms.png"),
      fullPage: true,
    });
  });

  test("/share/<token> renders cleanly under print media (or is gracefully skipped)", async ({ page }) => {
    const response = await page.goto(`/share/${AUDIT_SHARE_TOKEN}`, {
      waitUntil: "domcontentloaded",
    });

    if (!response || !response.ok()) {
      test.skip(true, `share token ${AUDIT_SHARE_TOKEN} not available (status ${response?.status() ?? "n/a"})`);
      return;
    }

    // The share view fetches the recording client-side — wait for the
    // article or empty-state to settle. If the API rejected the token
    // (revoked / wrong env), bail out of the print assertion gracefully.
    const settled = await page.waitForFunction(
      () => {
        return Boolean(
          document.querySelector("article.shared-note") ||
            document.querySelector(".shared-note .empty-state"),
        );
      },
      undefined,
      { timeout: 10_000 },
    ).catch(() => null);

    if (!settled) {
      test.skip(true, "shared note never resolved (API likely unreachable in this env)");
      return;
    }

    await assertPrintReset(page);
    await assertHiddenIfPresent(page, ".shared-note__download");
    await assertHiddenIfPresent(page, '[data-testid="shared-cta"]');
    await assertHiddenIfPresent(page, ".shared-note__brand");

    await page.screenshot({
      path: path.join(SNAPSHOT_DIR, "print-share.png"),
      fullPage: true,
    });
  });
});
