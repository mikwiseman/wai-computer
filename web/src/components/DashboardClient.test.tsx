import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/http";
import { DashboardClient } from "./DashboardClient";

const mockGetCurrentUser = vi.fn();
const mockListRecordings = vi.fn();
const mockCreateRecording = vi.fn();
const mockDeleteRecording = vi.fn();
const mockGetRecording = vi.fn();
const mockGenerateSummary = vi.fn();
const mockSearch = vi.fn();
const mockSemanticSearch = vi.fn();
const mockFulltextSearch = vi.fn();
const mockListActionItems = vi.fn();
const mockUpdateActionItem = vi.fn();
const mockListEntities = vi.fn();
const mockCreateEntity = vi.fn();
const mockDeleteEntity = vi.fn();
const mockChangePassword = vi.fn();
const mockLogout = vi.fn();
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

vi.mock("@/lib/api", () => ({
  getCurrentUser: (...args: unknown[]) => mockGetCurrentUser(...args),
  listRecordings: (...args: unknown[]) => mockListRecordings(...args),
  createRecording: (...args: unknown[]) => mockCreateRecording(...args),
  deleteRecording: (...args: unknown[]) => mockDeleteRecording(...args),
  getRecording: (...args: unknown[]) => mockGetRecording(...args),
  generateSummary: (...args: unknown[]) => mockGenerateSummary(...args),
  search: (...args: unknown[]) => mockSearch(...args),
  semanticSearch: (...args: unknown[]) => mockSemanticSearch(...args),
  fulltextSearch: (...args: unknown[]) => mockFulltextSearch(...args),
  listActionItems: (...args: unknown[]) => mockListActionItems(...args),
  updateActionItem: (...args: unknown[]) => mockUpdateActionItem(...args),
  listEntities: (...args: unknown[]) => mockListEntities(...args),
  createEntity: (...args: unknown[]) => mockCreateEntity(...args),
  deleteEntity: (...args: unknown[]) => mockDeleteEntity(...args),
  changePassword: (...args: unknown[]) => mockChangePassword(...args),
  logout: (...args: unknown[]) => mockLogout(...args),
}));

const baseUser = {
  id: "u1",
  email: "dashboard@example.com",
  created_at: "2026-02-27T00:00:00Z",
};

const baseRecording = {
  id: "r1",
  title: "Planning",
  type: "note",
  audio_url: null,
  duration_seconds: null,
  language: "en",
  created_at: "2026-02-27T00:00:00Z",
};

const baseRecordingDetail = {
  ...baseRecording,
  segments: [{ id: "s1", speaker: "A", content: "Hello", start_ms: 0, end_ms: 100, confidence: 0.9 }],
  summary: {
    summary: "A summary",
    key_points: [],
    decisions: [],
    topics: [],
    people_mentioned: [],
    sentiment: "neutral",
  },
  action_items: [{ id: "a1", task: "Task", owner: null, due_date: null, priority: "medium", status: "pending" }],
};

const baseActionItems = [
  {
    id: "a1",
    recording_id: "r1",
    task: "Task",
    owner: null,
    due_date: null,
    priority: "medium",
    status: "pending",
    source: "generated",
    created_at: "2026-02-27T00:00:00Z",
  },
];

const baseEntities = [
  {
    id: "e1",
    type: "topic",
    name: "Roadmap",
    metadata: { source: "seed" },
    created_at: "2026-02-27T00:00:00Z",
  },
];

function arrangeHappyPathMocks() {
  mockGetCurrentUser.mockResolvedValue(baseUser);
  mockListRecordings.mockResolvedValue([baseRecording]);
  mockCreateRecording.mockResolvedValue(baseRecording);
  mockDeleteRecording.mockResolvedValue(undefined);
  mockGetRecording.mockResolvedValue(baseRecordingDetail);
  mockGenerateSummary.mockResolvedValue(baseRecordingDetail.summary);
  mockSearch.mockResolvedValue({ results: [], total: 5 });
  mockSemanticSearch.mockResolvedValue({ results: [], total: 4 });
  mockFulltextSearch.mockResolvedValue({ results: [], total: 3 });
  mockListActionItems.mockResolvedValue(baseActionItems);
  mockUpdateActionItem.mockResolvedValue(baseActionItems[0]);
  mockListEntities.mockResolvedValue(baseEntities);
  mockCreateEntity.mockResolvedValue(baseEntities[0]);
  mockDeleteEntity.mockResolvedValue(undefined);
  mockChangePassword.mockResolvedValue({ message: "Password changed successfully" });
  mockLogout.mockResolvedValue({ message: "Logged out" });
}

