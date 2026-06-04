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
  onOpenInbox?: () => void;
  onOpenWai?: () => void | Promise<void>;
}

type BrainTab = "overview" | "index" | "wiki" | "graph";

const ENTITY_KINDS: Array<{ key: string; en: string; ru: string }> = [
  { key: "person", en: "People", ru: "Люди" },
  { key: "topic", en: "Topics", ru: "Темы" },
  { key: "project", en: "Projects", ru: "Проекты" },
];

/**
 * The Brain section: saved sources, approved knowledge, and the context Wai can
 * use. Home is the product surface; Knowledge and Map are secondary inspection
 * views. Honest empty + error states, with no silent fallback.
 */
export function BrainPanel({
  locale = "en",
  onError,
  onOpenSource,
  onOpenInbox,
  onOpenWai,
}: BrainPanelProps) {
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
  const approvedKnowledgeCount = Object.values(spaceHome?.claim_counts ?? {}).reduce(
    (sum, count) => sum + count,
    0,
  );
  const sourceCount =
    (overview?.recordings.total ?? stats.recordings ?? 0) +
    (overview?.materials.total ?? stats.items ?? 0);
  const memorySuggestionCount = Math.max(pendingReviewCount, proposals.length);
  const suggestionCount = reviewPacks.length + memorySuggestionCount;
  const brainName = selectedSpace?.name ?? t("Personal", "Личный");
  const hasApprovedKnowledge = approvedKnowledgeCount > 0;
  const canOpenWai = typeof onOpenWai === "function";

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
        if (exported.files.length === 0) {
          setExportMessage(
            t(
              "Nothing to export yet. Approved knowledge notes will appear here.",
              "Пока нечего экспортировать. Здесь появятся подтвержденные заметки.",
            ),
          );
        } else if (exported.files.length === 1) {
          setExportMessage(
            t("1 Markdown file is ready.", "Готов 1 Markdown-файл."),
          );
        } else {
          setExportMessage(
            t(
              `${exported.files.length} Markdown files are ready.`,
              `Готово Markdown-файлов: ${exported.files.length}.`,
            ),
          );
        }
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
        task: "Use this Brain as the source of truth.",
        limit: 80,
      });
      setContextPreview(context.markdown);
      if (context.claim_count === 0) {
        setContextMessage(
          t(
            "No approved knowledge yet. Approve suggestions first, then Wai can use them.",
            "Пока нет подтвержденных знаний. Сначала примите предложения, и Wai сможет их использовать.",
          ),
        );
      } else {
        setContextMessage(
          t(
            `${context.claim_count} approved items ready for Wai.`,
            `Подтверждено элементов для Wai: ${context.claim_count}.`,
          ),
        );
      }
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

  const copyContext = useCallback(async () => {
    if (!contextPreview) return;
    if (!navigator.clipboard?.writeText) {
      setContextMessage(
        t(
          "Context is ready in the preview below.",
          "Контекст готов в предпросмотре ниже.",
        ),
      );
      return;
    }
    await navigator.clipboard.writeText(contextPreview);
    setContextMessage(t("Context copied.", "Контекст скопирован."));
  }, [contextPreview, t]);

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

  const proposalLabel = useCallback(
    (proposal: MemoryProposal) =>
      proposal.risk === "high" ? t("Correction", "Исправление") : t("New fact", "Новый факт"),
    [t],
  );

  const authorityLabel = useCallback(
    (authority: string) => {
      if (authority === "self") return t("About you", "О вас");
      if (authority === "model") return t("Wai suggestion", "Предложение Wai");
      return sectionTitle(authority);
    },
    [sectionTitle, t],
  );

  const exportProfileLabel = useCallback(
    (profile: string) => {
      if (profile === "obsidian") return t("Export to Obsidian", "Экспорт в Obsidian");
      if (profile === "gbrain") return t("Export for GBrain", "Экспорт для GBrain");
      if (profile === "mempalace") return t("Export for MemPalace", "Экспорт для MemPalace");
      return t("Export notes", "Экспорт заметок");
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

  const brainHomeBody = (
    <>
      <section className="brain-panel__section brain-panel__section--hero">
        <div className="brain-panel__section-head">
          <div>
            <p className="brain-panel__eyebrow">{t("Use", "Использовать")}</p>
            <h3>{t("Use with Wai", "Использовать с Wai")}</h3>
          </div>
          <button
            type="button"
            className="wai-primary-button"
            disabled={contextLoading || !selectedSpaceId || !hasApprovedKnowledge}
            onClick={() => void prepareContext()}
          >
            {contextLoading ? t("Preparing", "Готовлю") : t("Use with Wai", "Использовать с Wai")}
          </button>
        </div>
        <p className="brain-panel__proposal-detail">
          {t(
            `Ask Wai using approved knowledge from ${brainName}.`,
            `Попросите Wai использовать подтвержденные знания из ${brainName}.`,
          )}
        </p>
        {sourceCount === 0 ? (
          <div className="brain-panel__empty">
            <p>
              {t(
                "Add recordings or materials to start building your Brain.",
                "Добавьте записи или материалы, чтобы начать собирать Мозг.",
              )}
            </p>
            {onOpenInbox ? (
              <button type="button" onClick={onOpenInbox}>
                {t("Open Inbox", "Открыть инбокс")}
              </button>
            ) : null}
          </div>
        ) : null}
        {!hasApprovedKnowledge ? (
          <p className="brain-panel__empty">
            {t(
              "No approved knowledge yet. Approve suggestions first, then Wai can use them.",
              "Пока нет подтвержденных знаний. Сначала примите предложения, и Wai сможет их использовать.",
            )}
          </p>
        ) : null}
        {contextMessage ? <p className="brain-panel__proposal-detail">{contextMessage}</p> : null}
        {contextPreview ? (
          <>
            <div className="brain-panel__export-row">
              <button type="button" onClick={() => void copyContext()}>
                {t("Copy context", "Скопировать контекст")}
              </button>
              <button type="button" disabled={!canOpenWai} onClick={() => void onOpenWai?.()}>
                {t("Open Ask Wai", "Открыть Wai")}
              </button>
            </div>
            <details className="brain-panel__context-preview">
              <summary>{t("What Wai will see", "Что увидит Wai")}</summary>
              <pre>{contextPreview}</pre>
            </details>
          </>
        ) : null}
      </section>

      <section className="brain-panel__section">
        <div className="brain-panel__section-head">
          <h3>{t("Brains", "Мозги")}</h3>
          <span>{spaces.length}</span>
        </div>
        {spaceError ? <p className="brain-panel__error-detail">{spaceError}</p> : null}
        {spaces.length > 0 ? (
          <>
            <div className="brain-panel__space-toolbar">
              <label>
                <span>{t("Brain", "Мозг")}</span>
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
            </div>
            <div className="brain-panel__coverage">
              <div className="brain-panel__coverage-block">
                <span>{t("Sources", "Источники")}</span>
                <strong>{sourceCount}</strong>
                <em>{t("saved recordings and materials", "записи и материалы")}</em>
              </div>
              <div className="brain-panel__coverage-block">
                <span>{t("Knowledge", "Знания")}</span>
                <strong>{approvedKnowledgeCount}</strong>
                <em>{t("approved items", "подтверждено")}</em>
              </div>
              <div className="brain-panel__coverage-block">
                <span>{t("Suggestions", "Предложения")}</span>
                <strong>{suggestionCount}</strong>
                <em>{t("need review", "нужно проверить")}</em>
              </div>
              <div className="brain-panel__coverage-block">
                <span>{t("Notes", "Заметки")}</span>
                <strong>{spaceHome?.page_count ?? 0}</strong>
                <em>{t("knowledge pages", "страницы знаний")}</em>
              </div>
            </div>
          </>
        ) : (
          <p className="brain-panel__empty">
            {t(
              "Add recordings or materials to start building your Brain.",
              "Добавьте записи или материалы, чтобы начать собирать Мозг.",
            )}
          </p>
        )}
      </section>

      <section className="brain-panel__section">
        <div className="brain-panel__section-head">
          <h3>{t("Review suggestions", "Проверить предложения")}</h3>
          <span>{suggestionCount}</span>
        </div>
        {reviewPacks.length > 0 ? (
          <>
            <p className="brain-panel__proposal-detail">
              {t(
                "Wai found possible knowledge for this Brain. Approve only what should guide future answers.",
                "Wai нашел возможные знания для этого Мозга. Подтверждайте только то, что должно влиять на будущие ответы.",
              )}
            </p>
            <div className="brain-panel__rows brain-panel__rows--spaced">
              {reviewPacks.map((pack) => {
                const acting = actingReviewPackIds.has(pack.id);
                return (
                  <article key={pack.id} className="brain-panel__proposal">
                    <div>
                      <p className="brain-panel__proposal-meta">
                        <span>{t("Knowledge suggestion", "Предложение знания")}</span>
                        <span>{pack.risk}</span>
                      </p>
                      <p className="brain-panel__proposal-content">{pack.title}</p>
                      <p className="brain-panel__proposal-detail">{pack.summary}</p>
                    </div>
                    <div className="brain-panel__proposal-actions">
                      <button
                        type="button"
                        aria-label={t("Ignore knowledge suggestion", "Игнорировать предложение знания")}
                        disabled={acting}
                        onClick={() => void decideReviewPack(pack.id, "reject")}
                      >
                        {t("Ignore", "Игнорировать")}
                      </button>
                      <button
                        type="button"
                        aria-label={t("Approve knowledge suggestion", "Подтвердить предложение знания")}
                        disabled={acting}
                        onClick={() => void decideReviewPack(pack.id, "accept")}
                      >
                        {t("Approve", "Подтвердить")}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </>
        ) : null}
        {proposals.length > 0 ? (
          <>
            <h4 className="brain-panel__group-title">{t("Memory suggestions", "Предложения памяти")}</h4>
            <div className="brain-panel__rows brain-panel__rows--spaced">
              {proposals.map((proposal) => {
                const acting = actingProposalIds.has(proposal.id);
                return (
                  <article key={proposal.id} className="brain-panel__proposal">
                    <div>
                      <p className="brain-panel__proposal-meta">
                        <span>{proposalLabel(proposal)}</span>
                        <span>{authorityLabel(proposal.authority)}</span>
                        <span>{Math.round(proposal.confidence * 100)}%</span>
                      </p>
                      <p className="brain-panel__proposal-content">{proposal.content}</p>
                      <p className="brain-panel__proposal-detail">{evidenceLabel(proposal)}</p>
                    </div>
                    <div className="brain-panel__proposal-actions">
                      <button
                        type="button"
                        aria-label={t("Ignore memory suggestion", "Игнорировать предложение памяти")}
                        disabled={acting}
                        onClick={() => void decideProposal(proposal.id, rejectMemoryProposal)}
                      >
                        {t("Ignore", "Игнорировать")}
                      </button>
                      <button
                        type="button"
                        aria-label={t("Approve memory suggestion", "Подтвердить предложение памяти")}
                        disabled={acting}
                        onClick={() => void decideProposal(proposal.id, acceptMemoryProposal)}
                      >
                        {t("Approve", "Подтвердить")}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </>
        ) : null}
        {suggestionCount === 0 && !reviewError ? (
          <p className="brain-panel__empty">
            {t("No suggestions need review.", "Нет предложений на проверку.")}
          </p>
        ) : null}
        {reviewError ? <p className="brain-panel__error-detail">{reviewError}</p> : null}
      </section>

      <section className="brain-panel__section">
        <h3>{t("Knowledge", "Знания")}</h3>
        {spaceHome?.recent_pages.length ? (
          <div className="brain-panel__rows brain-panel__rows--spaced">
            {spaceHome.recent_pages.map((page) => (
              <div key={page.id} className="brain-panel__source-row">
                <strong>{page.title}</strong>
                <em>
                  {page.kind} · {page.claims.length} {t("approved items", "подтверждено")}
                </em>
              </div>
            ))}
          </div>
        ) : null}
        {overview?.top_entities.length ? (
          <div className="brain-panel__rows brain-panel__rows--spaced">
            {overview.top_entities.map((entity) => entityOverviewRow(entity))}
          </div>
        ) : !spaceHome?.recent_pages.length ? (
          <p className="brain-panel__empty">
            {t(
              "No approved knowledge yet. Review suggestions or add more sources.",
              "Пока нет подтвержденных знаний. Проверьте предложения или добавьте источники.",
            )}
          </p>
        ) : null}
      </section>

      <section className="brain-panel__section">
        <h3>{t("Sources", "Источники")}</h3>
        <div className="brain-panel__coverage">
          {coverageBlock(t("Recordings", "Записи"), overview?.recordings, stats.recordings ?? 0)}
          {coverageBlock(t("Materials", "Материалы"), overview?.materials, stats.items ?? 0)}
        </div>
        {overview?.recent_sources.length ? (
          <div className="brain-panel__rows brain-panel__rows--spaced">
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
        ) : null}
      </section>

      <details className="brain-panel__context-preview">
        <summary>{t("Advanced", "Дополнительно")}</summary>
        <div className="brain-panel__workflow">
          <form
            className="brain-panel__workflow-card"
            onSubmit={(event) => {
              event.preventDefault();
              void shareSpace();
            }}
          >
            <span>{t("Share", "Поделиться")}</span>
            <strong>{t("Invite teammate", "Пригласить участника")}</strong>
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
                {sharing ? t("Inviting", "Приглашаю") : t("Invite", "Пригласить")}
              </button>
            </div>
            {shareMessage ? <em>{shareMessage}</em> : null}
          </form>
          <div className="brain-panel__workflow-card">
            <span>{t("Export", "Экспорт")}</span>
            <strong>{t("Export notes", "Экспорт заметок")}</strong>
            <div className="brain-panel__export-row">
              {(spaceHome?.engine_profiles ?? ["obsidian", "gbrain", "mempalace"]).map((profile) => (
                <button key={profile} type="button" onClick={() => void runExport(profile)}>
                  {exportProfileLabel(profile)}
                </button>
              ))}
            </div>
            {exportMessage ? <em>{exportMessage}</em> : null}
          </div>
        </div>
      </details>
    </>
  );

  const overviewBody = brainHomeBody;

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
            "Saved sources, approved knowledge, and what Wai can use to help you.",
            "Источники, подтвержденные знания и то, что Wai может использовать для помощи.",
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
          {t("Home", "Главная")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "index" || tab === "wiki"}
          className={`brain-panel__tab ${tab === "index" || tab === "wiki" ? "brain-panel__tab--active" : ""}`}
          onClick={() => setTab("index")}
        >
          {t("Knowledge", "Знания")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "graph"}
          className={`brain-panel__tab ${tab === "graph" ? "brain-panel__tab--active" : ""}`}
          onClick={() => setTab("graph")}
        >
          {t("Map", "Карта")}
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
            "Add recordings or materials to start building your Brain.",
            "Добавьте записи или материалы, чтобы начать собирать Мозг.",
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
              "Pick a person or topic from Knowledge to read its page.",
              "Выберите человека или тему в Знаниях, чтобы открыть страницу.",
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
