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
const mockStartSummaryGeneration = vi.fn();
const mockSearch = vi.fn();
const mockSemanticSearch = vi.fn();
const mockFulltextSearch = vi.fn();
const mockChangePassword = vi.fn();
const mockGetSettings = vi.fn();
const mockUpdateSettings = vi.fn();
const mockGetPreferences = vi.fn();
const mockUpdatePreferences = vi.fn();
const mockGetTelegramLinkStatus = vi.fn();
const mockStartTelegramLink = vi.fn();
const mockClaimTelegramLinkCode = vi.fn();
const mockUnlinkTelegram = vi.fn();
const mockLogout = vi.fn();
const mockListMcpConnections = vi.fn();
const mockRevokeMcpConnection = vi.fn();
const mockListApiKeys = vi.fn();
const mockCreateApiKey = vi.fn();
const mockRevokeApiKey = vi.fn();
const mockListFolders = vi.fn();
const mockCreateFolder = vi.fn();
const mockRenameFolder = vi.fn();
const mockDeleteFolder = vi.fn();
const mockAssignRecordingToFolder = vi.fn();
const mockListDictationEntries = vi.fn();
const mockListDictionaryWords = vi.fn();
const mockCreateDictionaryWord = vi.fn();
const mockDeleteDictionaryWord = vi.fn();
const mockListPersonalizationTerms = vi.fn();
const mockCreatePersonalizationTerm = vi.fn();
const mockUpdatePersonalizationTerm = vi.fn();
const mockDeletePersonalizationTerm = vi.fn();
const mockImportPersonalizationText = vi.fn();
const mockImportPersonalizationFile = vi.fn();
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
  startSummaryGeneration: (...args: unknown[]) => mockStartSummaryGeneration(...args),
  search: (...args: unknown[]) => mockSearch(...args),
  semanticSearch: (...args: unknown[]) => mockSemanticSearch(...args),
  fulltextSearch: (...args: unknown[]) => mockFulltextSearch(...args),
  changePassword: (...args: unknown[]) => mockChangePassword(...args),
  getSettings: (...args: unknown[]) => mockGetSettings(...args),
  updateSettings: (...args: unknown[]) => mockUpdateSettings(...args),
  getPreferences: (...args: unknown[]) => mockGetPreferences(...args),
  updatePreferences: (...args: unknown[]) => mockUpdatePreferences(...args),
  getTelegramLinkStatus: (...args: unknown[]) => mockGetTelegramLinkStatus(...args),
  startTelegramLink: (...args: unknown[]) => mockStartTelegramLink(...args),
  claimTelegramLinkCode: (...args: unknown[]) => mockClaimTelegramLinkCode(...args),
  unlinkTelegram: (...args: unknown[]) => mockUnlinkTelegram(...args),
  logout: (...args: unknown[]) => mockLogout(...args),
  listMcpConnections: (...args: unknown[]) => mockListMcpConnections(...args),
  revokeMcpConnection: (...args: unknown[]) => mockRevokeMcpConnection(...args),
  listApiKeys: (...args: unknown[]) => mockListApiKeys(...args),
  createApiKey: (...args: unknown[]) => mockCreateApiKey(...args),
  revokeApiKey: (...args: unknown[]) => mockRevokeApiKey(...args),
  listFolders: (...args: unknown[]) => mockListFolders(...args),
  createFolder: (...args: unknown[]) => mockCreateFolder(...args),
  renameFolder: (...args: unknown[]) => mockRenameFolder(...args),
  deleteFolder: (...args: unknown[]) => mockDeleteFolder(...args),
  assignRecordingToFolder: (...args: unknown[]) => mockAssignRecordingToFolder(...args),
  listDictationEntries: (...args: unknown[]) => mockListDictationEntries(...args),
  listDictionaryWords: (...args: unknown[]) => mockListDictionaryWords(...args),
  createDictionaryWord: (...args: unknown[]) => mockCreateDictionaryWord(...args),
  deleteDictionaryWord: (...args: unknown[]) => mockDeleteDictionaryWord(...args),
  listPersonalizationTerms: (...args: unknown[]) => mockListPersonalizationTerms(...args),
  createPersonalizationTerm: (...args: unknown[]) => mockCreatePersonalizationTerm(...args),
  updatePersonalizationTerm: (...args: unknown[]) => mockUpdatePersonalizationTerm(...args),
  deletePersonalizationTerm: (...args: unknown[]) => mockDeletePersonalizationTerm(...args),
  importPersonalizationText: (...args: unknown[]) => mockImportPersonalizationText(...args),
  importPersonalizationFile: (...args: unknown[]) => mockImportPersonalizationFile(...args),
}));

