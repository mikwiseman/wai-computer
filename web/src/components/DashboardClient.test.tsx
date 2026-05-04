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
  status: "ready",
  failure_code: null,
  failure_message: null,
  uploaded_at: null,
  duration_seconds: null,
  language: "multi",
  folder_id: null,
  deleted_at: null,
  starred_at: null,
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
  action_items: [{ id: "a1", recording_id: "r1", task: "Task", owner: null, due_date: null, priority: "medium", status: "pending", source: "auto", created_at: "2026-02-27T00:00:00Z" }],
  highlights: [],
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

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function waitForDashboardReady() {
  await waitFor(() => {
    expect(screen.getByTestId("user-email")).toHaveTextContent("dashboard@example.com");
  });
}

async function openLibraryView(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("tab-library"));
}

async function openSearchView(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("tab-search"));
}

async function openActionsView(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("tab-actions"));
}

async function openTopicsView(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("tab-topics"));
}

async function openSettingsView(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("tab-settings"));
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

  it("keeps the dashboard mounted during reload", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();
    const deferredRecordings = createDeferred<typeof baseRecording[]>();

    mockListRecordings
      .mockResolvedValueOnce([baseRecording])
      .mockImplementationOnce(() => deferredRecordings.promise);

    render(<DashboardClient />);

    await waitForDashboardReady();

    await user.click(screen.getByTestId("reload-dashboard"));

    expect(screen.getByTestId("user-email")).toHaveTextContent("dashboard@example.com");
    expect(screen.getByTestId("dashboard-refreshing")).toHaveTextContent("Refreshing dashboard...");
    expect(screen.queryByTestId("dashboard-loading")).not.toBeInTheDocument();
    expect(screen.getByTestId("reload-dashboard")).toBeDisabled();

    deferredRecordings.resolve([baseRecording]);

    await waitFor(() => {
      expect(screen.queryByTestId("dashboard-refreshing")).not.toBeInTheDocument();
    });
  });

  it("covers success and per-handler error branches", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    expect(screen.getByTestId("dashboard-loading")).toHaveTextContent("Loading dashboard...");

    await waitForDashboardReady();
    await openLibraryView(user);

    await user.click(screen.getByTestId("create-recording"));
    await waitFor(() => {
      expect(mockCreateRecording).toHaveBeenCalledWith({
        title: null,
        type: "note",
        language: "multi",
      });
    });

    await user.type(screen.getByTestId("recording-title"), "Sprint");
    await user.selectOptions(screen.getByTestId("recording-type"), "reflection");
    await user.click(screen.getByTestId("create-recording"));
    await waitFor(() => {
      expect(mockCreateRecording).toHaveBeenCalledWith({
        title: "Sprint",
        type: "reflection",
        language: "multi",
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
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Recording moved to trash.");
    });

    await openSearchView(user);
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

    await openActionsView(user);
    await user.click(screen.getByTestId("set-complete-a1"));
    await waitFor(() => {
      expect(mockUpdateActionItem).toHaveBeenCalledWith("a1", { status: "completed" });
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Action item updated.");
    });

    await user.click(screen.getByTestId("set-pending-a1"));
    await waitFor(() => {
      expect(mockUpdateActionItem).toHaveBeenCalledWith("a1", { status: "pending" });
    });

    await openTopicsView(user);
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

    await openSettingsView(user);
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

    await openLibraryView(user);
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

    await openSearchView(user);
    mockSearch.mockRejectedValueOnce(new Error("Search failed"));
    await user.selectOptions(screen.getByTestId("search-mode"), "hybrid");
    await user.click(screen.getByTestId("search-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Search failed");
    });

    await openActionsView(user);
    mockUpdateActionItem.mockRejectedValueOnce(new Error("Action failed"));
    await user.click(screen.getByTestId("set-complete-a1"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Action failed");
    });

    await openTopicsView(user);
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

    await openSettingsView(user);
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

    await waitForDashboardReady();
    await openLibraryView(user);

    await waitFor(() => {
      expect(screen.getByTestId("select-recording-r2")).toHaveTextContent("(untitled)");
      expect(screen.getByTestId("select-recording-r2")).toHaveTextContent("Note / Feb 27, 2026");
    });

    await user.click(screen.getByTestId("delete-recording-r2"));
    await waitFor(() => {
      expect(mockDeleteRecording).toHaveBeenCalledWith("r2");
    });

    await user.click(screen.getByTestId("select-recording-r2"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toHaveTextContent("(untitled recording)");
    });
  });

  it("renders search results when results are returned", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    mockSearch.mockResolvedValue({
      results: [
        {
          recording_id: "r1",
          recording_title: "Planning",
          recording_type: "note",
          segment_id: "seg1",
          speaker: "Alice",
          content: "We discussed the roadmap",
          start_ms: 1000,
          end_ms: 5000,
          score: 0.95,
        },
        {
          recording_id: "r1",
          recording_title: null,
          recording_type: "note",
          segment_id: "seg2",
          speaker: null,
          content: "Action items were assigned",
          start_ms: 6000,
          end_ms: 10000,
          score: 0.82,
        },
      ],
      total: 2,
    });

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSearchView(user);

    await user.type(screen.getByTestId("search-query"), "roadmap");
    await user.click(screen.getByTestId("search-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 2");
      expect(screen.getByTestId("search-results")).toBeInTheDocument();
      expect(screen.getByTestId("search-result-seg1")).toHaveTextContent("Planning");
      expect(screen.getByTestId("search-result-seg1")).toHaveTextContent("We discussed the roadmap");
      expect(screen.getByTestId("search-result-seg1")).toHaveTextContent("Alice");
      expect(screen.getByTestId("search-result-seg1")).toHaveTextContent("0.95");
      expect(screen.getByTestId("search-result-seg2")).toHaveTextContent("(untitled)");
    });

    await user.click(screen.getAllByRole("button", { name: "Open" })[0]);
    await waitFor(() => {
      expect(mockGetRecording).toHaveBeenCalledWith("r1");
      expect(screen.getByTestId("recording-detail")).toBeInTheDocument();
    });
  });

  it("renders no-results message when search returns empty", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    mockSearch.mockResolvedValue({ results: [], total: 0 });

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSearchView(user);

    await user.type(screen.getByTestId("search-query"), "nonexistent");
    await user.click(screen.getByTestId("search-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 0");
      expect(screen.getByTestId("search-no-results")).toHaveTextContent("No matching transcript segments found.");
    });
  });

  // --- Search mode change clears search results (bugfix verification) ---

  it("clears search results when search mode changes", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    mockSearch.mockResolvedValue({
      results: [
        {
          recording_id: "r1",
          recording_title: "Planning",
          recording_type: "note",
          segment_id: "seg1",
          speaker: "Alice",
          content: "Roadmap discussion",
          start_ms: 1000,
          end_ms: 5000,
          score: 0.9,
        },
      ],
      total: 1,
    });

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSearchView(user);

    // Perform a search to populate results
    await user.type(screen.getByTestId("search-query"), "roadmap");
    await user.click(screen.getByTestId("search-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 1");
      expect(screen.getByTestId("search-results")).toBeInTheDocument();
    });

    // Change search mode — results should be cleared immediately
    await user.selectOptions(screen.getByTestId("search-mode"), "semantic");

    await waitFor(() => {
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 0");
    });
    expect(screen.queryByTestId("search-results")).not.toBeInTheDocument();
  });

  // --- Empty search query doesn't call API ---

  it("does not call search API when query is empty", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSearchView(user);

    // Leave query empty and click search
    await user.click(screen.getByTestId("search-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Enter a search query.");
    });
    expect(mockSearch).not.toHaveBeenCalled();
    expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 0");
  });

  // --- Password change clears fields on success ---

  it("clears password fields after successful password change", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSettingsView(user);

    const currentPwdInput = screen.getByTestId("current-password");
    const newPwdInput = screen.getByTestId("new-password");

    // Fill in password fields
    await user.type(currentPwdInput, "myOldPassword");
    await user.type(newPwdInput, "myNewPassword");

    expect(currentPwdInput).toHaveValue("myOldPassword");
    expect(newPwdInput).toHaveValue("myNewPassword");

    // Submit password change
    await user.click(screen.getByTestId("change-password"));

    await waitFor(() => {
      expect(mockChangePassword).toHaveBeenCalledWith("myOldPassword", "myNewPassword");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Password changed successfully");
    });

    // Fields should be cleared after success
    expect(currentPwdInput).toHaveValue("");
    expect(newPwdInput).toHaveValue("");
  });

  // --- Password change does NOT clear fields on failure ---

  it("preserves password fields after failed password change", async () => {
    arrangeHappyPathMocks();
    mockChangePassword.mockRejectedValue(new Error("Invalid current password"));
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSettingsView(user);

    const currentPwdInput = screen.getByTestId("current-password");
    const newPwdInput = screen.getByTestId("new-password");

    await user.type(currentPwdInput, "wrongPassword");
    await user.type(newPwdInput, "newPassword123");

    await user.click(screen.getByTestId("change-password"));

    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Invalid current password");
    });

    // Fields should NOT be cleared after failure
    expect(currentPwdInput).toHaveValue("wrongPassword");
    expect(newPwdInput).toHaveValue("newPassword123");
  });

  // --- Entity creation calls API with correct params ---

  it("calls createEntity with type=topic, name from input, and metadata source=web", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openTopicsView(user);

    // Type a new entity name
    await user.type(screen.getByTestId("entity-name"), "Machine Learning");
    await user.click(screen.getByTestId("create-entity"));

    await waitFor(() => {
      expect(mockCreateEntity).toHaveBeenCalledWith({
        type: "topic",
        name: "Machine Learning",
        metadata: { source: "web" },
      });
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Entity created.");
    });

    // Entity name input should be cleared after successful creation
    expect(screen.getByTestId("entity-name")).toHaveValue("");
  });

  // --- Recording deletion refreshes the recordings list ---

  it("refreshes recording list after deleting a recording", async () => {
    arrangeHappyPathMocks();
    const secondRecording = {
      ...baseRecording,
      id: "r2",
      title: "Design Review",
    };

    // Initial load returns two recordings
    mockListRecordings.mockResolvedValueOnce([baseRecording, secondRecording]);
    // After deletion, list returns only one
    mockListRecordings.mockResolvedValueOnce([secondRecording]);

    const user = userEvent.setup();
    render(<DashboardClient />);
    await waitForDashboardReady();
    await openLibraryView(user);

    await waitFor(() => {
      expect(screen.getByTestId("select-recording-r1")).toBeInTheDocument();
      expect(screen.getByTestId("select-recording-r2")).toBeInTheDocument();
    });

    // Delete the first recording
    await user.click(screen.getByTestId("delete-recording-r1"));

    await waitFor(() => {
      expect(mockDeleteRecording).toHaveBeenCalledWith("r1");
      // listRecordings should have been called again (initial load + after delete)
      expect(mockListRecordings).toHaveBeenCalledTimes(2);
    });

    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Recording moved to trash.");
    });
  });

  // --- Deleting selected recording clears the detail panel ---

  it("clears selectedRecording detail when the selected recording is deleted", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openLibraryView(user);

    // Select the recording to show detail
    await user.click(screen.getByTestId("select-recording-r1"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toBeInTheDocument();
    });

    // Delete it
    await user.click(screen.getByTestId("delete-recording-r1"));

    await waitFor(() => {
      expect(mockDeleteRecording).toHaveBeenCalledWith("r1");
    });

    // Detail panel should be gone since we deleted the selected recording
    await waitFor(() => {
      expect(screen.queryByTestId("recording-detail")).not.toBeInTheDocument();
    });
  });

  it("returns to the new recording pane from a selected recording", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openLibraryView(user);

    await user.click(screen.getByTestId("select-recording-r1"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "New" }));

    expect(screen.queryByTestId("recording-detail")).not.toBeInTheDocument();
    expect(screen.getByTestId("recording-title")).toBeInTheDocument();
  });

  // --- Recording creation flow: fill form, submit, verify API called, list refreshed ---

  it("recording creation flow: fills form, submits, verifies API call, and refreshes list", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    const newRecording = {
      ...baseRecording,
      id: "r-new",
      title: "Standup Notes",
      type: "meeting",
    };

    // Initial load returns one recording
    mockListRecordings.mockResolvedValueOnce([baseRecording]);
    // After creation, list returns both recordings
    mockListRecordings.mockResolvedValueOnce([baseRecording, newRecording]);
    mockCreateRecording.mockResolvedValueOnce(newRecording);

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openLibraryView(user);

    // Verify only the initial recording is shown
    expect(screen.getByTestId("select-recording-r1")).toBeInTheDocument();
    expect(screen.queryByTestId("select-recording-r-new")).not.toBeInTheDocument();

    // Fill in the recording form
    await user.type(screen.getByTestId("recording-title"), "Standup Notes");
    await user.selectOptions(screen.getByTestId("recording-type"), "meeting");

    // Submit the form
    await user.click(screen.getByTestId("create-recording"));

    // Verify the API was called with the correct params
    await waitFor(() => {
      expect(mockCreateRecording).toHaveBeenCalledWith({
        title: "Standup Notes",
        type: "meeting",
        language: "multi",
      });
    });

    // Verify the recording list was refreshed (listRecordings called again)
    await waitFor(() => {
      expect(mockListRecordings).toHaveBeenCalledTimes(2);
    });

    // Verify the success message
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Recording created.");
    });

    // Verify the title input was cleared after successful creation
    expect(screen.getByTestId("recording-title")).toHaveValue("");
  });

  // --- Logout clears all state and redirects ---

  it("logout clears user state and redirects to login", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openLibraryView(user);

    // Verify state is populated before logout
    expect(screen.getByTestId("select-recording-r1")).toBeInTheDocument();
    expect(screen.getByTestId("recording-list")).toBeInTheDocument();

    // Click logout
    await user.click(screen.getByTestId("logout-button"));

    // Verify logout API was called
    await waitFor(() => {
      expect(mockLogout).toHaveBeenCalledTimes(1);
    });

    // Verify redirect to login page
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  // --- Action item update flow: toggle status and verify API + message ---

  it("action item update flow: marks complete, verifies API, then marks pending", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    const completedItem = { ...baseActionItems[0], status: "completed" };

    // After first update (complete), return completed item
    mockUpdateActionItem.mockResolvedValueOnce(completedItem);
    mockListActionItems
      .mockResolvedValueOnce(baseActionItems)           // initial load
      .mockResolvedValueOnce([completedItem])            // after marking complete
      .mockResolvedValueOnce(baseActionItems);           // after marking pending again

    // After second update (pending), return pending item
    mockUpdateActionItem.mockResolvedValueOnce(baseActionItems[0]);

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openActionsView(user);

    // Step 1: Mark action item as complete
    await user.click(screen.getByTestId("set-complete-a1"));

    await waitFor(() => {
      expect(mockUpdateActionItem).toHaveBeenCalledWith("a1", { status: "completed" });
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Action item updated.");
    });

    // Verify action items list was refreshed
    expect(mockListActionItems).toHaveBeenCalledTimes(2);

    // Step 2: Mark it back as pending
    await user.click(screen.getByTestId("set-pending-a1"));

    await waitFor(() => {
      expect(mockUpdateActionItem).toHaveBeenCalledWith("a1", { status: "pending" });
    });

    // Verify action items list was refreshed again
    await waitFor(() => {
      expect(mockListActionItems).toHaveBeenCalledTimes(3);
    });
  });

  // --- Search mode change back and forth clears results each time ---

  it("clears search results on every mode change, not just the first", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    mockSearch.mockResolvedValue({
      results: [
        {
          recording_id: "r1",
          recording_title: "Meeting",
          recording_type: "note",
          segment_id: "seg1",
          speaker: null,
          content: "Content",
          start_ms: 0,
          end_ms: 1000,
          score: 0.8,
        },
      ],
      total: 1,
    });
    mockSemanticSearch.mockResolvedValue({
      results: [
        {
          recording_id: "r1",
          recording_title: "Meeting",
          recording_type: "note",
          segment_id: "seg2",
          speaker: null,
          content: "Semantic content",
          start_ms: 0,
          end_ms: 1000,
          score: 0.7,
        },
      ],
      total: 1,
    });

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSearchView(user);

    // Search in hybrid mode
    await user.type(screen.getByTestId("search-query"), "test");
    await user.click(screen.getByTestId("search-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 1");
    });

    // Switch to semantic — results cleared
    await user.selectOptions(screen.getByTestId("search-mode"), "semantic");
    await waitFor(() => {
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 0");
    });

    // Search again in semantic mode
    await user.click(screen.getByTestId("search-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 1");
    });

    // Switch back to hybrid — results cleared again
    await user.selectOptions(screen.getByTestId("search-mode"), "hybrid");
    await waitFor(() => {
      expect(screen.getByTestId("search-total")).toHaveTextContent("Total: 0");
    });
  });
});
