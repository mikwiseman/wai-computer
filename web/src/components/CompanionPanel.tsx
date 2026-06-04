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
import { ApiError } from "@/lib/http";
import type {
  CompanionConversation,
  CompanionEvent,
  CompanionMessage,
  Recording,
} from "@/lib/types";

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
  actionsHeading: string;
  approve: string;
  approveAlways: string;
  reject: string;
  actionStatus: (status: string) => string;
}

const COPY: Record<Locale, CompanionCopy> = {
  en: {
    heading: "Ask Wai",
    chatsButton: (n) => `Threads (${n})`,
    hideChats: "Hide threads",
    newChat: "+ New thread",
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
    composerPlaceholder: "Ask Wai to search, remember, plan, or act...",
    composerAriaLabel: "Ask Wai to search, remember, plan, or act",
    stop: "Stop",
    ask: "Ask",
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
    heading: "Спросить Wai",
    chatsButton: (n) => `Диалоги (${n})`,
    hideChats: "Скрыть диалоги",
    newChat: "+ Новый диалог",
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
    composerPlaceholder: "Попросите Wai искать, помнить, планировать или действовать...",
    composerAriaLabel: "Попросить Wai искать, помнить, планировать или действовать",
    stop: "Стоп",
    ask: "Спросить",
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
}

interface StreamingCitation {
  index: number;
  segment_id: string;
  recording_id: string;
  start_ms: number | null;
  end_ms: number | null;
}

interface StreamingAssistant {
  text: string;
  citations: StreamingCitation[];
  toolCalls: { call_id: string; tool: string; summary: string | null }[];
}

interface ProposedAction {
  action_id: string;
  kind: string;
  tool: string;
  preview: string;
  recipient: string | null;
  expires_at: string;
  // pending | resolving | executed | rejected | dispatched | expired | failed
  status: string;
  detail?: string;
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
  initialMessage,
  onInitialMessageConsumed,
  onChatCreated,
  embedded = false,
}: CompanionPanelProps) {
  const [locale, setLocale] = useState<Locale>(localeProp ?? "en");
  const copy = COPY[locale];

  const [chats, setChats] = useState<CompanionConversation[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<CompanionMessage[]>([]);
  const [streamingAssistant, setStreamingAssistant] =
    useState<StreamingAssistant | null>(null);
  const [stage, setStage] = useState<"idle" | "searching" | "composing">("idle");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [renameTarget, setRenameTarget] = useState<{ chatId: string; value: string } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [pendingActions, setPendingActions] = useState<ProposedAction[]>([]);
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
    setPendingActions([]);
    if (!activeChatId) {
      setMessages([]);
      return;
    }
    void (async () => {
      try {
        const detail = await getChat(activeChatId);
        setMessages(detail.messages);
        setStreamingAssistant(null);
      } catch (e) {
        setError(formatError(e, copy));
      }
    })();
  }, [activeChatId, copy]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streamingAssistant?.text]);

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

    const streaming: StreamingAssistant = { text: "", citations: [], toolCalls: [] };
    setStreamingAssistant(streaming);

    const controller = new AbortController();
    abortRef.current = controller;
    let receivedError = false;

    try {
      for await (const evt of streamMessage(chatId, question, controller.signal)) {
        if (controller.signal.aborted) break;
        if (evt.type === "error") {
          receivedError = true;
          setError(evt.message);
          break;
        }
        handleEvent(evt, streaming);
        if (evt.type === "done") break;
      }
      if (controller.signal.aborted) return;
      // Reconcile optimistic rows with the persisted state (success OR error).
      try {
        const refreshed = await getChat(chatId);
        setMessages(refreshed.messages);
      } catch (refetchErr) {
        if (!receivedError) setError(formatError(refetchErr, copy));
      }
      setStreamingAssistant(null);
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
      setStreamingAssistant(null);
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

  function handleEvent(evt: CompanionEvent, streaming: StreamingAssistant) {
    switch (evt.type) {
      case "turn_start":
        // The server titles a new chat on its first turn; reflect it live so the
        // thread list stops showing "Thread · HH:MM" before the reload.
        if (evt.title) {
          const title = evt.title;
          setChats((prev) =>
            prev.map((c) =>
              c.id === activeChatId && !(c.title && c.title.trim())
                ? { ...c, title }
                : c,
            ),
          );
        }
        return;
      case "tool_call":
        streaming.toolCalls.push({
          call_id: evt.call_id,
          tool: evt.tool,
          summary: null,
        });
        setStreamingAssistant({ ...streaming });
        return;
      case "tool_result": {
        const tc = streaming.toolCalls.find((t) => t.call_id === evt.call_id);
        if (tc) tc.summary = evt.summary;
        setStreamingAssistant({ ...streaming });
        return;
      }
      case "token":
        streaming.text += evt.text;
        if (streaming.text.length > 0) setStage("composing");
        setStreamingAssistant({ ...streaming });
        return;
      case "citation":
        if (
          !streaming.citations.some(
            (c) => c.index === evt.index && c.segment_id === evt.segment_id,
          )
        ) {
          streaming.citations.push({
            index: evt.index,
            segment_id: evt.segment_id,
            recording_id: evt.recording_id,
            start_ms: evt.start_ms,
            end_ms: evt.end_ms,
          });
          setStreamingAssistant({ ...streaming });
        }
        return;
      case "action_proposed":
        // The agent wants to act (send / write / control the Mac). Surface it as
        // an inline card the user can approve or reject — previously this event
        // was silently dropped, so the agent could never actually do anything.
        setPendingActions((prev) =>
          prev.some((a) => a.action_id === evt.action_id)
            ? prev
            : [
                ...prev,
                {
                  action_id: evt.action_id,
                  kind: evt.kind,
                  tool: evt.tool,
                  preview: evt.preview,
                  recipient: evt.recipient,
                  expires_at: evt.expires_at,
                  status: "pending",
                },
              ],
        );
        return;
      case "action_result":
        setPendingActions((prev) =>
          prev.map((a) =>
            a.action_id === evt.action_id
              ? { ...a, status: evt.status, detail: evt.detail }
              : a,
          ),
        );
        return;
      case "memory_updated":
      case "narration":
      case "desktop_action":
        // Part of the event contract but not surfaced as their own UI here;
        // handled so they are never silently dropped. (Mutating actions arrive
        // as action_proposed above and are approved in-thread.)
        return;
      case "done":
        setStage("idle");
        return;
      case "error":
        // Handled in the outer loop, but defensive.
        setError(evt.message);
        return;
    }
  }

  async function handleResolveAction(
    actionId: string,
    decision: "once" | "always" | "reject",
  ) {
    if (!activeChatId) return;
    setError(null);
    setPendingActions((prev) =>
      prev.map((a) =>
        a.action_id === actionId ? { ...a, status: "resolving" } : a,
      ),
    );
    try {
      const res = await resolveAction(activeChatId, actionId, decision);
      setPendingActions((prev) =>
        prev.map((a) =>
          a.action_id === actionId ? { ...a, status: res.status } : a,
        ),
      );
    } catch (e) {
      // Surface the gate's verdict verbatim (409 already-resolved, 410 expired,
      // …) — no silent fallback. Reflect an expired action so the card locks.
      setError(formatError(e, copy));
      const expired = e instanceof ApiError && e.status === 410;
      setPendingActions((prev) =>
        prev.map((a) =>
          a.action_id === actionId
            ? { ...a, status: expired ? "expired" : "pending" }
            : a,
        ),
      );
    }
  }

  function handleStop() {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreamingAssistant(null);
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
  const isEmptyActive = !!activeChatId && messages.length === 0 && !streamingAssistant;

  return (
    <section className="qa-panel">
      <header className="qa-panel__header">
        <h2>{copy.heading}</h2>
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

        {messages.map((m) => (
          <article
            key={m.id}
            className="qa-bubble"
            data-role={m.role}
            data-testid={`companion-message-${m.role}`}
            style={{ marginBottom: 12, whiteSpace: "pre-wrap" }}
          >
            <strong style={{ display: "block", fontSize: 12, opacity: 0.6 }}>
              {m.role === "user" ? copy.user : copy.assistant}
            </strong>
            <div>{plainText(m.content)}</div>
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
        ))}

        {streamingAssistant ? (
          <article
            className="qa-bubble qa-bubble--loading"
            data-testid="companion-streaming"
            style={{ whiteSpace: "pre-wrap" }}
          >
            <strong style={{ display: "block", fontSize: 12, opacity: 0.6 }}>{copy.assistant}</strong>
            {stage === "searching" && streamingAssistant.text.length === 0 ? (
              <div style={{ fontStyle: "italic", opacity: 0.7 }}>
                {copy.searchingRecordings}
              </div>
            ) : null}
            {streamingAssistant.toolCalls.length > 0 && streamingAssistant.text.length === 0 ? (
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, opacity: 0.7 }}>
                {streamingAssistant.toolCalls.map((tc) => (
                  <li key={tc.call_id}>
                    {tc.tool}
                    {tc.summary ? ` → ${tc.summary}` : "…"}
                  </li>
                ))}
              </ul>
            ) : null}
            {streamingAssistant.text.length > 0 ? (
              <div>{streamingAssistant.text}</div>
            ) : null}
            {streamingAssistant.citations.length > 0 ? (
              <CitationStrip
                citations={streamingAssistant.citations}
                recordingTitles={recordingTitlesById}
                fallbackTitle={copy.recordingFallback}
              />
            ) : null}
          </article>
        ) : null}

        {pendingActions.length > 0 ? (
          <div className="companion-actions" data-testid="companion-actions">
            <strong className="companion-actions__heading">
              {copy.actionsHeading}
            </strong>
            {pendingActions.map((a) => (
              <ActionCard
                key={a.action_id}
                action={a}
                copy={copy}
                onResolve={(d) => void handleResolveAction(a.action_id, d)}
              />
            ))}
          </div>
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

function ActionCard({
  action,
  copy,
  onResolve,
}: {
  action: ProposedAction;
  copy: CompanionCopy;
  onResolve: (decision: "once" | "always" | "reject") => void;
}) {
  const open = action.status === "pending" || action.status === "resolving";
  const busy = action.status === "resolving";
  return (
    <div
      className="action-card"
      data-testid="companion-action-card"
      data-status={action.status}
    >
      <div className="action-card__preview">{action.preview}</div>
      {open ? (
        <div className="action-card__buttons">
          <button
            type="button"
            className="action-card__approve"
            disabled={busy}
            onClick={() => onResolve("once")}
            data-testid="companion-action-approve"
          >
            {copy.approve}
          </button>
          <button
            type="button"
            className="ghost-button compact-button"
            disabled={busy}
            onClick={() => onResolve("always")}
            data-testid="companion-action-always"
          >
            {copy.approveAlways}
          </button>
          <button
            type="button"
            className="ghost-button compact-button danger-button"
            disabled={busy}
            onClick={() => onResolve("reject")}
            data-testid="companion-action-reject"
          >
            {copy.reject}
          </button>
        </div>
      ) : (
        <div
          className="action-card__status"
          data-testid="companion-action-status"
        >
          {copy.actionStatus(action.status)}
        </div>
      )}
    </div>
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
