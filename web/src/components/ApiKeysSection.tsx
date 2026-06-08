"use client";

import { type FormEvent, type ReactNode, useCallback, useEffect, useState } from "react";

import { createApiKey, listApiKeys, revokeApiKey } from "@/lib/api";
import type { ApiKey, ApiKeyCreated } from "@/lib/types";

type Locale = "en" | "ru";

interface Copy {
  heading: string;
  note: ReactNode;
  placeholder: string;
  create: string;
  creating: string;
  allowWrite: string;
  createdNote: string;
  copy: string;
  copied: string;
  done: string;
  errLoad: string;
  errCreate: string;
  errRevoke: string;
  loading: string;
  empty: string;
  lastUsed: string;
  never: string;
  revoke: string;
  revoking: string;
  writeBadge: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    heading: "API tokens",
    note: (
      <>
        Static <code>wc_live_</code> Bearer tokens for headless access — a server, cron job, or an
        agent (OpenClaw, Hermes) acting as a memory bank. Works on the REST API and the MCP
        endpoint. Read-only by default; enable “save memories” to also let an agent write back via
        the MCP <code>remember</code> tool. The REST API stays read-only either way.
      </>
    ),
    placeholder: "Token name (e.g. openclaw-agent)",
    create: "Create token",
    creating: "Creating…",
    allowWrite: "Allow this token to save memories (write access)",
    createdNote: "Copy this token now — it won’t be shown again.",
    copy: "Copy",
    copied: "Copied",
    done: "Done",
    errLoad: "Couldn’t load API tokens.",
    errCreate: "Couldn’t create the token.",
    errRevoke: "Couldn’t revoke the token.",
    loading: "Loading…",
    empty: "No API tokens yet.",
    lastUsed: "last used",
    never: "never",
    revoke: "Revoke",
    revoking: "Revoking…",
    writeBadge: "memory write",
  },
  ru: {
    heading: "API-токены",
    note: (
      <>
        Статичные Bearer-токены <code>wc_live_</code> для headless-доступа — сервер, cron-задача или
        агент (OpenClaw, Hermes) в роли банка памяти. Работают в REST API и в MCP. По умолчанию
        только для чтения; включите «сохранять память», чтобы агент мог записывать через
        MCP-инструмент <code>remember</code>. REST API в любом случае остаётся только для чтения.
      </>
    ),
    placeholder: "Название токена (например, openclaw-agent)",
    create: "Создать токен",
    creating: "Создаём…",
    allowWrite: "Разрешить этому токену сохранять память (доступ на запись)",
    createdNote: "Скопируйте токен сейчас — он больше не будет показан.",
    copy: "Копировать",
    copied: "Скопировано",
    done: "Готово",
    errLoad: "Не удалось загрузить API-токены.",
    errCreate: "Не удалось создать токен.",
    errRevoke: "Не удалось отозвать токен.",
    loading: "Загрузка…",
    empty: "Пока нет API-токенов.",
    lastUsed: "последнее использование",
    never: "никогда",
    revoke: "Отозвать",
    revoking: "Отзыв…",
    writeBadge: "запись памяти",
  },
};

function formatDate(value: string | null, never: string): string {
  if (!value) return never;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return never;
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

interface ApiKeysSectionProps {
  locale?: Locale;
}

export function ApiKeysSection({ locale = "en" }: ApiKeysSectionProps) {
  const copy = COPY[locale];
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [allowMemoryWrite, setAllowMemoryWrite] = useState(false);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setKeys(await listApiKeys());
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.errLoad);
      setKeys([]);
    }
  }, [copy.errLoad]);

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
      const key = await createApiKey(trimmed, { allowMemoryWrite });
      setCreated(key);
      setCopied(false);
      setName("");
      setAllowMemoryWrite(false);
      setKeys((current) => [key, ...(current ?? [])]);
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.errCreate);
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
      setError(err instanceof Error ? err.message : copy.errRevoke);
    } finally {
      setRevoking(null);
    }
  }

  return (
    <div className="settings-form api-keys-section" data-testid="api-keys-section">
      <h3>{copy.heading}</h3>
      <p className="settings-note">{copy.note}</p>

      <form className="api-key-create-row" onSubmit={handleCreate}>
        <input
          type="text"
          data-testid="api-key-name-input"
          placeholder={copy.placeholder}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <button
          type="submit"
          className="ghost-button compact-button"
          data-testid="api-key-create"
          disabled={creating || name.trim().length === 0}
        >
          {creating ? copy.creating : copy.create}
        </button>
      </form>
      <label className="api-key-write-toggle" data-testid="api-key-allow-write">
        <input
          type="checkbox"
          checked={allowMemoryWrite}
          onChange={(event) => setAllowMemoryWrite(event.target.checked)}
        />
        <span>{copy.allowWrite}</span>
      </label>

      {created ? (
        <div className="api-key-created" data-testid="api-key-created-token" role="status">
          <p className="api-key-created-note">{copy.createdNote}</p>
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
              {copied ? copy.copied : copy.copy}
            </button>
            <button
              type="button"
              className="ghost-button compact-button"
              data-testid="api-key-dismiss-token"
              onClick={() => setCreated(null)}
            >
              {copy.done}
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
          {copy.loading}
        </p>
      ) : keys.length === 0 ? (
        <p className="settings-note" data-testid="api-keys-empty">
          {copy.empty}
        </p>
      ) : (
        <ul className="mcp-connection-rows">
          {keys.map((key) => (
            <li key={key.id} className="mcp-connection-row" data-testid={`api-key-${key.id}`}>
              <div className="mcp-connection-meta">
                <span className="mcp-connection-name">
                  {key.name}
                  {key.scopes?.includes("memory:write") ? (
                    <span
                      className="api-key-scope-badge"
                      data-testid={`api-key-write-badge-${key.id}`}
                    >
                      {copy.writeBadge}
                    </span>
                  ) : null}
                </span>
                <span className="mcp-connection-detail">
                  {key.prefix}…{key.last4} · {copy.lastUsed} {formatDate(key.last_used_at, copy.never)}
                </span>
              </div>
              <button
                type="button"
                className="ghost-button compact-button"
                data-testid={`api-key-revoke-${key.id}`}
                disabled={revoking === key.id}
                onClick={() => void handleRevoke(key.id)}
              >
                {revoking === key.id ? copy.revoking : copy.revoke}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
