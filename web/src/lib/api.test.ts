import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { apiFetch, apiFetchResponse, apiUpload } from "./http";

vi.mock("./http", () => ({
  apiFetch: vi.fn(),
  apiFetchResponse: vi.fn(),
  apiUpload: vi.fn(),
  syncLocalhostAuthCookie: vi.fn((token: string | null) => {
    if (!token) {
      document.cookie = "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax";
      return;
    }
    document.cookie = `wai_access_token=${encodeURIComponent(token)}; Path=/; SameSite=Lax`;
  }),
  syncLocalhostRefreshCookie: vi.fn((token: string | null) => {
    if (!token) {
      document.cookie = "wai_refresh_token=; Path=/; Max-Age=0; SameSite=Lax";
      return;
    }
    document.cookie = `wai_refresh_token=${encodeURIComponent(token)}; Path=/; SameSite=Lax`;
  }),
}));

const mockedApiFetch = vi.mocked(apiFetch);
const mockedApiFetchResponse = vi.mocked(apiFetchResponse);
const mockedApiUpload = vi.mocked(apiUpload);

beforeEach(() => {
  mockedApiFetch.mockReset();
  mockedApiFetch.mockResolvedValue({} as never);
  mockedApiFetchResponse.mockReset();
  mockedApiUpload.mockReset();
  mockedApiUpload.mockResolvedValue({} as never);
  document.cookie = "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax";
  document.cookie = "wai_refresh_token=; Path=/; Max-Age=0; SameSite=Lax";
});

