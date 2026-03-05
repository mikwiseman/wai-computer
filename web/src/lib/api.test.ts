import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { apiFetch } from "./http";

vi.mock("./http", () => ({
  apiFetch: vi.fn(),
}));

const mockedApiFetch = vi.mocked(apiFetch);

beforeEach(() => {
  mockedApiFetch.mockReset();
  mockedApiFetch.mockResolvedValue({} as never);
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
});