describe("DashboardClient", () => {
  beforeEach(() => {
    [
      mockGetCurrentUser,
      mockListRecordings,
      mockCreateRecording,
      mockDeleteRecording,
      mockGetRecording,
      mockGenerateSummary,
      mockSearch,
      mockSemanticSearch,
      mockFulltextSearch,
      mockListActionItems,
      mockUpdateActionItem,
      mockListEntities,
      mockCreateEntity,
      mockDeleteEntity,
      mockChangePassword,
      mockLogout,
      mockReplace,
    ].forEach((fn) => fn.mockReset());
  });

  it("redirects to login when initialize gets 401", async () => {
    mockGetCurrentUser.mockRejectedValue(new ApiError(401, "Unauthorized"));
    render(<DashboardClient />);

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("renders initialization error message for non-401 failure", async () => {
    mockGetCurrentUser.mockRejectedValue(new Error("Init failed"));
    render(<DashboardClient />);

    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Init failed");
    });
    expect(screen.getByTestId("user-email")).toHaveTextContent("No user");
  });

  it("covers success and per-handler error branches", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    expect(screen.getByTestId("dashboard-loading")).toHaveTextContent("Loading dashboard...");

    await waitFor(() => {
      expect(screen.getByTestId("user-email")).toHaveTextContent("dashboard@example.com");
    });

    await user.click(screen.getByTestId("create-recording"));
    await waitFor(() => {
      expect(mockCreateRecording).toHaveBeenCalledWith({
        title: null,
        type: "note",
        language: "en",
      });
    });

    await user.type(screen.getByTestId("recording-title"), "Sprint");
    await user.selectOptions(screen.getByTestId("recording-type"), "reflection");
    await user.click(screen.getByTestId("create-recording"));
    await waitFor(() => {
      expect(mockCreateRecording).toHaveBeenCalledWith({
        title: "Sprint",
        type: "reflection",
        language: "en",
      });
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Recording created.");
    });

    await user.click(screen.getByTestId("select-recording-r1"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("generate-summary-r1"));
    await waitFor(() => {
      expect(mockGenerateSummary).toHaveBeenCalledWith("r1");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Summary generated.");
    });

    await user.click(screen.getByTestId("delete-recording-r1"));
    await waitFor(() => {
      expect(mockDeleteRecording).toHaveBeenCalledWith("r1");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Recording deleted.");
    });

    await user.type(screen.getByTestId("search-query"), "roadmap");
    await user.click(screen.getByTestId("search-submit"));
    await waitFor(() => {
      expect(mockSearch).toHaveBeenCalled();
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 5");
    });

    await user.selectOptions(screen.getByTestId("search-mode"), "semantic");
    await user.click(screen.getByTestId("search-submit"));
    await waitFor(() => {
      expect(mockSemanticSearch).toHaveBeenCalled();
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 4");
    });

    await user.selectOptions(screen.getByTestId("search-mode"), "fts");
    await user.click(screen.getByTestId("search-submit"));
    await waitFor(() => {
      expect(mockFulltextSearch).toHaveBeenCalled();
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 3");
    });

    await user.click(screen.getByTestId("set-complete-a1"));
    await waitFor(() => {
      expect(mockUpdateActionItem).toHaveBeenCalledWith("a1", { status: "completed" });
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Action item updated.");
    });

    await user.click(screen.getByTestId("set-pending-a1"));
    await waitFor(() => {
      expect(mockUpdateActionItem).toHaveBeenCalledWith("a1", { status: "pending" });
    });

    await user.type(screen.getByTestId("entity-name"), "Budget");
    await user.click(screen.getByTestId("create-entity"));
    await waitFor(() => {
      expect(mockCreateEntity).toHaveBeenCalledWith({
        type: "topic",
        name: "Budget",
        metadata: { source: "web" },
      });
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Entity created.");
    });

    await user.click(screen.getByTestId("delete-entity-e1"));
    await waitFor(() => {
      expect(mockDeleteEntity).toHaveBeenCalledWith("e1");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Entity deleted.");
    });

    await user.type(screen.getByTestId("current-password"), "old");
    await user.type(screen.getByTestId("new-password"), "new");
    await user.click(screen.getByTestId("change-password"));
    await waitFor(() => {
      expect(mockChangePassword).toHaveBeenCalledWith("old", "new");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Password changed successfully");
    });

    await user.click(screen.getByTestId("reload-dashboard"));
    await waitFor(() => {
      expect(mockGetCurrentUser).toHaveBeenCalledTimes(2);
    });

    await user.click(screen.getByTestId("logout-button"));
    await waitFor(() => {
      expect(mockLogout).toHaveBeenCalled();
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });

    mockCreateRecording.mockRejectedValueOnce(new ApiError(400, "Create failed"));
    await user.type(screen.getByTestId("recording-title"), "Bad");
    await user.click(screen.getByTestId("create-recording"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Create failed");
    });

    mockGetRecording.mockRejectedValueOnce("unknown-error-type");
    await user.click(screen.getByTestId("select-recording-r1"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Unexpected error");
    });

    mockDeleteRecording.mockRejectedValueOnce(new Error("Delete failed"));
    await user.click(screen.getByTestId("delete-recording-r1"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Delete failed");
    });

    mockGenerateSummary.mockRejectedValueOnce(new Error("Generate failed"));
    await user.click(screen.getByTestId("generate-summary-r1"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Generate failed");
    });

    mockSearch.mockRejectedValueOnce(new Error("Search failed"));
    await user.selectOptions(screen.getByTestId("search-mode"), "hybrid");
    await user.click(screen.getByTestId("search-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Search failed");
    });

    mockUpdateActionItem.mockRejectedValueOnce(new Error("Action failed"));
    await user.click(screen.getByTestId("set-complete-a1"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Action failed");
    });

    mockCreateEntity.mockRejectedValueOnce(new Error("Create entity failed"));
    await user.type(screen.getByTestId("entity-name"), "Fail");
    await user.click(screen.getByTestId("create-entity"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Create entity failed");
    });

    mockDeleteEntity.mockRejectedValueOnce(new Error("Delete entity failed"));
    await user.click(screen.getByTestId("delete-entity-e1"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Delete entity failed");
    });

    mockChangePassword.mockRejectedValueOnce(new Error("Change password failed"));
    await user.type(screen.getByTestId("current-password"), "old2");
    await user.type(screen.getByTestId("new-password"), "new2");
    await user.click(screen.getByTestId("change-password"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Change password failed");
    });

    mockLogout.mockRejectedValueOnce(new Error("Logout failed"));
    await user.click(screen.getByTestId("logout-button"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Logout failed");
    });
  });

  it("renders untitled recording/detail fallbacks", async () => {
    const user = userEvent.setup();

    mockGetCurrentUser.mockResolvedValue(baseUser);
    mockListRecordings.mockResolvedValue([{ ...baseRecording, id: "r2", title: null }]);
    mockDeleteRecording.mockResolvedValue(undefined);
    mockListActionItems.mockResolvedValue([]);
    mockListEntities.mockResolvedValue([]);
    mockGetRecording.mockResolvedValue({
      ...baseRecordingDetail,
      id: "r2",
      title: null,
      summary: null,
    });

    render(<DashboardClient />);
    expect(screen.getByTestId("dashboard-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("select-recording-r2")).toHaveTextContent("(untitled) [note]");
    });

    await user.click(screen.getByTestId("delete-recording-r2"));
    await waitFor(() => {
      expect(mockDeleteRecording).toHaveBeenCalledWith("r2");
    });

    await user.click(screen.getByTestId("select-recording-r2"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toHaveTextContent("(untitled recording)");
      expect(screen.getByTestId("recording-detail")).toHaveTextContent("Summary: Not generated");
    });
  });
});
