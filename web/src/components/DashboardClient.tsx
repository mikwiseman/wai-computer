"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  changePassword,
  createEntity,
  createRecording,
  deleteEntity,
  deleteRecording,
  fulltextSearch,
  generateSummary,
  getCurrentUser,
  getRecording,
  getSettings,
  getTranscriptionOptions,
  listActionItems,
  listEntities,
  listRecordings,
  logout,
  restoreRecording,
  search,
  semanticSearch,
  updateActionItem,
  updateSettings,
} from "@/lib/api";
import { GlobalQAPanel } from "@/components/GlobalQAPanel";
import { RecordingDetailPanel } from "@/components/RecordingDetailPanel";
import { AudioUpload } from "@/components/AudioUpload";
import { RecorderPanel } from "@/components/RecorderPanel";
import { ApiError } from "@/lib/http";
import type {
  ActionItem,
  Entity,
  Recording,
  RecordingDetail,
  RecordingType,
  SearchResponse,
  TranscriptionModelOption,
  TranscriptionOptions,
  User,
  UserSettings,
} from "@/lib/types";

type SearchMode = "hybrid" | "semantic" | "fts";
type DashboardView = "wai" | "library" | "trash" | "search" | "actions" | "topics" | "settings";
type DetailMode = "active" | "trash";

function formatError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

