"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  acceptBrainReviewPack,
  addBrainSpaceMember,
  exportBrainSpace,
  getBrainGraph,
  getBrainSpaceHome,
  listBrainReviewPacks,
  listBrainSpacePages,
  listBrainSpaces,
  rejectBrainReviewPack,
} from "@/lib/api";
import type {
  BrainGraph,
  BrainOverviewEntity,
  BrainPage,
  BrainReviewPack,
  BrainSpace,
  BrainSpaceHome,
  BrainSpaceSourceSummary,
} from "@/lib/types";
import { EntityWikiView } from "@/components/EntityWikiView";

interface BrainPanelProps {
  locale?: string;
  onError?: (message: string) => void;
  onOpenSource?: (sourceKind: "recording" | "item", sourceId: string) => void;
  onOpenInbox?: () => void;
  onOpenWai?: (brain: { spaceId: string; spaceName: string }) => void | Promise<void>;
}

type BrainTab = "home" | "knowledge";

const CLAIM_KIND_LABELS: Record<string, { en: string; ru: string }> = {
  fact: { en: "Facts", ru: "Факты" },
  decision: { en: "Decisions", ru: "Решения" },
  principle: { en: "Principles", ru: "Принципы" },
  workflow_rule: { en: "Rules", ru: "Правила" },
  open_question: { en: "Open questions", ru: "Открытые вопросы" },
  conflict: { en: "Conflicts", ru: "Конфликты" },
};

/**
 * Brain is the user's confirmed project knowledge. Personal Wai Memory stays
 * outside this panel so project facts and user preferences do not collapse into
 * one review queue.
 */
