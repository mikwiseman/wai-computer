"use client";

import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  createChat,
  deleteChat,
  getChat,
  listChats,
  patchChat,
  resolveAction,
  streamMessage,
} from "@/lib/companion";
import {
  type CompanionActionResolution,
  type CompanionTurn,
  emptyTurn,
  failRunningTools,
  ingestEvent,
  setActionResolution,
  turnIsEmpty,
} from "@/lib/companionTimeline";
import { ApiError } from "@/lib/http";
import type {
  CompanionConversation,
  CompanionMessage,
  Recording,
} from "@/lib/types";
import { CompanionTimeline, Markdown } from "./CompanionTurnCards";

type Decision = "once" | "always" | "reject";

type Locale = "en" | "ru";

interface CompanionCopy {
  heading: string;
  chatsButton: (n: number) => string;
  hideChats: string;
  newChat: string;
  noChatsYet: string;
  emptyHeading: string;
  emptyBody: string;
  starterPrompts: [string, string, string, string];
  searchingRecordings: string;
  composerPlaceholder: string;
  composerAriaLabel: string;
  stop: string;
  ask: string;
  rename: string;
  delete: string;
  renameTitle: string;
  renameLabel: string;
  renameSave: string;
  renameCancel: string;
  deleteTitle: string;
  deleteBody: string;
  deleteConfirm: string;
  deleteCancel: string;
  user: string;
  assistant: string;
  somethingWentWrong: string;
  chatLabelPrefix: string;
  recordingFallback: string;
}

const COPY: Record<Locale, CompanionCopy> = {
  en: {
    heading: "Wai",
    chatsButton: (n) => `Threads (${n})`,
    hideChats: "Hide threads",
    newChat: "+ New session",
    noChatsYet: "No threads yet.",
    emptyHeading: "What should Wai do?",
    emptyBody: "Search, remember, plan, or act across your Inbox.",
    starterPrompts: [
      "Find what I promised this week.",
      "Summarize my last meeting and suggest next steps.",
      "Remember that I prefer short weekly launch updates.",
      "Open the source I need to continue this task.",
    ],
    searchingRecordings: "Searching Inbox...",
    composerPlaceholder: "Give Wai a task",
    composerAriaLabel: "Give Wai a task",
    stop: "Stop",
    ask: "Send",
    rename: "Rename",
    delete: "Delete",
    renameTitle: "Rename thread",
    renameLabel: "Thread name",
    renameSave: "Save",
    renameCancel: "Cancel",
    deleteTitle: "Delete this thread?",
    deleteBody: "This will permanently remove the thread and all of its messages.",
    deleteConfirm: "Delete",
    deleteCancel: "Cancel",
    user: "You",
    assistant: "Wai",
    somethingWentWrong: "Something went wrong",
    chatLabelPrefix: "Thread",
    recordingFallback: "Recording",
  },
  ru: {
    heading: "Wai",
    chatsButton: (n) => `Диалоги (${n})`,
    hideChats: "Скрыть диалоги",
    newChat: "+ Новая сессия",
    noChatsYet: "Диалогов пока нет.",
    emptyHeading: "Что сделать Wai?",
    emptyBody: "Ищет, помнит, планирует и действует по Инбоксу.",
    starterPrompts: [
      "Найди, что я обещал на этой неделе.",
      "Сделай сводку последней встречи и предложи следующие шаги.",
      "Запомни, что я предпочитаю короткие еженедельные апдейты по запуску.",
      "Открой источник, который нужен, чтобы продолжить эту задачу.",
    ],
    searchingRecordings: "Ищем по Инбоксу...",
    composerPlaceholder: "Дайте Wai задачу",
    composerAriaLabel: "Дайте Wai задачу",
    stop: "Стоп",
    ask: "Отправить",
    rename: "Переименовать",
    delete: "Удалить",
    renameTitle: "Переименовать диалог",
    renameLabel: "Название диалога",
    renameSave: "Сохранить",
    renameCancel: "Отмена",
    deleteTitle: "Удалить диалог?",
    deleteBody: "Диалог и все его сообщения будут удалены навсегда.",
    deleteConfirm: "Удалить",
    deleteCancel: "Отмена",
    user: "Вы",
    assistant: "Wai",
    somethingWentWrong: "Что-то пошло не так",
    chatLabelPrefix: "Диалог",
    recordingFallback: "Запись",
  },
};

function detectLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  const candidates = [
    ...Array.from(navigator.languages ?? []),
    navigator.language,
  ].filter(Boolean);
  return candidates[0]?.toLowerCase().startsWith("ru") ? "ru" : "en";
}

