"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  createMcpIngestionConnection,
  listMcpIngestionConnections,
  syncMcpIngestionConnection,
  updateMcpIngestionConnection,
} from "@/lib/api";
import type { McpIngestionConnection } from "@/lib/types";

/**
 * Connect-a-source: the inverse of exposing Wai as an MCP server — here Wai is
 * the CLIENT, pulling items from an external MCP server into the brain on a
 * schedule. Connect, pause/resume, or trigger a sync; errors surface (no silent
 * failure), and a server error is shown inline against its row.
 */
export function McpSourcesPanel() {
  const [sources, setSources] = useState<McpIngestionConnection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setSources(await listMcpIngestionConnections());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t load connected sources.");
      setSources([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleConnect = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const serverLabel = label.trim();
      const serverUrl = url.trim();
      if (submitting || !serverLabel || !serverUrl) return;
      setSubmitting(true);
      setError(null);
      try {
        const authToken = token.trim() || null;
        await createMcpIngestionConnection({
          server_label: serverLabel,
          server_url: serverUrl,
          auth_token: authToken,
          auth_type: authToken ? "bearer" : "none",
        });
        setLabel("");
        setUrl("");
        setToken("");
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Couldn’t connect that source.");
      } finally {
        setSubmitting(false);
      }
    },
    [label, url, token, submitting, load],
  );

  const handleToggle = useCallback(
    async (conn: McpIngestionConnection) => {
      setBusyId(conn.id);
      setError(null);
      try {
        await updateMcpIngestionConnection(conn.id, { enabled: !conn.enabled });
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Couldn’t update that source.");
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  const handleSync = useCallback(
    async (id: string) => {
      setBusyId(id);
      setError(null);
      try {
        await syncMcpIngestionConnection(id);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Couldn’t trigger a sync.");
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  return (
    <div className="mcp-connections mcp-sources" data-testid="mcp-sources">
      <h4>Connected sources</h4>
      <p className="settings-note">
        Pull items from any MCP server into your brain (read-only). Wai syncs on a
        schedule; pause or sync a source any time.
      </p>

      <form className="mcp-source-form" onSubmit={handleConnect}>
        <input
          aria-label="Source name"
          placeholder="Source name"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <input
          aria-label="Server URL"
          placeholder="https://example.com/mcp"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <input
          aria-label="Auth token (optional)"
          placeholder="Auth token (optional)"
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <button
          type="submit"
          className="primary-button compact-button"
          disabled={submitting || !label.trim() || !url.trim()}
        >
          {submitting ? "Connecting…" : "Connect"}
        </button>
      </form>

      {error ? (
        <p className="mcp-connections-error" data-testid="mcp-sources-error" role="alert">
          {error}
        </p>
      ) : null}

      {sources === null ? (
        <p className="settings-note" data-testid="mcp-sources-loading">
          Loading…
        </p>
      ) : sources.length === 0 ? (
        <p className="settings-note" data-testid="mcp-sources-empty">
          No sources connected yet.
        </p>
      ) : (
        <ul className="mcp-connection-rows">
          {sources.map((conn) => (
            <li
              key={conn.id}
              className="mcp-connection-row"
              data-testid={`mcp-source-${conn.id}`}
            >
              <div className="mcp-connection-meta">
                <span className="mcp-connection-name">{conn.server_label}</span>
                <span className="mcp-connection-detail">
                  {conn.enabled ? conn.status : "paused"}
                  {conn.last_error ? ` · ${conn.last_error}` : ""} · every{" "}
                  {conn.sync_interval_minutes}m
                </span>
              </div>
              <div className="mcp-source-actions">
                <button
                  type="button"
                  className="ghost-button compact-button"
                  disabled={busyId === conn.id}
                  onClick={() => void handleSync(conn.id)}
                >
                  Sync
                </button>
                <button
                  type="button"
                  className="ghost-button compact-button"
                  disabled={busyId === conn.id}
                  onClick={() => void handleToggle(conn)}
                >
                  {conn.enabled ? "Pause" : "Resume"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
