import { expect, test, type Page, type Route } from "@playwright/test";

const baseTimestamp = "2026-06-17T10:00:00Z";

type SchemeLayout = {
  version: 9;
  snap_to_grid: boolean;
  grid_size: number;
  viewport: { x: number; y: number; zoom: number };
  node_positions: Record<string, { x: number; y: number }>;
  strokes: Array<Record<string, unknown>>;
  cards: Array<Record<string, unknown>>;
  shapes: Array<Record<string, unknown>>;
  frames: Array<Record<string, unknown>>;
  frame_order: string[];
  texts: Array<Record<string, unknown>>;
  sources: Array<Record<string, unknown>>;
  connectors: Array<Record<string, unknown>>;
};

function blankLayout(): SchemeLayout {
  return {
    version: 9,
    snap_to_grid: false,
    grid_size: 40,
    viewport: { x: 0, y: 0, zoom: 1 },
    node_positions: {},
    strokes: [],
    cards: [],
    shapes: [],
    frames: [],
    frame_order: [],
    texts: [],
    sources: [],
    connectors: [],
  };
}

function schemePayload(layout: SchemeLayout) {
  return {
    id: "scheme-1",
    space_id: null,
    title: "Launch map",
    prompt: "Map launch decisions",
    scheme_type: "decision",
    origin: "brain",
    status: "draft",
    source_scope: null,
    layout,
    current_revision_id: "revision-1",
    created_at: baseTimestamp,
    updated_at: baseTimestamp,
    current_revision: {
      id: "revision-1",
      scheme_id: "scheme-1",
      revision_index: 1,
      source_fingerprint: "fingerprint",
      source_count: 1,
      freshness: {},
      diff: { changed: true },
      citations: [],
      compiled_at: baseTimestamp,
      created_at: baseTimestamp,
      projection: {
        version: 1,
        scheme_type: "decision",
        title: "Launch map",
        prompt: "Map launch decisions",
        summary: "Decision map from one source.",
        nodes: [
          {
            id: "lens:root",
            kind: "lens",
            title: "Launch map",
            body: "Map launch decisions",
            lane: "center",
            citation_ids: [],
            position: { x: 0, y: 0 },
          },
          {
            id: "source:item:1",
            kind: "source",
            title: "Launch memo",
            body: "The launch memo says the board approved the launch.",
            lane: "sources",
            source_kind: "item",
            source_id: "1",
            citation_ids: ["item:1"],
            position: { x: -360, y: 120 },
          },
        ],
        edges: [],
        stats: { total_source_count: 1 },
        briefing: null,
        citations: [
          {
            id: "item:1",
            source_kind: "item",
            source_id: "1",
            title: "Launch memo",
            kind: "material",
            created_at: baseTimestamp,
          },
        ],
        freshness: {},
      },
    },
  };
}

function jsonHeaders(route: Route) {
  return {
    "access-control-allow-origin": new URL(route.request().url()).origin,
    "access-control-allow-credentials": "true",
    "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
    "access-control-allow-headers": "Content-Type,Authorization",
    "content-type": "application/json",
  };
}

async function installSchemesApiMock(page: Page) {
  let currentLayout = blankLayout();
  const layoutUpdates: SchemeLayout[] = [];

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const headers = jsonHeaders(route);

    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers, body: "" });
      return;
    }

    if (path === "/api/auth/login" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: {
          ...headers,
          "set-cookie": "wai_access_token=token; Path=/; SameSite=Lax",
        },
        body: JSON.stringify({ access_token: "token", token_type: "bearer" }),
      });
      return;
    }

    if (path === "/api/auth/me" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify({
          id: "user-1",
          email: "qa@example.com",
          created_at: baseTimestamp,
          has_password: true,
          region: "global",
        }),
      });
      return;
    }

    if (path === "/api/folders" && method === "GET") {
      await route.fulfill({ status: 200, headers, body: JSON.stringify([]) });
      return;
    }

    if (path === "/api/recordings" && method === "GET") {
      await route.fulfill({ status: 200, headers, body: JSON.stringify([]) });
      return;
    }

    if (path === "/api/inbox" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify({ rows: [], next_cursor: null, has_more: false }),
      });
      return;
    }

    if (path === "/api/schemes" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify({ schemes: [schemePayload(currentLayout)] }),
      });
      return;
    }

    if (path === "/api/schemes/scheme-1" && method === "PATCH") {
      const payload = request.postDataJSON() as { layout?: SchemeLayout };
      if (!payload.layout) {
        await route.fulfill({
          status: 400,
          headers,
          body: JSON.stringify({ detail: "Missing layout" }),
        });
        return;
      }
      currentLayout = payload.layout;
      layoutUpdates.push(currentLayout);
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify(schemePayload(currentLayout)),
      });
      return;
    }

    await route.fulfill({
      status: 404,
      headers,
      body: JSON.stringify({ detail: `Unhandled route: ${method} ${path}` }),
    });
  });

  return layoutUpdates;
}

