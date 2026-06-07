"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import {
  createMcpIngestionConnection,
  deleteMcpIngestionConnection,
  getSourceCatalog,
  listMcpIngestionConnections,
  syncMcpIngestionConnection,
  updateMcpIngestionConnection,
} from "@/lib/api";
import type {
  McpIngestionConnection,
  SourceCatalog,
  SourceCatalogEntry,
} from "@/lib/types";

type Locale = "en" | "ru";

const ICONS: Record<string, string> = {
  gmail: "📧", telegram: "✈️", slack: "💬", notion: "📝", obsidian: "🪨",
  google_drive: "📁", google_calendar: "📅", wai_time: "⏱️", wai_money: "💰",
  custom: "🔌",
};

const t = (loc: Locale, en: string, ru: string) => (loc === "ru" ? ru : en);

function relativeTime(loc: Locale, iso: string | null): string {
  if (!iso) return "";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 90) return t(loc, "just now", "только что");
  const mins = Math.round(secs / 60);
  if (mins < 90) return t(loc, `${mins}m ago`, `${mins} мин назад`);
  const hrs = Math.round(mins / 60);
  if (hrs < 36) return t(loc, `${hrs}h ago`, `${hrs} ч назад`);
  return t(loc, `${Math.round(hrs / 24)}d ago`, `${Math.round(hrs / 24)} дн назад`);
}

const DEPTH_LABELS: Record<string, [string, string]> = {
  recent_30d: ["Recent 30 days", "Последние 30 дней"],
  recent_90d: ["Recent 90 days", "Последние 90 дней"],
  last_year: ["Last year", "Последний год"],
  everything: ["Everything", "Всё"],
};

/**
 * The Hermes-style "connect a source" surface: a categorized catalog of data
 * MCPs you flip on, plus an "Add custom MCP" escape hatch. Wai becomes the MCP
 * CLIENT, pulling each source's data into the brain (read-only) and linking it.
 */
interface McpSourcesPanelProps {
  locale?: Locale;
}

