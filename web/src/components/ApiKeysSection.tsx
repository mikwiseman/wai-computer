"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import { createApiKey, listApiKeys, revokeApiKey } from "@/lib/api";
import type { ApiKey, ApiKeyCreated } from "@/lib/types";

function formatDate(value: string | null): string {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "never";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

async function copyText(value: string): Promise<boolean> {
  if (!navigator.clipboard?.writeText) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}

export function ApiKeysSection() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setKeys(await listApiKeys());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t load API tokens.");
      setKeys([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || creating) return;
    setCreating(true);
    setError(null);
    try {
      const key = await createApiKey(trimmed);
      setCreated(key);
      setCopied(false);
      setName("");
      setKeys((current) => [key, ...(current ?? [])]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t create the token.");
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(id: string) {
    setRevoking(id);
    setError(null);
    try {
      await revokeApiKey(id);
      setKeys((current) => (current ?? []).filter((k) => k.id !== id));
      setCreated((current) => (current && current.id === id ? null : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn’t revoke the token.");
    } finally {
      setRevoking(null);
    }
  }

  return (
    <div className="settings-form api-keys-section" data-testid="api-keys-section">
      <h3>API tokens</h3>
      <p className="settings-note">
        Static <code>wc_live_</code> Bearer tokens for headless/automation access (read-only). Use
        one for a server or cron job that pulls your recordings without a browser login — works on
        the REST API and the MCP endpoint.
      </p>

      <form className="api-key-create-row" onSubmit={handleCreate}>
        <input
          type="text"
          data-testid="api-key-name-input"
          placeholder="Token name (e.g. meeting-collector)"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <button
          type="submit"
          className="ghost-button compact-button"
          data-testid="api-key-create"
          disabled={creating || name.trim().length === 0}
        >
          {creating ? "Creating…" : "Create token"}
        </button>
      </form>

      {created ? (
        <div className="api-key-created" data-testid="api-key-created-token" role="status">
          <p className="api-key-created-note">Copy this token now — it won’t be shown again.</p>
          <div className="api-key-token-row">
            <code className="api-key-token">{created.token}</code>
            <button
              type="button"
              className="ghost-button compact-button"
              data-testid="api-key-copy-token"
              onClick={async () => {
                if (await copyText(created.token)) {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              type="button"
              className="ghost-button compact-button"
              data-testid="api-key-dismiss-token"
              onClick={() => setCreated(null)}
            >
              Done
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <p className="mcp-connections-error" data-testid="api-keys-error" role="alert">
          {error}
        </p>
      ) : null}

      {keys === null ? (
        <p className="settings-note" data-testid="api-keys-loading">
          Loading…
        </p>
      ) : keys.length === 0 ? (
        <p className="settings-note" data-testid="api-keys-empty">
          No API tokens yet.
        </p>
      ) : (
        <ul className="mcp-connection-rows">
          {keys.map((key) => (
            <li key={key.id} className="mcp-connection-row" data-testid={`api-key-${key.id}`}>
              <div className="mcp-connection-meta">
                <span className="mcp-connection-name">{key.name}</span>
                <span className="mcp-connection-detail">
                  {key.prefix}…{key.last4} · last used {formatDate(key.last_used_at)}
                </span>
              </div>
              <button
                type="button"
                className="ghost-button compact-button"
                data-testid={`api-key-revoke-${key.id}`}
                disabled={revoking === key.id}
                onClick={() => void handleRevoke(key.id)}
              >
                {revoking === key.id ? "Revoking…" : "Revoke"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
