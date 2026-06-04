import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/http";
import { DashboardClient } from "./DashboardClient";

const mockGetCurrentUser = vi.fn();
const mockListInbox = vi.fn();
const mockListRecordings = vi.fn();
const mockCreateRecording = vi.fn();
const mockDeleteRecording = vi.fn();
const mockRestoreRecording = vi.fn();
const mockBulkRecordingOperation = vi.fn();
const mockDeleteDictationEntry = vi.fn();
const mockGetRecording = vi.fn();
const mockGenerateSummary = vi.fn();
const mockStartSummaryGeneration = vi.fn();
const mockSearch = vi.fn();
const mockSemanticSearch = vi.fn();
const mockFulltextSearch = vi.fn();
const mockChangePassword = vi.fn();
const mockGetSettings = vi.fn();
const mockUpdateSettings = vi.fn();
const mockGetTranscriptionOptions = vi.fn();
const mockGetPreferences = vi.fn();
const mockUpdatePreferences = vi.fn();
const mockGetTelegramLinkStatus = vi.fn();
const mockStartTelegramLink = vi.fn();
const mockClaimTelegramLinkCode = vi.fn();
const mockUnlinkTelegram = vi.fn();
const mockGetSystemInfo = vi.fn();
const mockGetDataOwnershipMap = vi.fn();
const mockStartSelfHostProvision = vi.fn();
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
const mockUnifiedSearch = vi.fn();
const mockCreateItem = vi.fn();
const mockGetItem = vi.fn();
const mockUploadItem = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

