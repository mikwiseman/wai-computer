"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  acceptBrainReviewPack,
  acceptMemoryProposal,
  addBrainSpaceMember,
  buildBrainContext,
  exportBrainSpace,
  getBrainGraph,
  getBrainSpaceHome,
  listBrainReviewPacks,
  listBrainSpaces,
  listMemoryProposals,
  rejectBrainReviewPack,
  rejectMemoryProposal,
} from "@/lib/api";
import type {
  BrainGraph,
  BrainGraphNode,
  BrainOverviewEntity,
  BrainReviewPack,
  BrainSourceCoverage,
  BrainSpace,
  BrainSpaceHome,
  MemoryProposal,
} from "@/lib/types";
import { BrainGraphView } from "@/components/BrainGraphView";
import { EntityWikiView } from "@/components/EntityWikiView";

interface BrainPanelProps {
  locale?: string;
  onError?: (message: string) => void;
  onOpenSource?: (sourceKind: "recording" | "item", sourceId: string) => void;
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
export function BrainPanel({ locale = "en", onError, onOpenSource }: BrainPanelProps) {
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
  const [spaces, setSpaces] = useState<BrainSpace[]>([]);
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null);
  const [spaceHome, setSpaceHome] = useState<BrainSpaceHome | null>(null);
  const [reviewPacks, setReviewPacks] = useState<BrainReviewPack[]>([]);
  const [spaceError, setSpaceError] = useState<string | null>(null);
  const [actingReviewPackIds, setActingReviewPackIds] = useState<Set<string>>(new Set());
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const [shareEmail, setShareEmail] = useState("");
  const [shareRole, setShareRole] = useState<"viewer" | "editor">("viewer");
  const [shareMessage, setShareMessage] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextMessage, setContextMessage] = useState<string | null>(null);
  const [contextPreview, setContextPreview] = useState<string | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<{ id: string; name: string } | null>(
    null,
  );
  const hasLoadedRef = useRef(false);

  const openWiki = useCallback((id: string, name: string) => {
    setSelectedEntity({ id, name });
    setTab("wiki");
  }, []);

  const t = useCallback(
    (en: string, ru: string) => (locale === "ru" ? ru : en),
    [locale],
  );

  const load = useCallback(async () => {
    const showFullLoading = !hasLoadedRef.current;
    if (showFullLoading) setLoading(true);
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
      hasLoadedRef.current = true;
      setLoading(false);
      return;
    }
    try {
      const spaceList = await listBrainSpaces();
      setSpaces(spaceList.spaces);
      const nextSpaceId =
        selectedSpaceId && spaceList.spaces.some((space) => space.id === selectedSpaceId)
          ? selectedSpaceId
          : (spaceList.spaces[0]?.id ?? null);
      setSelectedSpaceId(nextSpaceId);
      if (nextSpaceId) {
        const [home, packs] = await Promise.all([
          getBrainSpaceHome(nextSpaceId),
          listBrainReviewPacks(nextSpaceId, { status: "pending" }),
        ]);
        setSpaceHome(home);
        setReviewPacks(packs.review_packs);
      } else {
        setSpaceHome(null);
        setReviewPacks([]);
      }
      setSpaceError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't load Brain spaces.";
      setSpaceError(message);
      onError?.(message);
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
      hasLoadedRef.current = true;
      setLoading(false);
    }
  }, [focus, onError, selectedSpaceId]);

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
  const selectedSpace = spaces.find((space) => space.id === selectedSpaceId) ?? null;
  const spaceReviewCount = spaceHome?.pending_review_count ?? reviewPacks.length;

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

  const decideReviewPack = useCallback(
    async (id: string, decision: "accept" | "reject") => {
      if (!selectedSpaceId || actingReviewPackIds.has(id)) return;
      setActingReviewPackIds((current) => new Set(current).add(id));
      try {
        if (decision === "accept") {
          await acceptBrainReviewPack(selectedSpaceId, id);
        } else {
          await rejectBrainReviewPack(selectedSpaceId, id);
        }
        setReviewPacks((current) => current.filter((pack) => pack.id !== id));
        setSpaceHome((current) =>
          current
            ? {
                ...current,
                pending_review_count: Math.max(0, current.pending_review_count - 1),
              }
            : current,
        );
        setSpaceError(null);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Couldn't update the Space review pack.";
        setSpaceError(message);
        onError?.(message);
      } finally {
        setActingReviewPackIds((current) => {
          const next = new Set(current);
          next.delete(id);
          return next;
        });
      }
    },
    [actingReviewPackIds, onError, selectedSpaceId],
  );

  const runExport = useCallback(
    async (profile: string) => {
      if (!selectedSpaceId) return;
      setExportMessage(null);
      try {
        const exported = await exportBrainSpace(selectedSpaceId, profile);
        setExportMessage(
          t(
            `${exported.profile} export ready: ${exported.files.length} files.`,
            `Экспорт ${exported.profile}: ${exported.files.length} файлов.`,
          ),
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : "Couldn't export this Space.";
        setSpaceError(message);
        onError?.(message);
      }
    },
    [onError, selectedSpaceId, t],
  );

  const prepareContext = useCallback(async () => {
    if (!selectedSpaceId || contextLoading) return;
    setContextLoading(true);
    setContextMessage(null);
    try {
      const context = await buildBrainContext(selectedSpaceId, {
        task: "Use this Space as the source of truth.",
        limit: 80,
      });
      setContextPreview(context.markdown);
      setContextMessage(
        t(
          `${context.claim_count} claims ready for assistant context.`,
          `${context.claim_count} утверждений готовы для контекста ассистента.`,
        ),
      );
      setSpaceError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't prepare Space context.";
      setSpaceError(message);
      onError?.(message);
    } finally {
      setContextLoading(false);
    }
  }, [contextLoading, onError, selectedSpaceId, t]);

  const shareSpace = useCallback(async () => {
    const email = shareEmail.trim();
    if (!selectedSpaceId || !email || sharing) return;
    setSharing(true);
    setShareMessage(null);
    try {
      await addBrainSpaceMember(selectedSpaceId, { email, role: shareRole });
      setShareEmail("");
      setShareMessage(
        t(`Shared with ${email} as ${shareRole}.`, `Открыт доступ для ${email}: ${shareRole}.`),
      );
      setSpaceError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't share this Space.";
      setSpaceError(message);
      onError?.(message);
    } finally {
      setSharing(false);
    }
  }, [onError, selectedSpaceId, shareEmail, shareRole, sharing, t]);

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

  const openSource = useCallback(
    (sourceKind: string, sourceId: string) => {
      if (sourceKind !== "recording" && sourceKind !== "item") return;
      onOpenSource?.(sourceKind, sourceId);
    },
    [onOpenSource],
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

  const spaceCockpitBody = (
    <section className="brain-panel__section">
      <div className="brain-panel__section-head">
        <h3>{t("Space", "Пространство")}</h3>
        <span>{spaces.length}</span>
      </div>
      {spaceError ? <p className="brain-panel__error-detail">{spaceError}</p> : null}
      {spaces.length > 0 ? (
        <>
          <div className="brain-panel__space-toolbar">
            <label>
              <span>{t("Space", "Пространство")}</span>
              <select
                value={selectedSpaceId ?? ""}
                onChange={(event) => {
                  setSelectedSpaceId(event.target.value || null);
                  setExportMessage(null);
                  setShareMessage(null);
                  setContextMessage(null);
                  setContextPreview(null);
                }}
              >
                {spaces.map((space) => (
                  <option key={space.id} value={space.id}>
                    {space.name}
                  </option>
                ))}
              </select>
            </label>
            {selectedSpace ? (
              <div className="brain-panel__space-meta">
                <strong>{selectedSpace.engine_profile}</strong>
                <span>{selectedSpace.role}</span>
                <span>{selectedSpace.kind}</span>
              </div>
            ) : null}
          </div>
          <div className="brain-panel__coverage">
            <div className="brain-panel__coverage-block">
              <span>{t("Pages", "Страницы")}</span>
              <strong>{spaceHome?.page_count ?? 0}</strong>
              <em>{t("living wiki pages", "страницы вики")}</em>
            </div>
            <div className="brain-panel__coverage-block">
              <span>{t("Sources", "Источники")}</span>
              <strong>{spaceHome?.source_count ?? 0}</strong>
              <em>{Object.keys(spaceHome?.source_counts ?? {}).join(" · ") || t("none", "нет")}</em>
            </div>
            <div className="brain-panel__coverage-block">
              <span>{t("Knowledge", "Знания")}</span>
              <strong>
                {Object.values(spaceHome?.claim_counts ?? {}).reduce((sum, count) => sum + count, 0)}
              </strong>
              <em>
                {Object.entries(spaceHome?.claim_counts ?? {})
                  .map(([kind, count]) => `${kind} ${count}`)
                  .join(" · ") || t("none", "нет")}
              </em>
            </div>
            <div className="brain-panel__coverage-block">
              <span>{t("Review", "Проверка")}</span>
              <strong>{spaceReviewCount}</strong>
              <em>{t("pending decisions", "ожидают решения")}</em>
            </div>
          </div>
          <div className="brain-panel__workflow">
            <div className="brain-panel__workflow-card">
              <span>{t("Use", "Использовать")}</span>
              <strong>{t("Prepare context", "Подготовить контекст")}</strong>
              <button type="button" disabled={contextLoading} onClick={() => void prepareContext()}>
                {contextLoading ? t("Preparing", "Готовлю") : t("Prepare", "Подготовить")}
              </button>
              {contextMessage ? <em>{contextMessage}</em> : null}
            </div>
            <form
              className="brain-panel__workflow-card"
              onSubmit={(event) => {
                event.preventDefault();
                void shareSpace();
              }}
            >
              <span>{t("Share", "Поделиться")}</span>
              <div className="brain-panel__share-row">
                <input
                  type="email"
                  value={shareEmail}
                  placeholder={t("teammate@example.com", "email@example.com")}
                  onChange={(event) => setShareEmail(event.target.value)}
                />
                <select
                  value={shareRole}
                  onChange={(event) => setShareRole(event.target.value as "viewer" | "editor")}
                >
                  <option value="viewer">{t("Viewer", "Читатель")}</option>
                  <option value="editor">{t("Editor", "Редактор")}</option>
                </select>
                <button type="submit" disabled={sharing || shareEmail.trim().length === 0}>
                  {sharing ? t("Sharing", "Открываю") : t("Share", "Поделиться")}
                </button>
              </div>
              {shareMessage ? <em>{shareMessage}</em> : null}
            </form>
          </div>
          {reviewPacks.length > 0 ? (
            <div className="brain-panel__rows brain-panel__rows--spaced">
              {reviewPacks.map((pack) => {
                const acting = actingReviewPackIds.has(pack.id);
                return (
                  <article key={pack.id} className="brain-panel__proposal">
                    <div>
                      <p className="brain-panel__proposal-meta">
                        <span>{pack.kind}</span>
                        <span>{pack.risk}</span>
                      </p>
                      <p className="brain-panel__proposal-content">{pack.title}</p>
                      <p className="brain-panel__proposal-detail">{pack.summary}</p>
                    </div>
                    <div className="brain-panel__proposal-actions">
                      <button
                        type="button"
                        aria-label={t("Reject review pack", "Отклонить пакет")}
                        disabled={acting}
                        onClick={() => void decideReviewPack(pack.id, "reject")}
                      >
                        ×
                      </button>
                      <button
                        type="button"
                        aria-label={t("Accept review pack", "Принять пакет")}
                        disabled={acting}
                        onClick={() => void decideReviewPack(pack.id, "accept")}
                      >
                        ✓
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : null}
          {spaceHome?.recent_pages.length ? (
            <div className="brain-panel__rows brain-panel__rows--spaced">
              {spaceHome.recent_pages.map((page) => (
                <div key={page.id} className="brain-panel__source-row">
                  <strong>{page.title}</strong>
                  <em>
                    {page.kind} · {page.claims.length} {t("claims", "утверждений")}
                  </em>
                </div>
              ))}
            </div>
          ) : null}
          <div className="brain-panel__export-row">
            {(spaceHome?.engine_profiles ?? ["obsidian", "gbrain", "mempalace"]).map((profile) => (
              <button key={profile} type="button" onClick={() => void runExport(profile)}>
                {profile}
              </button>
            ))}
          </div>
          {exportMessage ? (
            <p className="brain-panel__proposal-detail">{exportMessage}</p>
          ) : null}
          {contextPreview ? (
            <details className="brain-panel__context-preview">
              <summary>{t("Context preview", "Предпросмотр контекста")}</summary>
              <pre>{contextPreview}</pre>
            </details>
          ) : null}
        </>
      ) : (
        <p className="brain-panel__empty">{t("No Spaces yet.", "Пространств пока нет.")}</p>
      )}
    </section>
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
      {spaceCockpitBody}
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
              <button
                key={source.id}
                type="button"
                className="brain-panel__source-row brain-panel__source-row--button"
                onClick={() => openSource(source.source_kind, source.source_id)}
              >
                <strong>{source.title}</strong>
                <em>
                  {t(
                    `${source.entity_count} entities · ${sourceKindLabel(source.source_kind)}`,
                    `${source.entity_count} сущностей · ${sourceKindLabel(source.source_kind)}`,
                  )}
                </em>
              </button>
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
            onOpenSource={openSource}
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
          onOpenSource={openSource}
          focused={focus !== null}
          onResetFocus={() => setFocus(null)}
          locale={locale}
        />
      )}
    </div>
  );
}
