"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  acceptMemoryProposal,
  getBrainGraph,
  listMemoryProposals,
  rejectMemoryProposal,
} from "@/lib/api";
import type {
  BrainGraph,
  BrainGraphNode,
  BrainOverviewEntity,
  BrainSourceCoverage,
  MemoryProposal,
} from "@/lib/types";
import { BrainGraphView } from "@/components/BrainGraphView";
import { EntityWikiView } from "@/components/EntityWikiView";

interface BrainPanelProps {
  locale?: string;
  onError?: (message: string) => void;
}

type BrainTab = "overview" | "index" | "wiki" | "graph";

const ENTITY_KINDS: Array<{ key: string; en: string; ru: string }> = [
  { key: "person", en: "People", ru: "Люди" },
  { key: "topic", en: "Topics", ru: "Темы" },
  { key: "project", en: "Projects", ru: "Проекты" },
];

/**
 * The Brain section: a knowledge graph of the people / topics / projects across
 * everything captured. Two views — a calm scannable Index (default) and the
 * Obsidian-style force Graph — both built from `GET /api/brain/graph`. `focus`
 * refetches the backend ego graph around a clicked entity. Honest empty + error
 * states (no silent fallback).
 */
export function BrainPanel({ locale = "en", onError }: BrainPanelProps) {
  const [graph, setGraph] = useState<BrainGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<BrainTab>("overview");
  const [focus, setFocus] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(true);
  const [proposals, setProposals] = useState<MemoryProposal[]>([]);
  const [pendingReviewCount, setPendingReviewCount] = useState(0);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [actingProposalIds, setActingProposalIds] = useState<Set<string>>(new Set());
  const [selectedEntity, setSelectedEntity] = useState<{ id: string; name: string } | null>(
    null,
  );

  const openWiki = useCallback((id: string, name: string) => {
    setSelectedEntity({ id, name });
    setTab("wiki");
  }, []);

  const t = useCallback(
    (en: string, ru: string) => (locale === "ru" ? ru : en),
    [locale],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setGraph(
        await getBrainGraph({
          focus: focus ?? undefined,
          include_sources: true,
          limit: 300,
        }),
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't load your brain.";
      setError(message);
      onError?.(message);
      setLoading(false);
      return;
    }
    try {
      const review = await listMemoryProposals({ status: "pending", limit: 50 });
      setProposals(review.proposals);
      setPendingReviewCount(review.pending_count);
      setReviewError(null);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Couldn't load memory changes for review.";
      setReviewError(message);
      onError?.(message);
    } finally {
      setLoading(false);
    }
  }, [focus, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const byKind = useMemo(() => {
    const map: Record<string, BrainGraphNode[]> = {};
    for (const node of graph?.nodes ?? []) {
      if (node.kind === "item" || node.kind === "recording") continue;
      (map[node.kind] ??= []).push(node);
    }
    for (const list of Object.values(map)) list.sort((a, b) => b.degree - a.degree);
    return map;
  }, [graph]);

  const stats = graph?.stats ?? {};
  const isEmpty = (graph?.nodes.length ?? 0) === 0;
  const overview = graph?.overview;

  const decideProposal = useCallback(
    async (id: string, action: (id: string) => Promise<MemoryProposal>) => {
      if (actingProposalIds.has(id)) return;
      setActingProposalIds((current) => new Set(current).add(id));
      try {
        await action(id);
        setProposals((current) => current.filter((proposal) => proposal.id !== id));
        setPendingReviewCount((current) => Math.max(0, current - 1));
        setReviewError(null);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Couldn't update the review queue.";
        setReviewError(message);
        onError?.(message);
      } finally {
        setActingProposalIds((current) => {
          const next = new Set(current);
          next.delete(id);
          return next;
        });
      }
    },
    [actingProposalIds, onError],
  );

  const evidenceLabel = useCallback(
    (proposal: MemoryProposal) => {
      for (const value of proposal.evidence ?? []) {
        if (!value || typeof value !== "object") continue;
        const row = value as Record<string, unknown>;
        if (typeof row.title === "string" && row.title.length > 0) {
          return t("Evidence: ", "Источник: ") + row.title;
        }
        if (
          typeof row.source_kind === "string" &&
          typeof row.source_id === "string" &&
          row.source_kind.length > 0 &&
          row.source_id.length > 0
        ) {
          return t("Evidence: ", "Источник: ") + `${row.source_kind}:${row.source_id}`;
        }
      }
      return null;
    },
    [t],
  );

  const sectionTitle = useCallback(
    (label: string) => {
      if (label === "human") return t("About you", "О вас");
      if (label === "topics") return t("Recurring topics", "Повторяющиеся темы");
      if (label === "preferences") return t("Preferences", "Предпочтения");
      return label;
    },
    [t],
  );

  const entityIcon = (kind: string) => {
    if (kind === "person") return "P";
    if (kind === "project") return "F";
    return "#";
  };

  const sourceKindLabel = useCallback(
    (kind: string) => {
      if (kind === "recording") return t("recording", "запись");
      if (kind === "item") return t("material", "материал");
      return kind;
    },
    [t],
  );

  const coverageBlock = (
    title: string,
    coverage: BrainSourceCoverage | undefined,
    fallbackTotal: number,
  ) => {
    const total = coverage?.total ?? fallbackTotal;
    const organized = coverage?.organized ?? fallbackTotal;
    const summarized = coverage?.summarized ?? organized;
    const unorganized = coverage?.unorganized ?? Math.max(total - organized, 0);
    return (
      <div className="brain-panel__coverage-block">
        <span>{title}</span>
        <strong>
          {organized} / {total}
        </strong>
        <em>
          {t(
            `${summarized} summarized · ${unorganized} not organized`,
            `${summarized} с саммари · ${unorganized} не организовано`,
          )}
        </em>
      </div>
    );
  };

  const entityOverviewRow = (entity: BrainOverviewEntity) => (
    <button
      key={entity.id}
      type="button"
      className="brain-panel__entity-row"
      onClick={() => openWiki(entity.id, entity.name)}
    >
      <span className="brain-panel__entity-icon">{entityIcon(entity.type)}</span>
      <span>
        <strong>{entity.name}</strong>
        <em>
          {t(
            `${entity.recording_count} recordings · ${entity.material_count} materials`,
            `${entity.recording_count} записей · ${entity.material_count} материалов`,
          )}
        </em>
      </span>
      <small>{entity.source_count}</small>
    </button>
  );

  const reviewBody = (
    <section className="brain-panel__section">
      <div className="brain-panel__section-head">
        <h3>{t("Needs review", "На проверку")}</h3>
        <span>{Math.max(pendingReviewCount, overview?.pending_review_count ?? 0)}</span>
      </div>
      {reviewError ? <p className="brain-panel__error-detail">{reviewError}</p> : null}
      {proposals.length > 0 ? (
        <div className="brain-panel__rows">
          {proposals.map((proposal) => {
            const acting = actingProposalIds.has(proposal.id);
            return (
              <article key={proposal.id} className="brain-panel__proposal">
                <div>
                  <p className="brain-panel__proposal-meta">
                    <span>{proposal.risk === "high" ? t("Correction", "Исправление") : t("New fact", "Новый факт")}</span>
                    <span>{sectionTitle(proposal.block_label)}</span>
                    <span>{Math.round(proposal.confidence * 100)}%</span>
                  </p>
                  <p className="brain-panel__proposal-content">{proposal.content}</p>
                  {proposal.target_line ? (
                    <p className="brain-panel__proposal-detail">
                      {t("Replaces: ", "Заменяет: ") + proposal.target_line}
                    </p>
                  ) : null}
                  {evidenceLabel(proposal) ? (
                    <p className="brain-panel__proposal-detail">{evidenceLabel(proposal)}</p>
                  ) : null}
                </div>
                <div className="brain-panel__proposal-actions">
                  <button
                    type="button"
                    aria-label={t("Reject", "Отклонить")}
                    disabled={acting}
                    onClick={() => void decideProposal(proposal.id, rejectMemoryProposal)}
                  >
                    ×
                  </button>
                  <button
                    type="button"
                    aria-label={t("Accept", "Принять")}
                    disabled={acting}
                    onClick={() => void decideProposal(proposal.id, acceptMemoryProposal)}
                  >
                    ✓
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      ) : reviewError ? null : (
        <p className="brain-panel__empty">{t("No memory changes need review.", "Нет изменений памяти на проверку.")}</p>
      )}
    </section>
  );

  const overviewBody = (
    <>
      <section className="brain-panel__section">
        <h3>{t("Coverage", "Покрытие")}</h3>
        <div className="brain-panel__coverage">
          {coverageBlock(t("Recordings", "Записи"), overview?.recordings, stats.recordings ?? 0)}
          {coverageBlock(t("Materials", "Материалы"), overview?.materials, stats.items ?? 0)}
          <div className="brain-panel__coverage-block">
            <span>{t("Needs review", "На проверку")}</span>
            <strong>{Math.max(pendingReviewCount, overview?.pending_review_count ?? 0)}</strong>
            <em>{t("memory changes", "изменений памяти")}</em>
          </div>
        </div>
      </section>
      {Math.max(pendingReviewCount, overview?.pending_review_count ?? 0) > 0 || reviewError
        ? reviewBody
        : null}
      <section className="brain-panel__section">
        <h3>{t("Top entities", "Главное")}</h3>
        {overview?.top_entities.length ? (
          <div className="brain-panel__rows">
            {overview.top_entities.map((entity) => entityOverviewRow(entity))}
          </div>
        ) : (
          <p className="brain-panel__empty">
            {t("No organized entities yet.", "Пока нет организованных сущностей.")}
          </p>
        )}
      </section>
      {overview?.recent_sources.length ? (
        <section className="brain-panel__section">
          <h3>{t("Recently organized", "Недавно организовано")}</h3>
          <div className="brain-panel__rows">
            {overview.recent_sources.map((source) => (
              <div key={source.id} className="brain-panel__source-row">
                <strong>{source.title}</strong>
                <em>
                  {t(
                    `${source.entity_count} entities · ${sourceKindLabel(source.source_kind)}`,
                    `${source.entity_count} сущностей · ${sourceKindLabel(source.source_kind)}`,
                  )}
                </em>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );

  const indexBody = (
    <>
      <div className="brain-panel__stats">
        <span>
          {stats.people ?? 0} {t("people", "людей")}
        </span>
        <span>
          {stats.topics ?? 0} {t("topics", "тем")}
        </span>
        <span>
          {(stats.items ?? 0) + (stats.recordings ?? 0)} {t("sources", "источников")}
        </span>
      </div>
      {ENTITY_KINDS.map(({ key, en, ru }) => {
        const list = byKind[key] ?? [];
        if (list.length === 0) return null;
        return (
          <section key={key} className="brain-panel__group">
            <h3 className="brain-panel__group-title">{t(en, ru)}</h3>
            <ul className="brain-panel__chips">
              {list.map((node) => (
                <li key={node.id}>
                  <button
                    type="button"
                    className="brain-panel__chip"
                    title={`${node.degree} ${t("mentions", "упоминаний")}`}
                    onClick={() => openWiki(node.id, node.label)}
                  >
                    <span>{node.label}</span>
                    <em>{node.degree}</em>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </>
  );

  return (
    <div className="brain-panel">
      <header className="brain-panel__header">
        <h2 className="brain-panel__title">{t("Brain", "Мозг")}</h2>
        <p className="brain-panel__subtitle">
          {t(
            "People, topics and projects across everything you've captured.",
            "Люди, темы и проекты по всему, что вы сохранили.",
          )}
        </p>
      </header>

      <div className="brain-panel__tabs" role="tablist" aria-label={t("Brain views", "Виды мозга")}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "overview"}
          className={`brain-panel__tab ${tab === "overview" ? "brain-panel__tab--active" : ""}`}
          onClick={() => setTab("overview")}
        >
          {t("Overview", "Обзор")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "index"}
          className={`brain-panel__tab ${tab === "index" ? "brain-panel__tab--active" : ""}`}
          onClick={() => setTab("index")}
        >
          {t("Index", "Индекс")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "wiki"}
          className={`brain-panel__tab ${tab === "wiki" ? "brain-panel__tab--active" : ""}`}
          onClick={() => setTab("wiki")}
        >
          {t("Wiki", "Вики")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "graph"}
          className={`brain-panel__tab ${tab === "graph" ? "brain-panel__tab--active" : ""}`}
          onClick={() => setTab("graph")}
        >
          {t("Graph", "Граф")}
        </button>
      </div>

      {loading ? (
        <p className="brain-panel__status">{t("Loading…", "Загрузка…")}</p>
      ) : error ? (
        <div className="brain-panel__error">
          <p>{t("Couldn't load your brain.", "Не удалось загрузить мозг.")}</p>
          <p className="brain-panel__error-detail">{error}</p>
          <button type="button" className="wai-primary-button" onClick={() => void load()}>
            {t("Retry", "Повторить")}
          </button>
        </div>
      ) : isEmpty && tab !== "overview" ? (
        <p className="brain-panel__empty">
          {t(
            "Your brain is empty — add materials or record, and the people & topics they mention will appear here.",
            "Ваш мозг пуст — добавьте материалы или записи, и здесь появятся люди и темы из них.",
          )}
        </p>
      ) : tab === "overview" ? (
        overviewBody
      ) : tab === "index" ? (
        indexBody
      ) : tab === "wiki" ? (
        selectedEntity ? (
          <EntityWikiView
            entityId={selectedEntity.id}
            onNavigate={(id, name) => setSelectedEntity({ id, name })}
            onError={onError}
            locale={locale}
          />
        ) : (
          <p className="brain-panel__empty">
            {t(
              "Pick a person or topic from the Index to read its page.",
              "Выберите человека или тему в Индексе, чтобы открыть страницу.",
            )}
          </p>
        )
      ) : (
        <BrainGraphView
          graph={graph as BrainGraph}
          showSources={showSources}
          onToggleSources={setShowSources}
          onFocusEntity={(id) => setFocus(id)}
          focused={focus !== null}
          onResetFocus={() => setFocus(null)}
          locale={locale}
        />
      )}
    </div>
  );
}