export function BrainPanel({
  locale = "en",
  onError,
  onOpenSource,
  onOpenInbox,
  onOpenWai,
}: BrainPanelProps) {
  const [graph, setGraph] = useState<BrainGraph | null>(null);
  const [spaces, setSpaces] = useState<BrainSpace[]>([]);
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null);
  const [spaceHome, setSpaceHome] = useState<BrainSpaceHome | null>(null);
  const [pages, setPages] = useState<BrainPage[]>([]);
  const [reviewPacks, setReviewPacks] = useState<BrainReviewPack[]>([]);
  const [tab, setTab] = useState<BrainTab>("home");
  const [selectedEntity, setSelectedEntity] = useState<{ id: string; name: string } | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [spaceError, setSpaceError] = useState<string | null>(null);
  const [actingReviewPackIds, setActingReviewPackIds] = useState<Set<string>>(new Set());
  const [asking, setAsking] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const [shareEmail, setShareEmail] = useState("");
  const [shareRole, setShareRole] = useState<"viewer" | "editor">("viewer");
  const [shareMessage, setShareMessage] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const hasLoadedRef = useRef(false);

  const t = useCallback(
    (en: string, ru: string) => (locale === "ru" ? ru : en),
    [locale],
  );

  const selectedSpace = spaces.find((space) => space.id === selectedSpaceId) ?? null;
  const brainName = selectedSpace?.name ?? t("Personal", "Личный");

  const load = useCallback(async () => {
    const showFullLoading = !hasLoadedRef.current;
    if (showFullLoading) setLoading(true);
    setError(null);
    try {
      const [graphData, spaceList] = await Promise.all([
        getBrainGraph({ include_sources: true, limit: 120 }),
        listBrainSpaces(),
      ]);
      setGraph(graphData);
      setSpaces(spaceList.spaces);

      const nextSpaceId =
        selectedSpaceId && spaceList.spaces.some((space) => space.id === selectedSpaceId)
          ? selectedSpaceId
          : (spaceList.spaces[0]?.id ?? null);
      setSelectedSpaceId(nextSpaceId);

      if (nextSpaceId) {
        const [home, packs, pageList] = await Promise.all([
          getBrainSpaceHome(nextSpaceId),
          listBrainReviewPacks(nextSpaceId, { status: "pending" }),
          listBrainSpacePages(nextSpaceId),
        ]);
        setSpaceHome(home);
        setReviewPacks(packs.review_packs);
        setPages(pageList.pages);
      } else {
        setSpaceHome(null);
        setReviewPacks([]);
        setPages([]);
      }
      setSpaceError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't load your Brain.";
      setError(message);
      onError?.(message);
    } finally {
      hasLoadedRef.current = true;
      setLoading(false);
    }
  }, [onError, selectedSpaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const approvedKnowledgeCount = Object.values(spaceHome?.claim_counts ?? {}).reduce(
    (sum, count) => sum + count,
    0,
  );
  const sourceCount = spaceHome?.source_count ?? 0;
  const suggestionCount = Math.max(spaceHome?.pending_review_count ?? 0, reviewPacks.length);
  const noteCount = spaceHome?.page_count ?? pages.length;
  const sources = useMemo(() => spaceHome?.sources ?? [], [spaceHome?.sources]);
  const recentPages = useMemo(
    () => (pages.length > 0 ? pages : (spaceHome?.recent_pages ?? [])),
    [pages, spaceHome?.recent_pages],
  );
  const canOpenWai = Boolean(selectedSpace && onOpenWai);
  const topEntities = graph?.overview?.top_entities ?? [];
  const hasAnything =
    spaces.length > 0 ||
    sourceCount > 0 ||
    approvedKnowledgeCount > 0 ||
    suggestionCount > 0 ||
    topEntities.length > 0;

  const claimGroups = useMemo(() => {
    const groups = new Map<string, BrainPage["claims"]>();
    for (const page of recentPages) {
      for (const claim of page.claims) {
        if (claim.status !== "active") continue;
        const bucket = groups.get(claim.kind) ?? [];
        bucket.push(claim);
        groups.set(claim.kind, bucket);
      }
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [recentPages]);

  const claimKindLabel = useCallback(
    (kind: string) => {
      const label = CLAIM_KIND_LABELS[kind];
      if (!label) return kind;
      return t(label.en, label.ru);
    },
    [t],
  );

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

  const openKnowledgeEntity = useCallback((entity: BrainOverviewEntity) => {
    setSelectedEntity({ id: entity.id, name: entity.name });
    setTab("knowledge");
  }, []);

  const onSpaceChange = useCallback((spaceId: string) => {
    setSelectedSpaceId(spaceId || null);
    setSelectedEntity(null);
    setActionMessage(null);
    setExportMessage(null);
    setShareMessage(null);
  }, []);

  const askWai = useCallback(async () => {
    if (!selectedSpace || !onOpenWai || asking) return;
    setAsking(true);
    setActionMessage(null);
    try {
      await onOpenWai({ spaceId: selectedSpace.id, spaceName: selectedSpace.name });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't open Wai with this Brain.";
      setSpaceError(message);
      onError?.(message);
    } finally {
      setAsking(false);
    }
  }, [asking, onError, onOpenWai, selectedSpace]);

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
          err instanceof Error ? err.message : "Couldn't update this knowledge suggestion.";
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
      const message = err instanceof Error ? err.message : "Couldn't share this Brain.";
      setSpaceError(message);
      onError?.(message);
    } finally {
      setSharing(false);
    }
  }, [onError, selectedSpaceId, shareEmail, shareRole, sharing, t]);

  const runExport = useCallback(
    async (profile: string) => {
      if (!selectedSpaceId) return;
      setExportMessage(null);
      try {
        const exported = await exportBrainSpace(selectedSpaceId, profile);
        if (exported.files.length === 0) {
          setExportMessage(t("No files yet.", "Пока нет файлов."));
        } else if (exported.files.length === 1) {
          setExportMessage(t("1 Markdown file is ready.", "Готов 1 Markdown-файл."));
        } else {
          setExportMessage(
            t(
              `${exported.files.length} Markdown files are ready.`,
              `Готово Markdown-файлов: ${exported.files.length}.`,
            ),
          );
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "Couldn't export this Brain.";
        setSpaceError(message);
        onError?.(message);
      }
    },
    [onError, selectedSpaceId, t],
  );

  const exportProfileLabel = useCallback(
    (profile: string) => {
      if (profile === "obsidian") return t("Obsidian", "Obsidian");
      if (profile === "gbrain") return t("GBrain", "GBrain");
      if (profile === "mempalace") return t("MemPalace", "MemPalace");
      return profile;
    },
    [t],
  );

  const metricCard = (label: string, value: number, detail: string) => (
    <div className="brain-panel__coverage-block">
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{detail}</em>
    </div>
  );

  const sourceRow = (source: BrainSpaceSourceSummary) => (
    <button
      key={source.id}
      type="button"
      className="brain-panel__source-row brain-panel__source-row--button"
      onClick={() => openSource(source.source_kind, source.source_id)}
    >
      <strong>{source.source_title ?? t("Untitled source", "Источник без названия")}</strong>
      <em>{sourceKindLabel(source.source_kind)}</em>
    </button>
  );

  const knowledgePageRow = (page: BrainPage) => (
    <article key={page.id} className="brain-panel__source-row">
      <strong>{page.title}</strong>
      <em>
        {page.kind} · {page.claims.length} {t("approved", "подтверждено")}
      </em>
      {page.claims.slice(0, 3).map((claim) => (
        <p key={claim.id} className="brain-panel__proposal-detail">
          {claim.text}
        </p>
      ))}
    </article>
  );

  const entityRow = (entity: BrainOverviewEntity) => (
    <button
      key={entity.id}
      type="button"
      className="brain-panel__entity-row"
      onClick={() => openKnowledgeEntity(entity)}
    >
      <span className="brain-panel__entity-icon">
        {entity.type === "person" ? "P" : entity.type === "project" ? "F" : "#"}
      </span>
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

  const homeBody = (
    <>
      <section className="brain-panel__section brain-panel__section--hero">
        <div>
          <span className="brain-panel__eyebrow">{t("Ask Brain", "Спросить Мозг")}</span>
          <h3>{t(`Ask Wai with ${brainName}`, `Спросить Wai с «${brainName}»`)}</h3>
          <p className="brain-panel__proposal-detail">
            {approvedKnowledgeCount > 0
              ? t(
                  `${approvedKnowledgeCount} approved knowledge items will be attached to the chat.`,
                  `В чат будет добавлено подтвержденных знаний: ${approvedKnowledgeCount}.`,
                )
              : t(
                  "There is no approved knowledge yet. You can still open Wai and add sources from Inbox.",
                  "Пока нет подтвержденных знаний. Можно открыть Wai и добавить источники из инбокса.",
                )}
          </p>
          {actionMessage ? <p className="brain-panel__proposal-detail">{actionMessage}</p> : null}
        </div>
        <button type="button" className="wai-primary-button" disabled={!canOpenWai || asking} onClick={() => void askWai()}>
          {asking ? t("Opening…", "Открываю…") : t("Ask Wai", "Спросить Wai")}
        </button>
      </section>

      <section className="brain-panel__section">
        <div className="brain-panel__section-head">
          <h3>{t("Project Knowledge", "Знания проекта")}</h3>
          {spaces.length > 0 ? (
            <label className="brain-panel__space-toolbar">
              <span>{t("Brain", "Мозг")}</span>
              <select value={selectedSpaceId ?? ""} onChange={(event) => onSpaceChange(event.target.value)}>
                {spaces.map((space) => (
                  <option key={space.id} value={space.id}>
                    {space.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        {spaceError ? <p className="brain-panel__error-detail">{spaceError}</p> : null}
        <div className="brain-panel__coverage">
          {metricCard(t("Sources", "Источники"), sourceCount, t("saved", "сохранено"))}
          {metricCard(t("Knowledge", "Знания"), approvedKnowledgeCount, t("approved", "подтверждено"))}
          {metricCard(t("Review", "Проверка"), suggestionCount, t("suggestions", "предложения"))}
          {metricCard(t("Pages", "Страницы"), noteCount, t("notes", "заметки"))}
        </div>
      </section>

      <section className="brain-panel__section">
        <div className="brain-panel__section-head">
          <h3>{t("Review Knowledge", "Проверить знания")}</h3>
          <span>{suggestionCount}</span>
        </div>
        {reviewPacks.length > 0 ? (
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
                    <button type="button" disabled={acting} onClick={() => void decideReviewPack(pack.id, "reject")}>
                      {t("Ignore", "Игнорировать")}
                    </button>
                    <button type="button" disabled={acting} onClick={() => void decideReviewPack(pack.id, "accept")}>
                      {t("Approve", "Подтвердить")}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <p className="brain-panel__empty">
            {t("No project knowledge is waiting for review.", "Нет знаний проекта на проверку.")}
          </p>
        )}
      </section>

      <section className="brain-panel__section">
        <div className="brain-panel__section-head">
          <h3>{t("Knowledge", "Знания")}</h3>
          <button type="button" className="brain-panel__link-button" onClick={() => setTab("knowledge")}>
            {t("Open", "Открыть")}
          </button>
        </div>
        {recentPages.length > 0 ? (
          <div className="brain-panel__rows brain-panel__rows--spaced">
            {recentPages.slice(0, 4).map(knowledgePageRow)}
          </div>
        ) : (
          <p className="brain-panel__empty">
            {t("Approved knowledge pages will appear here.", "Здесь появятся подтвержденные страницы знаний.")}
          </p>
        )}
      </section>

      <section className="brain-panel__section">
        <div className="brain-panel__section-head">
          <h3>{t("Sources", "Источники")}</h3>
          {onOpenInbox ? (
            <button type="button" className="brain-panel__link-button" onClick={onOpenInbox}>
              {t("Open Inbox", "Открыть инбокс")}
            </button>
          ) : null}
        </div>
        {sources.length > 0 ? (
          <div className="brain-panel__rows brain-panel__rows--spaced">
            {sources.slice(0, 8).map(sourceRow)}
          </div>
        ) : (
          <p className="brain-panel__empty">
            {t("Add recordings or materials from Inbox to build this Brain.", "Добавьте записи или материалы из инбокса.")}
          </p>
        )}
      </section>

      <section className="brain-panel__section brain-panel__section--muted">
        <div className="brain-panel__section-head">
          <h3>{t("Wai Memory", "Память Wai")}</h3>
        </div>
        <p className="brain-panel__proposal-detail">
          {t(
            "Personal preferences stay separate from Project Knowledge.",
            "Личные предпочтения хранятся отдельно от знаний проекта.",
          )}
        </p>
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
            <strong>{t("Markdown", "Markdown")}</strong>
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

  const knowledgeBody = selectedEntity ? (
    <>
      <button
        type="button"
        className="brain-panel__link-button brain-panel__back-button"
        onClick={() => setSelectedEntity(null)}
      >
        {t("Back to Knowledge", "Назад к знаниям")}
      </button>
      <EntityWikiView
        entityId={selectedEntity.id}
        onNavigate={(id, name) => setSelectedEntity({ id, name })}
        onError={onError}
        onOpenSource={openSource}
        locale={locale}
      />
    </>
  ) : (
    <>
      <section className="brain-panel__section">
        <h3>{t("Approved Pages", "Подтвержденные страницы")}</h3>
        {recentPages.length > 0 ? (
          <div className="brain-panel__rows brain-panel__rows--spaced">
            {recentPages.map(knowledgePageRow)}
          </div>
        ) : (
          <p className="brain-panel__empty">
            {t("Approve suggestions or add sources to create knowledge pages.", "Подтвердите предложения или добавьте источники.")}
          </p>
        )}
      </section>

      {claimGroups.length > 0 ? (
        <section className="brain-panel__section">
          <h3>{t("Confirmed Items", "Подтвержденные элементы")}</h3>
          {claimGroups.map(([kind, claims]) => (
            <div key={kind} className="brain-panel__group">
              <h4 className="brain-panel__group-title">{claimKindLabel(kind)}</h4>
              <div className="brain-panel__rows brain-panel__rows--spaced">
                {claims.map((claim) => (
                  <article key={claim.id} className="brain-panel__source-row">
                    <strong>{claim.text}</strong>
                    <em>{Math.round(claim.confidence * 100)}%</em>
                  </article>
                ))}
              </div>
            </div>
          ))}
        </section>
      ) : null}

      {topEntities.length > 0 ? (
        <section className="brain-panel__section">
          <h3>{t("Explore", "Исследовать")}</h3>
          <div className="brain-panel__rows brain-panel__rows--spaced">
            {topEntities.slice(0, 12).map(entityRow)}
          </div>
        </section>
      ) : null}
    </>
  );

  return (
    <div className="brain-panel">
      <header className="brain-panel__header">
        <h2 className="brain-panel__title">{t("Brain", "Мозг")}</h2>
        <p className="brain-panel__subtitle">
          {t(
            "Sources, confirmed knowledge, and chats that use it.",
            "Источники, подтвержденные знания и чаты, которые их используют.",
          )}
        </p>
      </header>

      <div className="brain-panel__tabs" role="tablist" aria-label={t("Brain views", "Виды мозга")}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "home"}
          className={`brain-panel__tab ${tab === "home" ? "brain-panel__tab--active" : ""}`}
          onClick={() => setTab("home")}
        >
          {t("Home", "Главная")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "knowledge"}
          className={`brain-panel__tab ${tab === "knowledge" ? "brain-panel__tab--active" : ""}`}
          onClick={() => setTab("knowledge")}
        >
          {t("Knowledge", "Знания")}
        </button>
      </div>

      {loading ? (
        <p className="brain-panel__status">{t("Loading…", "Загрузка…")}</p>
      ) : error ? (
        <div className="brain-panel__error">
          <p>{t("Couldn't load your Brain.", "Не удалось загрузить Мозг.")}</p>
          <p className="brain-panel__error-detail">{error}</p>
          <button type="button" className="wai-primary-button" onClick={() => void load()}>
            {t("Retry", "Повторить")}
          </button>
        </div>
      ) : !hasAnything ? (
        <section className="brain-panel__section">
          <h3>{t("Start with sources", "Начните с источников")}</h3>
          <p className="brain-panel__empty">
            {t("Add recordings or materials from Inbox to build your Brain.", "Добавьте записи или материалы из инбокса.")}
          </p>
          {onOpenInbox ? (
            <button type="button" className="wai-primary-button" onClick={onOpenInbox}>
              {t("Open Inbox", "Открыть инбокс")}
            </button>
          ) : null}
        </section>
      ) : tab === "home" ? (
        homeBody
      ) : (
        knowledgeBody
      )}
    </div>
  );
}
