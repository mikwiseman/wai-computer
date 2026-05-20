"use client";

import { useCallback, useEffect, useState } from "react";

import { listMcpConnections, revokeMcpConnection } from "@/lib/api";
import type { McpConnection } from "@/lib/types";

function formatDate(value: string | null): string {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "never";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function McpConnectionsList() {
  const [connections, setConnections] = useState<McpConnection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setConnections(await listMcpConnections());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t load connected clients.");
      setConnections([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleRevoke(clientId: string) {
    setRevoking(clientId);
    setError(null);
    try {
      await revokeMcpConnection(clientId);
      setConnections((current) => (current ?? []).filter((c) => c.client_id !== clientId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t revoke that client.");
    } finally {
      setRevoking(null);
    }
  }

  return (
    <div className="mcp-connections" data-testid="mcp-connections">
      <h4>Connected clients</h4>
      <p className="settings-note">
        Apps you’ve approved for read-only access to your library. Revoke any you no longer use —
        access is cut off on wai.computer immediately.
      </p>

      {error ? (
        <p className="mcp-connections-error" data-testid="mcp-connections-error" role="alert">
          {error}
        </p>
      ) : null}

      {connections === null ? (
        <p className="settings-note" data-testid="mcp-connections-loading">
          Loading…
        </p>
      ) : connections.length === 0 ? (
        <p className="settings-note" data-testid="mcp-connections-empty">
          No clients connected yet.
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
                <span className="mcp-connection-name">{connection.client_name}</span>
                <span className="mcp-connection-detail">
                  {connection.scopes.join(", ")} · last active {formatDate(connection.last_active_at)}
                </span>
              </div>
              <button
                type="button"
                className="ghost-button compact-button"
                data-testid={`mcp-revoke-${connection.client_id}`}
                disabled={revoking === connection.client_id}
                onClick={() => void handleRevoke(connection.client_id)}
              >
                {revoking === connection.client_id ? "Revoking…" : "Revoke"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
