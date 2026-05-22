import { expect, test, type Page } from "@playwright/test";

const sharedRecording = {
  id: "rec-theme",
  title: "Theme review with a very long shared note title that should wrap cleanly on narrow screens",
  type: "meeting",
  duration_seconds: 3725,
  language: "en",
  created_at: "2026-05-21T08:15:00Z",
  shared_at: "2026-05-21T08:45:00Z",
  segments: [
    {
      id: "seg-1",
      speaker: "Mik",
      content: "The shared note should stay readable in light and dark mode.",
      start_ms: 1000,
      end_ms: 9000,
      confidence: 0.98,
    },
  ],
  summary: {
    summary: "The team checked the public shared note theme.",
    key_points: ["Check dark mode", "Check mobile wrapping"],
    decisions: [],
    topics: ["theme"],
    people_mentioned: ["Mik"],
    sentiment: "neutral",
  },
  action_items: [
    {
      id: "action-1",
      recording_id: "rec-theme",
      task: "Fix any theme regressions in web public pages",
      owner: null,
      due_date: null,
      priority: "high",
      status: "pending",
      source: "generated",
      created_at: "2026-05-21T08:30:00Z",
    },
  ],
  highlights: [],
};

async function installSharedRecordingMock(page: Page) {
  await page.route("**/api/recordings/shared/theme-token", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(sharedRecording),
    });
  });
}

async function expectNoViewportOverflow(page: Page) {
  const overflowers = await page.evaluate(() => {
    return Array.from(document.querySelectorAll("body *"))
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && (rect.left < -1 || rect.right > window.innerWidth + 1);
      })
      .map((element) => ({
        tag: element.tagName,
        className: element.getAttribute("class"),
        text: element.textContent?.trim().slice(0, 80),
      }));
  });

  expect(overflowers).toEqual([]);
}

function channel(value: string): number {
  return Number(value);
}

function luminance(rgb: string): number {
  const match = rgb.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!match) return 255;
  return 0.2126 * channel(match[1]) + 0.7152 * channel(match[2]) + 0.0722 * channel(match[3]);
}

async function expectDarkReadableSurface(page: Page) {
  const colors = await page.evaluate(() => {
    const bodyStyle = getComputedStyle(document.body);
    return {
      background: bodyStyle.backgroundColor,
      color: bodyStyle.color,
    };
  });

  expect(luminance(colors.background)).toBeLessThan(80);
  expect(luminance(colors.color)).toBeGreaterThan(150);
}

test.describe("web-facing theme and responsive pass", () => {
  test.beforeEach(async ({ page }) => {
    await installSharedRecordingMock(page);
  });

  test("public, auth, billing, and shared routes do not overflow on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });

    for (const path of [
      "/",
      "/pricing",
      "/ru/pricing",
      "/login",
      "/auth/verify?locale=ru",
      "/auth/reset?token=reset-token&locale=ru",
      "/billing/cancel?provider=tinkoff&lang=ru",
      "/share/theme-token",
    ]) {
      await page.goto(path, { waitUntil: "networkidle" });
      await expectNoViewportOverflow(page);
    }
  });

  test("dark color scheme produces dark readable public surfaces", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ colorScheme: "dark" });

    for (const path of ["/login", "/billing/cancel?provider=tinkoff&lang=ru", "/share/theme-token"]) {
      await page.goto(path, { waitUntil: "networkidle" });
      await expectDarkReadableSurface(page);
    }
  });

  test("public brand marks use the current mark asset", async ({ page }) => {
    await page.goto("/");

    const maskImage = await page
      .getByLabel("WaiComputer home")
      .locator("span")
      .first()
      .evaluate((element) => {
        const style = getComputedStyle(element);
        return style.maskImage || style.webkitMaskImage;
      });

    expect(maskImage).toContain("brand-mark.svg");
  });

  test("billing result page does not send external checkout returns back to billing", async ({ page }) => {
    await page.goto("/billing/cancel?provider=tinkoff&lang=ru");

    await expect(page.getByRole("link", { name: "Вернуться к подписке" })).toHaveCount(0);

    const styles = await page.getByRole("heading", { name: "Оплата не прошла" }).evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        display: style.display,
        color: style.color,
        fontSize: Number.parseFloat(style.fontSize),
      };
    });

    expect(styles.display).toBe("block");
    expect(styles.fontSize).toBeGreaterThan(24);
    expect(luminance(styles.color)).toBeGreaterThan(210);
  });
});
