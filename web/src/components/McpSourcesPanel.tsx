"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  createMcpIngestionConnection,
  listMcpIngestionConnections,
  syncMcpIngestionConnection,
  updateMcpIngestionConnection,
} from "@/lib/api";
import type { McpIngestionConnection } from "@/lib/types";

type Locale = "en" | "ru";

interface Copy {
  errLoad: string;
  errConnect: string;
  errUpdate: string;
  errSync: string;
  heading: string;
  note: string;
  nameLabel: string;
  urlLabel: string;
  tokenLabel: string;
  connecting: string;
  connect: string;
  loading: string;
  empty: string;
  paused: string;
  everyPrefix: string;
  minSuffix: string;
  sync: string;
  pause: string;
  resume: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    errLoad: "Couldn’t load connected sources.",
    errConnect: "Couldn’t connect that source.",
    errUpdate: "Couldn’t update that source.",
    errSync: "Couldn’t trigger a sync.",
    heading: "Connected sources",
    note: "Pull items from any MCP server into your brain (read-only). Wai syncs on a schedule; pause or sync a source any time.",
    nameLabel: "Source name",
    urlLabel: "Server URL",
    tokenLabel: "Auth token (optional)",
    connecting: "Connecting…",
    connect: "Connect",
    loading: "Loading…",
    empty: "No sources connected yet.",
    paused: "paused",
    everyPrefix: "every ",
    minSuffix: "m",
    sync: "Sync",
    pause: "Pause",
    resume: "Resume",
  },
  ru: {
    errLoad: "Не удалось загрузить подключённые источники.",
    errConnect: "Не удалось подключить источник.",
    errUpdate: "Не удалось обновить источник.",
    errSync: "Не удалось запустить синхронизацию.",
    heading: "Подключённые источники",
    note: "Подтягивайте материалы из любого MCP-сервера в свой мозг (только чтение). Wai синхронизирует по расписанию; источник можно поставить на паузу или синхронизировать в любой момент.",
    nameLabel: "Название источника",
    urlLabel: "URL сервера",
    tokenLabel: "Токен доступа (необязательно)",
    connecting: "Подключение…",
    connect: "Подключить",
    loading: "Загрузка…",
    empty: "Пока нет подключённых источников.",
    paused: "на паузе",
    everyPrefix: "каждые ",
    minSuffix: " мин",
    sync: "Синхр.",
    pause: "Пауза",
    resume: "Возобновить",
  },
};

/**
 * Connect-a-source: the inverse of exposing Wai as an MCP server — here Wai is
 * the CLIENT, pulling items from an external MCP server into the brain on a
 * schedule. Connect, pause/resume, or trigger a sync; errors surface (no silent
 * failure), and a server error is shown inline against its row.
 */
interface McpSourcesPanelProps {
  locale?: Locale;
}

export function McpSourcesPanel({ locale = "en" }: McpSourcesPanelProps) {
  const copy = COPY[locale];
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
      setError(err instanceof Error ? err.message : copy.errLoad);
      setSources([]);
    }
  }, [copy.errLoad]);

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
        setError(err instanceof Error ? err.message : copy.errConnect);
      } finally {
        setSubmitting(false);
      }
    },
    [label, url, token, submitting, load, copy.errConnect],
  );

  const handleToggle = useCallback(
    async (conn: McpIngestionConnection) => {
      setBusyId(conn.id);
      setError(null);
      try {
        await updateMcpIngestionConnection(conn.id, { enabled: !conn.enabled });
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : copy.errUpdate);
      } finally {
        setBusyId(null);
      }
    },
    [load, copy.errUpdate],
  );

  const handleSync = useCallback(
    async (id: string) => {
      setBusyId(id);
      setError(null);
      try {
        await syncMcpIngestionConnection(id);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : copy.errSync);
      } finally {
        setBusyId(null);
      }
    },
    [load, copy.errSync],
  );

  return (
    <div className="mcp-connections mcp-sources" data-testid="mcp-sources">
      <h4>{copy.heading}</h4>
      <p className="settings-note">{copy.note}</p>

      <form className="mcp-source-form" onSubmit={handleConnect}>
        <input
          aria-label={copy.nameLabel}
          placeholder={copy.nameLabel}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <input
          aria-label={copy.urlLabel}
          placeholder="https://example.com/mcp"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <input
          aria-label={copy.tokenLabel}
          placeholder={copy.tokenLabel}
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <button
          type="submit"
          className="primary-button compact-button"
          disabled={submitting || !label.trim() || !url.trim()}
        >
          {submitting ? copy.connecting : copy.connect}
        </button>
      </form>

      {error ? (
        <p className="mcp-connections-error" data-testid="mcp-sources-error" role="alert">
          {error}
        </p>
      ) : null}

      {sources === null ? (
        <p className="settings-note" data-testid="mcp-sources-loading">
          {copy.loading}
        </p>
      ) : sources.length === 0 ? (
        <p className="settings-note" data-testid="mcp-sources-empty">
          {copy.empty}
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
                  {conn.enabled ? conn.status : copy.paused}
                  {conn.last_error ? ` · ${conn.last_error}` : ""} · {copy.everyPrefix}
                  {conn.sync_interval_minutes}{copy.minSuffix}
                </span>
              </div>
              <div className="mcp-source-actions">
                <button
                  type="button"
                  className="ghost-button compact-button"
                  disabled={busyId === conn.id}
                  onClick={() => void handleSync(conn.id)}
                >
                  {copy.sync}
                </button>
                <button
                  type="button"
                  className="ghost-button compact-button"
                  disabled={busyId === conn.id}
                  onClick={() => void handleToggle(conn)}
                >
                  {conn.enabled ? copy.pause : copy.resume}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