vi.mock("@/lib/api", () => ({
  getCurrentUser: (...args: unknown[]) => mockGetCurrentUser(...args),
  listInbox: (...args: unknown[]) => mockListInbox(...args),
  listRecordings: (...args: unknown[]) => mockListRecordings(...args),
  createRecording: (...args: unknown[]) => mockCreateRecording(...args),
  deleteRecording: (...args: unknown[]) => mockDeleteRecording(...args),
  restoreRecording: (...args: unknown[]) => mockRestoreRecording(...args),
  bulkRecordingOperation: (...args: unknown[]) => mockBulkRecordingOperation(...args),
  deleteDictationEntry: (...args: unknown[]) => mockDeleteDictationEntry(...args),
  getRecording: (...args: unknown[]) => mockGetRecording(...args),
  generateSummary: (...args: unknown[]) => mockGenerateSummary(...args),
  startSummaryGeneration: (...args: unknown[]) => mockStartSummaryGeneration(...args),
  search: (...args: unknown[]) => mockSearch(...args),
  semanticSearch: (...args: unknown[]) => mockSemanticSearch(...args),
  fulltextSearch: (...args: unknown[]) => mockFulltextSearch(...args),
  unifiedSearch: (...args: unknown[]) => mockUnifiedSearch(...args),
  changePassword: (...args: unknown[]) => mockChangePassword(...args),
  getSettings: (...args: unknown[]) => mockGetSettings(...args),
  updateSettings: (...args: unknown[]) => mockUpdateSettings(...args),
  getTranscriptionOptions: (...args: unknown[]) => mockGetTranscriptionOptions(...args),
  getPreferences: (...args: unknown[]) => mockGetPreferences(...args),
  updatePreferences: (...args: unknown[]) => mockUpdatePreferences(...args),
  getTelegramLinkStatus: (...args: unknown[]) => mockGetTelegramLinkStatus(...args),
  startTelegramLink: (...args: unknown[]) => mockStartTelegramLink(...args),
  claimTelegramLinkCode: (...args: unknown[]) => mockClaimTelegramLinkCode(...args),
  unlinkTelegram: (...args: unknown[]) => mockUnlinkTelegram(...args),
  getSystemInfo: (...args: unknown[]) => mockGetSystemInfo(...args),
  getDataOwnershipMap: (...args: unknown[]) => mockGetDataOwnershipMap(...args),
  startSelfHostProvision: (...args: unknown[]) => mockStartSelfHostProvision(...args),
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
  createItem: (...args: unknown[]) => mockCreateItem(...args),
  getItem: (...args: unknown[]) => mockGetItem(...args),
  uploadItem: (...args: unknown[]) => mockUploadItem(...args),
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

const baseInboxResponse = {
  rows: [],
  next_cursor: null,
  has_more: false,
};

function inboxRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "item:item-1",
    source_kind: "item",
    source_id: "item-1",
    detail: { kind: "item", id: "item-1" },
    title: "Folder note",
    source_label: "Material",
    sublabel: "note",
    activity_at: "2026-02-27T00:00:00Z",
    created_at: "2026-02-27T00:00:00Z",
    updated_at: "2026-02-27T00:00:00Z",
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
    ...overrides,
  };
}

function recordingInboxRow(recording: typeof baseRecording = baseRecording) {
  return inboxRow({
    id: `recording:${recording.id}`,
    source_kind: "recording",
    source_id: recording.id,
    detail: { kind: "recording", id: recording.id },
    title: recording.title,
    source_label: "Recording",
    sublabel: recording.type,
    status:
      recording.status === "ready"
        ? "ready"
        : recording.status === "failed"
          ? "failed"
          : "processing",
    source_status: recording.status,
    error: recording.failure_code
      ? { code: recording.failure_code, message: recording.failure_message ?? "" }
      : null,
    folder_id: recording.folder_id,
    duration_seconds: recording.duration_seconds,
    language: recording.language,
    has_summary: false,
    is_starred: recording.starred_at !== null,
    is_trashed: recording.deleted_at !== null,
  });
}

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
  dictation_cleanup_level: "none",
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

const baseSystemInfo = {
  app_name: "WaiComputer",
  deployment_mode: "wai_cloud",
  public_base_url: "https://wai.computer",
  cloud_base_url: "https://wai.computer",
  mcp_url: "https://wai.computer/mcp",
  git_sha: null,
  git_dirty: false,
  audio_retention_policy: "delete_after_processing",
  self_hosting_available: true,
  billing_mode: "cloud",
};

const baseDataOwnershipMap = {
  audio_retention_policy: "delete_after_processing",
  tables: [
    {
      name: "recordings",
      table: "recordings",
      classification: "owned_exportable",
      reason: "Recording metadata and lifecycle state.",
      contains_user_content: true,
      requires_reconnect: false,
    },
  ],
  artifacts: [
    {
      name: "document_uploads",
      classification: "owned_exportable",
      reason: "Original document uploads move with the user's data.",
      contains_user_content: true,
      requires_reconnect: false,
      path_hint: "${UPLOAD_STAGING_DIR}/items/<user_id>/*",
    },
  ],
};

function arrangeHappyPathMocks() {
  mockGetCurrentUser.mockResolvedValue(baseUser);
  mockListInbox.mockResolvedValue({
    rows: [recordingInboxRow()],
    next_cursor: null,
    has_more: false,
  });
  mockListRecordings.mockResolvedValue([baseRecording]);
  mockCreateRecording.mockResolvedValue(baseRecording);
  mockDeleteRecording.mockResolvedValue(undefined);
  mockRestoreRecording.mockResolvedValue(baseRecording);
  mockBulkRecordingOperation.mockResolvedValue(undefined);
  mockDeleteDictationEntry.mockResolvedValue(undefined);
  mockGetRecording.mockResolvedValue(baseRecordingDetail);
  mockGenerateSummary.mockResolvedValue(baseRecordingDetail.summary);
  mockStartSummaryGeneration.mockResolvedValue({ status: "queued" });
  mockSearch.mockResolvedValue({ results: [], total: 5 });
  mockSemanticSearch.mockResolvedValue({ results: [], total: 4 });
  mockFulltextSearch.mockResolvedValue({ results: [], total: 3 });
  mockChangePassword.mockResolvedValue({ message: "Password changed successfully" });
  mockGetSettings.mockResolvedValue(baseSettings);
  mockUpdateSettings.mockResolvedValue(baseSettings);
  mockGetTranscriptionOptions.mockResolvedValue(null);
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
  mockGetSystemInfo.mockResolvedValue(baseSystemInfo);
  mockGetDataOwnershipMap.mockResolvedValue(baseDataOwnershipMap);
  mockStartSelfHostProvision.mockResolvedValue({
    job_id: "selfhost_demo",
    status: "manual_review_required",
    hostname: "demo.self.wai.computer",
    vps_ip: "203.0.113.10",
    message: "Provisioning inputs are valid.",
    steps: [],
  });
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
  mockCreateItem.mockResolvedValue({});
  mockGetItem.mockResolvedValue({});
  mockUploadItem.mockResolvedValue({ kind: "item", item: {} });
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

async function openInboxCreatePane(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("tab-inbox"));
  await waitFor(() => {
    expect(screen.getByTestId("workspace-title")).toHaveTextContent("Inbox");
  });
  const addButton = screen.queryByRole("button", { name: "+ Add" });
  if (addButton) {
    await user.click(addButton);
  }
  const manualRecording = screen.queryByText("Create empty recording");
  if (manualRecording) {
    await user.click(manualRecording);
  }
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
      mockListInbox,
      mockListRecordings,
      mockCreateRecording,
      mockDeleteRecording,
      mockRestoreRecording,
      mockBulkRecordingOperation,
      mockDeleteDictationEntry,
      mockGetRecording,
      mockGenerateSummary,
      mockStartSummaryGeneration,
      mockSearch,
      mockSemanticSearch,
      mockFulltextSearch,
      mockChangePassword,
      mockGetSettings,
      mockUpdateSettings,
      mockGetTranscriptionOptions,
      mockGetTelegramLinkStatus,
      mockStartTelegramLink,
      mockClaimTelegramLinkCode,
      mockUnlinkTelegram,
      mockGetSystemInfo,
      mockGetDataOwnershipMap,
      mockStartSelfHostProvision,
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
      mockCreateItem,
      mockGetItem,
      mockUploadItem,
      mockReplace,
    ].forEach((fn) => fn.mockReset());
    mockListInbox.mockResolvedValue(baseInboxResponse);
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
    await openInboxCreatePane(user);

    await user.click(screen.getByTestId("create-recording"));
    await waitFor(() => {
      expect(mockCreateRecording).toHaveBeenCalledWith(expect.objectContaining({
        title: null,
        type: "note",
        language: "multi",
      }));
    });

    await user.click(screen.getByRole("button", { name: "+ Add" }));
    await user.click(screen.getByText("Create empty recording"));
    await user.type(screen.getByTestId("recording-title"), "Sprint");
    await user.selectOptions(screen.getByTestId("recording-type"), "reflection");
    await user.click(screen.getByTestId("create-recording"));
    await waitFor(() => {
      expect(mockCreateRecording).toHaveBeenCalledWith(expect.objectContaining({
        title: "Sprint",
        type: "reflection",
        language: "multi",
      }));
      expect(mockCreateRecording).toHaveBeenCalled();
    });

    await user.click(screen.getByTestId("select-recording-r1"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toBeInTheDocument();
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

    await openInboxCreatePane(user);
    // r1 is still selected from earlier, so the detail panel is showing.
    // Clicking "+ Add" clears the selection and returns the Inbox create pane.
    await user.click(screen.getByRole("button", { name: "+ Add" }));
    await user.click(screen.getByText("Create empty recording"));
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
    const untitledRecording = { ...baseRecording, id: "r2", title: null };
    mockListRecordings.mockResolvedValue([untitledRecording]);
    mockListInbox.mockResolvedValue({
      rows: [recordingInboxRow(untitledRecording)],
      next_cursor: null,
      has_more: false,
    });
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
    await openInboxCreatePane(user);

    await waitFor(() => {
      expect(screen.getByTestId("select-recording-r2")).toHaveTextContent("Untitled recording");
      expect(screen.getByTestId("select-recording-r2")).toHaveTextContent("Recording / note / Feb 27, 2026");
    });

    await user.click(screen.getByTestId("select-recording-r2"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toHaveTextContent("(untitled recording)");
    });
  });

  it("renders unified results across recordings and items in Everything mode", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();
    mockUnifiedSearch.mockResolvedValue({
      results: [
        {
          source_kind: "recording", parent_id: "r1", chunk_id: "c1", title: "Planning",
          kind: "note", snippet: "roadmap talk", score: 0.9, created_at: null,
        },
        {
          source_kind: "item", parent_id: "i1", chunk_id: "c2", title: "Solar PDF",
          kind: "pdf", snippet: "solar economics", score: 0.7, created_at: null,
        },
      ],
      total: 2,
    });

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSearchView(user);
    await user.selectOptions(screen.getByTestId("search-mode"), "everything");
    await user.type(screen.getByTestId("search-query"), "solar");
    await user.click(screen.getByTestId("search-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("unified-search-results")).toBeInTheDocument(),
    );
    expect(screen.getByText("Solar PDF")).toBeInTheDocument();
    expect(screen.getByText("Planning")).toBeInTheDocument();
    expect(mockUnifiedSearch).toHaveBeenCalledWith({ q: "solar", limit: 25 });
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
      expect(screen.getByTestId("workspace-title")).toHaveTextContent("Inbox");
      expect(screen.getByTestId("tab-inbox")).toHaveAttribute("aria-current", "page");
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

  it("opens Server & Data settings from the self-host migration deep link", async () => {
    arrangeHappyPathMocks();
    window.history.pushState({}, "", "/dashboard?view=settings#server-data");

    render(<DashboardClient />);
    await waitForDashboardReady();

    await waitFor(() => {
      expect(screen.getByTestId("server-data-section")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Check setup" })).toBeInTheDocument();
    expect(mockGetSystemInfo).toHaveBeenCalled();
    expect(mockGetDataOwnershipMap).toHaveBeenCalled();
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
    mockListInbox
      .mockResolvedValueOnce({
        rows: [recordingInboxRow(baseRecording), recordingInboxRow(secondRecording)],
        next_cursor: null,
        has_more: false,
      })
      .mockResolvedValue({
        rows: [recordingInboxRow(secondRecording)],
        next_cursor: null,
        has_more: false,
      });

    const user = userEvent.setup();
    render(<DashboardClient />);
    await waitForDashboardReady();
    await openInboxCreatePane(user);

    await waitFor(() => {
      expect(screen.getByTestId("select-recording-r1")).toBeInTheDocument();
      expect(screen.getByTestId("select-recording-r2")).toBeInTheDocument();
    });

    // Open the first recording's detail panel and trash it via the
    // confirmation modal (Mac parity: deletion always goes through confirm).
    await user.click(screen.getByTestId("select-recording-r1"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Move to Trash" }));
    await user.click(screen.getByTestId("confirm-delete-recording-action"));

    await waitFor(() => {
      // Active-library deletion threads { permanent: false } so the recording
      // is moved to Trash rather than removed outright.
      expect(mockDeleteRecording).toHaveBeenCalledWith("r1", { permanent: false });
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
    await openInboxCreatePane(user);

    // Select the recording to show detail
    await user.click(screen.getByTestId("select-recording-r1"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toBeInTheDocument();
    });

    // Trash via the detail panel confirmation modal
    await user.click(screen.getByRole("button", { name: "Move to Trash" }));
    await user.click(screen.getByTestId("confirm-delete-recording-action"));

    await waitFor(() => {
      // Active-library deletion threads { permanent: false } (move to Trash).
      expect(mockDeleteRecording).toHaveBeenCalledWith("r1", { permanent: false });
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
    await openInboxCreatePane(user);

    await user.click(screen.getByTestId("select-recording-r1"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "+ Add" }));
    await user.click(screen.getByText("Create empty recording"));

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
    mockListInbox
      .mockResolvedValueOnce({
        rows: [recordingInboxRow(baseRecording)],
        next_cursor: null,
        has_more: false,
      })
      .mockResolvedValue({
        rows: [recordingInboxRow(baseRecording), recordingInboxRow(newRecording)],
        next_cursor: null,
        has_more: false,
      });
    mockCreateRecording.mockResolvedValueOnce(newRecording);
    mockGetRecording.mockImplementation(async (recordingId: string) =>
      recordingId === "r-new"
        ? {
            ...baseRecordingDetail,
            id: "r-new",
            title: "Standup Notes",
            type: "meeting",
          }
        : baseRecordingDetail,
    );

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openInboxCreatePane(user);

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
      expect(mockCreateRecording).toHaveBeenCalledWith(expect.objectContaining({
        title: "Standup Notes",
        type: "meeting",
        language: "multi",
      }));
    });

    // Verify the recording list was refreshed (listRecordings called again)
    await waitFor(() => {
      expect(mockListRecordings).toHaveBeenCalledTimes(2);
    });

    // Inbox refreshes the list and selects the newly created recording.
    await waitFor(() => {
      expect(screen.getByTestId("select-recording-r-new")).toBeInTheDocument();
    });
    expect(screen.getByTestId("recording-detail")).toHaveTextContent("Standup Notes");
    expect(screen.queryByTestId("recording-title")).not.toBeInTheDocument();
  });

  // --- Logout clears all state and redirects ---

  it("logout clears user state and redirects to login", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openInboxCreatePane(user);

    // Verify state is populated before logout
    await waitFor(() => {
      expect(screen.getByTestId("select-recording-r1")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByTestId("select-recording-r1")).toBeInTheDocument();
    });

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
    expect(screen.getByTestId("tab-inbox")).toBeInTheDocument();
    expect(screen.queryByTestId("tab-library")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-wai")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-add")).not.toBeInTheDocument();
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

  it("opens a folder through the universal Inbox and creates items in that folder", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-work", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ]);
    mockListRecordings.mockResolvedValue([
      { ...baseRecording, id: "r-folded", title: "Inside Work", folder_id: "folder-work" },
      { ...baseRecording, id: "r-loose", title: "Outside", folder_id: null },
    ]);
    mockListInbox.mockImplementation(async (params?: { folder_id?: string | null }) =>
      params?.folder_id === "folder-work"
        ? { rows: [inboxRow()], next_cursor: null, has_more: false }
        : baseInboxResponse,
    );
    mockCreateItem.mockResolvedValue({
      id: "item-folder-new",
      state: "raw",
      status: "ready",
      error: null,
      summary: null,
      folder_id: "folder-work",
    });

    const user = userEvent.setup();
    render(<DashboardClient />);
    await waitForDashboardReady();

    await waitFor(() => {
      expect(screen.getByTestId("sidebar-folder-folder-work")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("open-folder-folder-work"));

    await waitFor(() => {
      expect(screen.getByTestId("workspace-title")).toHaveTextContent("Work");
      expect(screen.getByText("Folder note")).toBeInTheDocument();
      expect(mockListInbox).toHaveBeenCalledWith(
        expect.objectContaining({ folder_id: "folder-work" }),
      );
    });
    expect(screen.queryByTestId("select-recording-r-folded")).not.toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(/Paste a link or any text/i), "new folder note");
    await user.click(screen.getByRole("button", { name: /^Add$/ }));

    await waitFor(() => {
      expect(mockCreateItem).toHaveBeenCalledWith({
        source: "paste",
        kind: "note",
        body: "new folder note",
        folder_id: "folder-work",
      });
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

  // ===================================================================
  // Additional coverage: trash, bulk ops, summary/restore, folder
  // rename/delete modals, dictation history, dictionary, telegram,
  // keyboard navigation, status pills, settings checkbox.
  // ===================================================================

  // --- Trash view: loads trashed recordings and shows restore empty state ---

  it("loads trashed recordings when the trash tab is opened and shows the restore prompt", async () => {
    arrangeHappyPathMocks();
    const trashed = { ...baseRecording, id: "trashed-1", title: "Old idea", deleted_at: "2026-05-01T00:00:00Z" };
    mockListRecordings.mockImplementation(async (args?: { trashed?: boolean }) =>
      args?.trashed ? [trashed] : [baseRecording],
    );
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();

    await user.click(screen.getByTestId("tab-trash"));

    await waitFor(() => {
      expect(mockListRecordings).toHaveBeenCalledWith({ limit: 100, trashed: true });
      expect(screen.getByTestId("workspace-title")).toHaveTextContent("Trash");
      expect(screen.getByTestId("select-recording-trashed-1")).toHaveTextContent("Old idea");
    });

    // The trash detail pane shows the "select a recording" prompt, not a recorder.
    expect(screen.getByText("Select a Recording")).toBeInTheDocument();
    expect(screen.queryByTestId("recording-title")).not.toBeInTheDocument();
  });

  it("permanently deletes a trashed recording and restores it from the detail panel", async () => {
    arrangeHappyPathMocks();
    const trashed = { ...baseRecording, id: "trashed-1", title: "Old", deleted_at: "2026-05-01T00:00:00Z" };
    mockListRecordings.mockImplementation(async (args?: { trashed?: boolean }) =>
      args?.trashed ? [trashed] : [baseRecording],
    );
    mockGetRecording.mockResolvedValue({ ...baseRecordingDetail, ...trashed });
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-trash"));

    await user.click(screen.getByTestId("select-recording-trashed-1"));
    await waitFor(() => {
      expect(screen.getByTestId("recording-detail")).toBeInTheDocument();
    });

    // Restore from the detail panel.
    await user.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => {
      expect(mockRestoreRecording).toHaveBeenCalledWith("trashed-1");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Recording restored.");
    });
  });

  it("surfaces an error when restoring a recording fails", async () => {
    arrangeHappyPathMocks();
    const trashed = { ...baseRecording, id: "trashed-1", title: "Old", deleted_at: "2026-05-01T00:00:00Z" };
    mockListRecordings.mockImplementation(async (args?: { trashed?: boolean }) =>
      args?.trashed ? [trashed] : [baseRecording],
    );
    mockGetRecording.mockResolvedValue({ ...baseRecordingDetail, ...trashed });
    mockRestoreRecording.mockRejectedValueOnce(new Error("Restore failed"));
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-trash"));
    await user.click(screen.getByTestId("select-recording-trashed-1"));
    await waitFor(() => expect(screen.getByTestId("recording-detail")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Restore failed");
    });
  });

  it("permanently deletes a trashed recording via the confirm modal", async () => {
    arrangeHappyPathMocks();
    const trashed = { ...baseRecording, id: "trashed-1", title: "Old", deleted_at: "2026-05-01T00:00:00Z" };
    mockListRecordings.mockImplementation(async (args?: { trashed?: boolean }) =>
      args?.trashed ? [trashed] : [baseRecording],
    );
    mockGetRecording.mockResolvedValue({ ...baseRecordingDetail, ...trashed });
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-trash"));
    await user.click(screen.getByTestId("select-recording-trashed-1"));
    await waitFor(() => expect(screen.getByTestId("recording-detail")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Delete Permanently" }));
    await user.click(screen.getByTestId("confirm-delete-recording-action"));

    await waitFor(() => {
      expect(mockDeleteRecording).toHaveBeenCalledWith("trashed-1", { permanent: true });
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Recording permanently deleted.");
    });
  });

  // --- Bulk operations: select mode, move-to-folder, trash, restore ---

  it("does not render old recording bulk-move controls in the universal Inbox", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-work", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ]);
    mockListRecordings.mockResolvedValue([
      { ...baseRecording, id: "r1", title: "A" },
      { ...baseRecording, id: "r2", title: "B" },
    ]);
    mockListInbox.mockResolvedValue({
      rows: [
        recordingInboxRow({ ...baseRecording, id: "r1", title: "A" }),
        recordingInboxRow({ ...baseRecording, id: "r2", title: "B" }),
      ],
      next_cursor: null,
      has_more: false,
    });
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-inbox"));

    await waitFor(() => expect(mockListInbox).toHaveBeenCalled());
    expect(screen.getByTestId("workspace-title")).toHaveTextContent("Inbox");
    expect(screen.queryByTestId("select-mode-toggle")).not.toBeInTheDocument();
    expect(screen.queryByTestId("bulk-move-folder")).not.toBeInTheDocument();
    expect(mockBulkRecordingOperation).not.toHaveBeenCalled();
  });

  it("does not render old recording bulk-trash controls in the universal Inbox", async () => {
    arrangeHappyPathMocks();
    mockListRecordings.mockResolvedValue([
      { ...baseRecording, id: "r1", title: "A" },
      { ...baseRecording, id: "r2", title: "B" },
    ]);
    mockListInbox.mockResolvedValue({
      rows: [
        recordingInboxRow({ ...baseRecording, id: "r1", title: "A" }),
        recordingInboxRow({ ...baseRecording, id: "r2", title: "B" }),
      ],
      next_cursor: null,
      has_more: false,
    });
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-inbox"));

    await waitFor(() => expect(mockListInbox).toHaveBeenCalled());
    expect(screen.getByTestId("workspace-title")).toHaveTextContent("Inbox");
    expect(screen.queryByTestId("select-mode-toggle")).not.toBeInTheDocument();
    expect(screen.queryByTestId("bulk-trash")).not.toBeInTheDocument();
    expect(mockBulkRecordingOperation).not.toHaveBeenCalled();
  });

  it("bulk-restores selected recordings from the trash view", async () => {
    arrangeHappyPathMocks();
    const trashed = { ...baseRecording, id: "t1", title: "Trashed", deleted_at: "2026-05-01T00:00:00Z" };
    mockListRecordings.mockImplementation(async (args?: { trashed?: boolean }) =>
      args?.trashed ? [trashed] : [baseRecording],
    );
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-trash"));
    await waitFor(() => expect(screen.getByTestId("select-recording-t1")).toBeInTheDocument());

    await user.click(screen.getByTestId("select-mode-toggle"));
    await user.click(screen.getByTestId("select-checkbox-t1"));
    await user.click(screen.getByTestId("bulk-restore"));

    await waitFor(() => {
      expect(mockBulkRecordingOperation).toHaveBeenCalledWith(["t1"], "restore", undefined);
    });
  });

  // --- Folder rename modal ---

  it("renames a folder through the rename modal", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-1", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ]);
    mockRenameFolder.mockResolvedValueOnce({
      id: "folder-1",
      name: "Projects",
      created_at: "2026-05-27T00:00:00Z",
    });
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await waitFor(() => expect(screen.getByTestId("rename-folder-folder-1")).toBeInTheDocument());

    await user.click(screen.getByTestId("rename-folder-folder-1"));
    const input = await screen.findByTestId("folder-rename-input");
    expect(input).toHaveValue("Work");
    await user.clear(input);
    await user.type(input, "Projects");
    await user.click(screen.getByTestId("folder-rename-submit"));

    await waitFor(() => {
      expect(mockRenameFolder).toHaveBeenCalledWith("folder-1", "Projects");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Folder renamed.");
    });
    expect(screen.queryByTestId("folder-rename-modal")).not.toBeInTheDocument();
  });

  it("rejects an empty folder rename without calling the API", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-1", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ]);
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await waitFor(() => expect(screen.getByTestId("rename-folder-folder-1")).toBeInTheDocument());

    await user.click(screen.getByTestId("rename-folder-folder-1"));
    const input = await screen.findByTestId("folder-rename-input");
    await user.clear(input);
    await user.click(screen.getByTestId("folder-rename-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Enter a folder name.");
    });
    expect(mockRenameFolder).not.toHaveBeenCalled();
    // The modal stays open since the rename was invalid.
    expect(screen.getByTestId("folder-rename-modal")).toBeInTheDocument();
  });

  it("closes the rename modal with the Escape shortcut", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-1", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ]);
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await waitFor(() => expect(screen.getByTestId("rename-folder-folder-1")).toBeInTheDocument());

    await user.click(screen.getByTestId("rename-folder-folder-1"));
    expect(await screen.findByTestId("folder-rename-modal")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByTestId("folder-rename-modal")).not.toBeInTheDocument();
    });
  });

  // --- Folder delete modal ---

  it("deletes a folder through the confirm modal and refreshes recordings", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-1", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ]);
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await waitFor(() => expect(screen.getByTestId("delete-folder-folder-1")).toBeInTheDocument());

    // Open the folder first so the delete handler exercises the active-folder
    // branch that resets the view back to the library.
    await user.click(screen.getByTestId("open-folder-folder-1"));
    await waitFor(() => expect(screen.getByTestId("workspace-title")).toHaveTextContent("Work"));

    await user.click(screen.getByTestId("delete-folder-folder-1"));
    expect(await screen.findByTestId("folder-delete-modal")).toBeInTheDocument();
    await user.click(screen.getByTestId("folder-delete-confirm"));

    await waitFor(() => {
      expect(mockDeleteFolder).toHaveBeenCalledWith("folder-1");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Folder deleted.");
    });
    expect(screen.queryByTestId("sidebar-folder-folder-1")).not.toBeInTheDocument();
  });

  it("cancels a folder deletion without calling the API", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-1", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ]);
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await waitFor(() => expect(screen.getByTestId("delete-folder-folder-1")).toBeInTheDocument());

    await user.click(screen.getByTestId("delete-folder-folder-1"));
    expect(await screen.findByTestId("folder-delete-modal")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(screen.queryByTestId("folder-delete-modal")).not.toBeInTheDocument();
    });
    expect(mockDeleteFolder).not.toHaveBeenCalled();
  });

  // --- Dictation history: stats, delete entry (optimistic + rollback), clear ---

  const dictationEntry = (overrides: Record<string, unknown> = {}) => ({
    client_entry_id: "e1",
    raw_text: "raw words here",
    cleaned_text: "cleaned words here",
    duration_seconds: 12,
    word_count: 3,
    occurred_at: "2026-05-26T10:00:00Z",
    ...overrides,
  });

  it("renders dictation history entries with stats and deletes a single entry", async () => {
    arrangeHappyPathMocks();
    mockListDictationEntries.mockResolvedValue([
      dictationEntry({ client_entry_id: "e1", word_count: 4, duration_seconds: 60 }),
      dictationEntry({ client_entry_id: "e2", word_count: 6, duration_seconds: 60, cleaned_text: null }),
    ]);
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-history"));

    await waitFor(() => {
      expect(screen.getByTestId("history-list")).toBeInTheDocument();
      // Stats header sums word_count = 10 across entries.
      expect(screen.getByTestId("dictation-stats")).toHaveTextContent("10");
    });
    // Entry e2 falls back to raw_text since cleaned_text is null.
    expect(screen.getByTestId("history-entry-e2")).toHaveTextContent("raw words here");

    await user.click(screen.getByTestId("delete-history-e1"));
    await waitFor(() => {
      expect(mockDeleteDictationEntry).toHaveBeenCalledWith("e1");
      expect(screen.queryByTestId("history-entry-e1")).not.toBeInTheDocument();
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Entry removed.");
    });
  });

  it("rolls back the optimistic delete when removing a dictation entry fails", async () => {
    arrangeHappyPathMocks();
    mockListDictationEntries.mockResolvedValue([dictationEntry({ client_entry_id: "e1" })]);
    mockDeleteDictationEntry.mockRejectedValueOnce(new Error("Delete failed"));
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-history"));
    await waitFor(() => expect(screen.getByTestId("history-entry-e1")).toBeInTheDocument());

    await user.click(screen.getByTestId("delete-history-e1"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Delete failed");
    });
    // Entry is restored after the failed delete.
    expect(screen.getByTestId("history-entry-e1")).toBeInTheDocument();
  });

  it("clears all dictation history through the confirm modal", async () => {
    arrangeHappyPathMocks();
    mockListDictationEntries.mockResolvedValue([
      dictationEntry({ client_entry_id: "e1" }),
      dictationEntry({ client_entry_id: "e2" }),
    ]);
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-history"));
    await waitFor(() => expect(screen.getByTestId("history-list")).toBeInTheDocument());

    await user.click(screen.getByTestId("history-clear-all"));
    expect(await screen.findByTestId("history-confirm-clear")).toBeInTheDocument();
    await user.click(screen.getByTestId("history-confirm-clear-action"));

    await waitFor(() => {
      expect(mockDeleteDictationEntry).toHaveBeenCalledWith("e1");
      expect(mockDeleteDictationEntry).toHaveBeenCalledWith("e2");
      expect(screen.getByTestId("history-empty")).toBeInTheDocument();
    });
  });

  // --- Dictionary: delete, duplicate guard, overuse warning, search filter ---

  it("deletes a dictionary word", async () => {
    arrangeHappyPathMocks();
    mockListDictionaryWords.mockResolvedValue([
      { client_word_id: "w-1", word: "kube", replacement: "Kubernetes", occurred_at: "2026-05-26T00:00:00Z" },
    ]);
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-dictionary"));
    await waitFor(() => expect(screen.getByTestId("dictionary-word-w-1")).toBeInTheDocument());

    await user.click(screen.getByTestId("delete-dictionary-w-1"));
    await waitFor(() => {
      expect(mockDeleteDictionaryWord).toHaveBeenCalledWith("w-1");
      expect(screen.queryByTestId("dictionary-word-w-1")).not.toBeInTheDocument();
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Word removed.");
    });
  });

  it("rejects a duplicate dictionary word case-insensitively without calling the API", async () => {
    arrangeHappyPathMocks();
    mockListDictionaryWords.mockResolvedValue([
      { client_word_id: "w-1", word: "Kube", replacement: null, occurred_at: "2026-05-26T00:00:00Z" },
    ]);
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-dictionary"));
    await waitFor(() => expect(screen.getByTestId("dictionary-word-w-1")).toBeInTheDocument());

    await user.type(screen.getByTestId("new-dictionary-word"), "kube");
    await user.click(screen.getByTestId("add-dictionary-word"));

    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Already in your dictionary.");
    });
    expect(mockCreateDictionaryWord).not.toHaveBeenCalled();
  });

  it("rejects an empty dictionary word", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-dictionary"));
    await waitFor(() => expect(screen.getByTestId("dictionary-empty")).toBeInTheDocument());

    await user.click(screen.getByTestId("add-dictionary-word"));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Enter a word.");
    });
    expect(mockCreateDictionaryWord).not.toHaveBeenCalled();
  });

  it("shows the overuse warning and filters words via the search box", async () => {
    arrangeHappyPathMocks();
    const words = Array.from({ length: 31 }, (_, i) => ({
      client_word_id: `w-${i}`,
      word: i === 0 ? "alpha" : `term${i}`,
      replacement: i === 0 ? "Alpha Corp" : null,
      occurred_at: "2026-05-26T00:00:00Z",
    }));
    mockListDictionaryWords.mockResolvedValue(words);
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-dictionary"));

    await waitFor(() => {
      expect(screen.getByTestId("dictionary-overuse")).toBeInTheDocument();
      expect(screen.getByTestId("dictionary-list")).toBeInTheDocument();
    });

    // Filter by replacement text — only the "alpha" row matches "corp".
    await user.type(screen.getByTestId("dictionary-search"), "corp");
    await waitFor(() => {
      expect(screen.getByTestId("dictionary-word-w-0")).toBeInTheDocument();
      expect(screen.queryByTestId("dictionary-word-w-1")).not.toBeInTheDocument();
    });
  });

  it("marks the dictionary unavailable when creating a word 404s", async () => {
    arrangeHappyPathMocks();
    mockCreateDictionaryWord.mockRejectedValueOnce(new ApiError(404, "Not Found"));
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-dictionary"));
    await waitFor(() => expect(screen.getByTestId("dictionary-empty")).toBeInTheDocument());

    await user.type(screen.getByTestId("new-dictionary-word"), "newterm");
    await user.click(screen.getByTestId("add-dictionary-word"));

    await waitFor(() => {
      expect(screen.getByTestId("dictionary-unavailable")).toBeInTheDocument();
    });
  });

  // --- Telegram: start link, unlink, refresh status ---

  it("starts a Telegram link, stores the pairing and navigates to the deep link", async () => {
    arrangeHappyPathMocks();
    const hrefSetter = vi.fn();
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        ...originalLocation,
        set href(value: string) {
          hrefSetter(value);
        },
        get href() {
          return originalLocation.href;
        },
      },
    });
    const user = userEvent.setup();

    try {
      render(<DashboardClient />);
      await waitForDashboardReady();
      await openSettingsView(user);

      await user.click(screen.getByRole("button", { name: "Link Telegram" }));

      await waitFor(() => {
        expect(mockStartTelegramLink).toHaveBeenCalled();
        expect(hrefSetter).toHaveBeenCalledWith(
          "tg://resolve?domain=waicomputer_bot&start=link_token",
        );
        expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Telegram opened.");
      });
      // The awaiting-start hint shows once a pairing exists.
      expect(screen.getByText(/Waiting for Start in Telegram/)).toBeInTheDocument();
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    }
  });

  it("unlinks Telegram when already linked", async () => {
    arrangeHappyPathMocks();
    mockGetTelegramLinkStatus.mockResolvedValue({
      ...baseTelegramStatus,
      linked: true,
      username: "mik",
      telegram_user_id: 7,
      linked_at: "2026-05-22T09:00:00Z",
    });
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSettingsView(user);

    await waitFor(() => {
      expect(screen.getByText("@mik")).toBeInTheDocument();
    });

    // After unlinking, the status refetch reports unlinked.
    mockGetTelegramLinkStatus.mockResolvedValueOnce(baseTelegramStatus);
    await user.click(screen.getByRole("button", { name: "Disconnect" }));

    await waitFor(() => {
      expect(mockUnlinkTelegram).toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Link Telegram" })).toBeInTheDocument();
    });
  });

  it("reports an error when starting a Telegram link fails", async () => {
    arrangeHappyPathMocks();
    mockStartTelegramLink.mockRejectedValueOnce(new Error("TG link failed"));
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSettingsView(user);

    await user.click(screen.getByRole("button", { name: "Link Telegram" }));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("TG link failed");
    });
  });

  it("requires a code before claiming a Telegram link by code", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSettingsView(user);

    await user.click(screen.getByRole("button", { name: "Link by code" }));
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Enter the Telegram code.");
    });
    expect(mockClaimTelegramLinkCode).not.toHaveBeenCalled();
  });

  // --- Keyboard navigation shortcuts (n / d / l / w / Escape) ---

  it("navigates between views with single-key shortcuts", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();

    await user.keyboard("l");
    await waitFor(() => {
      expect(screen.getByTestId("workspace-title")).toHaveTextContent("Inbox");
    });
    (document.activeElement as HTMLElement | null)?.blur();

    await user.keyboard("w");
    await waitFor(() => expect(screen.getByTestId("workspace-title")).toHaveTextContent("Inbox"));
    (document.activeElement as HTMLElement | null)?.blur();

    await user.keyboard("d");
    await waitFor(() => expect(screen.getByTestId("workspace-title")).toHaveTextContent("Dictate"));
    (document.activeElement as HTMLElement | null)?.blur();

    // 'n' focuses the Inbox create pane.
    await user.keyboard("n");
    await waitFor(() => {
      expect(screen.getByTestId("workspace-title")).toHaveTextContent("Inbox");
      expect(screen.getByTestId("recording-title")).toBeInTheDocument();
    });
  });

  it("Escape closes the folder creator without deleting state", async () => {
    arrangeHappyPathMocks();
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();

    await user.click(screen.getByTestId("open-create-folder"));
    expect(screen.getByTestId("create-folder-form")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByTestId("create-folder-form")).not.toBeInTheDocument();
    });
  });

  // --- Recording status pills (processing + sanitized failure message) ---

  it("renders an in-progress status pill and a sanitized failure message", async () => {
    arrangeHappyPathMocks();
    mockListRecordings.mockResolvedValue([
      { ...baseRecording, id: "r-proc", title: "Working", status: "processing" },
      {
        ...baseRecording,
        id: "r-fail",
        title: "Broken",
        status: "failed",
        failure_message: 'Traceback (most recent call last): File "/var/app/x.py", line 3',
      },
    ]);
    mockListInbox.mockResolvedValue({
      rows: [
        recordingInboxRow({ ...baseRecording, id: "r-proc", title: "Working", status: "processing" }),
        recordingInboxRow({
          ...baseRecording,
          id: "r-fail",
          title: "Broken",
          status: "failed",
          failure_message: 'Traceback (most recent call last): File "/var/app/x.py", line 3',
        }),
      ],
      next_cursor: null,
      has_more: false,
    });
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await user.click(screen.getByTestId("tab-inbox"));

    await waitFor(() => {
      // "processing" status renders as a pill with the underscore stripped.
      expect(screen.getByTestId("select-recording-r-proc")).toHaveTextContent("processing");
      expect(screen.getByTestId("select-recording-r-fail")).toHaveTextContent("failed");
      expect(screen.getByTestId("select-recording-r-fail")).not.toHaveTextContent("Traceback");
    });
  });

  // --- Settings: dictation cleanup level update ---

  it("updates the dictation cleanup level and persists the setting", async () => {
    arrangeHappyPathMocks();
    mockUpdateSettings.mockResolvedValueOnce({
      ...baseSettings,
      dictation_post_filter_enabled: true,
      dictation_cleanup_level: "medium",
    });
    const user = userEvent.setup();

    render(<DashboardClient />);
    await waitForDashboardReady();
    await openSettingsView(user);

    const medium = await screen.findByRole("radio", { name: /medium/i });
    expect(medium).not.toBeChecked();

    await user.click(medium);
    await waitFor(() => {
      expect(mockUpdateSettings).toHaveBeenCalledWith({ dictation_cleanup_level: "medium" });
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Settings updated.");
    });
  });

  // --- Assign-to-folder error path reconciles via a refetch ---

  it("reverts and reports when assigning a recording to a folder fails", async () => {
    arrangeHappyPathMocks();
    mockListFolders.mockResolvedValue([
      { id: "folder-x", name: "Box", created_at: "2026-05-27T00:00:00Z" },
    ]);
    mockListRecordings.mockResolvedValue([
      { ...baseRecording, id: "rec-drag", title: "Drag me", folder_id: null },
    ]);
    mockAssignRecordingToFolder.mockRejectedValueOnce(new Error("Assign failed"));

    render(<DashboardClient />);
    await waitForDashboardReady();
    await waitFor(() => expect(screen.getByTestId("sidebar-folder-folder-x")).toBeInTheDocument());

    const target = screen.getByTestId("sidebar-folder-folder-x");
    const dataTransfer = {
      getData: vi.fn(() => "rec-drag"),
      setData: vi.fn(),
      dropEffect: "move",
      effectAllowed: "move",
    };
    const dropEvent = new Event("drop", { bubbles: true });
    Object.defineProperty(dropEvent, "dataTransfer", { value: dataTransfer, writable: false });
    target.dispatchEvent(dropEvent);

    await waitFor(() => {
      expect(mockAssignRecordingToFolder).toHaveBeenCalledWith("rec-drag", "folder-x");
      expect(screen.getByTestId("dashboard-message")).toHaveTextContent("Assign failed");
    });
    // listRecordings is called twice on the error path (initial + reconcile).
    expect(mockListRecordings.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
