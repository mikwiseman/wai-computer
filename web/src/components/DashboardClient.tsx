"use client";

import { FormEvent, useEffect, useState } from "react";
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
  listActionItems,
  listEntities,
  listRecordings,
  logout,
  search,
  semanticSearch,
  updateActionItem,
} from "@/lib/api";
import { ChatPanel } from "@/components/ChatPanel";
import { ApiError } from "@/lib/http";
import type {
  ActionItem,
  Entity,
  Recording,
  RecordingDetail,
  RecordingType,
  SearchResponse,
  User,
} from "@/lib/types";

type SearchMode = "hybrid" | "semantic" | "fts";

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unexpected error";
}

export function DashboardClient() {
  const router = useRouter();

  const [initializing, setInitializing] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);

  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [recordingTitle, setRecordingTitle] = useState("");
  const [recordingType, setRecordingType] = useState<RecordingType>("note");
  const [selectedRecording, setSelectedRecording] = useState<RecordingDetail | null>(null);

  const [searchMode, setSearchMode] = useState<SearchMode>("hybrid");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null);

  const [actionItems, setActionItems] = useState<ActionItem[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [entityName, setEntityName] = useState("");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  async function loadRecordingsState() {
    const response = await listRecordings({ limit: 50 });
    setRecordings(response);
  }

  async function loadActionItemsState() {
    const response = await listActionItems({ limit: 50 });
    setActionItems(response);
  }

  async function loadEntitiesState() {
    const response = await listEntities();
    setEntities(response);
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
      setMessage("Recording created.");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleSelectRecording(recordingId: string) {
    setMessage(null);
    try {
      const detail = await getRecording(recordingId);
      setSelectedRecording(detail);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleDeleteRecording(recordingId: string) {
    setMessage(null);
    try {
      await deleteRecording(recordingId);
      if (selectedRecording?.id === recordingId) {
        setSelectedRecording(null);
      }
      await Promise.all([loadRecordingsState(), loadActionItemsState()]);
      setMessage("Recording deleted.");
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
      await loadActionItemsState();
      setMessage("Summary generated.");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    try {
      if (searchMode === "hybrid") {
        setSearchResponse(await search({ q: searchQuery, limit: 25, offset: 0 }));
        return;
      }
      if (searchMode === "semantic") {
        setSearchResponse(await semanticSearch({ q: searchQuery, limit: 25, threshold: 0.3 }));
        return;
      }
      setSearchResponse(await fulltextSearch({ q: searchQuery, limit: 25, offset: 0 }));
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
      const response = await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setMessage(response.message);
    } catch (error: unknown) {
      setMessage(formatError(error));
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
    return <p data-testid="dashboard-loading">Loading dashboard...</p>;
  }

  return (
    <div className="stack">
      <header className="card row">
        <div>
          <h1>WaiComputer Web</h1>
          <p data-testid="user-email">{user?.email ?? "No user"}</p>
          {refreshing ? <p data-testid="dashboard-refreshing">Refreshing dashboard...</p> : null}
        </div>
        <div className="row">
          <button
            data-testid="reload-dashboard"
            type="button"
            onClick={() => void initialize({ preserveView: true })}
            disabled={refreshing}
          >
            {refreshing ? "Reloading..." : "Reload"}
          </button>
          <button data-testid="logout-button" type="button" onClick={handleLogout}>
            Logout
          </button>
        </div>
      </header>

      {message ? (
        <p data-testid="dashboard-message" role="status">
          {message}
        </p>
      ) : null}

      <section className="card stack">
        <h2>Recordings</h2>
        <form className="row" onSubmit={handleCreateRecording}>
          <input
            data-testid="recording-title"
            placeholder="Recording title"
            value={recordingTitle}
            onChange={(event) => setRecordingTitle(event.target.value)}
          />
          <select
            data-testid="recording-type"
            value={recordingType}
            onChange={(event) => setRecordingType(event.target.value as RecordingType)}
          >
            <option value="note">note</option>
            <option value="meeting">meeting</option>
            <option value="reflection">reflection</option>
          </select>
          <button data-testid="create-recording" type="submit">
            Create
          </button>
        </form>
        <ul data-testid="recording-list">
          {recordings.map((recording) => (
            <li key={recording.id} className="row">
              <button
                type="button"
                onClick={() => handleSelectRecording(recording.id)}
                data-testid={`select-recording-${recording.id}`}
              >
                {recording.title ?? "(untitled)"} [{recording.type}]
              </button>
              <button
                type="button"
                onClick={() => handleGenerateSummary(recording.id)}
                data-testid={`generate-summary-${recording.id}`}
              >
                Generate summary
              </button>
              <button
                type="button"
                onClick={() => handleDeleteRecording(recording.id)}
                data-testid={`delete-recording-${recording.id}`}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      </section>

      {selectedRecording ? (
        <section className="card stack" data-testid="recording-detail">
          <h2>{selectedRecording.title ?? "(untitled recording)"}</h2>
          <p>Segments: {selectedRecording.segments.length}</p>
          <p>Actions: {selectedRecording.action_items.length}</p>
          <p>Summary: {selectedRecording.summary?.summary ?? "Not generated"}</p>
        </section>
      ) : null}

      <section className="card stack">
        <h2>Search</h2>
        <form className="row" onSubmit={handleSearch}>
          <input
            data-testid="search-query"
            placeholder="Search query"
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
            <option value="hybrid">hybrid</option>
            <option value="semantic">semantic</option>
            <option value="fts">fts</option>
          </select>
          <button data-testid="search-submit" type="submit">
            Search
          </button>
        </form>
        <p data-testid="search-total">Total: {searchResponse?.total ?? 0}</p>
        {searchResponse?.results && searchResponse.results.length > 0 ? (
          <ul data-testid="search-results">
            {searchResponse.results.map((result) => (
              <li key={result.segment_id} data-testid={`search-result-${result.segment_id}`}>
                <strong>{result.recording_title ?? "(untitled)"}</strong>
                {" "}
                <span>{result.content}</span>
                {result.speaker ? <small> — {result.speaker}</small> : null}
                <small> (score: {result.score.toFixed(2)})</small>
              </li>
            ))}
          </ul>
        ) : searchResponse && searchResponse.total === 0 ? (
          <p data-testid="search-no-results">No results found.</p>
        ) : null}
      </section>

      <ChatPanel recordings={recordings} />

      <section className="card stack">
        <h2>Action Items</h2>
        <ul data-testid="action-item-list">
          {actionItems.map((item) => (
            <li key={item.id} className="row">
              <span>{item.task}</span>
              <span>{item.status}</span>
              <button
                type="button"
                data-testid={`set-complete-${item.id}`}
                onClick={() => handleUpdateAction(item.id, "completed")}
              >
                Complete
              </button>
              <button
                type="button"
                data-testid={`set-pending-${item.id}`}
                onClick={() => handleUpdateAction(item.id, "pending")}
              >
                Pending
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="card stack">
        <h2>Entities</h2>
        <form className="row" onSubmit={handleCreateEntity}>
          <input
            data-testid="entity-name"
            placeholder="Entity name"
            value={entityName}
            onChange={(event) => setEntityName(event.target.value)}
            required
          />
          <button data-testid="create-entity" type="submit">
            Create topic
          </button>
        </form>
        <ul data-testid="entity-list">
          {entities.map((entity) => (
            <li key={entity.id} className="row">
              <span>{entity.name}</span>
              <button
                type="button"
                onClick={() => handleDeleteEntity(entity.id)}
                data-testid={`delete-entity-${entity.id}`}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="card stack">
        <h2>Settings</h2>
        <form className="row" onSubmit={handleChangePassword}>
          <input
            data-testid="current-password"
            type="password"
            placeholder="Current password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            required
          />
          <input
            data-testid="new-password"
            type="password"
            placeholder="New password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            required
          />
          <button data-testid="change-password" type="submit">
            Change password
          </button>
        </form>
      </section>
    </div>
  );
}