export function McpSourcesPanel({ locale = "en" }: McpSourcesPanelProps) {
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null);
  const [conns, setConns] = useState<McpIngestionConnection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // Inline connect form state, keyed by catalog entry id (null = none open).
  const [openEntry, setOpenEntry] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [depth, setDepth] = useState("");
  // Custom-source disclosure.
  const [customOpen, setCustomOpen] = useState(false);
  const [cLabel, setCLabel] = useState("");
  const [cUrl, setCUrl] = useState("");
  const [cToken, setCToken] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      const [cat, list] = await Promise.all([
        catalog ? Promise.resolve(catalog) : getSourceCatalog(),
        listMcpIngestionConnections(),
      ]);
      setCatalog(cat);
      setConns(list);
      if (!depth) setDepth(cat.default_backfill_depth);
    } catch (err) {
      setError(err instanceof Error ? err.message : t(locale, "Couldn’t load sources.", "Не удалось загрузить источники."));
      setConns([]);
    }
  }, [catalog, depth, locale]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const byCatalog = useMemo(() => {
    const m = new Map<string, McpIngestionConnection>();
    for (const c of conns ?? []) if (c.catalog_id) m.set(c.catalog_id, c);
    return m;
  }, [conns]);

  const customConns = useMemo(
    () => (conns ?? []).filter((c) => !c.catalog_id),
    [conns],
  );

  const run = useCallback(
    async (id: string, fn: () => Promise<unknown>, errMsg: string) => {
      setBusyId(id);
      setError(null);
      try {
        await fn();
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : errMsg);
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  const connectTile = useCallback(
    async (entry: SourceCatalogEntry, authToken: string | null) => {
      await run(
        `tile-${entry.id}`,
        async () => {
          const created = await createMcpIngestionConnection({
            catalog_id: entry.id,
            auth_token: authToken,
            backfill_depth: depth || undefined,
          });
          setOpenEntry(null);
          setToken("");
          await syncMcpIngestionConnection(created.id).catch(() => undefined);
        },
        t(locale, "Couldn’t connect that source.", "Не удалось подключить источник."),
      );
    },
    [run, depth, locale],
  );

  const connectCustom = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const label = cLabel.trim();
      const url = cUrl.trim();
      if (!url) return;
      await run(
        "custom",
        async () => {
          const authToken = cToken.trim() || null;
          const created = await createMcpIngestionConnection({
            server_label: label || undefined,
            server_url: url,
            auth_type: authToken ? "pat" : "none", // FIX: was "bearer" (invalid)
            auth_token: authToken,
            backfill_depth: depth || undefined,
          });
          setCLabel("");
          setCUrl("");
          setCToken("");
          setCustomOpen(false);
          await syncMcpIngestionConnection(created.id).catch(() => undefined);
        },
        t(locale, "Couldn’t connect that source.", "Не удалось подключить источник."),
      );
    },
    [cLabel, cUrl, cToken, depth, run, locale],
  );

  const statusLine = useCallback(
    (c: McpIngestionConnection): { text: string; danger: boolean } => {
      if (["error", "error_terminal", "needs_setup", "degraded"].includes(c.status)) {
        const reason = c.status === "needs_setup"
          ? t(locale, "couldn’t read this server", "не удалось прочитать сервер")
          : c.last_error || t(locale, "sync error", "ошибка синхронизации");
        return { text: t(locale, `Reconnect needed — ${reason}`, `Нужно переподключить — ${reason}`), danger: true };
      }
      if (!c.enabled) {
        return { text: t(locale, `Paused · ${c.item_count} items`, `Пауза · ${c.item_count} материалов`), danger: false };
      }
      if (!c.last_sync_at) return { text: t(locale, "Syncing…", "Синхронизация…"), danger: false };
      return {
        text: t(locale, `Synced ${c.item_count} · ${relativeTime(locale, c.last_sync_at)}`,
          `Синхр. ${c.item_count} · ${relativeTime(locale, c.last_sync_at)}`),
        danger: false,
      };
    },
    [locale],
  );

  const depthSelect = (
    <label className="mcp-depth">
      <span>{t(locale, "History", "История")}</span>
      <select value={depth} onChange={(e) => setDepth(e.target.value)}>
        {(catalog?.backfill_depths ?? []).map((d) => (
          <option key={d} value={d}>
            {t(locale, DEPTH_LABELS[d]?.[0] ?? d, DEPTH_LABELS[d]?.[1] ?? d)}
          </option>
        ))}
      </select>
    </label>
  );

  const renderConnectedRow = (c: McpIngestionConnection) => {
    const s = statusLine(c);
    return (
      <li key={c.id} className="mcp-connection-row" data-testid={`mcp-source-${c.id}`}>
        <div className="mcp-connection-meta">
          <span className="mcp-connection-name">
            {ICONS[c.source_type ?? "custom"] ?? ICONS.custom} {c.server_label}
          </span>
          <span className={`mcp-connection-detail${s.danger ? " mcp-detail-danger" : ""}`}>
            {s.text}
          </span>
        </div>
        <div className="mcp-source-actions">
          <a className="ghost-button compact-button" href="?view=brain">
            {t(locale, "View in Brain →", "В Мозге →")}
          </a>
          <button type="button" className="ghost-button compact-button"
            disabled={busyId === c.id}
            onClick={() => void run(c.id, () => syncMcpIngestionConnection(c.id), t(locale, "Sync failed.", "Ошибка синхронизации."))}>
            {t(locale, "Sync", "Синхр.")}
          </button>
          <button type="button" className="ghost-button compact-button"
            disabled={busyId === c.id}
            onClick={() => void run(c.id, () => updateMcpIngestionConnection(c.id, { enabled: !c.enabled }), t(locale, "Update failed.", "Ошибка обновления."))}>
            {c.enabled ? t(locale, "Pause", "Пауза") : t(locale, "Resume", "Возобновить")}
          </button>
          <button type="button" className="ghost-button compact-button mcp-disconnect"
            disabled={busyId === c.id}
            onClick={() => {
              if (window.confirm(t(locale, `Disconnect ${c.server_label}? Future syncs stop; items stay in your Brain.`, `Отключить ${c.server_label}? Синхронизация остановится; материалы останутся в Мозге.`))) {
                void run(c.id, () => deleteMcpIngestionConnection(c.id), t(locale, "Disconnect failed.", "Не удалось отключить."));
              }
            }}>
            {t(locale, "Disconnect", "Отключить")}
          </button>
        </div>
      </li>
    );
  };

  const renderTile = (entry: SourceCatalogEntry) => {
    const conn = byCatalog.get(entry.id);
    const isOpen = openEntry === entry.id;
    const comingSoon = entry.status !== "available";
    return (
      <li key={entry.id} className="mcp-tile" data-testid={`mcp-tile-${entry.id}`}>
        <div className="mcp-tile-main">
          <span className="mcp-tile-icon" aria-hidden>{ICONS[entry.id] ?? ICONS.custom}</span>
          <div className="mcp-tile-text">
            <span className="mcp-tile-name">{entry.name}</span>
            <span className="mcp-tile-tagline">{t(locale, entry.tagline_en, entry.tagline_ru)}</span>
          </div>
          <div className="mcp-tile-action">
            {conn ? (
              <span className="mcp-pill mcp-pill-on">{t(locale, "Connected", "Подключено")}</span>
            ) : comingSoon ? (
              <span className="mcp-pill mcp-pill-soon">{t(locale, "Soon", "Скоро")}</span>
            ) : (
              <button type="button" className="primary-button compact-button"
                disabled={busyId === `tile-${entry.id}`}
                onClick={() => {
                  if (entry.auth_type === "pat") { setOpenEntry(entry.id); setToken(""); }
                  else void connectTile(entry, null);
                }}>
                {busyId === `tile-${entry.id}` ? t(locale, "Connecting…", "Подключение…") : t(locale, "Connect", "Подключить")}
              </button>
            )}
          </div>
        </div>
        {isOpen && entry.auth_type === "pat" ? (
          <div className="mcp-tile-form">
            <input aria-label={t(locale, "Access token", "Токен доступа")} type="password"
              placeholder={t(locale, entry.setup_hint_en ?? "Access token", entry.setup_hint_ru ?? "Токен доступа")}
              value={token} onChange={(e) => setToken(e.target.value)} />
            {depthSelect}
            <button type="button" className="primary-button compact-button"
              disabled={!token.trim() || busyId === `tile-${entry.id}`}
              onClick={() => void connectTile(entry, token.trim())}>
              {t(locale, "Connect", "Подключить")}
            </button>
            <button type="button" className="ghost-button compact-button" onClick={() => setOpenEntry(null)}>
              {t(locale, "Cancel", "Отмена")}
            </button>
          </div>
        ) : null}
      </li>
    );
  };

  return (
    <div className="mcp-connections mcp-sources" data-testid="mcp-sources">
      <h4>{t(locale, "Sources", "Источники")}</h4>
      <p className="settings-note">
        {t(locale,
          "Connect your apps so everything flows into your Brain — searchable, summarized, and linked. Read-only.",
          "Подключите приложения, чтобы всё попадало в Мозг — с поиском, сводками и связями. Только чтение.")}
      </p>

      {error ? (
        <p className="mcp-connections-error" data-testid="mcp-sources-error" role="alert">{error}</p>
      ) : null}

      {conns && conns.length > 0 ? (
        <div className="mcp-cat-group">
          <h5 className="mcp-cat-title">{t(locale, "Connected", "Подключённые")}</h5>
          <ul className="mcp-connection-rows">
            {[...byCatalog.values(), ...customConns].map(renderConnectedRow)}
          </ul>
        </div>
      ) : null}

      {catalog === null ? (
        <p className="settings-note" data-testid="mcp-sources-loading">{t(locale, "Loading…", "Загрузка…")}</p>
      ) : (
        catalog.categories.map((cat) => {
          const entries = catalog.entries.filter((e) => e.category === cat.id);
          if (entries.length === 0) return null;
          return (
            <div key={cat.id} className="mcp-cat-group">
              <h5 className="mcp-cat-title">{t(locale, cat.name_en, cat.name_ru)}</h5>
              <ul className="mcp-tile-list">{entries.map(renderTile)}</ul>
            </div>
          );
        })
      )}

      {catalog?.custom_supported ? (
        <div className="mcp-cat-group">
          <button type="button" className="ghost-button" onClick={() => setCustomOpen((v) => !v)}
            aria-expanded={customOpen} data-testid="mcp-custom-toggle">
            {customOpen ? "▾ " : "▸ "}{t(locale, "Add custom MCP (advanced)", "Добавить свой MCP (для продвинутых)")}
          </button>
          {customOpen ? (
            <form className="mcp-source-form" onSubmit={connectCustom}>
              <input aria-label={t(locale, "Source name", "Название")} placeholder={t(locale, "Source name", "Название")}
                value={cLabel} onChange={(e) => setCLabel(e.target.value)} />
              <input aria-label={t(locale, "Server URL", "URL сервера")} placeholder="https://example.com/mcp"
                value={cUrl} onChange={(e) => setCUrl(e.target.value)} />
              <input aria-label={t(locale, "Auth token (optional)", "Токен (необязательно)")} type="password"
                placeholder={t(locale, "Auth token (optional)", "Токен (необязательно)")}
                value={cToken} onChange={(e) => setCToken(e.target.value)} />
              {depthSelect}
              <button type="submit" className="primary-button compact-button"
                data-testid="mcp-custom-submit"
                disabled={busyId === "custom" || !cUrl.trim()}>
                {busyId === "custom" ? t(locale, "Connecting…", "Подключение…") : t(locale, "Connect", "Подключить")}
              </button>
            </form>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
