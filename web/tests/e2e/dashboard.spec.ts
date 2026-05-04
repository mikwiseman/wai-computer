import { expect, test, Route, Page } from "@playwright/test";

interface MockState {
  recordings: Array<{
    id: string;
    title: string | null;
    type: "meeting" | "note" | "reflection";
    audio_url: string | null;
    duration_seconds: number | null;
    language: string | null;
    created_at: string;
  }>;
  actionItems: Array<{
    id: string;
    recording_id: string;
    task: string;
    owner: string | null;
    due_date: string | null;
    priority: "high" | "medium" | "low" | null;
    status: "pending" | "in_progress" | "completed" | "cancelled";
    source: string;
    created_at: string;
  }>;
  entities: Array<{
    id: string;
    type: "person" | "topic" | "project" | "organization";
    name: string;
    metadata: Record<string, unknown> | null;
    created_at: string;
  }>;
}

const corsHeaders = {
  "access-control-allow-origin": "http://localhost:3000",
  "access-control-allow-credentials": "true",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
  "access-control-allow-headers": "Content-Type,Authorization",
  "content-type": "application/json",
};

async function installApiMock(page: Page, state: MockState) {
  const handler = async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (method === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: corsHeaders,
        body: "",
      });
      return;
    }

    if (path === "/api/auth/login" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: {
          ...corsHeaders,
          "set-cookie": "wai_access_token=token; Path=/; SameSite=Lax",
        },
        body: JSON.stringify({ access_token: "token", token_type: "bearer" }),
      });
      return;
    }

    if (path === "/api/auth/logout" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: {
          ...corsHeaders,
          "set-cookie": "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax",
        },
        body: JSON.stringify({ message: "Logged out" }),
      });
      return;
    }

    if (path === "/api/auth/me" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({
          id: "user-1",
          email: "qa@example.com",
          created_at: "2026-02-26T00:00:00Z",
        }),
      });
      return;
    }

    if (path === "/api/auth/register" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: {
          ...corsHeaders,
          "set-cookie": "wai_access_token=token; Path=/; SameSite=Lax",
        },
        body: JSON.stringify({ access_token: "token", token_type: "bearer" }),
      });
      return;
    }

    if (path === "/api/auth/magic-link" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({ message: "Magic link sent to your email" }),
      });
      return;
    }

    if (path === "/api/recordings" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify(state.recordings),
      });
      return;
    }

    if (path === "/api/recordings" && method === "POST") {
      const payload = request.postDataJSON() as { title?: string | null; type: "meeting" | "note" | "reflection" };
      const created = {
        id: `rec-${state.recordings.length + 1}`,
        title: payload.title ?? null,
        type: payload.type,
        audio_url: null,
        duration_seconds: null,
        language: "multi",
        created_at: "2026-02-26T00:00:00Z",
      };
      state.recordings.unshift(created);
      await route.fulfill({
        status: 201,
        headers: corsHeaders,
        body: JSON.stringify(created),
      });
      return;
    }

    if (path.startsWith("/api/recordings/") && method === "DELETE") {
      const recordingId = path.split("/")[3];
      state.recordings = state.recordings.filter((recording) => recording.id !== recordingId);
      await route.fulfill({ status: 204, headers: corsHeaders, body: "" });
      return;
    }

    if (path.startsWith("/api/recordings/") && path.endsWith("/generate-summary") && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({
          summary: "Generated summary",
          key_points: ["One"],
          decisions: [],
          topics: ["topic"],
          people_mentioned: [],
          sentiment: "positive",
        }),
      });
      return;
    }

    if (path.startsWith("/api/recordings/") && method === "GET") {
      const recordingId = path.split("/")[3];
      const recording = state.recordings.find((item) => item.id === recordingId);
      if (!recording) {
        await route.fulfill({
          status: 404,
          headers: corsHeaders,
          body: JSON.stringify({ detail: "Recording not found" }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({
          ...recording,
          segments: [],
          summary: {
            summary: "Generated summary",
            key_points: ["One"],
            decisions: [],
            topics: ["topic"],
            people_mentioned: [],
            sentiment: "positive",
          },
          action_items: state.actionItems.filter((item) => item.recording_id === recording.id),
        }),
      });
      return;
    }

    if (path.startsWith("/api/search") && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({ results: [], total: 0 }),
      });
      return;
    }

    if (path === "/api/action-items" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify(state.actionItems),
      });
      return;
    }

    if (path.startsWith("/api/action-items/") && method === "PATCH") {
      const itemId = path.split("/")[3];
      const payload = request.postDataJSON() as { status?: "pending" | "in_progress" | "completed" | "cancelled" };
      state.actionItems = state.actionItems.map((item) =>
        item.id === itemId ? { ...item, status: payload.status ?? item.status } : item,
      );
      const updated = state.actionItems.find((item) => item.id === itemId);
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify(updated),
      });
      return;
    }

    if (path === "/api/entities" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify(state.entities),
      });
      return;
    }

    if (path === "/api/entities" && method === "POST") {
      const payload = request.postDataJSON() as {
        type: "person" | "topic" | "project" | "organization";
        name: string;
      };
      const entity = {
        id: `ent-${state.entities.length + 1}`,
        type: payload.type,
        name: payload.name,
        metadata: null,
        created_at: "2026-02-26T00:00:00Z",
      };
      state.entities.push(entity);
      await route.fulfill({
        status: 201,
        headers: corsHeaders,
        body: JSON.stringify(entity),
      });
      return;
    }

    if (path.startsWith("/api/entities/") && method === "DELETE") {
      const entityId = path.split("/")[3];
      state.entities = state.entities.filter((entity) => entity.id !== entityId);
      await route.fulfill({ status: 204, headers: corsHeaders, body: "" });
      return;
    }

    if (path === "/api/settings/change-password" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({ message: "Password changed successfully" }),
      });
      return;
    }

    await route.fulfill({
      status: 404,
      headers: corsHeaders,
      body: JSON.stringify({ detail: `Unhandled route: ${method} ${path}` }),
    });
  };

  await page.route("**/api/**", handler);
}

