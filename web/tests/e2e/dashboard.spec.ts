import { expect, test, Route, Page } from "@playwright/test";

interface Recording {
  id: string;
  title: string | null;
  type: "meeting" | "note" | "reflection";
  audio_url: string | null;
  duration_seconds: number | null;
  language: string | null;
  status: string;
  folder_id: string | null;
  deleted_at: string | null;
  starred_at: string | null;
  failure_code: string | null;
  failure_message: string | null;
  created_at: string;
  updated_at: string | null;
  uploaded_at: string | null;
}

interface InboxRow {
  id: string;
  source_kind: "recording" | "item" | "chat";
  source_id: string;
  detail: { kind: "recording" | "item" | "chat"; id: string };
  title: string | null;
  source_label: string;
  sublabel: string | null;
  activity_at: string;
  created_at: string;
  updated_at: string | null;
  occurred_at: string | null;
  status: "ready" | "processing" | "needs_input" | "failed" | "archived";
  source_status: string | null;
  error: { code: string; message: string } | null;
  folder_id: string | null;
  duration_seconds: number | null;
  language: string | null;
  has_summary: boolean | null;
  is_starred: boolean;
  is_pinned: boolean;
  is_archived: boolean;
  is_trashed: boolean;
}

interface MockState {
  recordings: Recording[];
  inboxRows: InboxRow[];
}

const corsHeaders = {
  "access-control-allow-origin": "http://localhost:3000",
  "access-control-allow-credentials": "true",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
  "access-control-allow-headers": "Content-Type,Authorization",
  "content-type": "application/json",
};

const baseTimestamp = "2026-02-26T00:00:00Z";

function makeRecording(overrides: Partial<Recording>): Recording {
  return {
    id: "rec-1",
    title: "Existing recording",
    type: "note",
    audio_url: null,
    duration_seconds: 120,
    language: "multi",
    status: "ready",
    folder_id: null,
    deleted_at: null,
    starred_at: null,
    failure_code: null,
    failure_message: null,
    created_at: baseTimestamp,
    updated_at: baseTimestamp,
    uploaded_at: baseTimestamp,
    ...overrides,
  };
}

function recordingRow(recording: Recording): InboxRow {
  return {
    id: `recording:${recording.id}`,
    source_kind: "recording",
    source_id: recording.id,
    detail: { kind: "recording", id: recording.id },
    title: recording.title,
    source_label: "Recording",
    sublabel: recording.type,
    activity_at: recording.uploaded_at ?? recording.created_at,
    created_at: recording.created_at,
    updated_at: recording.updated_at,
    occurred_at: recording.uploaded_at,
    status: "ready",
    source_status: recording.status,
    error: null,
    folder_id: recording.folder_id,
    duration_seconds: recording.duration_seconds,
    language: recording.language,
    has_summary: true,
    is_starred: false,
    is_pinned: false,
    is_archived: false,
    is_trashed: false,
  };
}

const materialRow: InboxRow = {
  id: "item:item-1",
  source_kind: "item",
  source_id: "item-1",
  detail: { kind: "item", id: "item-1" },
  title: "Launch PDF",
  source_label: "Material",
  sublabel: "pdf",
  activity_at: baseTimestamp,
  created_at: baseTimestamp,
  updated_at: baseTimestamp,
  occurred_at: null,
  status: "ready",
  source_status: "ready",
  error: null,
  folder_id: "folder-work",
  duration_seconds: null,
  language: null,
  has_summary: true,
  is_starred: false,
  is_pinned: false,
  is_archived: false,
  is_trashed: false,
};

const chatRow: InboxRow = {
  id: "chat:chat-1",
  source_kind: "chat",
  source_id: "chat-1",
  detail: { kind: "chat", id: "chat-1" },
  title: "Chat with Wai",
  source_label: "Wai chat",
  sublabel: "Chat",
  activity_at: baseTimestamp,
  created_at: baseTimestamp,
  updated_at: baseTimestamp,
  occurred_at: baseTimestamp,
  status: "ready",
  source_status: null,
  error: null,
  folder_id: null,
  duration_seconds: null,
  language: null,
  has_summary: null,
  is_starred: false,
  is_pinned: false,
  is_archived: false,
  is_trashed: false,
};

function settingsPayload() {
  return {
    default_language: "ru",
    summary_language: "ru",
    summary_instructions: null,
    dictation_cleanup_level: "medium",
    dictation_auto_paste: true,
    dictation_global_shortcut: "fn",
    voice_profile_prompt: null,
    ui_language: "en",
    theme: "system",
    accent_color: "teal",
    mcp_enabled: true,
  };
}