test("Schemes board duplicates, locks, and unlocks a placed sticky", async ({ page }) => {
  const layoutUpdates = await installSchemesApiMock(page);

  await page.goto("/login");
  await page.getByTestId("auth-email").fill("qa@example.com");
  await page.getByTestId("password-mode-button").click();
  await page.getByTestId("auth-password").fill("password123");
  await page.getByTestId("auth-submit").click();

  await expect(page.getByTestId("user-email")).toContainText("qa@example.com");
  await page.getByTestId("tab-schemes").click();
  await expect(page.getByTestId("workspace-title")).toContainText("Schemes");
  await expect(page.getByTestId("schemes-panel")).toBeVisible();
  await expect(page.getByRole("button", { name: "Pin sources" })).toBeEnabled();
  await expect(page.getByRole("checkbox", { name: "Snap to grid" })).toBeVisible();
  await page.getByRole("button", { name: "Pin sources" }).click();
  await expect(page.locator(".scheme-source")).toHaveCount(1);
  expect(layoutUpdates.at(-1)?.sources).toEqual([
    expect.objectContaining({
      source_kind: "item",
      source_id: "1",
      citation_id: "item:1",
      title: "Launch memo",
    }),
  ]);

  const board = page.locator(".scheme-board__viewport");
  await expect(board).toBeVisible();
  const boardBox = await board.boundingBox();
  if (!boardBox) {
    throw new Error("Schemes board viewport is not measurable");
  }

  await page.getByRole("button", { name: "Highlight" }).click();
  await page.mouse.move(boardBox.x + 120, boardBox.y + 120);
  await page.mouse.down();
  await page.mouse.move(boardBox.x + 210, boardBox.y + 120);
  await page.mouse.up();
  await expect(page.locator(".scheme-board__svg-item path[stroke='#facc15']")).toHaveCount(1);
  expect(layoutUpdates.at(-1)?.strokes).toEqual([
    expect.objectContaining({
      kind: "highlighter",
      color: "#facc15",
      width: 14,
      opacity: 0.35,
    }),
  ]);

  await page.getByRole("button", { name: "Erase" }).click();
  await page.mouse.move(boardBox.x + 150, boardBox.y + 120);
  await page.mouse.down();
  await page.mouse.move(boardBox.x + 200, boardBox.y + 120);
  await page.mouse.up();
  await expect(page.locator(".scheme-board__svg-item path[stroke='#facc15']")).toHaveCount(0);
  expect(layoutUpdates.at(-1)?.strokes).toEqual([]);

  await page.getByRole("button", { name: "Sticky" }).click();
  await page.getByRole("checkbox", { name: "Snap to grid" }).check();
  await board.click({ position: { x: Math.max(220, boardBox.width - 260), y: boardBox.height - 100 } });
  await expect(page.locator(".scheme-sticky")).toHaveCount(1);
  expect(layoutUpdates.at(-1)?.snap_to_grid).toBe(true);
  expect(Math.abs(Number(layoutUpdates.at(-1)?.cards[0]?.x ?? 1) % 40)).toBe(0);
  expect(Math.abs(Number(layoutUpdates.at(-1)?.cards[0]?.y ?? 1) % 40)).toBe(0);
  await expect(page.getByRole("button", { name: "Duplicate" })).toBeEnabled();
  const resizeHandle = page.locator('[data-scheme-resize-handle="se"]').first();
  await expect(resizeHandle).toBeVisible();
  const resizeHandleBox = await resizeHandle.boundingBox();
  if (!resizeHandleBox) {
    throw new Error("Schemes resize handle is not measurable");
  }
  await page.mouse.move(resizeHandleBox.x + resizeHandleBox.width / 2, resizeHandleBox.y + resizeHandleBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(resizeHandleBox.x + resizeHandleBox.width / 2 + 70, resizeHandleBox.y + resizeHandleBox.height / 2 + 44);
  await page.mouse.up();
  await expect.poll(() => Number(layoutUpdates.at(-1)?.cards[0]?.width ?? 0)).toBeGreaterThan(220);
  await expect.poll(() => Number(layoutUpdates.at(-1)?.cards[0]?.height ?? 0)).toBeGreaterThan(150);

  await page.getByRole("button", { name: "Duplicate" }).click();
  await expect(page.locator(".scheme-sticky")).toHaveCount(2);

  await expect(page.getByRole("button", { name: "Undo" })).toBeEnabled();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator(".scheme-sticky")).toHaveCount(1);

  await expect(page.getByRole("button", { name: "Redo" })).toBeEnabled();
  await page.getByRole("button", { name: "Redo" }).click();
  await expect(page.locator(".scheme-sticky")).toHaveCount(2);

  await page.getByRole("button", { name: "Select" }).click();
  await board.click({ position: { x: 12, y: 12 } });
  await expect(page.locator(".scheme-sticky--selected")).toHaveCount(0);

  const lassoBox = {
    left: boardBox.x + 12,
    top: boardBox.y + 12,
    right: boardBox.x + boardBox.width - 12,
    bottom: boardBox.y + boardBox.height - 12,
  };

  await page.getByRole("button", { name: "Lasso" }).click();
  await page.mouse.move(lassoBox.left, lassoBox.top);
  await page.mouse.down();
  await page.mouse.move(lassoBox.right, lassoBox.top);
  await page.mouse.move(lassoBox.right, lassoBox.bottom);
  await expect(page.locator(".scheme-board__lasso path")).toHaveCount(1);
  await page.mouse.move(lassoBox.left, lassoBox.bottom);
  await page.mouse.move(lassoBox.left, lassoBox.top);
  await page.mouse.up();
  await expect(page.locator(".scheme-board__lasso path")).toHaveCount(0);
  await expect.poll(async () => page.locator(".scheme-sticky--selected").count()).toBeGreaterThan(0);

  await page.getByRole("button", { name: "Select" }).click();
  const stickyTextareas = page.getByLabel("Sticky note");
  await stickyTextareas.nth(0).click({ force: true });
  await expect(page.locator(".scheme-sticky--selected")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Lock" })).toBeEnabled();
  await page.getByRole("button", { name: "Lock" }).click();
  await expect(page.locator(".scheme-sticky.scheme-board__item--locked")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Duplicate" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Delete" })).toBeDisabled();
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.locator(".scheme-sticky.scheme-board__item--locked")).toHaveCount(0);

  await expect(page.getByRole("button", { name: "Front" })).toBeEnabled();
  await page.getByRole("button", { name: "Front" }).click();
  await expect(page.getByRole("button", { name: "Lock" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Duplicate" })).toBeEnabled();
  await expect(page.locator(".scheme-sticky.scheme-board__item--locked")).toHaveCount(0);

  expect(
    layoutUpdates
      .filter((layout) => layout.cards.length > 0)
      .slice(0, 5)
      .map((layout) => layout.cards.length),
  ).toEqual([1, 1, 2, 1, 2]);
  expect(layoutUpdates.some((layout) => layout.cards.some((card) => typeof card.z_index === "number"))).toBe(true);
  expect(layoutUpdates.some((layout) => layout.cards.some((card) => card.locked === true))).toBe(true);
  expect(layoutUpdates.at(-1)?.cards.some((card) => card.locked === true)).toBe(false);
});