interface CompanionPanelProps {
  recordings: Recording[];
  locale?: Locale;
  initialChatId?: string | null;
  onChatCreated?: (chat: CompanionConversation) => void;
  embedded?: boolean;
}

interface StreamingCitation {
  index: number;
  segment_id: string;
  recording_id: string;
  start_ms: number | null;
  end_ms: number | null;
}

function formatError(error: unknown, copy: CompanionCopy): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return copy.somethingWentWrong;
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object"
    && error !== null
    && "name" in error
    && (error as { name?: unknown }).name === "AbortError"
  );
}

function chatLabel(chat: CompanionConversation, copy: CompanionCopy, locale: Locale): string {
  if (chat.title && chat.title.trim()) return chat.title;
  const t = chat.last_message_at ?? chat.created_at;
  const d = new Date(t);
  const bcp = locale === "ru" ? "ru-RU" : undefined;
  return `${copy.chatLabelPrefix} · ${d.toLocaleDateString(bcp)} ${d.toLocaleTimeString(bcp, { hour: "2-digit", minute: "2-digit" })}`;
}

function plainText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const out: string[] = [];
    for (const block of content) {
      if (block && typeof block === "object" && "text" in block) {
        const t = (block as { text?: unknown }).text;
        if (typeof t === "string") out.push(t);
      }
    }
    return out.join("");
  }
  return "";
}

