"use client";

import { useCallback, useEffect, useState } from "react";
import { getEntityPage } from "@/lib/api";
import type { EntityPage } from "@/lib/types";

interface EntityWikiViewProps {
  entityId: string;
  onNavigate: (id: string, name: string) => void;
  onError?: (message: string) => void;
  locale?: string;
}

/**
 * The "wiki style" page for one entity: an infobox, the related entities it
 * co-occurs with (clickable → navigate the wiki), and the source backlinks (the
 * items/recordings that mention it, with context). Honest loading/error/empty.
 */
export function EntityWikiView({ entityId, onNavigate, onError, locale = "en" }: EntityWikiViewProps) {
  const t = useCallback(
    (en: string, ru: string) => (locale === "ru" ? ru : en),
    [locale],
  );
  const [page, setPage] = useState<EntityPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPage(await getEntityPage(entityId));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't load this page.";
      setError(message);
      onError?.(message);
    } finally {
      setLoading(false);
    }
  }, [entityId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <p className="brain-wiki__status">{t("Loading…", "Загрузка…")}</p>;
  }
  if (error) {
    return (
      <div className="brain-wiki__error">
        <p>{t("Couldn't load this page.", "Не удалось загрузить страницу.")}</p>
        <p className="brain-wiki__error-detail">{error}</p>
        <button type="button" className="wai-primary-button" onClick={() => void load()}>
          {t("Retry", "Повторить")}
        </button>
      </div>
    );
  }
  if (!page) return null;

  return (
    <article className="brain-wiki">
      <header className="brain-wiki__header">
        <span className="brain-wiki__type">{page.type}</span>
        <h3 className="brain-wiki__title">{page.name}</h3>
        <p className="brain-wiki__meta">
          {page.mention_count} {t("mentions", "упоминаний")}
        </p>
      </header>

      {page.related.length > 0 ? (
        <section className="brain-wiki__section">
          <h4 className="brain-wiki__h4">{t("Related", "Связанные")}</h4>
          <ul className="brain-wiki__related">
            {page.related.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className="brain-wiki__related-chip"
                  title={`${r.shared} ${t("shared sources", "общих источников")}`}
                  onClick={() => onNavigate(r.id, r.name)}
                >
                  <span>{r.name}</span>
                  <em>{r.shared}</em>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="brain-wiki__section">
        <h4 className="brain-wiki__h4">{t("Sources", "Источники")}</h4>
        {page.sources.length === 0 ? (
          <p className="brain-wiki__empty">
            {t("Nothing mentions this yet.", "Пока ничего не упоминает это.")}
          </p>
        ) : (
          <ul className="brain-wiki__sources">
            {page.sources.map((s, i) => (
              <li key={`${s.source_kind}:${s.source_id}:${i}`} className="brain-wiki__source">
                <span className="brain-wiki__source-kind">{s.source_kind}</span>
                <span className="brain-wiki__source-title">{s.title}</span>
                {s.context ? (
                  <p className="brain-wiki__source-context">{s.context}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  );
}
