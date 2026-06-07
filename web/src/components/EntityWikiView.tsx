"use client";

import { useCallback, useEffect, useState } from "react";
import { getEntityPage } from "@/lib/api";
import type { EntityPage, EntityPageCitation } from "@/lib/types";

interface EntityWikiViewProps {
  entityId: string;
  onNavigate: (id: string, name: string) => void;
  onError?: (message: string) => void;
  onOpenSource?: (sourceKind: "recording" | "item" | "chat", sourceId: string) => void;
  locale?: string;
}

function citationsFor(page: EntityPage): EntityPageCitation[] {
  const explicitCitations = page.citations ?? [];
  if (explicitCitations.length > 0) return explicitCitations;
  return (page.sources ?? []).map((source) => ({
    id: `${source.source_kind}:${source.source_id}`,
    source_kind: source.source_kind,
    source_id: source.source_id,
    title: source.title,
    context: source.context,
    occurred_at: source.occurred_at ?? null,
  }));
}

function citationLabels(ids: string[], citations: Map<string, EntityPageCitation>): string {
  return ids
    .map((id) => citations.get(id)?.title)
    .filter((title): title is string => Boolean(title))
    .slice(0, 3)
    .join(", ");
}

/**
 * Cached wiki page for one entity. The server owns compilation; this component
 * only renders the structured sections and keeps related navigation clickable.
 */
export function EntityWikiView({
  entityId,
  onNavigate,
  onError,
  onOpenSource,
  locale = "en",
}: EntityWikiViewProps) {
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

  const citations = citationsFor(page);
  const citationMap = new Map(citations.map((citation) => [citation.id, citation]));
  const facts = page.facts ?? [];
  const timeline = page.timeline ?? [];
  const questions = page.questions ?? [];
  const actions = page.actions ?? [];
  const explicitRelated = page.related_explanations ?? [];
  const relatedExplanations = explicitRelated.length > 0
    ? explicitRelated
    : (page.related ?? []).map((related) => ({
        ...related,
        explanation: `${related.shared} ${t("shared sources", "общих источников")}`,
        citation_ids: [],
      }));

  return (
    <article className="brain-wiki">
      <header className="brain-wiki__header">
        <span className="brain-wiki__type">{page.type}</span>
        <h3 className="brain-wiki__title">{page.name}</h3>
        <p className="brain-wiki__meta">
          {page.mention_count} {t("mentions", "упоминаний")}
        </p>
      </header>

      <section className="brain-wiki__section brain-wiki__overview">
        <p>{page.overview}</p>
      </section>

      <section className="brain-wiki__section">
        <h4 className="brain-wiki__h4">{t("Facts", "Факты")}</h4>
        {facts.length === 0 ? (
          <p className="brain-wiki__empty">{t("No extracted facts yet.", "Пока нет фактов.")}</p>
        ) : (
          <ul className="brain-wiki__list">
            {facts.map((fact) => (
              <li key={fact.id}>
                <span>{fact.text}</span>
                {citationLabels(fact.citation_ids ?? [], citationMap) ? (
                  <em>{citationLabels(fact.citation_ids ?? [], citationMap)}</em>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="brain-wiki__section">
        <h4 className="brain-wiki__h4">{t("Timeline", "Хронология")}</h4>
        {timeline.length === 0 ? (
          <p className="brain-wiki__empty">
            {t("No timeline events yet.", "Пока нет событий.")}
          </p>
        ) : (
          <ol className="brain-wiki__timeline">
            {timeline.map((event) => (
              <li key={event.id}>
                <span>{event.title}</span>
                {event.description ? <p>{event.description}</p> : null}
                {citationLabels(event.citation_ids ?? [], citationMap) ? (
                  <em>{citationLabels(event.citation_ids ?? [], citationMap)}</em>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="brain-wiki__section">
        <h4 className="brain-wiki__h4">{t("Related", "Связанные")}</h4>
        {relatedExplanations.length === 0 ? (
          <p className="brain-wiki__empty">
            {t("No related entities yet.", "Пока нет связанных сущностей.")}
          </p>
        ) : (
          <ul className="brain-wiki__related">
            {relatedExplanations.map((related) => (
              <li key={related.id}>
                <button
                  type="button"
                  className="brain-wiki__related-card"
                  onClick={() => onNavigate(related.id, related.name)}
                >
                  <span>{related.name}</span>
                  <p>{related.explanation}</p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="brain-wiki__section">
        <h4 className="brain-wiki__h4">{t("Questions", "Вопросы")}</h4>
        {questions.length === 0 ? (
          <p className="brain-wiki__empty">
            {t("No open questions found.", "Открытых вопросов не найдено.")}
          </p>
        ) : (
          <ul className="brain-wiki__list">
            {questions.map((question) => (
              <li key={question.id}>
                <span>{question.text}</span>
                {citationLabels(question.citation_ids ?? [], citationMap) ? (
                  <em>{citationLabels(question.citation_ids ?? [], citationMap)}</em>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="brain-wiki__section">
        <h4 className="brain-wiki__h4">{t("Actions", "Действия")}</h4>
        {actions.length === 0 ? (
          <p className="brain-wiki__empty">
            {t("No action items found.", "Действий не найдено.")}
          </p>
        ) : (
          <ul className="brain-wiki__list">
            {actions.map((action) => (
              <li key={action.id}>
                <span>{action.text}</span>
                <em>
                  {[action.owner, action.status, citationLabels(action.citation_ids ?? [], citationMap)]
                    .filter(Boolean)
                    .join(" · ")}
                </em>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="brain-wiki__section">
        <h4 className="brain-wiki__h4">{t("Citations", "Цитаты")}</h4>
        {citations.length === 0 ? (
          <p className="brain-wiki__empty">
            {t("Nothing mentions this yet.", "Пока ничего не упоминает это.")}
          </p>
        ) : (
          <ul className="brain-wiki__sources">
            {citations.map((s) => (
              <li key={s.id} className="brain-wiki__source">
                <button
                  type="button"
                  className="brain-wiki__source-link"
                  aria-label={`${t("Open source", "Открыть источник")}: ${s.title}`}
                  onClick={() => {
                    if (s.source_kind === "recording" || s.source_kind === "item") {
                      onOpenSource?.(s.source_kind, s.source_id);
                    }
                  }}
                >
                  <span className="brain-wiki__source-kind">{s.source_kind}</span>
                  <span className="brain-wiki__source-title">{s.title}</span>
                </button>
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