async function installApiMock(page: Page, state: MockState) {
  const handler = async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders, body: "" });
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
          created_at: baseTimestamp,
          has_password: true,
        }),
      });
      return;
    }

    if (path === "/api/folders" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify([
          { id: "folder-work", name: "Work", created_at: baseTimestamp },
        ]),
      });
      return;
    }

    if (path === "/api/recordings" && method === "GET") {
      const trashed = url.searchParams.get("trashed") === "true";
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify(
          trashed
            ? []
            : state.recordings.filter((recording) => recording.deleted_at === null),
        ),
      });
      return;
    }

    if (path === "/api/inbox" && method === "GET") {
      const sourceKind = url.searchParams.get("source_kind");
      const folderId = url.searchParams.get("folder_id");
      const rows = state.inboxRows.filter((row) => {
        if (sourceKind && row.source_kind !== sourceKind) return false;
        if (folderId && row.folder_id !== folderId) return false;
        return true;
      });
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({ rows, next_cursor: null, has_more: false }),
      });
      return;
    }

    if (path === "/api/recordings" && method === "POST") {
      const payload = request.postDataJSON() as {
        title?: string | null;
        type?: "meeting" | "note" | "reflection";
        folder_id?: string | null;
      };
      const created = makeRecording({
        id: `rec-${state.recordings.length + 1}`,
        title: payload.title ?? null,
        type: payload.type ?? "note",
        folder_id: payload.folder_id ?? null,
      });
      state.recordings.unshift(created);
      state.inboxRows.unshift(recordingRow(created));
      await route.fulfill({
        status: 201,
        headers: corsHeaders,
        body: JSON.stringify(created),
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
          segments: [{ id: "seg-1", speaker: "A", start_ms: 0, end_ms: 1000, content: "Hello" }],
          summary: {
            summary: "Generated summary",
            key_points: ["One"],
            decisions: [],
            topics: ["topic"],
            people_mentioned: [],
            sentiment: "positive",
          },
          summary_generation: null,
          action_items: [],
          highlights: [],
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

    if (path === "/api/settings" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify(settingsPayload()),
      });
      return;
    }

    if (path === "/api/settings/transcription-options" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({ providers: [], defaults: {} }),
      });
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

    if (path === "/api/telegram/link" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({ linked: false, telegram_user: null }),
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

test("web dashboard uses the universal Inbox shell", async ({ page }) => {
  const firstRecording = makeRecording({ id: "rec-1", title: "Existing recording" });
  const state: MockState = {
    recordings: [firstRecording],
    inboxRows: [recordingRow(firstRecording), materialRow, chatRow],
  };

  await installApiMock(page, state);

  await page.goto("/login");
  await page.getByTestId("auth-email").fill("qa@example.com");
  await page.getByTestId("password-mode-button").click();
  await page.getByTestId("auth-password").fill("password123");
  await page.getByTestId("auth-submit").click();

  await expect(page.getByTestId("user-email")).toContainText("qa@example.com");
  await expect(page.getByTestId("workspace-title")).toContainText("Inbox");
  await expect(page.getByTestId("tab-library")).toHaveCount(0);
  await expect(page.getByTestId("tab-wai")).toHaveCount(0);
  await expect(page.getByTestId("tab-agents")).toHaveCount(0);
  await expect(page.getByTestId("select-recording-rec-1")).toContainText("Existing recording");
  await expect(page.getByText("Launch PDF")).toBeVisible();
  await expect(page.getByText("Chat with Wai")).toBeVisible();

  await page.goto("/dashboard?view=agents");
  await expect(page.getByTestId("workspace-title")).toContainText("Inbox");
  await expect(page.getByTestId("tab-agents")).toHaveCount(0);

  await page.getByRole("button", { name: "+ Add" }).click();
  await page.getByText("Create empty recording").click();
  await page.getByTestId("recording-title").fill("New recording");
  await page.getByTestId("create-recording").click();
  await expect(page.getByTestId("select-recording-rec-2")).toContainText("New recording");
  await expect(page.getByTestId("recording-detail")).toContainText("New recording");

  await page.getByTestId("tab-search").click();
  await page.getByTestId("search-query").fill("roadmap");
  await page.getByTestId("search-submit").click();
  await expect(page.getByTestId("search-total")).toContainText("0");

  await page.getByTestId("tab-settings").click();
  await page.getByTestId("current-password").fill("old-pass");
  await page.getByTestId("new-password").fill("new-pass");
  await page.getByTestId("change-password").click();
  await expect(page.getByTestId("dashboard-message")).toContainText("Password changed");

  await page.getByTestId("logout-button").click();
  await expect(page).toHaveURL(/\/login$/);
});