test("web dashboard flow covers core features", async ({ page }) => {
  const state: MockState = {
    recordings: [
      {
        id: "rec-1",
        title: "Existing recording",
        type: "note",
        audio_url: null,
        duration_seconds: null,
        language: "multi",
        created_at: "2026-02-26T00:00:00Z",
      },
    ],
    actionItems: [
      {
        id: "ai-1",
        recording_id: "rec-1",
        task: "Follow up",
        owner: null,
        due_date: null,
        priority: "medium",
        status: "pending",
        source: "generated",
        created_at: "2026-02-26T00:00:00Z",
      },
    ],
    entities: [],
  };

  await installApiMock(page, state);

  await page.goto("/login");
  await page.getByTestId("auth-email").fill("qa@example.com");
  await page.getByTestId("auth-password").fill("password123");
  await page.getByTestId("auth-submit").click();

  await expect(page.getByTestId("user-email")).toContainText("qa@example.com");
  await page.getByTestId("tab-library").click();

  await page.getByTestId("recording-title").fill("New recording");
  await page.getByTestId("create-recording").click();
  await expect(page.getByTestId("dashboard-message")).toContainText("Recording created");

  await page.getByTestId("tab-search").click();
  await page.getByTestId("search-query").fill("roadmap");
  await page.getByTestId("search-submit").click();
  await expect(page.getByTestId("search-total")).toContainText("0");

  await page.getByTestId("tab-topics").click();
  await page.getByTestId("entity-name").fill("Roadmap");
  await page.getByTestId("create-entity").click();
  await expect(page.getByTestId("dashboard-message")).toContainText("Entity created");

  await page.getByTestId("tab-actions").click();
  await page.getByTestId("set-complete-ai-1").click();
  await expect(page.getByTestId("dashboard-message")).toContainText("Action item updated");

  await page.getByTestId("tab-settings").click();
  await page.getByTestId("current-password").fill("old-pass");
  await page.getByTestId("new-password").fill("new-pass");
  await page.getByTestId("change-password").click();
  await expect(page.getByTestId("dashboard-message")).toContainText("Password changed");

  await page.getByTestId("logout-button").click();
  await expect(page).toHaveURL(/\/login$/);
});
