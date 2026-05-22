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
    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/recordings/rec/summary");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/recordings/rec/generate-summary", {
      method: "POST",
    });
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

  it("calls action item endpoints", async () => {
    await api.listActionItems({ status: "pending", priority: "high", limit: 20, offset: 3 });
    await api.updateActionItem("item1", { status: "completed", due_date: null });
    await api.deleteActionItem("item1");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(
      1,
      "/api/action-items?status=pending&priority=high&limit=20&offset=3",
    );
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/action-items/item1", {
      method: "PATCH",
      body: JSON.stringify({ status: "completed", due_date: null }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/action-items/item1", {
      method: "DELETE",
    });
  });

  it("omits empty action item params", async () => {
    await api.listActionItems();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/action-items");
  });

  it("calls entity endpoints", async () => {
    await api.listEntities("topic");
    await api.getEntity("ent");
    await api.createEntity({ type: "topic", name: "Roadmap", metadata: { a: 1 } });
    await api.deleteEntity("ent");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/entities?type=topic");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/entities/ent");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/entities", {
      method: "POST",
      body: JSON.stringify({ type: "topic", name: "Roadmap", metadata: { a: 1 } }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(4, "/api/entities/ent", {
      method: "DELETE",
    });
  });

  it("omits empty entity type", async () => {
    await api.listEntities(undefined);
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/entities");
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
      selected_provider: "soniox",
      selected_model: "stt-async-v4",
      language: "ru",
      candidate_count: 3,
    });

    expect(mockedApiFetch).toHaveBeenCalledWith("/api/benchmarks/dictation/battle/vote", {
      method: "POST",
      body: JSON.stringify({
        battle_id: "battle-1",
        selected_candidate_id: "candidate-a",
        selected_provider: "soniox",
        selected_model: "stt-async-v4",
        language: "ru",
        candidate_count: 3,
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

  it("calls updateActionItem with multiple fields in PATCH body", async () => {
    await api.updateActionItem("item42", {
      task: "Updated task description",
      owner: "Alice",
      due_date: "2026-04-01",
      priority: "high",
      status: "in_progress",
    });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/action-items/item42", {
      method: "PATCH",
      body: JSON.stringify({
        task: "Updated task description",
        owner: "Alice",
        due_date: "2026-04-01",
        priority: "high",
        status: "in_progress",
      }),
    });
  });

  it("calls updateActionItem with partial fields (only owner)", async () => {
    await api.updateActionItem("item99", { owner: "Bob" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/action-items/item99", {
      method: "PATCH",
      body: JSON.stringify({ owner: "Bob" }),
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
});