export function CompanionPanel({
  recordings,
  locale: localeProp,
  initialChatId,
  onChatCreated,
  embedded = false,
}: CompanionPanelProps) {
  const [locale, setLocale] = useState<Locale>(localeProp ?? "en");
  const copy = COPY[locale];

  const [chats, setChats] = useState<CompanionConversation[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [activeScope, setActiveScope] = useState<CompanionConversation["scope"]>(null);
  const [messages, setMessages] = useState<CompanionMessage[]>([]);
  const [liveTurn, setLiveTurn] = useState<CompanionTurn>(emptyTurn());
  const [completedTurns, setCompletedTurns] = useState<Record<string, CompanionTurn>>({});
  const [stage, setStage] = useState<"idle" | "searching" | "composing">("idle");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [renameTarget, setRenameTarget] = useState<{ chatId: string; value: string } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const threadEndRef = useRef<HTMLDivElement | null>(null);
  const initialized = useRef(false);

  useEffect(() => {
    if (localeProp) {
      setLocale(localeProp);
      return;
    }
    setLocale(detectLocale());
  }, [localeProp]);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void (async () => {
      try {
        const data = await listChats();
        setChats(data.chats);
        if (initialChatId && data.chats.some((chat) => chat.id === initialChatId)) {
          setActiveChatId(initialChatId);
        } else if (data.chats.length > 0) {
          setActiveChatId(data.chats[0].id);
        }
      } catch (e) {
        setError(formatError(e, COPY[detectLocale()]));
      }
    })();
  }, [initialChatId]);

  useEffect(() => {
    if (!initialChatId) return;
    setActiveChatId(initialChatId);
  }, [initialChatId]);

  useEffect(() => {
    if (!activeChatId) {
      setMessages([]);
      setActiveScope(null);
      return;
    }
    void (async () => {
      try {
        const detail = await getChat(activeChatId);
        setMessages(detail.messages);
        setActiveScope(detail.scope);
        setLiveTurn(emptyTurn());
        setCompletedTurns({});
      } catch (e) {
        setError(formatError(e, copy));
      }
    })();
  }, [activeChatId, copy]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, liveTurn]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const recordingTitlesById = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of recordings) m.set(r.id, r.title ?? copy.recordingFallback);
    return m;
  }, [recordings, copy.recordingFallback]);

  async function handleNewChat() {
    setError(null);
    try {
      const chat = await createChat();
      setChats((prev) => [chat, ...prev]);
      setActiveChatId(chat.id);
      setActiveScope(chat.scope);
      onChatCreated?.(chat);
    } catch (e) {
      setError(formatError(e, copy));
    }
  }

  function requestDeleteChat(chatId: string) {
    setDeleteTarget(chatId);
  }

  async function confirmDeleteChat() {
    const chatId = deleteTarget;
    if (!chatId) return;
    setDeleteTarget(null);
    setError(null);
    try {
      await deleteChat(chatId);
      setChats((prev) => prev.filter((c) => c.id !== chatId));
      if (activeChatId === chatId) {
        setActiveChatId(null);
      }
    } catch (e) {
      setError(formatError(e, copy));
    }
  }

  function requestRenameChat(chatId: string, currentTitle: string) {
    setRenameTarget({ chatId, value: currentTitle });
  }

  async function submitRenameChat(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!renameTarget) return;
    const next = renameTarget.value.trim();
    const chatId = renameTarget.chatId;
    setRenameTarget(null);
    if (!next) return;
    try {
      const updated = await patchChat(chatId, { title: next });
      setChats((prev) => prev.map((c) => (c.id === chatId ? updated : c)));
    } catch (e) {
      setError(formatError(e, copy));
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = input.trim();
    if (!question || loading) return;

    // Abort any prior turn so two streams never overlap.
    abortRef.current?.abort();

    setError(null);
    setInput("");
    setLoading(true);
    setStage("searching");

    let chatId = activeChatId;
    if (!chatId) {
      try {
        const chat = await createChat();
        setChats((prev) => [chat, ...prev]);
        setActiveChatId(chat.id);
        setActiveScope(chat.scope);
        setMessages([]);
        onChatCreated?.(chat);
        chatId = chat.id;
      } catch (e) {
        setError(formatError(e, copy));
        setLoading(false);
        setStage("idle");
        return;
      }
    }

    // Optimistically render the user turn.
    const optimisticUser: CompanionMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: question,
      tool_calls: null,
      citations: [],
      model: null,
      input_tokens: null,
      output_tokens: null,
      cached_tokens: null,
      latency_ms: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticUser]);

    let turn = emptyTurn();
    setLiveTurn(turn);

    const controller = new AbortController();
    abortRef.current = controller;
    let receivedError = false;

    try {
      for await (const evt of streamMessage(chatId, question, controller.signal)) {
        if (controller.signal.aborted) break;
        if (evt.type === "error") {
          receivedError = true;
          turn = failRunningTools(turn, locale === "ru" ? "Остановлено" : "Stopped");
          setLiveTurn(turn);
          setError(evt.message);
          break;
        }
        turn = ingestEvent(turn, evt);
        setLiveTurn(turn);
        if (evt.type === "token") setStage("composing");
        if (evt.type === "done") {
          if (!turnIsEmpty(turn)) {
            const messageId = evt.message_id;
            const completed = turn;
            setCompletedTurns((prev) => ({ ...prev, [messageId]: completed }));
          }
          break;
        }
      }
      if (controller.signal.aborted) return;
      // Reconcile optimistic rows with the persisted state (success OR error).
      try {
        const refreshed = await getChat(chatId);
        setMessages(refreshed.messages);
      } catch (refetchErr) {
        if (!receivedError) setError(formatError(refetchErr, copy));
      }
      if (!receivedError) {
        setChats((prev) => {
          const idx = prev.findIndex((c) => c.id === chatId);
          if (idx < 0) return prev;
          const next = [...prev];
          const [moved] = next.splice(idx, 1);
          return [moved, ...next];
        });
      }
    } catch (e) {
      if (controller.signal.aborted || isAbortError(e)) {
        return;
      }
      setError(formatError(e, copy));
      try {
        const refreshed = await getChat(chatId);
        setMessages(refreshed.messages);
      } catch {
        /* keep optimistic row visible */
      }
    } finally {
      setLoading(false);
      setStage("idle");
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
    }
  }

  function setActionRes(actionId: string, resolution: CompanionActionResolution) {
    setLiveTurn((prev) => setActionResolution(prev, actionId, resolution));
    setCompletedTurns((prev) => {
      let changed = false;
      const next: Record<string, CompanionTurn> = {};
      for (const [key, value] of Object.entries(prev)) {
        const updated = setActionResolution(value, actionId, resolution);
        next[key] = updated;
        if (updated !== value) changed = true;
      }
      return changed ? next : prev;
    });
  }

  async function handleResolve(chatId: string, actionId: string, decision: Decision) {
    setActionRes(actionId, { state: "executing" });
    try {
      const resp = await resolveAction(chatId, actionId, decision);
      setActionRes(actionId, {
        state: "resolved",
        status: resp.status,
        detail: resp.recipient ?? "",
      });
    } catch (e) {
      setActionRes(actionId, {
        state: "resolved",
        status: "failed",
        detail: formatError(e, copy),
      });
    }
  }

  function handleStop() {
    abortRef.current?.abort();
    abortRef.current = null;
    setLiveTurn((prev) =>
      failRunningTools(prev, locale === "ru" ? "Остановлено" : "Stopped"),
    );
    setLoading(false);
    setStage("idle");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.closest("form")?.requestSubmit();
    }
  }

  const hasNoChats = chats.length === 0 && !activeChatId;
  const isEmptyActive =
    !!activeChatId && messages.length === 0 && turnIsEmpty(liveTurn) && !loading;
  const hasBrainScope = Boolean(activeScope?.brain_space_id);

  return (
    <section className="qa-panel">
      <header className="qa-panel__header">
        <h2>{copy.heading}</h2>
        {hasBrainScope ? (
          <span className="scope-chip">
            {locale === "ru" ? "Мозг подключен" : "Brain attached"}
          </span>
        ) : null}
        {!embedded ? (
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="ghost-button compact-button"
            onClick={() => setSidebarCollapsed((c) => !c)}
            aria-pressed={!sidebarCollapsed}
            data-testid="companion-toggle-history"
          >
            {sidebarCollapsed ? copy.chatsButton(chats.length) : copy.hideChats}
          </button>
          <button
            type="button"
            className="ghost-button compact-button"
            onClick={handleNewChat}
            data-testid="companion-new-chat"
          >
            {copy.newChat}
          </button>
        </div>
        ) : null}
      </header>

      {!embedded && !sidebarCollapsed ? (
        <aside
          className="qa-scope"
          aria-label={locale === "ru" ? "Диалоги Wai" : "Wai threads"}
          data-testid="companion-chat-list"
        >
          {chats.length === 0 ? (
            <span>{copy.noChatsYet}</span>
          ) : (
            chats.map((c) => (
              <span key={c.id} className="scope-chip" style={{ gap: 6 }}>
                <button
                  type="button"
                  onClick={() => setActiveChatId(c.id)}
                  aria-current={c.id === activeChatId ? "page" : undefined}
                  style={{
                    background: "transparent",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                    fontWeight: c.id === activeChatId ? 600 : 400,
                  }}
                >
                  {chatLabel(c, copy, locale)}
                </button>
                <button
                  type="button"
                  className="ghost-button compact-button"
                  onClick={() => requestRenameChat(c.id, c.title ?? "")}
                  aria-label={copy.rename}
                >
                  {copy.rename}
                </button>
                <button
                  type="button"
                  className="ghost-button compact-button danger-button"
                  onClick={() => requestDeleteChat(c.id)}
                  aria-label={copy.delete}
                >
                  {copy.delete}
                </button>
              </span>
            ))
          )}
        </aside>
      ) : null}

      <div className="qa-output" data-testid="companion-thread">
        {hasNoChats ? (
          <div className="empty-state empty-state--center">
            <h3>{copy.emptyHeading}</h3>
            <p>{copy.emptyBody}</p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
              {copy.starterPrompts.map((p) => (
                <button
                  key={p}
                  type="button"
                  className="ghost-button compact-button"
                  onClick={() => setInput(p)}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {isEmptyActive ? (
          <div className="empty-state empty-state--center">
            <h3>{copy.emptyHeading}</h3>
            <p>{copy.emptyBody}</p>
          </div>
        ) : null}

        {messages.map((m) =>
          m.role === "user" ? (
            <article
              key={m.id}
              className="qa-bubble"
              data-role="user"
              data-testid="companion-message-user"
              style={{ marginBottom: 12, whiteSpace: "pre-wrap" }}
            >
              <strong style={{ display: "block", fontSize: 12, opacity: 0.6 }}>
                {copy.user}
              </strong>
              <div>{plainText(m.content)}</div>
            </article>
          ) : (
            <article
              key={m.id}
              className="qa-bubble qa-bubble--assistant"
              data-role="assistant"
              data-testid="companion-message-assistant"
              style={{ marginBottom: 12 }}
            >
              <strong style={{ display: "block", fontSize: 12, opacity: 0.6 }}>
                {copy.assistant}
              </strong>
              {completedTurns[m.id] ? (
                <CompanionTimeline
                  items={completedTurns[m.id].items}
                  isLive={false}
                  locale={locale}
                  onResolve={
                    activeChatId
                      ? (aid, dec) => void handleResolve(activeChatId, aid, dec)
                      : undefined
                  }
                />
              ) : (
                <Markdown text={plainText(m.content)} />
              )}
              {m.citations.length > 0 ? (
                <CitationStrip
                  citations={m.citations.map((c) => ({
                    index: c.citation_index,
                    segment_id: c.segment_id ?? "",
                    recording_id: c.recording_id ?? "",
                    start_ms: null,
                    end_ms: null,
                  }))}
                  recordingTitles={recordingTitlesById}
                  fallbackTitle={copy.recordingFallback}
                />
              ) : null}
            </article>
          ),
        )}

        {loading ? (
          <article
            className="qa-bubble qa-bubble--assistant qa-bubble--loading"
            data-testid="companion-streaming"
          >
            <strong style={{ display: "block", fontSize: 12, opacity: 0.6 }}>
              {copy.assistant}
            </strong>
            {turnIsEmpty(liveTurn) ? (
              <div style={{ fontStyle: "italic", opacity: 0.7 }}>
                {stage === "searching"
                  ? locale === "ru"
                    ? "Думаю…"
                    : "Thinking…"
                  : copy.searchingRecordings}
              </div>
            ) : (
              <CompanionTimeline
                items={liveTurn.items}
                isLive={true}
                locale={locale}
                onResolve={
                  activeChatId
                    ? (aid, dec) => void handleResolve(activeChatId, aid, dec)
                    : undefined
                }
              />
            )}
            {liveTurn.citations.length > 0 ? (
              <CitationStrip
                citations={liveTurn.citations}
                recordingTitles={recordingTitlesById}
                fallbackTitle={copy.recordingFallback}
              />
            ) : null}
          </article>
        ) : null}

        <div ref={threadEndRef} />

        {error ? (
          <p role="alert" className="inline-alert">
            {error}
          </p>
        ) : null}
      </div>

      <form className="qa-input" onSubmit={handleSend}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={copy.composerPlaceholder}
          rows={3}
          disabled={loading}
          data-testid="companion-composer"
          aria-label={copy.composerAriaLabel}
        />
        {loading ? (
          <button type="button" onClick={handleStop} data-testid="companion-stop">
            {copy.stop}
          </button>
        ) : (
          <button type="submit" disabled={input.trim().length === 0}>
            {copy.ask}
          </button>
        )}
      </form>

      {deleteTarget ? (
        <ConfirmModal
          title={copy.deleteTitle}
          body={copy.deleteBody}
          confirmLabel={copy.deleteConfirm}
          cancelLabel={copy.deleteCancel}
          onConfirm={() => void confirmDeleteChat()}
          onCancel={() => setDeleteTarget(null)}
        />
      ) : null}

      {renameTarget ? (
        <RenameModal
          title={copy.renameTitle}
          label={copy.renameLabel}
          saveLabel={copy.renameSave}
          cancelLabel={copy.renameCancel}
          value={renameTarget.value}
          onChange={(value) =>
            setRenameTarget((prev) => (prev ? { ...prev, value } : prev))
          }
          onSubmit={submitRenameChat}
          onCancel={() => setRenameTarget(null)}
        />
      ) : null}
    </section>
  );
}

function CitationStrip({
  citations,
  recordingTitles,
  fallbackTitle,
}: {
  citations: StreamingCitation[];
  recordingTitles: Map<string, string>;
  fallbackTitle: string;
}) {
  const sorted = [...citations].sort((a, b) => a.index - b.index);
  return (
    <div
      className="qa-sources"
      style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}
      data-testid="companion-citations"
    >
      {sorted.map((c) => {
        const title = recordingTitles.get(c.recording_id) ?? fallbackTitle;
        return (
          <span key={`${c.segment_id}-${c.index}`} className="scope-chip">
            [{c.index}] {title}
            {c.start_ms !== null ? ` · ${formatMs(c.start_ms)}` : ""}
          </span>
        );
      })}
    </div>
  );
}

function formatMs(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function ConfirmModal({
  title,
  body,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") onCancel();
  }
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="companion-confirm-title"
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
      onKeyDown={handleKey}
      data-testid="companion-confirm-modal"
    >
      <div className="modal-card">
        <h3 id="companion-confirm-title">{title}</h3>
        <p>{body}</p>
        <div className="modal-actions">
          <button
            type="button"
            className="ghost-button compact-button"
            onClick={onCancel}
            data-testid="companion-confirm-cancel"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className="ghost-button compact-button danger-button"
            onClick={onConfirm}
            data-testid="companion-confirm-accept"
            autoFocus
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function RenameModal({
  title,
  label,
  saveLabel,
  cancelLabel,
  value,
  onChange,
  onSubmit,
  onCancel,
}: {
  title: string;
  label: string;
  saveLabel: string;
  cancelLabel: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
}) {
  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") onCancel();
  }
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="companion-rename-title"
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
      onKeyDown={handleKey}
      data-testid="companion-rename-modal"
    >
      <form className="modal-card" onSubmit={onSubmit}>
        <h3 id="companion-rename-title">{title}</h3>
        <label className="modal-field">
          <span>{label}</span>
          <input
            type="text"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            autoFocus
            data-testid="companion-rename-input"
          />
        </label>
        <div className="modal-actions">
          <button
            type="button"
            className="ghost-button compact-button"
            onClick={onCancel}
            data-testid="companion-rename-cancel"
          >
            {cancelLabel}
          </button>
          <button
            type="submit"
            className="ghost-button compact-button"
            data-testid="companion-rename-save"
          >
            {saveLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