function formatDuration(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function typeLabel(type: RecordingType): string {
  return type.charAt(0).toUpperCase() + type.slice(1);
}

function statusText(recording: Recording): string | null {
  if (recording.failure_message) return recording.failure_message;
  if (!recording.status || recording.status === "ready") return null;
  return recording.status.replace("_", " ");
}

function modelOptionId(option: TranscriptionModelOption): string {
  return `${option.provider}:${option.model}`;
}

function splitModelOptionId(value: string): { provider: string; model: string } | null {
  const [provider, ...modelParts] = value.split(":");
  const model = modelParts.join(":");
  if (!provider || !model) return null;
  return { provider, model };
}

function selectedModelDescription(
  options: TranscriptionModelOption[],
  provider: string,
  model: string,
): string | null {
  return options.find((option) => option.provider === provider && option.model === model)?.description ?? null;
}

export function DashboardClient() {
  const router = useRouter();

  const [initializing, setInitializing] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);

  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [trashRecordings, setTrashRecordings] = useState<Recording[]>([]);
  const [recordingTitle, setRecordingTitle] = useState("");
  const [recordingType, setRecordingType] = useState<RecordingType>("note");
  const [selectedRecording, setSelectedRecording] = useState<RecordingDetail | null>(null);
  const [selectedMode, setSelectedMode] = useState<DetailMode>("active");

  const [searchMode, setSearchMode] = useState<SearchMode>("hybrid");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null);

  const [actionItems, setActionItems] = useState<ActionItem[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [entityName, setEntityName] = useState("");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [view, setView] = useState<DashboardView>("wai");
  const [accountSettings, setAccountSettings] = useState<UserSettings | null>(null);
  const [transcriptionOptions, setTranscriptionOptions] = useState<TranscriptionOptions | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsLoadedOnce, setSettingsLoadedOnce] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);

  const activeRecordingCount = recordings.length;
  const pendingActionCount = useMemo(
    () => actionItems.filter((item) => item.status !== "completed" && item.status !== "cancelled").length,
    [actionItems],
  );
  const accountHasPassword = user?.has_password !== false;

  async function loadRecordingsState() {
    const active = await listRecordings({ limit: 100 });
    setRecordings(active);
  }

  async function loadTrashRecordingsState() {
    const trashed = await listRecordings({ limit: 100, trashed: true });
    setTrashRecordings(trashed);
  }

  async function loadActionItemsState() {
    const response = await listActionItems({ limit: 100 });
    setActionItems(response);
  }

  async function loadEntitiesState() {
    const response = await listEntities();
    setEntities(response);
  }

  async function loadAccountSettings() {
    setSettingsLoading(true);
    try {
      const [settingsResponse, optionsResponse] = await Promise.all([
        getSettings(),
        getTranscriptionOptions(),
      ]);
      setAccountSettings(settingsResponse);
      setTranscriptionOptions(optionsResponse);
    } catch (error: unknown) {
      setMessage(formatError(error));
    } finally {
      setSettingsLoadedOnce(true);
      setSettingsLoading(false);
    }
  }

  async function initialize(options?: { preserveView?: boolean }) {
    const preserveView = options?.preserveView ?? false;
    try {
      if (preserveView) {
        setRefreshing(true);
      } else {
        setInitializing(true);
      }
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      await Promise.all([loadRecordingsState(), loadActionItemsState(), loadEntitiesState()]);
    } catch (error: unknown) {
      const text = formatError(error);
      if (error instanceof ApiError && error.status === 401) {
        router.replace("/login");
        return;
      }
      setMessage(text);
    } finally {
      setInitializing(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void initialize();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (view !== "settings" || settingsLoadedOnce || settingsLoading) return;
    void loadAccountSettings();
  }, [view, settingsLoadedOnce, settingsLoading]);

  async function handleCreateRecording(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    try {
      await createRecording({
        title: recordingTitle.length > 0 ? recordingTitle : null,
        type: recordingType,
        language: "multi",
      });
      setRecordingTitle("");
      await loadRecordingsState();
      setView("library");
      setMessage("Recording created.");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleSelectRecording(recordingId: string, mode: DetailMode = "active") {
    setMessage(null);
    try {
      const detail = await getRecording(recordingId);
      setSelectedRecording(detail);
      setSelectedMode(mode);
      setView(mode === "trash" ? "trash" : "library");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleDeleteRecording(recordingId: string, options?: { permanent?: boolean }) {
    setMessage(null);
    try {
      if (options) {
        await deleteRecording(recordingId, options);
      } else {
        await deleteRecording(recordingId);
      }
      if (selectedRecording?.id === recordingId) {
        setSelectedRecording(null);
      }
      await Promise.all([
        loadRecordingsState(),
        options?.permanent ? loadTrashRecordingsState() : Promise.resolve(),
        loadActionItemsState(),
      ]);
      setMessage(options?.permanent ? "Recording permanently deleted." : "Recording moved to trash.");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleRestoreRecording(recordingId: string) {
    setMessage(null);
    try {
      await restoreRecording(recordingId);
      if (selectedRecording?.id === recordingId) {
        setSelectedRecording(null);
      }
      await Promise.all([loadRecordingsState(), loadTrashRecordingsState()]);
      setMessage("Recording restored.");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleGenerateSummary(recordingId: string) {
    setMessage(null);
    try {
      await generateSummary(recordingId);
      const detail = await getRecording(recordingId);
      setSelectedRecording(detail);
      setSelectedMode("active");
      await loadActionItemsState();
      setMessage("Summary generated.");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchQuery.trim();
    setMessage(null);
    if (query.length === 0) {
      setSearchResponse(null);
      setMessage("Enter a search query.");
      return;
    }
    try {
      if (searchMode === "hybrid") {
        setSearchResponse(await search({ q: query, limit: 25, offset: 0 }));
        return;
      }
      if (searchMode === "semantic") {
        setSearchResponse(await semanticSearch({ q: query, limit: 25, threshold: 0.3 }));
        return;
      }
      setSearchResponse(await fulltextSearch({ q: query, limit: 25, offset: 0 }));
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleUpdateAction(itemId: string, status: ActionItem["status"]) {
    setMessage(null);
    try {
      await updateActionItem(itemId, { status });
      await loadActionItemsState();
      setMessage("Action item updated.");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleCreateEntity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    try {
      await createEntity({ type: "topic", name: entityName, metadata: { source: "web" } });
      setEntityName("");
      await loadEntitiesState();
      setMessage("Entity created.");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleDeleteEntity(entityId: string) {
    setMessage(null);
    try {
      await deleteEntity(entityId);
      await loadEntitiesState();
      setMessage("Entity deleted.");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleChangePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    try {
      const response = await changePassword(accountHasPassword ? currentPassword : "", newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setUser((current) => current ? { ...current, has_password: true } : current);
      setMessage(response.message);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleUpdateAccountSettings(patch: Partial<UserSettings>) {
    setMessage(null);
    setSettingsSaving(true);
    try {
      const updated = await updateSettings(patch);
      setAccountSettings(updated);
      setMessage("Settings updated.");
    } catch (error: unknown) {
      setMessage(formatError(error));
    } finally {
      setSettingsSaving(false);
    }
  }

  async function handleLogout() {
    setMessage(null);
    try {
      await logout();
      router.replace("/login");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  if (initializing) {
    return (
      <div className="loading-screen">
        <p data-testid="dashboard-loading">Loading dashboard...</p>
      </div>
    );
  }

  const navigation = [
    { key: "wai", label: "Wai", detail: "Ask across notes", count: null },
    { key: "library", label: "All Recordings", detail: "Library", count: activeRecordingCount },
    { key: "trash", label: "Trash", detail: "Recently removed", count: trashRecordings.length },
    { key: "search", label: "Search", detail: "Transcript lookup", count: null },
    { key: "actions", label: "Action Items", detail: "Follow-ups", count: pendingActionCount },
    { key: "topics", label: "Topics", detail: "Entities", count: entities.length },
    { key: "settings", label: "Settings", detail: "Account", count: null },
  ] as const;

  return (
    <div className="web-app-shell">
      <aside className="app-sidebar" aria-label="WaiSay navigation">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true" />
          <div>
            <h1>WaiSay</h1>
            <p data-testid="user-email">{user?.email ?? "No user"}</p>
          </div>
        </div>

        <nav className="sidebar-nav">
          {navigation.map((item) => (
            <button
              key={item.key}
              data-testid={`tab-${item.key}`}
              type="button"
              className="sidebar-nav__item"
              aria-current={view === item.key ? "page" : undefined}
              onClick={() => {
                setView(item.key);
                if (item.key === "trash") {
                  void loadTrashRecordingsState();
                }
              }}
            >
              <span>
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
              </span>
              {item.count !== null ? <em>{item.count}</em> : null}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button
            data-testid="reload-dashboard"
            type="button"
            className="ghost-button"
            onClick={() => void initialize({ preserveView: true })}
            disabled={refreshing}
          >
            {refreshing ? "Reloading..." : "Reload"}
          </button>
          <button data-testid="logout-button" type="button" className="ghost-button" onClick={handleLogout}>
            Logout
          </button>
        </div>
      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div>
            <h2>{navigation.find((item) => item.key === view)?.label ?? "WaiSay"}</h2>
          </div>
          {refreshing ? <p data-testid="dashboard-refreshing">Refreshing dashboard...</p> : null}
        </header>

        {message ? (
          <p className="dashboard-message" data-testid="dashboard-message" role="status">
            {message}
          </p>
        ) : null}

        {view === "wai" ? <WaiView recordings={recordings} /> : null}
        {view === "library" ? renderLibrary("active", recordings) : null}
        {view === "trash" ? renderLibrary("trash", trashRecordings) : null}
        {view === "search" ? renderSearchView() : null}
        {view === "actions" ? renderActionsView() : null}
        {view === "topics" ? renderTopicsView() : null}
        {view === "settings" ? renderSettingsView() : null}
      </main>
    </div>
  );

  function renderLibrary(mode: DetailMode, items: Recording[]) {
    const isTrash = mode === "trash";
    const title = isTrash ? "Trash" : "All Recordings";

    return (
      <div className="library-grid">
        <section className="recording-list-panel" aria-label={title}>
          <header className="panel-header">
            <div>
              <h3>{title}</h3>
              <p>{items.length} {items.length === 1 ? "recording" : "recordings"}</p>
            </div>
            {!isTrash ? (
              <button
                type="button"
                className="ghost-button compact-button"
                onClick={() => {
                  setSelectedRecording(null);
                  setSelectedMode("active");
                }}
              >
                New
              </button>
            ) : null}
          </header>

          {items.length === 0 ? (
            <div className="empty-state">
              <h3>{isTrash ? "Trash is Empty" : "No Recordings"}</h3>
              <p>{isTrash ? "Deleted recordings will appear here." : "Record in the browser or import an audio file."}</p>
            </div>
          ) : (
            <ul className="recording-list" data-testid="recording-list">
              {items.map((recording) => (
                <li key={recording.id}>
                  <button
                    type="button"
                    className="recording-row"
                    aria-current={selectedRecording?.id === recording.id && selectedMode === mode ? "true" : undefined}
                    onClick={() => void handleSelectRecording(recording.id, mode)}
                    data-testid={`select-recording-${recording.id}`}
                  >
                    <span className="recording-row__main">
                      <strong>{recording.title ?? "(untitled)"}</strong>
                      <small>
                        {typeLabel(recording.type)} / {formatDate(recording.created_at)}
                        {recording.duration_seconds ? ` / ${formatDuration(recording.duration_seconds)}` : ""}
                      </small>
                    </span>
                    {statusText(recording) ? <span className="status-pill">{statusText(recording)}</span> : null}
                  </button>

                  {!isTrash ? (
                    <div className="row-actions">
                      <button
                        type="button"
                        className="ghost-button compact-button"
                        onClick={() => void handleGenerateSummary(recording.id)}
                        data-testid={`generate-summary-${recording.id}`}
                      >
                        Summarize
                      </button>
                      <button
                        type="button"
                        className="ghost-button compact-button danger-button"
                        onClick={() => void handleDeleteRecording(recording.id)}
                        data-testid={`delete-recording-${recording.id}`}
                      >
                        Trash
                      </button>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="recording-detail-area" aria-label="Recording detail">
          {selectedRecording && selectedMode === mode ? (
            <RecordingDetailPanel
              recording={selectedRecording}
              mode={mode}
              onRecordingUpdate={setSelectedRecording}
              onRestore={(recordingId) => void handleRestoreRecording(recordingId)}
              onDelete={(recordingId) => void handleDeleteRecording(recordingId, { permanent: isTrash })}
            />
          ) : isTrash ? (
            <div className="empty-state empty-state--center">
              <h3>Select a Recording</h3>
              <p>Choose a trashed recording to restore or delete it permanently.</p>
            </div>
          ) : (
            <NewRecordingPane
              title={recordingTitle}
              type={recordingType}
              onTitleChange={setRecordingTitle}
              onTypeChange={setRecordingType}
              onSubmit={handleCreateRecording}
              onComplete={async (detail) => {
                setSelectedRecording(detail);
                setSelectedMode("active");
                await loadRecordingsState();
              }}
              onError={setMessage}
            />
          )}
        </section>
      </div>
    );
  }

  function renderSearchView() {
    return (
      <section className="tool-panel">
        <form className="search-form" onSubmit={handleSearch}>
          <input
            data-testid="search-query"
            placeholder="Search recordings..."
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
          <select
            data-testid="search-mode"
            value={searchMode}
            onChange={(event) => {
              setSearchMode(event.target.value as SearchMode);
              setSearchResponse(null);
            }}
          >
            <option value="hybrid">Hybrid</option>
            <option value="semantic">Semantic</option>
            <option value="fts">Full text</option>
          </select>
          <button data-testid="search-submit" type="submit">
            Search
          </button>
        </form>

        <p data-testid="search-total" className="muted-text">Total: {searchResponse?.total ?? 0}</p>
        {searchResponse?.results && searchResponse.results.length > 0 ? (
          <ul className="search-results" data-testid="search-results">
            {searchResponse.results.map((result) => (
              <li key={result.segment_id} data-testid={`search-result-${result.segment_id}`}>
                <strong>{result.recording_title ?? "(untitled)"}</strong>
                <p>{result.content}</p>
                <div className="search-result-footer">
                  <small>
                    {result.speaker ? `${result.speaker} / ` : ""}Score {result.score.toFixed(2)}
                  </small>
                  <button
                    type="button"
                    className="ghost-button compact-button"
                    onClick={() => void handleSelectRecording(result.recording_id)}
                  >
                    Open
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : searchResponse && searchResponse.total === 0 ? (
          <div className="empty-state" data-testid="search-no-results">
            <h3>No Results</h3>
            <p>No matching transcript segments found.</p>
          </div>
        ) : null}
      </section>
    );
  }

  function renderActionsView() {
    return (
      <section className="tool-panel">
        {actionItems.length === 0 ? (
          <div className="empty-state">
            <h3>No Action Items</h3>
            <p>Generated follow-ups will appear here after summaries are created.</p>
          </div>
        ) : (
          <ul className="action-list" data-testid="action-item-list">
            {actionItems.map((item) => (
              <li key={item.id} className="action-list__item">
                <div>
                  <strong>{item.task}</strong>
                  <p className="metadata-row">
                    <span>{item.status.replace("_", " ")}</span>
                    {item.priority ? <span>{item.priority}</span> : null}
                    {item.owner ? <span>{item.owner}</span> : null}
                  </p>
                </div>
                <div className="row-actions">
                  <button
                    type="button"
                    data-testid={`set-complete-${item.id}`}
                    className="ghost-button compact-button"
                    onClick={() => void handleUpdateAction(item.id, "completed")}
                  >
                    Complete
                  </button>
                  <button
                    type="button"
                    data-testid={`set-pending-${item.id}`}
                    className="ghost-button compact-button"
                    onClick={() => void handleUpdateAction(item.id, "pending")}
                  >
                    Pending
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  function renderTopicsView() {
    return (
      <section className="tool-panel">
        <form className="search-form" onSubmit={handleCreateEntity}>
          <input
            data-testid="entity-name"
            placeholder="Topic name"
            value={entityName}
            onChange={(event) => setEntityName(event.target.value)}
            required
          />
          <button data-testid="create-entity" type="submit">
            Create topic
          </button>
        </form>
        <ul className="topic-list" data-testid="entity-list">
          {entities.map((entity) => (
            <li key={entity.id}>
              <span>{entity.name}</span>
              <button
                type="button"
                className="ghost-button compact-button danger-button"
                onClick={() => void handleDeleteEntity(entity.id)}
                data-testid={`delete-entity-${entity.id}`}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      </section>
    );
  }

  function renderModelSelect({
    label,
    options,
    provider,
    model,
    buildPatch,
    testId,
  }: {
    label: string;
    options: TranscriptionModelOption[];
    provider: string;
    model: string;
    buildPatch: (selection: { provider: string; model: string }) => Partial<UserSettings>;
    testId: string;
  }) {
    const value = `${provider}:${model}`;
    const description = selectedModelDescription(options, provider, model);

    return (
      <label className="settings-model-field">
        <span>{label}</span>
        <select
          data-testid={testId}
          value={value}
          disabled={settingsSaving}
          onChange={(event) => {
            const selection = splitModelOptionId(event.target.value);
            if (!selection) return;
            void handleUpdateAccountSettings(buildPatch(selection));
          }}
        >
          {options.map((option) => (
            <option key={modelOptionId(option)} value={modelOptionId(option)}>
              {option.label}
            </option>
          ))}
        </select>
        {description ? <small>{description}</small> : null}
      </label>
    );
  }

  function renderSettingsView() {
    return (
      <section className="tool-panel settings-panel">
        <div className="settings-form">
          <h3>Transcription</h3>
          {settingsLoading ? <p className="settings-note">Loading account model settings...</p> : null}
          {accountSettings && transcriptionOptions ? (
            <>
              {renderModelSelect({
                label: "Dictation live model",
                options: transcriptionOptions.dictation_live_stt,
                provider: accountSettings.dictation_live_stt_provider,
                model: accountSettings.dictation_live_stt_model,
                testId: "dictation-live-stt-model",
                buildPatch: (selection) => ({
                  dictation_live_stt_provider: selection.provider,
                  dictation_live_stt_model: selection.model,
                }),
              })}
              {renderModelSelect({
                label: "Recording live model",
                options: transcriptionOptions.recording_live_stt,
                provider: accountSettings.recording_live_stt_provider,
                model: accountSettings.recording_live_stt_model,
                testId: "recording-live-stt-model",
                buildPatch: (selection) => ({
                  recording_live_stt_provider: selection.provider,
                  recording_live_stt_model: selection.model,
                }),
              })}
              {renderModelSelect({
                label: "Full session model",
                options: transcriptionOptions.file_stt,
                provider: accountSettings.file_stt_provider,
                model: accountSettings.file_stt_model,
                testId: "file-stt-model",
                buildPatch: (selection) => ({
                  file_stt_provider: selection.provider,
                  file_stt_model: selection.model,
                }),
              })}
              <label className="settings-checkbox-field">
                <input
                  type="checkbox"
                  checked={accountSettings.dictation_post_filter_enabled}
                  disabled={settingsSaving}
                  onChange={(event) =>
                    void handleUpdateAccountSettings({
                      dictation_post_filter_enabled: event.target.checked,
                    })
                  }
                />
                <span>Post-filter dictated text</span>
              </label>
              {accountSettings.dictation_post_filter_enabled
                ? renderModelSelect({
                    label: "Post-filter model",
                    options: transcriptionOptions.dictation_post_filter,
                    provider: accountSettings.dictation_post_filter_provider,
                    model: accountSettings.dictation_post_filter_model,
                    testId: "dictation-post-filter-model",
                    buildPatch: (selection) => ({
                      dictation_post_filter_provider: selection.provider,
                      dictation_post_filter_model: selection.model,
                    }),
                  })
                : null}
            </>
          ) : settingsLoadedOnce && !settingsLoading ? (
            <button type="button" className="ghost-button compact-button" onClick={() => void loadAccountSettings()}>
              Retry loading model settings
            </button>
          ) : null}
        </div>

        <form className="settings-form" onSubmit={handleChangePassword}>
          <h3>Account</h3>
          {!accountHasPassword ? (
            <p className="settings-note" data-testid="set-password-note">
              You signed in with a magic link. Set a password to use email and password login.
            </p>
          ) : (
            <label>
              <span>Current password</span>
              <input
                data-testid="current-password"
                type="password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                required
              />
            </label>
          )}
          <label>
            <span>New password</span>
            <input
              data-testid="new-password"
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              required
            />
          </label>
          <button data-testid="change-password" type="submit">
            {accountHasPassword ? "Change password" : "Set password"}
          </button>
        </form>
      </section>
    );
  }
}

function WaiView({ recordings }: { recordings: Recording[] }) {
  return (
    <div className="wai-panel">
      <GlobalQAPanel recordings={recordings} />
    </div>
  );
}

function NewRecordingPane({
  title,
  type,
  onTitleChange,
  onTypeChange,
  onSubmit,
  onComplete,
  onError,
}: {
  title: string;
  type: RecordingType;
  onTitleChange: (value: string) => void;
  onTypeChange: (value: RecordingType) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onComplete: (detail: RecordingDetail) => void | Promise<void>;
  onError: (message: string) => void;
}) {
  return (
    <section className="new-recording-panel">
      <div className="new-recording-panel__intro">
        <div className="app-glyph" aria-hidden="true" />
        <h3>New Recording</h3>
      </div>

      <div className="recording-options">
        <RecorderPanel onRecordingComplete={onComplete} onError={onError} />
        <AudioUpload onUploadComplete={onComplete} onError={onError} />
      </div>

      <form className="manual-note-form" onSubmit={onSubmit}>
        <input
          data-testid="recording-title"
          placeholder="Create an empty note..."
          value={title}
          onChange={(event) => onTitleChange(event.target.value)}
        />
        <select
          data-testid="recording-type"
          value={type}
          onChange={(event) => onTypeChange(event.target.value as RecordingType)}
        >
          <option value="note">Note</option>
          <option value="meeting">Meeting</option>
          <option value="reflection">Reflection</option>
        </select>
        <button data-testid="create-recording" type="submit">
          Create
        </button>
      </form>
    </section>
  );
}
