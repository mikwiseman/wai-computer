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
  type StreamMessageOptions,
} from "@/lib/companion";
import {
  type CompanionActionResolution,
  type CompanionTurn,
  type CompanionTurnItem,
  emptyTurn,
  ingestEvent,
  itemsFromStoredToolCalls,
  markTurnInterrupted,
  setActionResolution,
  setStoredActionResolution,
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
  stillWorking: string;
  turnFailed: string;
  turnFailedEmpty: string;
  somethingWentWrong: string;
  chatLabelPrefix: string;
  recordingFallback: string;
  actionsHeading: string;
  approve: string;
  approveAlways: string;
  reject: string;
  actionStatus: (status: string) => string;
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
    searchingRecordings: "Searching Inbox…",
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
    stillWorking: "Still working…",
    turnFailed: "Turn failed.",
    turnFailedEmpty: "Turn failed before Wai wrote a response.",
    somethingWentWrong: "Something went wrong",
    chatLabelPrefix: "Thread",
    recordingFallback: "Recording",
    actionsHeading: "Needs your approval",
    approve: "Approve",
    approveAlways: "Always",
    reject: "Reject",
    actionStatus: (s) =>
      ({
        executed: "Done",
        rejected: "Rejected",
        dispatched: "Sent to your Mac",
        expired: "Expired",
        failed: "Failed",
      })[s] ?? s,
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
    searchingRecordings: "Ищем по Инбоксу…",
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
    stillWorking: "Еще работает…",
    turnFailed: "Не удалось выполнить запрос.",
    turnFailedEmpty: "Не удалось выполнить запрос до ответа Wai.",
    somethingWentWrong: "Что-то пошло не так",
    chatLabelPrefix: "Диалог",
    recordingFallback: "Запись",
    actionsHeading: "Нужно ваше подтверждение",
    approve: "Подтвердить",
    approveAlways: "Всегда",
    reject: "Отклонить",
    actionStatus: (s) =>
      ({
        executed: "Готово",
        rejected: "Отклонено",
        dispatched: "Отправлено на ваш Mac",
        expired: "Истекло",
        failed: "Ошибка",
      })[s] ?? s,
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
  // Type-and-go: a first message to auto-send once the thread is active, so the
  // user's first keystroke in the inbox IS the turn (no extra click).
  initialMessage?: string | null;
  onInitialMessageConsumed?: () => void;
  onChatCreated?: (chat: CompanionConversation) => void;
  embedded?: boolean;
  viewingRecordingId?: string | null;
  viewingFolderId?: string | null;
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

function storedTimelineItemsForMessage(message: CompanionMessage): CompanionTurnItem[] {
  const items = itemsFromStoredToolCalls(message.tool_calls);
  if (items.length === 0) return [];

  const text = plainText(message.content);
  if (!text.trim()) return items;
  return [...items, { kind: "text", id: `stored-text-${message.id}`, markdown: text }];
}

function stoppedText(locale: Locale): string {
  return locale === "ru" ? "Остановлено." : "Stopped.";
}

function failedText(locale: Locale): string {
  return locale === "ru" ? "Не удалось." : "Failed.";
}

function persistedTurnState(
  status: string | undefined,
  copy: CompanionCopy,
  hasVisibleOutput: boolean,
): { role: "status" | "alert"; className: string; text: string; testId: string } | null {
  if (status === "streaming") {
    return {
      role: "status",
      className: "wai-message-state wai-message-state--streaming",
      text: copy.stillWorking,
      testId: "companion-message-streaming-status",
    };
  }
  if (status === "failed") {
    return {
      role: "alert",
      className: "wai-message-state wai-message-state--failed",
      text: hasVisibleOutput ? copy.turnFailed : copy.turnFailedEmpty,
      testId: "companion-message-failed-status",
    };
  }
  return null;
}

function localDateString(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function browserTimezone(): string | undefined {
  if (typeof Intl === "undefined") return undefined;
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return typeof timezone === "string" && timezone.trim() ? timezone : undefined;
}

function turnOptions({
  viewingRecordingId,
  viewingFolderId,
}: {
  viewingRecordingId?: string | null;
  viewingFolderId?: string | null;
}): StreamMessageOptions {
  const options: StreamMessageOptions = {
    clientLocalDate: localDateString(new Date()),
  };
  const timezone = browserTimezone();
  if (timezone) options.clientTimezone = timezone;
  if (viewingRecordingId) options.viewingRecordingId = viewingRecordingId;
  if (viewingFolderId) options.viewingFolderId = viewingFolderId;
  return options;
}

export function CompanionPanel({
  recordings,
  locale: localeProp,
  initialChatId,
  initialMessage,
  onInitialMessageConsumed,
  onChatCreated,
  embedded = false,
  viewingRecordingId,
  viewingFolderId,
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
  const initialSentRef = useRef<string | null>(null);

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
    setError(null);
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

  // Auto-follow the stream. `behavior:"auto"` + rAF instead of "smooth":
  // liveTurn changes on every streamed token, and a per-token smooth scroll
  // never finishes animating — the compositor thrashes for the whole answer.
  // rAF coalesces bursts of tokens into at most one scroll per frame.
  const scrollScheduled = useRef(false);
  useEffect(() => {
    if (scrollScheduled.current) return;
    scrollScheduled.current = true;
    requestAnimationFrame(() => {
      scrollScheduled.current = false;
      threadEndRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    });
  }, [messages, liveTurn]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // Type-and-go: auto-send the handed-in first message once the thread is active.
  // Keyed by chat+text so a re-render never re-sends, yet a later type-and-go
  // (even with identical text in a different thread) still fires.
  useEffect(() => {
    const msg = initialMessage?.trim();
    if (!msg || !activeChatId || loading) return;
    const key = `${activeChatId}::${msg}`;
    if (initialSentRef.current === key) return;
    initialSentRef.current = key;
    void handleSend(undefined, msg);
    onInitialMessageConsumed?.();
  }, [initialMessage, activeChatId]); // eslint-disable-line react-hooks/exhaustive-deps

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

  async function handleSend(event?: FormEvent<HTMLFormElement>, overrideText?: string) {
    event?.preventDefault();
    const question = (overrideText ?? input).trim();
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
      for await (const evt of streamMessage(
        chatId,
        question,
        controller.signal,
        turnOptions({ viewingRecordingId, viewingFolderId }),
      )) {
        if (controller.signal.aborted) break;
        if (evt.type === "error") {
          receivedError = true;
          turn = markTurnInterrupted(turn, failedText(locale));
          setLiveTurn(turn);
          setError(evt.message);
          break;
        }
        if (evt.type === "turn_start" && evt.title) {
          const title = evt.title;
          setChats((prev) =>
            prev.map((c) =>
              c.id === chatId && !(c.title && c.title.trim())
                ? { ...c, title }
                : c,
            ),
          );
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
        setLiveTurn(emptyTurn());
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
      turn = markTurnInterrupted(turn, failedText(locale));
      setLiveTurn(turn);
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
    setMessages((prev) =>
      prev.map((message) => {
        const nextToolCalls = setStoredActionResolution(
          message.tool_calls,
          actionId,
          resolution,
        );
        return nextToolCalls === message.tool_calls
          ? message
          : { ...message, tool_calls: nextToolCalls };
      }),
    );
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
      const detail = formatError(e, copy);
      setActionRes(actionId, {
        state: "resolved",
        status: e instanceof ApiError && e.status === 410 ? "expired" : "failed",
        detail,
      });
      setError(detail);
    }
  }

  function handleStop() {
    abortRef.current?.abort();
    abortRef.current = null;
    setLiveTurn((prev) =>
      markTurnInterrupted(prev, stoppedText(locale)),
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

        {messages.map((m) => {
          if (m.role === "user") {
            return (
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
            );
          }

          const completedTurn = completedTurns[m.id];
          const storedItems = completedTurn ? [] : storedTimelineItemsForMessage(m);
          const assistantText = plainText(m.content);
          const hasVisibleOutput =
            Boolean(completedTurn)
            || storedItems.length > 0
            || assistantText.trim().length > 0;
          const state = persistedTurnState(m.status, copy, hasVisibleOutput);

          return (
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
              {state ? (
                <p
                  role={state.role}
                  className={state.className}
                  data-testid={state.testId}
                >
                  {state.text}
                </p>
              ) : null}
              {completedTurn ? (
                <CompanionTimeline
                  items={completedTurn.items}
                  isLive={false}
                  locale={locale}
                  onResolve={
                    activeChatId
                      ? (aid, dec) => void handleResolve(activeChatId, aid, dec)
                      : undefined
                  }
                />
              ) : storedItems.length > 0 ? (
                <CompanionTimeline
                  items={storedItems}
                  isLive={false}
                  locale={locale}
                  onResolve={
                    activeChatId
                      ? (aid, dec) => void handleResolve(activeChatId, aid, dec)
                      : undefined
                  }
                />
              ) : (
                <Markdown text={assistantText} />
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
          );
        })}

        {loading || !turnIsEmpty(liveTurn) ? (
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
