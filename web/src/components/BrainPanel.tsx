"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  acceptBrainReviewPack,
  addBrainSpaceMember,
  askBrain,
  exportBrainSpace,
  getBrainSpaceHome,
  listBrainReviewPacks,
  listBrainSpaces,
  listEntities,
  rejectBrainReviewPack,
} from "@/lib/api";
import type {
  BrainAnswer,
  BrainReviewPack,
  BrainSpace,
  BrainSpaceHome,
  BrainSpaceSourceSummary,
  Entity,
  EntityType,
} from "@/lib/types";
import { EntityWikiView } from "@/components/EntityWikiView";

interface BrainPanelProps {
  locale?: string;
  onError?: (message: string) => void;
  onOpenSource?: (sourceKind: "recording" | "item", sourceId: string) => void;
  onOpenInbox?: () => void;
  onOpenWai?: (brain: { spaceId: string; spaceName: string }) => void | Promise<void>;
}

type PageFilter = "all" | "person" | "project" | "topic";

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

/**
 * Brain is one surface: a single Ask box over everything you've recorded, and a
 * browsable list of living Pages (people / projects / topics) that compile
 * themselves from your sources. Curated knowledge + sources sit quietly below.
 */
export function BrainPanel({
  locale = "en",
  onError,
  onOpenSource,
  onOpenInbox,
  onOpenWai,
}: BrainPanelProps) {
  const t = useCallback((en: string, ru: string) => (locale === "ru" ? ru : en), [locale]);

  // Ask your Brain
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<BrainAnswer | null>(null);
  const [asking, setAsking] = useState(false);

  // Pages (entities)
  const [entities, setEntities] = useState<Entity[]>([]);
  const [filter, setFilter] = useState<PageFilter>("all");
  const [search, setSearch] = useState("");
  const [selectedEntity, setSelectedEntity] = useState<{ id: string; name: string } | null>(null);

  // Curated knowledge (Brain spaces) — demoted into the disclosure below
  const [spaces, setSpaces] = useState<BrainSpace[]>([]);
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null);
  const [spaceHome, setSpaceHome] = useState<BrainSpaceHome | null>(null);
  const [reviewPacks, setReviewPacks] = useState<BrainReviewPack[]>([]);
  const [actingReviewPackIds, setActingReviewPackIds] = useState<Set<string>>(new Set());
  const [shareEmail, setShareEmail] = useState("");
  const [shareRole, setShareRole] = useState<"viewer" | "editor">("viewer");
  const [shareMessage, setShareMessage] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const [exportMessage, setExportMessage] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [curatedError, setCuratedError] = useState<string | null>(null);
  const hasLoadedRef = useRef(false);

  const selectedSpace = spaces.find((s) => s.id === selectedSpaceId) ?? null;

  const load = useCallback(async () => {
    if (!hasLoadedRef.current) setLoading(true);
    setError(null);
    try {
      const [entityList, spaceList] = await Promise.all([
        listEntities({ limit: 200 }),
        listBrainSpaces(),
      ]);
      setEntities(entityList);
      setSpaces(spaceList.spaces);
      const nextSpaceId =
        selectedSpaceId && spaceList.spaces.some((s) => s.id === selectedSpaceId)
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
      setCuratedError(null);
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

  const ask = useCallback(async () => {
    const q = question.trim();
    if (!q || asking) return;
    setAsking(true);
    try {
      setAnswer(await askBrain(q));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't ask your Brain.";
      setError(message);
      onError?.(message);
    } finally {
      setAsking(false);
    }
  }, [asking, onError, question]);

  const openSource = useCallback(
    (sourceKind: string, sourceId: string) => {
      if (sourceKind !== "recording" && sourceKind !== "item") return;
      onOpenSource?.(sourceKind, sourceId);
    },
    [onOpenSource],
  );

  const decideReviewPack = useCallback(
    async (id: string, decision: "accept" | "reject") => {
      if (!selectedSpaceId || actingReviewPackIds.has(id)) return;
      setActingReviewPackIds((cur) => new Set(cur).add(id));
      try {
        if (decision === "accept") await acceptBrainReviewPack(selectedSpaceId, id);
        else await rejectBrainReviewPack(selectedSpaceId, id);
        setReviewPacks((cur) => cur.filter((p) => p.id !== id));
        setCuratedError(null);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Couldn't update this suggestion.";
        setCuratedError(message);
        onError?.(message);
      } finally {
        setActingReviewPackIds((cur) => {
          const next = new Set(cur);
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
      setShareMessage(t(`Shared with ${email} as ${shareRole}.`, `Доступ открыт: ${email} (${shareRole}).`));
      setCuratedError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't share this Brain.";
      setCuratedError(message);
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
        const n = exported.files.length;
        setExportMessage(
          n === 0
            ? t("No files yet.", "Пока нет файлов.")
            : n === 1
              ? t("1 Markdown file is ready.", "Готов 1 Markdown-файл.")
              : t(`${n} Markdown files are ready.`, `Готово Markdown-файлов: ${n}.`),
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : "Couldn't export this Brain.";
        setCuratedError(message);
        onError?.(message);
      }
    },
    [onError, selectedSpaceId, t],
  );

  const exportProfileLabel = useCallback((profile: string) => {
    if (profile === "obsidian") return "Obsidian";
    if (profile === "gbrain") return "GBrain";
    if (profile === "mempalace") return "MemPalace";
    return profile;
  }, []);

  const visiblePages = useMemo(() => {
    const q = search.trim().toLowerCase();
    return entities.filter(
      (e) =>
        (filter === "all" || e.type === filter) &&
        (q === "" || e.name.toLowerCase().includes(q)),
    );
  }, [entities, filter, search]);

  const approvedKnowledgeCount = Object.values(spaceHome?.claim_counts ?? {}).reduce(
    (sum, n) => sum + n,
    0,
  );
  const sources = spaceHome?.sources ?? [];
  const hasAnything =
    entities.length > 0 ||
    approvedKnowledgeCount > 0 ||
    reviewPacks.length > 0 ||
    sources.length > 0;

  const freshness = answer?.freshness;
  const headsUp =
    freshness?.stale && (freshness.weeks_since ?? 0) > 0
      ? t(
          `Heads-up: nothing has been added about this in ${freshness.weeks_since} weeks.`,
          `Важно: по этой теме ничего не добавляли уже ${freshness.weeks_since} нед.`,
        )
      : null;

  const pageRow = (e: Entity) => (
    <button
      key={e.id}
      type="button"
      className="brain-panel__entity-row"
      onClick={() => setSelectedEntity({ id: e.id, name: e.name })}
    >
      <span className="brain-panel__entity-icon">{entityGlyph(e.type)}</span>
      <span>
        <strong>{e.name}</strong>
        <em>{t(e.type, e.type)}</em>
      </span>
      <small>
        {e.source_count ?? 0} {t("sources", "источн.")}
      </small>
    </button>
  );

  const sourceRow = (source: BrainSpaceSourceSummary) => (
    <button
      key={source.id}
      type="button"
      className="brain-panel__source-row brain-panel__source-row--button"
      onClick={() => openSource(source.source_kind, source.source_id)}
    >
      <strong>{source.source_title ?? t("Untitled source", "Источник без названия")}</strong>
      <em>{source.source_kind === "recording" ? t("recording", "запись") : t("material", "материал")}</em>
    </button>
  );

  const askPanel = (
    <section className="brain-ask">
      <form
        className="brain-ask__bar"
        onSubmit={(event) => {
          event.preventDefault();
          void ask();
        }}
      >
        <input
          className="brain-ask__input"
          value={question}
          placeholder={t("Ask your Brain anything…", "Спросите свой Мозг о чём угодно…")}
          aria-label={t("Ask your Brain", "Спросить Мозг")}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <button type="submit" className="wai-primary-button" disabled={asking || question.trim() === ""}>
          {asking ? t("Thinking…", "Думаю…") : t("Ask", "Спросить")}
        </button>
      </form>

      {answer ? (
        <div className="brain-ask__answer">
          {answer.answer ? (
            <p className="brain-ask__answer-text">{answer.answer}</p>
          ) : (
            <p className="brain-ask__answer-empty">
              {t("Nothing in your recordings answers this yet.", "В ваших записях пока нет ответа на это.")}
            </p>
          )}

          {answer.citations.length > 0 ? (
            <div className="brain-ask__citations">
              {answer.citations.map((c, i) => (
                <button
                  key={c.id}
                  type="button"
                  className="brain-ask__chip"
                  onClick={() => openSource(c.source_kind, c.source_id)}
                  title={c.title ?? undefined}
                >
                  [{i + 1}] {c.title ?? t("Recording", "Запись")}
                </button>
              ))}
            </div>
          ) : null}

          {answer.gaps.length > 0 ? (
            <div className="brain-ask__gaps">
              <span className="brain-ask__gaps-title">{t("What I don't know", "Чего я не знаю")}</span>
              <ul>
                {answer.gaps.map((gap) => (
                  <li key={gap}>{gap}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {headsUp ? <p className="brain-ask__heads-up">⚠ {headsUp}</p> : null}

          {selectedSpace && onOpenWai ? (
            <button
              type="button"
              className="brain-panel__link-button"
              onClick={() => void onOpenWai({ spaceId: selectedSpace.id, spaceName: selectedSpace.name })}
            >
              {t("Open full chat", "Открыть полный чат")}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );

  const pagesSection = (
    <section className="brain-panel__section">
      <div className="brain-panel__section-head">
        <h3>{t("Pages", "Страницы")}</h3>
        <div className="brain-pages__filters" role="tablist" aria-label={t("Filter pages", "Фильтр страниц")}>
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
          {visiblePages.map(pageRow)}
        </div>
      ) : (
        <p className="brain-panel__empty">
          {entities.length === 0
            ? t("Pages appear as Wai finds people, projects, and topics in your recordings.", "Страницы появляются, когда Wai находит людей, проекты и темы в ваших записях.")
            : t("No pages match.", "Нет совпадений.")}
        </p>
      )}
    </section>
  );

  const curatedDisclosure = (
    <details className="brain-panel__context-preview">
      <summary>{t("Curated knowledge · Sources", "Подтверждённые знания · Источники")}</summary>

      {spaces.length > 1 ? (
        <label className="brain-panel__space-toolbar">
          <span>{t("Brain", "Мозг")}</span>
          <select
            value={selectedSpaceId ?? ""}
            onChange={(event) => setSelectedSpaceId(event.target.value || null)}
          >
            {spaces.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {curatedError ? <p className="brain-panel__error-detail">{curatedError}</p> : null}

      <section className="brain-panel__section">
        <div className="brain-panel__section-head">
          <h4>{t("Review", "Проверка")}</h4>
          <span>{reviewPacks.length}</span>
        </div>
        {reviewPacks.length > 0 ? (
          <div className="brain-panel__rows brain-panel__rows--spaced">
            {reviewPacks.map((pack) => {
              const acting = actingReviewPackIds.has(pack.id);
              return (
                <article key={pack.id} className="brain-panel__proposal">
                  <div>
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
          <p className="brain-panel__empty">{t("Nothing waiting for review.", "Нет знаний на проверку.")}</p>
        )}
      </section>

      <section className="brain-panel__section">
        <div className="brain-panel__section-head">
          <h4>{t("Sources", "Источники")}</h4>
          {onOpenInbox ? (
            <button type="button" className="brain-panel__link-button" onClick={onOpenInbox}>
              {t("Open Inbox", "Открыть инбокс")}
            </button>
          ) : null}
        </div>
        {sources.length > 0 ? (
          <div className="brain-panel__rows brain-panel__rows--spaced">{sources.slice(0, 8).map(sourceRow)}</div>
        ) : (
          <p className="brain-panel__empty">{t("Add recordings or materials from Inbox.", "Добавьте записи или материалы из инбокса.")}</p>
        )}
      </section>

      <div className="brain-panel__workflow">
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
            <select value={shareRole} onChange={(event) => setShareRole(event.target.value as "viewer" | "editor")}>
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

      <p className="brain-panel__proposal-detail brain-panel__memory-note">
        {t("Personal preferences live in Settings → Memory.", "Личные предпочтения — в Настройки → Память.")}
      </p>
    </details>
  );

  return (
    <div className="brain-panel">
      <header className="brain-panel__header">
        <h2 className="brain-panel__title">{t("Brain", "Мозг")}</h2>
        <p className="brain-panel__subtitle">
          {t(
            "Ask anything you've recorded — and open a living page on anyone or anything.",
            "Спросите о чём угодно из записей — и откройте живую страницу о любом человеке или теме.",
          )}
        </p>
      </header>

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
      ) : selectedEntity ? (
        <>
          <button
            type="button"
            className="brain-panel__link-button brain-panel__back-button"
            onClick={() => setSelectedEntity(null)}
          >
            {t("Back to Pages", "Назад к страницам")}
          </button>
          <EntityWikiView
            entityId={selectedEntity.id}
            onNavigate={(id, name) => setSelectedEntity({ id, name })}
            onError={onError}
            onOpenSource={openSource}
            locale={locale}
          />
        </>
      ) : !hasAnything ? (
        <>
          {askPanel}
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
        </>
      ) : (
        <>
          {askPanel}
          {pagesSection}
          {curatedDisclosure}
        </>
      )}
    </div>
  );
}