const baseUser = {
  id: "u1",
  email: "dashboard@example.com",
  created_at: "2026-02-27T00:00:00Z",
  has_password: true,
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

const baseSettings = {
  default_language: "ru",
  summary_language: "ru",
  summary_style: "medium",
  summary_instructions: null,
  dictation_live_stt_provider: "deepgram",
  dictation_live_stt_model: "nova-3",
  recording_live_stt_provider: "deepgram",
  recording_live_stt_model: "nova-3",
  file_stt_provider: "elevenlabs",
  file_stt_model: "scribe_v2",
  dictation_post_filter_enabled: false,
  dictation_post_filter_provider: "openai",
  dictation_post_filter_model: "gpt-5.5",
};

const baseTelegramStatus = {
  linked: false,
  bot_username: "waicomputer_bot",
  telegram_user_id: null,
  username: null,
  first_name: null,
  last_name: null,
  linked_at: null,
};

function arrangeHappyPathMocks() {
  mockGetCurrentUser.mockResolvedValue(baseUser);
  mockListRecordings.mockResolvedValue([baseRecording]);
  mockCreateRecording.mockResolvedValue(baseRecording);
  mockDeleteRecording.mockResolvedValue(undefined);
  mockGetRecording.mockResolvedValue(baseRecordingDetail);
  mockGenerateSummary.mockResolvedValue(baseRecordingDetail.summary);
  mockStartSummaryGeneration.mockResolvedValue({ status: "queued" });
  mockSearch.mockResolvedValue({ results: [], total: 5 });
  mockSemanticSearch.mockResolvedValue({ results: [], total: 4 });
  mockFulltextSearch.mockResolvedValue({ results: [], total: 3 });
  mockChangePassword.mockResolvedValue({ message: "Password changed successfully" });
  mockGetSettings.mockResolvedValue(baseSettings);
  mockUpdateSettings.mockResolvedValue(baseSettings);
  mockGetPreferences.mockResolvedValue({ theme: "system", accent: "teal" });
  mockUpdatePreferences.mockResolvedValue({ theme: "system", accent: "teal" });
  mockGetTelegramLinkStatus.mockResolvedValue(baseTelegramStatus);
  mockStartTelegramLink.mockResolvedValue({
    bot_username: "waicomputer_bot",
    deep_link: "tg://resolve?domain=waicomputer_bot&start=link_token",
    web_link: "https://t.me/waicomputer_bot?start=link_token",
    expires_at: "2026-05-22T09:00:00Z",
  });
  mockClaimTelegramLinkCode.mockResolvedValue({
    ...baseTelegramStatus,
    linked: true,
    telegram_user_id: 123,
    username: "mik",
    linked_at: "2026-05-22T09:00:00Z",
  });
  mockUnlinkTelegram.mockResolvedValue(undefined);
  mockLogout.mockResolvedValue({ message: "Logged out" });
  mockListMcpConnections.mockResolvedValue([]);
  mockRevokeMcpConnection.mockResolvedValue(undefined);
  mockListApiKeys.mockResolvedValue([]);
  mockCreateApiKey.mockResolvedValue({});
  mockRevokeApiKey.mockResolvedValue(undefined);
  mockListFolders.mockResolvedValue([]);
  mockCreateFolder.mockImplementation(async (name: string) => ({
    id: `folder-${name.toLowerCase().replace(/\s+/g, "-")}`,
    name,
    created_at: "2026-05-27T00:00:00Z",
  }));
  mockRenameFolder.mockImplementation(async (id: string, name: string) => ({
    id,
    name,
    created_at: "2026-05-27T00:00:00Z",
  }));
  mockDeleteFolder.mockResolvedValue(undefined);
  mockAssignRecordingToFolder.mockResolvedValue(undefined);
  mockListDictationEntries.mockResolvedValue([]);
  mockListDictionaryWords.mockResolvedValue([]);
  mockCreateDictionaryWord.mockImplementation(async (input: { word: string; replacement?: string | null }) => ({
    client_word_id: `word-${input.word}`,
    word: input.word,
    replacement: input.replacement ?? null,
    occurred_at: "2026-05-27T00:00:00Z",
  }));
  mockDeleteDictionaryWord.mockResolvedValue(undefined);
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
      mockStartSummaryGeneration,
      mockSearch,
      mockSemanticSearch,
      mockFulltextSearch,
      mockChangePassword,
      mockGetSettings,
      mockUpdateSettings,
      mockGetTelegramLinkStatus,
      mockStartTelegramLink,
      mockClaimTelegramLinkCode,
      mockUnlinkTelegram,
      mockLogout,
      mockListMcpConnections,
      mockRevokeMcpConnection,
      mockListApiKeys,
      mockCreateApiKey,
      mockRevokeApiKey,
      mockListFolders,
      mockCreateFolder,
      mockRenameFolder,
      mockDeleteFolder,
      mockAssignRecordingToFolder,
      mockListDictationEntries,
      mockListDictionaryWords,
      mockCreateDictionaryWord,
      mockDeleteDictionaryWord,
      mockListPersonalizationTerms,
      mockCreatePersonalizationTerm,
      mockUpdatePersonalizationTerm,
      mockDeletePersonalizationTerm,
      mockImportPersonalizationText,
      mockImportPersonalizationFile,
      mockReplace,
    ].forEach((fn) => fn.mockReset());
    mockListFolders.mockResolvedValue([]);
    mockListDictationEntries.mockResolvedValue([]);
    mockListDictionaryWords.mockResolvedValue([]);
    mockListPersonalizationTerms.mockResolvedValue([]);
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
      expect(mockStartSummaryGeneration).toHaveBeenCalledWith("r1", { instructions: null });
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

    mockStartSummaryGeneration.mockRejectedValueOnce(new Error("Generate failed"));
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
  }, 15_000);

  it("renders untitled recording/detail fallbacks", async () => {
    const user = userEvent.setup();

    mockGetCurrentUser.mockResolvedValue(baseUser);
    mockListRecordings.mockResolvedValue([{ ...baseRecording, id: "r2", title: null }]);
    mockDeleteRecording.mockResolvedValue(undefined);
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

  it("sets first password for magic-link accounts without requiring current password", async () => {
    arrangeHappyPathMocks();
    mockGetCurrentUser.mockResolvedValue({ ...baseUser, has_password: false });
    mockChangePassword.mockResolvedValue({ message: "Password set successfully" });
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSettingsView(user);

    expect(screen.getByTestId("set-password-note")).toHaveTextContent("magic link");
    expect(screen.queryByTestId("current-password")).not.toBeInTheDocument();
    await user.type(screen.getByTestId("new-password"), "firstPassword");
    await user.click(screen.getByTestId("change-password"));

    await waitFor(() => {
      expect(mockChangePassword).toHaveBeenCalledWith("", "firstPassword");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Password set successfully");
    });

    expect(screen.getByTestId("current-password")).toBeInTheDocument();
  });

  it("claims Telegram bot link code from settings (RU locale)", async () => {
    arrangeHappyPathMocks();
    const originalLanguage = navigator.language;
    const originalLanguages = navigator.languages;
    Object.defineProperty(navigator, "language", {
      value: "ru-RU",
      configurable: true,
    });
    Object.defineProperty(navigator, "languages", {
      value: ["ru-RU"],
      configurable: true,
    });
    const user = userEvent.setup();

    try {
      render(<DashboardClient />);
      await waitForDashboardReady();
      await openSettingsView(user);

      await waitFor(() => {
        expect(screen.getByText("Код из Telegram")).toBeInTheDocument();
      });
      await user.type(screen.getByPlaceholderText("Введите код из бота"), "ABCD-2345");
      await user.click(screen.getByRole("button", { name: "Привязать по коду" }));

      await waitFor(() => {
        expect(mockClaimTelegramLinkCode).toHaveBeenCalledWith("ABCD-2345");
        expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Telegram привязан.");
      });
    } finally {
      Object.defineProperty(navigator, "language", {
        value: originalLanguage,
        configurable: true,
      });
      Object.defineProperty(navigator, "languages", {
        value: originalLanguages,
        configurable: true,
      });
    }
  });

  it("renders Telegram settings in English by default", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSettingsView(user);

    await waitFor(() => {
      expect(screen.getByText("Code from Telegram")).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: "Link Telegram" }),
    ).toBeInTheDocument();
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

  // --- Sidebar surface parity with Mac (Folders, Dictation History, Dictionary) ---

  it("renders the new sidebar entries: history and dictionary tabs and Folders group", async () => {
    arrangeHappyPathMocks();
    render(<DashboardClient />);
    await waitForDashboardReady();

    expect(screen.getByTestId("tab-history")).toBeInTheDocument();
    expect(screen.getByTestId("tab-dictionary")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar-folders-label")).toBeInTheDocument();
    expect(screen.getByTestId("open-create-folder")).toBeInTheDocument();
  });

  // --- Folder creation flow ---

  it("creates a folder via the sidebar group, calling createFolder", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();
    mockCreateFolder.mockResolvedValueOnce({
      id: "folder-1",
      name: "Work",
      created_at: "2026-05-27T00:00:00Z",
    });

    render(<DashboardClient />);
    await waitForDashboardReady();

    await user.click(screen.getByTestId("open-create-folder"));
    await user.type(screen.getByTestId("new-folder-name"), "Work");
    await user.click(screen.getByTestId("submit-create-folder"));

    await waitFor(() => {
      expect(mockCreateFolder).toHaveBeenCalledWith("Work");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Folder created.");
    });

    // Folder appears in the sidebar list
    await waitFor(() => {
      expect(screen.getByTestId("sidebar-folder-folder-1")).toBeInTheDocument();
    });
  });

  // --- Keyboard shortcut: '/' focuses the search input ---

  it("'/' key switches to search view and focuses the search input", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();

    // Trigger '/' globally — the keydown listener handles it.
    await user.keyboard("/");

    await waitFor(() => {
      expect(screen.getByTestId("search-query")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByTestId("search-query"));
    });
  });

  // --- Keyboard shortcut: '?' toggles the cheatsheet modal ---

  it("'?' key toggles the keyboard shortcuts cheatsheet", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();

    expect(screen.queryByTestId("shortcuts-modal")).not.toBeInTheDocument();

    // '?' is Shift+/ — keyboard("?") emits that.
    await user.keyboard("?");

    await waitFor(() => {
      expect(screen.getByTestId("shortcuts-modal")).toBeInTheDocument();
    });

    // Closing via the button.
    await user.click(screen.getByTestId("shortcuts-close"));
    await waitFor(() => {
      expect(screen.queryByTestId("shortcuts-modal")).not.toBeInTheDocument();
    });
  });

  // --- Keyboard shortcuts are suppressed inside inputs ---

  it("does not fire shortcuts while typing in an input", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSearchView(user);

    const queryInput = screen.getByTestId("search-query");
    queryInput.focus();
    await user.keyboard("/");

    // Cheatsheet should still be closed
    expect(screen.queryByTestId("shortcuts-modal")).not.toBeInTheDocument();
    // The slash should have been typed into the input, not consumed
    expect(queryInput).toHaveValue("/");
  });

  // --- Dictation History falls back to the unavailable empty state on 404 ---

  it("falls back to 'coming soon' empty state when dictation history endpoint 404s", async () => {
    arrangeHappyPathMocks();
    mockListDictationEntries.mockRejectedValueOnce(new ApiError(404, "Not Found"));
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();

    await user.click(screen.getByTestId("tab-history"));

    await waitFor(() => {
      expect(screen.getByTestId("history-unavailable")).toBeInTheDocument();
    });
  });

  // --- Dictionary view renders existing words and supports adding new ones ---

  it("renders existing dictionary words and creates new ones", async () => {
    arrangeHappyPathMocks();
    mockListDictionaryWords.mockResolvedValueOnce([
      {
        client_word_id: "w-1",
        word: "WaiComputer",
        replacement: "Wai Computer",
        occurred_at: "2026-05-26T00:00:00Z",
      },
    ]);
    mockCreateDictionaryWord.mockResolvedValueOnce({
      client_word_id: "w-2",
      word: "k8s",
      replacement: "Kubernetes",
      occurred_at: "2026-05-27T00:00:00Z",
    });
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();

    await user.click(screen.getByTestId("tab-dictionary"));

    await waitFor(() => {
      expect(screen.getByTestId("dictionary-word-w-1")).toBeInTheDocument();
    });

    await user.type(screen.getByTestId("new-dictionary-word"), "k8s");
    await user.type(screen.getByTestId("new-dictionary-replacement"), "Kubernetes");
    await user.click(screen.getByTestId("add-dictionary-word"));

    await waitFor(() => {
      expect(mockCreateDictionaryWord).toHaveBeenCalledWith({
        word: "k8s",
        replacement: "Kubernetes",
      });
      expect(screen.getByTestId("dictionary-word-w-2")).toBeInTheDocument();
    });
  });

  // --- Folder selection switches the workspace title and filters recordings ---

  it("opens a folder from the sidebar and shows the folder name in the workspace header", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-work", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ]);
    mockListRecordings.mockResolvedValueOnce([
      { ...baseRecording, id: "r-folded", title: "Inside Work", folder_id: "folder-work" },
      { ...baseRecording, id: "r-loose", title: "Outside", folder_id: null },
    ]);

    const user = userEvent.setup();
    render(<DashboardClient />);
    await waitForDashboardReady();

    await waitFor(() => {
      expect(screen.getByTestId("sidebar-folder-folder-work")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("open-folder-folder-work"));

    await waitFor(() => {
      expect(screen.getByTestId("workspace-title")).toHaveTextContent("Work");
      expect(screen.getByTestId("select-recording-r-folded")).toBeInTheDocument();
      expect(screen.queryByTestId("select-recording-r-loose")).not.toBeInTheDocument();
    });
  });

  // --- Folder count badges in the sidebar reflect the recordings list ---

  it("renders folder count badges and updates them when a recording is assigned", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-work", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ]);
    mockListRecordings
      .mockResolvedValueOnce([
        { ...baseRecording, id: "r-1", title: "Loose", folder_id: null },
        {
          ...baseRecording,
          id: "r-2",
          title: "Already inside",
          folder_id: "folder-work",
        },
      ])
      // The post-assignment refetch returns the new canonical state.
      .mockResolvedValueOnce([
        { ...baseRecording, id: "r-1", title: "Loose", folder_id: "folder-work" },
        {
          ...baseRecording,
          id: "r-2",
          title: "Already inside",
          folder_id: "folder-work",
        },
      ]);

    render(<DashboardClient />);
    await waitForDashboardReady();

    await waitFor(() => {
      expect(screen.getByTestId("folder-count-folder-work")).toHaveTextContent("1");
    });

    // Simulate a drop on the folder by dispatching a native event with a
    // stubbed DataTransfer.
    const dropTarget = screen.getByTestId("sidebar-folder-folder-work");
    const dataTransfer = {
      getData: vi.fn(() => "r-1"),
      setData: vi.fn(),
      dropEffect: "move",
      effectAllowed: "move",
    };
    const dropEvent = new Event("drop", { bubbles: true });
    Object.defineProperty(dropEvent, "dataTransfer", {
      value: dataTransfer,
      writable: false,
    });
    dropTarget.dispatchEvent(dropEvent);

    await waitFor(() => {
      expect(mockAssignRecordingToFolder).toHaveBeenCalledWith("r-1", "folder-work");
    });

    // After the optimistic update + refetch, both recordings are inside the
    // folder so the badge reads "2".
    await waitFor(() => {
      expect(screen.getByTestId("folder-count-folder-work")).toHaveTextContent("2");
    });
  });

  // --- Drop event invokes assignRecordingToFolder with the dragged id ---

  it("drop event on a folder calls assignRecordingToFolder with the dragged recording id", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-x", name: "Box", created_at: "2026-05-27T00:00:00Z" },
    ]);
    mockListRecordings.mockResolvedValue([
      { ...baseRecording, id: "rec-drag", title: "Drag me", folder_id: null },
    ]);

    render(<DashboardClient />);
    await waitForDashboardReady();

    await waitFor(() => {
      expect(screen.getByTestId("sidebar-folder-folder-x")).toBeInTheDocument();
    });

    const target = screen.getByTestId("sidebar-folder-folder-x");
    const dataTransfer = {
      getData: vi.fn((type: string) =>
        type === "application/x-wai-recording" ? "rec-drag" : "",
      ),
      setData: vi.fn(),
      dropEffect: "move",
      effectAllowed: "move",
    };
    const dropEvent = new Event("drop", { bubbles: true });
    Object.defineProperty(dropEvent, "dataTransfer", {
      value: dataTransfer,
      writable: false,
    });
    target.dispatchEvent(dropEvent);

    await waitFor(() => {
      expect(mockAssignRecordingToFolder).toHaveBeenCalledWith(
        "rec-drag",
        "folder-x",
      );
    });
  });
});
