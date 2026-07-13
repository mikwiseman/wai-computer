"use client";

import { useCallback, useEffect, useState } from "react";

import { listMcpConnections, revokeMcpConnection } from "@/lib/api";
import type { McpConnection } from "@/lib/types";

type Locale = "en" | "ru";

interface Copy {
  never: string;
  errLoad: string;
  errRevoke: string;
  confirmRevoke: string;
  cancel: string;
  heading: string;
  note: string;
  loading: string;
  empty: string;
  lastActive: string;
  revoking: string;
  revoke: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    never: "never",
    errLoad: "Couldn’t load connected clients.",
    errRevoke: "Couldn’t revoke that client.",
    confirmRevoke: "Revoke now",
    cancel: "Cancel",
    heading: "Connected clients",
    note: "Apps you’ve approved to read your library — and, where you granted it (the “memory write” badge), to save memories too. Revoke any you no longer use — access is cut off on wai.computer immediately.",
    loading: "Loading…",
    empty: "No clients connected yet.",
    lastActive: "last active",
    revoking: "Revoking…",
    revoke: "Revoke",
  },
  ru: {
    never: "никогда",
    errLoad: "Не удалось загрузить подключённые клиенты.",
    errRevoke: "Не удалось отозвать доступ клиента.",
    confirmRevoke: "Точно отозвать",
    cancel: "Отмена",
    heading: "Подключённые клиенты",
    note: "Приложения, которым вы разрешили читать вашу библиотеку — а где вы дали право (значок «memory write») — и сохранять память. Отзовите те, которыми больше не пользуетесь — доступ на wai.computer прекращается сразу.",
    loading: "Загрузка…",
    empty: "Пока нет подключённых клиентов.",
    lastActive: "последняя активность",
    revoking: "Отзыв…",
    revoke: "Отозвать",
  },
};

function formatDate(value: string | null, never: string): string {
  if (!value) return never;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return never;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

interface McpConnectionsListProps {
  locale?: Locale;
}

export function McpConnectionsList({ locale = "en" }: McpConnectionsListProps) {
  const copy = COPY[locale];
  const [connections, setConnections] = useState<McpConnection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [confirmingRevoke, setConfirmingRevoke] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setConnections(await listMcpConnections());
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.errLoad);
      setConnections([]);
    }
  }, [copy.errLoad]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleRevoke(clientId: string) {
    setConfirmingRevoke(null);
    setRevoking(clientId);
    setError(null);
    try {
      await revokeMcpConnection(clientId);
      setConnections((current) => (current ?? []).filter((c) => c.client_id !== clientId));
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.errRevoke);
    } finally {
      setRevoking(null);
    }
  }

  return (
    <div className="mcp-connections" data-testid="mcp-connections">
      <h4>{copy.heading}</h4>
      <p className="settings-note">{copy.note}</p>

      {error ? (
        <p className="mcp-connections-error" data-testid="mcp-connections-error" role="alert">
          {error}
        </p>
      ) : null}

      {connections === null ? (
        <p className="settings-note" data-testid="mcp-connections-loading">
          {copy.loading}
        </p>
      ) : connections.length === 0 ? (
        <p className="settings-note" data-testid="mcp-connections-empty">
          {copy.empty}
        </p>
      ) : (
        <ul className="mcp-connection-rows">
          {connections.map((connection) => (
            <li
              key={connection.client_id}
              className="mcp-connection-row"
              data-testid={`mcp-connection-${connection.client_id}`}
            >
              <div className="mcp-connection-meta">
                <span className="mcp-connection-name">
                  {connection.client_name}
                  {connection.scopes?.includes("mcp:write") ? (
                    <span
                      className="api-key-scope-badge"
                      data-testid={`mcp-connection-write-${connection.client_id}`}
                    >
                      memory write
                    </span>
                  ) : null}
                </span>
                <span className="mcp-connection-detail">
                  {connection.scopes.join(", ")} · {copy.lastActive}{" "}
                  {formatDate(connection.last_active_at, copy.never)}
                </span>
              </div>
              {confirmingRevoke === connection.client_id ? (
                <span className="row-actions">
                  <button
                    type="button"
                    className="ghost-button compact-button"
                    data-testid={`mcp-revoke-cancel-${connection.client_id}`}
                    onClick={() => setConfirmingRevoke(null)}
                  >
                    {copy.cancel}
                  </button>
                  <button
                    type="button"
                    className="ghost-button compact-button danger-button"
                    data-testid={`mcp-revoke-confirm-${connection.client_id}`}
                    disabled={revoking === connection.client_id}
                    onClick={() => void handleRevoke(connection.client_id)}
                  >
                    {revoking === connection.client_id ? copy.revoking : copy.confirmRevoke}
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  className="ghost-button compact-button danger-button"
                  data-testid={`mcp-revoke-${connection.client_id}`}
                  disabled={revoking === connection.client_id}
                  onClick={() => setConfirmingRevoke(connection.client_id)}
                >
                  {revoking === connection.client_id ? copy.revoking : copy.revoke}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