describe("api client wrappers", () => {
  it("calls register", async () => {
    await api.register("a@example.com", "p");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: "a@example.com",
        password: "p",
        accepted_legal_terms: false,
        legal_terms_version: api.LEGAL_TERMS_VERSION,
        legal_privacy_version: api.LEGAL_PRIVACY_VERSION,
      }),
    });
  });

  it("passes register locale hints when provided", async () => {
    await api.register("a@example.com", "p", {
      locale: "ru",
      region: "ru",
      acceptedLegalTerms: true,
    });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: "a@example.com",
        password: "p",
        locale: "ru",
        region: "ru",
        accepted_legal_terms: true,
        legal_terms_version: api.LEGAL_TERMS_VERSION,
        legal_privacy_version: api.LEGAL_PRIVACY_VERSION,
      }),
    });
  });

  it("calls login", async () => {
    await api.login("a@example.com", "p");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: "a@example.com", password: "p" }),
    });
  });

  it("passes login locale hints when provided", async () => {
    await api.login("a@example.com", "p", { locale: "ru", region: "ru" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: "a@example.com",
        password: "p",
        locale: "ru",
        region: "ru",
      }),
    });
  });

  it("calls magic link endpoints", async () => {
    await api.requestMagicLink("a@example.com");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/auth/magic-link", {
      method: "POST",
      body: JSON.stringify({ email: "a@example.com" }),
    });

    await api.verifyMagicLink("token");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/auth/verify-magic", {
      method: "POST",
      body: JSON.stringify({ token: "token" }),
    });
  });

  it("passes magic-link locale hints when provided", async () => {
    await api.requestMagicLink("a@example.com", {
      locale: "ru",
      region: "ru",
      acceptedLegalTerms: true,
    });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/magic-link", {
      method: "POST",
      body: JSON.stringify({
        email: "a@example.com",
        locale: "ru",
        region: "ru",
        accepted_legal_terms: true,
        legal_terms_version: api.LEGAL_TERMS_VERSION,
        legal_privacy_version: api.LEGAL_PRIVACY_VERSION,
      }),
    });
  });

  it("passes verify magic-link locale when provided", async () => {
    await api.verifyMagicLink("token", { locale: "ru" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/verify-magic", {
      method: "POST",
      body: JSON.stringify({ token: "token", locale: "ru" }),
    });
  });

  it("calls token/account endpoints", async () => {
    await api.refreshToken();
    await api.logout();
    await api.getCurrentUser();

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/auth/refresh", { method: "POST" });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/auth/logout", { method: "POST" });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/auth/me");
  });

  it("calls system and self-host setup endpoints", async () => {
    const provisionInput = {
      hostname: "demo.self.wai.computer",
      vps_ip: "203.0.113.10",
      ssh_username: "root",
      auth_method: "ssh_key" as const,
      ssh_public_key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest demo",
      ssh_password: null,
    };

    await api.getSystemInfo();
    await api.getDataOwnershipMap();
    await api.getSelfHostMigrationPreflight();
    await api.getSelfHostMigrationContract();
    await api.startSelfHostProvision(provisionInput);

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/system/info");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/system/data-map");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/self-host/migration/preflight");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(4, "/api/self-host/migration/contract");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(5, "/api/self-host/provision", {
      method: "POST",
      body: JSON.stringify(provisionInput),
    });
  });

  it("calls agent control-plane endpoints", async () => {
    const createInput = {
      name: "Daily brief",
      kind: "brief",
      trigger_type: "manual" as const,
      config: { steps: [{ tool: "note", args: { text: "hi" } }] },
      autonomy: "propose" as const,
    };

    await api.getAgentCapabilities();
    await api.listAgents({ limit: 10 });
    await api.createAgent(createInput);
    await api.updateAgent("agent-1", { enabled: false });
    await api.startAgentRun("agent-1", {
      trigger_kind: "manual",
      trigger_payload: { objective: "brief me" },
      idempotency_key: "same",
    });
    await api.listAgentRuns("agent-1", { status: "pending", limit: 5 });
    await api.listAllAgentRuns({ status: "awaiting_approval" });
    await api.getAgentRun("agent-1", "run-1");
    await api.listAgentRunSteps("agent-1", "run-1");
    await api.cancelAgentRun("agent-1", "run-1", "stop");
    await api.listAgentActions({ status: "pending", limit: 3 });
    await api.listAgentRunActions("agent-1", "run-1");
    await api.resolveAgentAction("agent-1", "run-1", "action-1", { decision: "always" });
    await api.deleteAgent("agent-1");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/agents/capabilities");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/agents?limit=10");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/agents", {
      method: "POST",
      body: JSON.stringify(createInput),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(4, "/api/agents/agent-1", {
      method: "PATCH",
      body: JSON.stringify({ enabled: false }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(5, "/api/agents/agent-1/runs", {
      method: "POST",
      body: JSON.stringify({
        trigger_kind: "manual",
        trigger_payload: { objective: "brief me" },
        idempotency_key: "same",
      }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(
      6,
      "/api/agents/agent-1/runs?status=pending&limit=5",
    );
    expect(mockedApiFetch).toHaveBeenNthCalledWith(
      7,
      "/api/agents/runs?status=awaiting_approval",
    );
    expect(mockedApiFetch).toHaveBeenNthCalledWith(8, "/api/agents/agent-1/runs/run-1");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(9, "/api/agents/agent-1/runs/run-1/steps");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(
      10,
      "/api/agents/agent-1/runs/run-1/cancel",
      {
        method: "POST",
        body: JSON.stringify({ reason: "stop" }),
      },
    );
    expect(mockedApiFetch).toHaveBeenNthCalledWith(11, "/api/agents/actions?status=pending&limit=3");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(
      12,
      "/api/agents/agent-1/runs/run-1/actions",
    );
    expect(mockedApiFetch).toHaveBeenNthCalledWith(
      13,
      "/api/agents/agent-1/runs/run-1/actions/action-1/resolve",
      {
        method: "POST",
        body: JSON.stringify({ decision: "always" }),
      },
    );
    expect(mockedApiFetchResponse).toHaveBeenNthCalledWith(1, "/api/agents/agent-1", {
      method: "DELETE",
    });
  });

  it("calls shared reminder endpoints", async () => {
    const input = {
      text: "Check launch metrics",
      due_at: "2026-06-04T18:30:00Z",
      source: "web" as const,
      metadata: { origin: "dashboard" },
    };

    await api.listReminders({ status: "pending", limit: 5 });
    await api.createReminder(input);
    await api.cancelReminder("reminder-1");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/reminders?status=pending&limit=5");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/reminders", {
      method: "POST",
      body: JSON.stringify(input),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/reminders/reminder-1/cancel", {
      method: "POST",
    });
  });

  it("mirrors auth tokens into the localhost cookie", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      access_token: "local-token",
      refresh_token: "refresh-token",
      token_type: "bearer",
    } as never);

    await api.login("a@example.com", "p");

    expect(document.cookie).toContain("wai_access_token=local-token");
    expect(document.cookie).toContain("wai_refresh_token=refresh-token");
  });

  it("clears the localhost cookie on logout", async () => {
    document.cookie = "wai_access_token=local-token; Path=/; SameSite=Lax";
    document.cookie = "wai_refresh_token=refresh-token; Path=/; SameSite=Lax";

    await api.logout();

    expect(document.cookie).not.toContain("wai_access_token=local-token");
    expect(document.cookie).not.toContain("wai_refresh_token=refresh-token");
  });

  it("builds recording list query params", async () => {
    await api.listRecordings({ skip: 1, limit: 10, type: "meeting" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings?skip=1&limit=10&type=meeting");
  });

  it("omits empty list recording query params", async () => {
    await api.listRecordings({ skip: undefined, limit: undefined, type: undefined });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings");
  });

  it("calls recording CRUD", async () => {
    await api.createRecording({ title: null, type: "note", language: "multi" });
    await api.getRecording("rec");
    await api.updateRecording("rec", { title: "New" });
    await api.deleteRecording("rec");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/recordings", {
      method: "POST",
      body: JSON.stringify({ title: null, type: "note", language: "multi" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/recordings/rec");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/recordings/rec", {
      method: "PATCH",
      body: JSON.stringify({ title: "New" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(4, "/api/recordings/rec", {
      method: "DELETE",
    });
  });

  it("decodes media upload recording ids", async () => {
    mockedApiUpload.mockResolvedValueOnce({
      kind: "recording",
      status: "processing",
      recording_id: "rec-media",
    } as never);

    const result = await api.uploadItem(new File(["video"], "clip.mp4", { type: "video/mp4" }));

    expect(result).toEqual({
      kind: "recording",
      status: "processing",
      recording_id: "rec-media",
    });
  });

  it("rejects media upload responses without a recording id", async () => {
    mockedApiUpload.mockResolvedValueOnce({
      kind: "recording",
      status: "processing",
    } as never);

    await expect(
      api.uploadItem(new File(["video"], "clip.mp4", { type: "video/mp4" })),
    ).rejects.toThrow("Media upload response missing recording_id.");
  });

  it("calls scheme board endpoints", async () => {
    const layout = {
      version: 7 as const,
      viewport: { x: 0, y: 0, zoom: 1 },
      node_positions: { "lens:root": { x: 24, y: -12 } },
      strokes: [
        {
          id: "stroke-1",
          points: [{ x: 0, y: 0, pressure: 1 }, { x: 20, y: 40, pressure: 0.75 }],
          kind: "pen",
          color: "#2563eb",
          width: 5,
          opacity: 1,
          locked: false,
          z_index: 0,
        },
      ],
      cards: [],
      shapes: [],
      frames: [],
      texts: [],
      sources: [],
      connectors: [],
    };

    await api.listSchemes();
    await api.createScheme({ prompt: "Map recent decisions" });
    await api.getScheme("scheme-1");
    await api.updateScheme("scheme-1", { layout });
    await api.refreshScheme("scheme-1");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/schemes");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/schemes", {
      method: "POST",
      body: JSON.stringify({ prompt: "Map recent decisions" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/schemes/scheme-1");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(4, "/api/schemes/scheme-1", {
      method: "PATCH",
      body: JSON.stringify({ layout }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(5, "/api/schemes/scheme-1/refresh", {
      method: "POST",
    });
  });

  it("applies createRecording defaults", async () => {
    await api.createRecording({});
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings", {
      method: "POST",
      body: JSON.stringify({ title: null, type: "note", language: "multi" }),
    });
  });

  it("calls summary endpoints", async () => {
    await api.getSummary("rec");
    await api.generateSummary("rec");
    await api.getSummaryGeneration("rec");
    await api.startSummaryGeneration("rec", { instructions: "Focus on decisions" });
    await api.getRecordingSummaryAudio("rec");
    await api.startRecordingSummaryAudio("rec");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/recordings/rec/summary");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/recordings/rec/generate-summary", {
      method: "POST",
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/recordings/rec/summary-generation");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(4, "/api/recordings/rec/summary-generation", {
      method: "POST",
      body: JSON.stringify({ instructions: "Focus on decisions" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(5, "/api/recordings/rec/summary/audio");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(6, "/api/recordings/rec/summary/audio", {
      method: "POST",
    });
  });

  it("downloads summary audio through authenticated response fetch", async () => {
    const mockBlob = new Blob(["audio"], { type: "audio/mpeg" });
    mockedApiFetchResponse.mockResolvedValueOnce({
      blob: vi.fn().mockResolvedValue(mockBlob),
    } as unknown as Response);

    const result = await api.downloadRecordingSummaryAudio("rec");

    expect(mockedApiFetchResponse).toHaveBeenCalledWith(
      "/api/recordings/rec/summary/audio/file",
    );
    expect(result).toBe(mockBlob);
  });

  it("calls item summary audio endpoints", async () => {
    await api.getItemSummaryAudio("item");
    await api.startItemSummaryAudio("item");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/items/item/summary/audio");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/items/item/summary/audio", {
      method: "POST",
    });
  });

  it("downloads item summary audio through authenticated response fetch", async () => {
    const mockBlob = new Blob(["audio"], { type: "audio/mpeg" });
    mockedApiFetchResponse.mockResolvedValueOnce({
      blob: vi.fn().mockResolvedValue(mockBlob),
    } as unknown as Response);

    const result = await api.downloadItemSummaryAudio("item");

    expect(mockedApiFetchResponse).toHaveBeenCalledWith(
      "/api/items/item/summary/audio/file",
    );
    expect(result).toBe(mockBlob);
  });

  it("calls Telegram link endpoints", async () => {
    await api.getTelegramLinkStatus();
    await api.startTelegramLink();
    await api.claimTelegramLinkCode("ABCD-2345");
    await api.unlinkTelegram();

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/telegram/link");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/telegram/link/start", {
      method: "POST",
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/telegram/link/claim", {
      method: "POST",
      body: JSON.stringify({ code: "ABCD-2345" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(4, "/api/telegram/link", {
      method: "DELETE",
    });
  });

  it("calls search endpoints", async () => {
    await api.search({ q: "roadmap", limit: 5, offset: 2 });
    await api.semanticSearch({ q: "roadmap", limit: 7, threshold: 0.4 });
    await api.fulltextSearch({ q: "roadmap", limit: 11, offset: 9 });

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/search?q=roadmap&limit=5&offset=2");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/search/semantic?q=roadmap&limit=7&threshold=0.4");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/search/fts?q=roadmap&limit=11&offset=9");
  });

  it("calls change password endpoint", async () => {
    await api.changePassword("old", "new");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/settings/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: "old",
        new_password: "new",
      }),
    });
  });

  it("calls createDictationBenchmarkBattle with multipart audio", async () => {
    const audio = new Blob(["audio"], { type: "audio/webm" });

    await api.createDictationBenchmarkBattle({ audio, filename: "sample.webm", language: "ru" });

    expect(mockedApiUpload).toHaveBeenCalledWith(
      "/api/benchmarks/dictation/battle",
      expect.any(FormData),
    );
    const formData = mockedApiUpload.mock.calls[0]?.[1] as FormData;
    expect(formData.get("language")).toBe("ru");
    expect(formData.get("audio")).toBeInstanceOf(File);
    expect((formData.get("audio") as File).name).toBe("sample.webm");
  });

  it("calls submitDictationBenchmarkVote endpoint", async () => {
    await api.submitDictationBenchmarkVote({
      battle_id: "battle-1",
      selected_candidate_id: "candidate-a",
      selected_provider: "elevenlabs",
      selected_model: "scribe_v2",
      language: "ru",
      candidate_count: 1,
    });

    expect(mockedApiFetch).toHaveBeenCalledWith("/api/benchmarks/dictation/battle/vote", {
      method: "POST",
      body: JSON.stringify({
        battle_id: "battle-1",
        selected_candidate_id: "candidate-a",
        selected_provider: "elevenlabs",
        selected_model: "scribe_v2",
        language: "ru",
        candidate_count: 1,
      }),
    });
  });

  it("calls getSpeakerStats", async () => {
    await api.getSpeakerStats("rec1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/speaker-stats");
  });

  it("calls getRelatedRecordings with default limit", async () => {
    await api.getRelatedRecordings("rec1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/related");
  });

  it("calls getRelatedRecordings with explicit limit", async () => {
    await api.getRelatedRecordings("rec1", 5);
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/related?limit=5");
  });

  it("calls getWeeklyDigest", async () => {
    await api.getWeeklyDigest();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/digest/weekly");
  });

  it("calls getRecordingAnalytics", async () => {
    await api.getRecordingAnalytics();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/analytics");
  });

  it("calls searchTranscript", async () => {
    await api.searchTranscript("rec1", "roadmap", 10);
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/api/recordings/rec1/transcript/search?q=roadmap&limit=10",
    );
  });

  it("calls searchTranscript without limit", async () => {
    await api.searchTranscript("rec1", "meeting");
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/api/recordings/rec1/transcript/search?q=meeting",
    );
  });

  it("calls getTranscriptStats", async () => {
    await api.getTranscriptStats("rec1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/transcript-stats");
  });

  it("calls getRecordingKeywords", async () => {
    await api.getRecordingKeywords("rec1", 10);
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/api/recordings/rec1/keywords?limit=10",
    );
  });

  it("calls getRecordingKeywords without limit", async () => {
    await api.getRecordingKeywords("rec1");
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/api/recordings/rec1/keywords",
    );
  });

  it("calls starRecording", async () => {
    await api.starRecording("rec1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/star", {
      method: "POST",
    });
  });

  it("calls unstarRecording", async () => {
    await api.unstarRecording("rec1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/star", {
      method: "DELETE",
    });
  });

  it("calls createRecording with all parameters (title, type, language)", async () => {
    await api.createRecording({ title: "Sprint Retro", type: "meeting", language: "en" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings", {
      method: "POST",
      body: JSON.stringify({ title: "Sprint Retro", type: "meeting", language: "en" }),
    });
  });

  it("calls deleteRecording (simple DELETE)", async () => {
    await api.deleteRecording("rec-to-delete");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec-to-delete", {
      method: "DELETE",
    });
  });

  it("calls deleteRecording with permanent flag", async () => {
    await api.deleteRecording("rec-to-delete", { permanent: true });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec-to-delete?permanent=true", {
      method: "DELETE",
    });
  });

  it("calls restoreRecording", async () => {
    await api.restoreRecording("rec-to-restore");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec-to-restore/restore", {
      method: "POST",
    });
  });

  it("calls bulkRecordingOperation for delete", async () => {
    await api.bulkRecordingOperation(["id1", "id2"], "delete");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/bulk", {
      method: "POST",
      body: JSON.stringify({
        recording_ids: ["id1", "id2"],
        action: "delete",
        folder_id: undefined,
      }),
    });
  });

  it("calls bulkRecordingOperation for move with folder", async () => {
    await api.bulkRecordingOperation(["id1"], "move", "folder1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/bulk", {
      method: "POST",
      body: JSON.stringify({
        recording_ids: ["id1"],
        action: "move",
        folder_id: "folder1",
      }),
    });
  });

  it("calls exportRecording with correct URL and returns blob", async () => {
    const mockBlob = new Blob(["# Test"]);
    const mockResponse = {
      blob: vi.fn().mockResolvedValue(mockBlob),
    } as unknown as Response;
    mockedApiFetchResponse.mockResolvedValueOnce(mockResponse);

    const result = await api.exportRecording("rec1", "markdown");

    expect(mockedApiFetchResponse).toHaveBeenCalledWith(
      "/api/recordings/rec1/export?format=markdown",
    );
    expect(result).toBeInstanceOf(Blob);
  });

  it("throws on export failure", async () => {
    mockedApiFetchResponse.mockRejectedValueOnce(new Error("Something went wrong. Please try again in a moment."));

    await expect(api.exportRecording("rec1", "txt")).rejects.toThrow();
  });

  it("calls exportSharedRecording with correct public URL and returns blob", async () => {
    const mockBlob = new Blob(["# Shared"]);
    const mockResponse = {
      blob: vi.fn().mockResolvedValue(mockBlob),
    } as unknown as Response;
    mockedApiFetchResponse.mockResolvedValueOnce(mockResponse);

    const result = await api.exportSharedRecording("share-token", "markdown");

    expect(mockedApiFetchResponse).toHaveBeenCalledWith(
      "/api/recordings/shared/share-token/export?format=markdown",
    );
    expect(result).toBeInstanceOf(Blob);
  });

  it("calls createRecordingShareLink", async () => {
    await api.createRecordingShareLink("rec1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1/share", {
      method: "POST",
    });
  });

  it("calls getSharedRecording", async () => {
    await api.getSharedRecording("share-token");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/shared/share-token");
  });

  it("calls listFolders", async () => {
    await api.listFolders();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/folders");
  });

  it("calls createFolder", async () => {
    await api.createFolder("Work");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/folders", {
      method: "POST",
      body: JSON.stringify({ name: "Work" }),
    });
  });

  it("calls renameFolder", async () => {
    await api.renameFolder("folder-1", "Personal");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/folders/folder-1", {
      method: "PATCH",
      body: JSON.stringify({ name: "Personal" }),
    });
  });

  it("calls deleteFolder", async () => {
    await api.deleteFolder("folder-1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/folders/folder-1", {
      method: "DELETE",
    });
  });

  it("calls assignRecordingToFolder with folder_id", async () => {
    await api.assignRecordingToFolder("rec1", "folder-1");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1", {
      method: "PATCH",
      body: JSON.stringify({ folder_id: "folder-1" }),
    });
  });

  it("calls assignRecordingToFolder with null clears the folder", async () => {
    await api.assignRecordingToFolder("rec1", null);
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/rec1", {
      method: "PATCH",
      body: JSON.stringify({ folder_id: null }),
    });
  });

  it("calls listDictationEntries", async () => {
    await api.listDictationEntries();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/dictation/entries");
  });

  it("calls listDictionaryWords", async () => {
    await api.listDictionaryWords();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/dictation/dictionary");
  });

  it("calls createDictionaryWord with client_word_id and timestamp", async () => {
    await api.createDictionaryWord({ word: "k8s", replacement: "Kubernetes" });
    expect(mockedApiFetch).toHaveBeenCalledTimes(1);
    const [path, init] = mockedApiFetch.mock.calls[0];
    expect(path).toBe("/api/dictation/dictionary");
    expect(init?.method).toBe("POST");
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;
    expect(body.word).toBe("k8s");
    expect(body.replacement).toBe("Kubernetes");
    expect(typeof body.client_word_id).toBe("string");
    expect((body.client_word_id as string).length).toBeGreaterThan(0);
    expect(typeof body.occurred_at).toBe("string");
  });

  it("calls deleteDictionaryWord", async () => {
    await api.deleteDictionaryWord("word-id");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/dictation/dictionary/word-id", {
      method: "DELETE",
    });
  });
});
