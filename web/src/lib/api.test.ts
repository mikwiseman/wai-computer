import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { apiFetch } from "./http";

vi.mock("./http", () => ({
  apiFetch: vi.fn(),
  getApiBaseUrl: vi.fn(() => ""),
}));

const mockedApiFetch = vi.mocked(apiFetch);

beforeEach(() => {
  mockedApiFetch.mockReset();
  mockedApiFetch.mockResolvedValue({} as never);
  document.cookie = "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax";
});

describe("api client wrappers", () => {
  it("calls register", async () => {
    await api.register("a@example.com", "p");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email: "a@example.com", password: "p" }),
    });
  });

  it("calls login", async () => {
    await api.login("a@example.com", "p");
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: "a@example.com", password: "p" }),
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
      token_type: "bearer",
    } as never);

    await api.login("a@example.com", "p");

    expect(document.cookie).toContain("wai_access_token=local-token");
  });

  it("clears the localhost cookie on logout", async () => {
    document.cookie = "wai_access_token=local-token; Path=/; SameSite=Lax";

    await api.logout();

    expect(document.cookie).not.toContain("wai_access_token=local-token");
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

  it("calls chat endpoints", async () => {
    await api.sendChatMessage({ question: "What happened?", session_id: "s1", recording_ids: ["r1"] });
    await api.listChatSessions();
    await api.getChatSession("s1");
    await api.deleteChatSession("s1");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/chat", {
      method: "POST",
      body: JSON.stringify({ question: "What happened?", session_id: "s1", recording_ids: ["r1"] }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/chat/sessions");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/chat/sessions/s1");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(4, "/api/chat/sessions/s1", { method: "DELETE" });
  });

  it("applies sendChatMessage defaults for optional fields", async () => {
    await api.sendChatMessage({ question: "Hello" });
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/chat", {
      method: "POST",
      body: JSON.stringify({ question: "Hello", session_id: null, recording_ids: null }),
    });
  });

  it("calls getWeeklyDigest", async () => {
    await api.getWeeklyDigest();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/digest/weekly");
  });

  it("calls getRecordingAnalytics", async () => {
    await api.getRecordingAnalytics();
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/recordings/analytics");
  });

  it("calls exportRecording with correct URL and returns blob", async () => {
    const mockBlob = new Blob(["# Test"]);
    const mockResponse = {
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(mockBlob),
    } as unknown as Response;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(mockResponse);

    const result = await api.exportRecording("rec1", "markdown");

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/api/recordings/rec1/export?format=markdown"),
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );
    expect(result).toBeInstanceOf(Blob);

    fetchSpy.mockRestore();
  });

  it("throws on export failure", async () => {
    const mockResponse = {
      ok: false,
      status: 404,
      statusText: "Not Found",
    } as unknown as Response;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(mockResponse);

    await expect(api.exportRecording("rec1", "txt")).rejects.toThrow("Export failed: 404 Not Found");

    fetchSpy.mockRestore();
  });
});
