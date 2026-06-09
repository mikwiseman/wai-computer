"use client";

import { useCallback, useEffect, useState } from "react";
import { listEntities } from "@/lib/api";
import type { Entity, EntityType } from "@/lib/types";
import { EntityWikiView } from "@/components/EntityWikiView";

interface BrainPanelProps {
  locale?: string;
  onError?: (message: string) => void;
  onOpenSource?: (sourceKind: "recording" | "item" | "chat", sourceId: string) => void;
  onOpenInbox?: () => void;
  /** (entityId, name) -> open the Wai chat scoped to that page. */
  onAskWaiAboutEntity?: (entityId: string, name: string) => void;
}

type PageFilter = "all" | "person" | "project" | "topic";
type Translator = (en: string, ru: string) => string;

const FILTERS: { key: PageFilter; en: string; ru: string }[] = [
  { key: "all", en: "All", ru: "Все" },
  { key: "person", en: "People", ru: "Люди" },
  { key: "project", en: "Projects", ru: "Проекты" },
  { key: "topic", en: "Topics", ru: "Темы" },
];

function entityGlyph(type: EntityType | string): string {
  if (type === "person") return "P";
  if (type === "project") return "F";
  if (type === "organization") return "O";
  return "#";
}

function entityTypeLabel(type: string, t: Translator): string {
  if (type === "person") return t("Person", "Человек");
  if (type === "project") return t("Project", "Проект");
  if (type === "organization") return t("Organization", "Организация");
  return t("Topic", "Тема");
}

/**
 * The Brain section: a browsable WIKI of compiled pages (people / projects /
 * topics). Each page is a cited living dossier; "Ask Wai about X" deep-links
 * into the Wai chat scoped to that entity. Ask + maps live in Wai/Inbox.
 */
export function BrainPanel({
  locale = "en",
  onError,
  onOpenSource,
  onOpenInbox,
  onAskWaiAboutEntity,
}: BrainPanelProps) {
  const t = useCallback((en: string, ru: string) => (locale === "ru" ? ru : en), [locale]);

  const [entities, setEntities] = useState<Entity[]>([]);
  const [filter, setFilter] = useState<PageFilter>("all");
  const [search, setSearch] = useState("");
  const [selectedEntity, setSelectedEntity] = useState<{ id: string; name: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // No-fallback: a transient failure must NOT look like "empty brain".
      setEntities(await listEntities({ limit: 200 }));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't load your Brain.";
      setError(message);
      onError?.(message);
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const openSource = useCallback(
    (sourceKind: string, sourceId: string) => {
      if (sourceKind !== "recording" && sourceKind !== "item" && sourceKind !== "chat") return;
      onOpenSource?.(sourceKind, sourceId);
    },
    [onOpenSource],
  );

  const query = search.trim().toLowerCase();
  const visiblePages = entities.filter(
    (entity) =>
      (filter === "all" || entity.type === filter) &&
      (query === "" || entity.name.toLowerCase().includes(query)),
  );

  if (loading) {
    return (
      <section className="brain-panel brain-panel--loading">
        <div className="brain-panel__loading">{t("Loading Brain…", "Загружаю Мозг…")}</div>
      </section>
    );
  }

  if (selectedEntity) {
    return (
      <section className="brain-panel">
        <button
          type="button"
          className="brain-panel__back"
          onClick={() => setSelectedEntity(null)}
        >
          ← {t("Back to Pages", "Назад к страницам")}
        </button>
        <EntityWikiView
          entityId={selectedEntity.id}
          locale={locale}
          onOpenSource={openSource}
          onNavigate={(id, name) => setSelectedEntity({ id, name })}
          onAskWai={onAskWaiAboutEntity}
        />
      </section>
    );
  }

  if (error && entities.length === 0) {
    return (
      <section className="brain-panel brain-panel--mirror">
        <header className="brain-panel__hero">
          <div>
            <h2>{t("Brain", "Мозг")}</h2>
          </div>
        </header>
        <div className="brain-panel__error">
          <p>{t("Couldn't load your Brain.", "Не удалось загрузить Мозг.")}</p>
          <p className="brain-panel__error-text">{error}</p>
          <button type="button" className="wai-primary-button" onClick={() => void load()}>
            {t("Retry", "Повторить")}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="brain-panel brain-panel--mirror">
      <header className="brain-panel__hero">
        <div>
          <h2>{t("Brain", "Мозг")}</h2>
          <p>
            {t(
              "Your wiki — the people, projects, and topics Wai compiles from everything you capture.",
              "Ваша вики — люди, проекты и темы, которые Wai собирает из всего, что вы фиксируете.",
            )}
          </p>
        </div>
      </header>

      {error ? <p className="brain-panel__error-text">{error}</p> : null}

      {entities.length === 0 ? (
        <div className="brain-panel__empty-state">
          <p>
            {t(
              "Pages appear as Wai finds people, projects, and topics in your sources.",
              "Страницы появляются, когда Wai находит людей, проекты и темы в ваших источниках.",
            )}
          </p>
          {onOpenInbox ? (
            <button type="button" className="wai-secondary-button" onClick={() => onOpenInbox()}>
              {t("Open Inbox", "Открыть инбокс")}
            </button>
          ) : null}
        </div>
      ) : (
        <section className="brain-panel__section">
          <div className="brain-panel__section-head">
            <h3>{t("Pages", "Страницы")}</h3>
            <div
              className="brain-pages__filters"
              role="tablist"
              aria-label={t("Filter pages", "Фильтр страниц")}
            >
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  role="tab"
                  aria-selected={filter === f.key}
                  className={`brain-pages__filter ${filter === f.key ? "brain-pages__filter--active" : ""}`}
                  onClick={() => setFilter(f.key)}
                >
                  {t(f.en, f.ru)}
                </button>
              ))}
            </div>
          </div>
          <input
            className="brain-pages__search"
            value={search}
            placeholder={t("Search people, projects, topics…", "Поиск людей, проектов, тем…")}
            aria-label={t("Search pages", "Поиск страниц")}
            onChange={(event) => setSearch(event.target.value)}
          />
          {visiblePages.length > 0 ? (
            <div className="brain-panel__rows brain-panel__rows--spaced">
              {visiblePages.map((entity) => (
                <button
                  key={entity.id}
                  type="button"
                  className="brain-panel__entity-row"
                  onClick={() => setSelectedEntity({ id: entity.id, name: entity.name })}
                >
                  <span className="brain-panel__entity-icon">{entityGlyph(entity.type)}</span>
                  <span>
                    <strong>{entity.name}</strong>
                    <em>{entity.overview_snippet || entityTypeLabel(entity.type, t)}</em>
                  </span>
                  <small>
                    {entity.source_count ?? 0}{" "}
                    {(entity.source_count ?? 0) === 1
                      ? t("source", "источн.")
                      : t("sources", "источн.")}
                  </small>
                </button>
              ))}
            </div>
          ) : (
            <p className="brain-panel__empty">{t("No pages match.", "Нет совпадений.")}</p>
          )}
        </section>
      )}
    </section>
  );
}
