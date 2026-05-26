"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  changePassword,
  claimTelegramLinkCode,
  createEntity,
  createRecording,
  deleteEntity,
  deleteRecording,
  fulltextSearch,
  generateSummary,
  getCurrentUser,
  getRecording,
  getSettings,
  getTelegramLinkStatus,
  listActionItems,
  listEntities,
  listRecordings,
  logout,
  restoreRecording,
  search,
  semanticSearch,
  startTelegramLink,
  updateActionItem,
  updateSettings,
  unlinkTelegram,
} from "@/lib/api";
import { CompanionPanel } from "@/components/CompanionPanel";
import { RecordingDetailPanel } from "@/components/RecordingDetailPanel";
import { AudioUpload } from "@/components/AudioUpload";
import { RecorderPanel } from "@/components/RecorderPanel";
import { McpConnectSection } from "@/components/McpConnectSection";
import { ApiKeysSection } from "@/components/ApiKeysSection";
import { ApiError } from "@/lib/http";
import type {
  ActionItem,
  Entity,
  Recording,
  RecordingDetail,
  RecordingType,
  SearchResponse,
  TelegramLinkStatus,
  TelegramPairing,
  User,
  UserSettings,
} from "@/lib/types";

type SearchMode = "hybrid" | "semantic" | "fts";
type DashboardView = "wai" | "library" | "trash" | "search" | "actions" | "topics" | "settings";
type DetailMode = "active" | "trash";
type Locale = "en" | "ru";

const LIST_LIMIT = 100;

interface DashboardCopy {
  loadingDashboard: string;
  refreshing: string;
  reload: string;
  reloading: string;
  logout: string;
  noUser: string;
  fallbackTitle: string;
  retryLoadSettings: string;
  // Sidebar nav (label + one-line value prop subtitle)
  nav: {
    wai: { label: string; detail: string };
    library: { label: string; detail: string };
    trash: { label: string; detail: string };
    search: { label: string; detail: string };
    actions: { label: string; detail: string };
    topics: { label: string; detail: string };
    settings: { label: string; detail: string };
  };
  // Library
  library: {
    title: string;
    trashTitle: string;
    recordingsCount: (n: number) => string;
    newButton: string;
    emptyTitle: string;
    emptyBody: string;
    trashEmptyTitle: string;
    trashEmptyBody: string;
    selectTitle: string;
    selectTrashBody: string;
    untitled: string;
    summarize: string;
    trashAction: string;
    couldNotProcess: string;
    newRecordingHeading: string;
    titlePlaceholder: string;
    create: string;
    typeNote: string;
    typeMeeting: string;
    typeReflection: string;
  };
  // Search
  search: {
    placeholder: string;
    submit: string;
    hybrid: string;
    semantic: string;
    fts: string;
    total: (n: number) => string;
    enterQuery: string;
    noResultsTitle: string;
    noResultsBody: string;
    score: string;
    open: string;
  };
  // Action items
  actions: {
    emptyTitle: string;
    emptyBody: string;
    complete: string;
    pending: string;
    updated: string;
  };
  // Topics
  topics: {
    placeholder: string;
    create: string;
    delete: string;
    created: string;
    deleted: string;
  };
  // Settings
  settings: {
    dictationHeading: string;
    loadingSettings: string;
    cleanupCheckbox: string;
    settingsUpdated: string;
    accountHeading: string;
    magicLinkNote: string;
    currentPassword: string;
    newPassword: string;
    changePassword: string;
    setPassword: string;
  };
  // Telegram (RU + EN parity required by audit)
  telegram: {
    heading: string;
    intro: string;
    linkedAs: string;
    disconnect: string;
    instructions: string;
    linkButton: string;
    linkOpening: string;
    awaitingStart: string;
    codeLabel: string;
    codeHelp: string;
    codePlaceholder: string;
    linkByCodeButton: string;
    opened: string;
    enterCode: string;
    linked: string;
  };
  // Misc dashboard messages
  msg: {
    recordingCreated: string;
    summaryGenerated: string;
    recordingTrashed: string;
    recordingDeletedPermanently: string;
    recordingRestored: string;
  };
}

const COPY: Record<Locale, DashboardCopy> = {
  en: {
    loadingDashboard: "Loading dashboard...",
    refreshing: "Refreshing dashboard...",
    reload: "Reload",
    reloading: "Reloading...",
    logout: "Logout",
    noUser: "No user",
    fallbackTitle: "WaiComputer",
    retryLoadSettings: "Retry loading account settings",
    nav: {
      wai: { label: "Wai", detail: "Ask anything about what you said" },
      library: { label: "All Recordings", detail: "Every note, meeting, and reflection" },
      trash: { label: "Trash", detail: "Restore or delete forever" },
      search: { label: "Search", detail: "Find a moment across transcripts" },
      actions: { label: "Action Items", detail: "Follow-ups pulled from your notes" },
      topics: { label: "Topics", detail: "People, projects, and ideas you mention" },
      settings: { label: "Settings", detail: "Account, dictation, and integrations" },
    },
    library: {
      title: "All Recordings",
      trashTitle: "Trash",
      recordingsCount: (n) => `${n} ${n === 1 ? "recording" : "recordings"}`,
      newButton: "New",
      emptyTitle: "No Recordings",
      emptyBody: "Record in the browser or import an audio file.",
      trashEmptyTitle: "Trash is Empty",
      trashEmptyBody: "Deleted recordings will appear here.",
      selectTitle: "Select a Recording",
      selectTrashBody: "Choose a trashed recording to restore or delete it permanently.",
      untitled: "(untitled)",
      summarize: "Summarize",
      trashAction: "Trash",
      couldNotProcess: "Could not process this recording. Please try again or contact support.",
      newRecordingHeading: "New Recording",
      titlePlaceholder: "Create an empty note...",
      create: "Create",
      typeNote: "Note",
      typeMeeting: "Meeting",
      typeReflection: "Reflection",
    },
    search: {
      placeholder: "Search recordings...",
      submit: "Search",
      hybrid: "Hybrid",
      semantic: "Semantic",
      fts: "Full text",
      total: (n) => `Total: ${n}`,
      enterQuery: "Enter a search query.",
      noResultsTitle: "No Results",
      noResultsBody: "No matching transcript segments found.",
      score: "Score",
      open: "Open",
    },
    actions: {
      emptyTitle: "No Action Items",
      emptyBody: "Generated follow-ups will appear here after summaries are created.",
      complete: "Complete",
      pending: "Pending",
      updated: "Action item updated.",
    },
    topics: {
      placeholder: "Topic name",
      create: "Create topic",
      delete: "Delete",
      created: "Entity created.",
      deleted: "Entity deleted.",
    },
    settings: {
      dictationHeading: "Dictation",
      loadingSettings: "Loading account settings...",
      cleanupCheckbox: "Clean up dictated text before insertion",
      settingsUpdated: "Settings updated.",
      accountHeading: "Account",
      magicLinkNote:
        "You signed in with a magic link. Set a password to use email and password login.",
      currentPassword: "Current password",
      newPassword: "New password",
      changePassword: "Change password",
      setPassword: "Set password",
    },
    telegram: {
      heading: "Telegram",
      intro:
        "Link @waicomputer_bot to send voice, video, and text questions. Media is transcribed, summarized, and saved to your Library.",
      linkedAs: "Linked as",
      disconnect: "Disconnect",
      instructions:
        "Tap “Link Telegram” — the bot will open. After you press Start linking finishes automatically.",
      linkButton: "Link Telegram",
      linkOpening: "Opening...",
      awaitingStart:
        "Waiting for Start in Telegram. You don't need to come back and copy a code.",
      codeLabel: "Code from Telegram",
      codeHelp: "Only if you started linking from Telegram.",
      codePlaceholder: "Enter the code from the bot",
      linkByCodeButton: "Link by code",
      opened:
        "Telegram opened. Tap Start in the bot — WaiComputer will finish linking automatically.",
      enterCode: "Enter the Telegram code.",
      linked: "Telegram linked.",
    },
    msg: {
      recordingCreated: "Recording created.",
      summaryGenerated: "Summary generated.",
      recordingTrashed: "Recording moved to trash.",
      recordingDeletedPermanently: "Recording permanently deleted.",
      recordingRestored: "Recording restored.",
    },
  },
  ru: {
    loadingDashboard: "Загружаем дашборд...",
    refreshing: "Обновляем дашборд...",
    reload: "Обновить",
    reloading: "Обновляем...",
    logout: "Выйти",
    noUser: "Нет пользователя",
    fallbackTitle: "WaiComputer",
    retryLoadSettings: "Повторить загрузку настроек",
    nav: {
      wai: { label: "Wai", detail: "Спросите о чём угодно из ваших записей" },
      library: { label: "Все записи", detail: "Все заметки, встречи и размышления" },
      trash: { label: "Корзина", detail: "Восстановить или удалить навсегда" },
      search: { label: "Поиск", detail: "Найти момент по всем расшифровкам" },
      actions: { label: "Задачи", detail: "Действия, извлечённые из ваших записей" },
      topics: { label: "Темы", detail: "Люди, проекты и идеи, о которых вы говорите" },
      settings: { label: "Настройки", detail: "Аккаунт, диктовка и интеграции" },
    },
    library: {
      title: "Все записи",
      trashTitle: "Корзина",
      recordingsCount: (n) =>
        `${n} ${n === 1 ? "запись" : n >= 2 && n <= 4 ? "записи" : "записей"}`,
      newButton: "Новая",
      emptyTitle: "Записей пока нет",
      emptyBody: "Запишите в браузере или загрузите аудиофайл.",
      trashEmptyTitle: "Корзина пуста",
      trashEmptyBody: "Удалённые записи появятся здесь.",
      selectTitle: "Выберите запись",
      selectTrashBody: "Выберите запись в корзине, чтобы восстановить или удалить навсегда.",
      untitled: "(без названия)",
      summarize: "Суммировать",
      trashAction: "В корзину",
      couldNotProcess:
        "Не удалось обработать эту запись. Попробуйте ещё раз или обратитесь в поддержку.",
      newRecordingHeading: "Новая запись",
      titlePlaceholder: "Создать пустую заметку...",
      create: "Создать",
      typeNote: "Заметка",
      typeMeeting: "Встреча",
      typeReflection: "Размышление",
    },
    search: {
      placeholder: "Искать в записях...",
      submit: "Найти",
      hybrid: "Гибридный",
      semantic: "Семантический",
      fts: "По тексту",
      total: (n) => `Всего: ${n}`,
      enterQuery: "Введите поисковый запрос.",
      noResultsTitle: "Ничего не найдено",
      noResultsBody: "Не нашли подходящих фрагментов транскрипта.",
      score: "Релевантность",
      open: "Открыть",
    },
    actions: {
      emptyTitle: "Задач пока нет",
      emptyBody: "Действия будут появляться здесь после создания саммари.",
      complete: "Готово",
      pending: "В работе",
      updated: "Задача обновлена.",
    },
    topics: {
      placeholder: "Название темы",
      create: "Создать тему",
      delete: "Удалить",
      created: "Тема создана.",
      deleted: "Тема удалена.",
    },
    settings: {
      dictationHeading: "Диктовка",
      loadingSettings: "Загружаем настройки аккаунта...",
      cleanupCheckbox: "Чистить диктованный текст перед вставкой",
      settingsUpdated: "Настройки сохранены.",
      accountHeading: "Аккаунт",
      magicLinkNote:
        "Вы вошли по magic-ссылке. Задайте пароль, чтобы входить по email и паролю.",
      currentPassword: "Текущий пароль",
      newPassword: "Новый пароль",
      changePassword: "Сменить пароль",
      setPassword: "Задать пароль",
    },
    telegram: {
      heading: "Telegram",
      intro:
        "Привяжите @waicomputer_bot, чтобы отправлять голосовые, видео и вопросы текстом. Медиа расшифровываются, суммаризируются и сохраняются в Библиотеку.",
      linkedAs: "Привязан как",
      disconnect: "Отключить",
      instructions:
        "Нажмите «Привязать Telegram» — откроется бот. После Start привязка завершится автоматически.",
      linkButton: "Привязать Telegram",
      linkOpening: "Открываем...",
      awaitingStart: "Ждем Start в Telegram. Возвращаться и копировать код не нужно.",
      codeLabel: "Код из Telegram",
      codeHelp: "Только если вы начали привязку из Telegram.",
      codePlaceholder: "Введите код из бота",
      linkByCodeButton: "Привязать по коду",
      opened:
        "Telegram открыт. Нажмите Start в боте — WaiComputer завершит привязку автоматически.",
      enterCode: "Введите код из Telegram.",
      linked: "Telegram привязан.",
    },
    msg: {
      recordingCreated: "Запись создана.",
      summaryGenerated: "Саммари сгенерировано.",
      recordingTrashed: "Запись перемещена в корзину.",
      recordingDeletedPermanently: "Запись удалена навсегда.",
      recordingRestored: "Запись восстановлена.",
    },
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

function formatError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

function formatDuration(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function formatDate(value: string, locale: Locale): string {
  const bcp = locale === "ru" ? "ru-RU" : undefined;
  return new Date(value).toLocaleDateString(bcp, { dateStyle: "medium" });
}

function typeLabel(type: RecordingType, copy: DashboardCopy): string {
  switch (type) {
    case "note":
      return copy.library.typeNote;
    case "meeting":
      return copy.library.typeMeeting;
    case "reflection":
      return copy.library.typeReflection;
  }
}

// Hide OS paths, errno markers, and traceback fragments from end users.
function isLikelyInternalError(message: string): boolean {
  if (!message) return false;
  return (
    /\[Errno\b/.test(message)
    || /\/var\//.test(message)
    || /\/Users\//.test(message)
    || /\/tmp\//.test(message)
    || /\bTraceback\b/.test(message)
    || /\bFile\s+"[^"]+",\s+line\s+\d+/.test(message)
  );
}

function displayFailureMessage(failureMessage: string, copy: DashboardCopy): string {
  if (isLikelyInternalError(failureMessage)) {
    return copy.library.couldNotProcess;
  }
  return failureMessage;
}

function statusText(recording: Recording, copy: DashboardCopy): string | null {
  if (recording.failure_message) {
    return displayFailureMessage(recording.failure_message, copy);
  }
  if (!recording.status || recording.status === "ready") return null;
  return recording.status.replace("_", " ");
}

// API caps list endpoints at `LIST_LIMIT`. When a list arrives full, the true
// total is unknown — render "100+" so we never report an inflated, capped
// number as the source of truth.
function displayCount(rawArrayLength: number, displayedCount?: number): string {
  const total = displayedCount ?? rawArrayLength;
  if (rawArrayLength >= LIST_LIMIT) return `${total}+`;
  return String(total);
}

export function DashboardClient() {
  const router = useRouter();

  const [locale, setLocale] = useState<Locale>("en");
  const copy = COPY[locale];

  const [initializing, setInitializing] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);

  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [trashRecordings, setTrashRecordings] = useState<Recording[]>([]);
  const [recordingTitle, setRecordingTitle] = useState("");
  const [recordingType, setRecordingType] = useState<RecordingType>("note");
  const [selectedRecording, setSelectedRecording] = useState<RecordingDetail | null>(null);
  const [selectedMode, setSelectedMode] = useState<DetailMode>("active");

  const [searchMode, setSearchMode] = useState<SearchMode>("hybrid");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null);

  const [actionItems, setActionItems] = useState<ActionItem[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [entityName, setEntityName] = useState("");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [view, setView] = useState<DashboardView>("wai");
  const [accountSettings, setAccountSettings] = useState<UserSettings | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsLoadedOnce, setSettingsLoadedOnce] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [telegramStatus, setTelegramStatus] = useState<TelegramLinkStatus | null>(null);
  const [telegramPairing, setTelegramPairing] = useState<TelegramPairing | null>(null);
  const [telegramLinkCode, setTelegramLinkCode] = useState("");
  const [telegramLoading, setTelegramLoading] = useState(false);

  useEffect(() => {
    setLocale(detectLocale());
  }, []);

  const pendingActionCount = useMemo(
    () =>
      actionItems.filter(
        (item) => item.status !== "completed" && item.status !== "cancelled",
      ).length,
    [actionItems],
  );
  const accountHasPassword = user?.has_password !== false;

  async function loadRecordingsState() {
    const active = await listRecordings({ limit: LIST_LIMIT });
    setRecordings(active);
  }

  async function loadTrashRecordingsState() {
    const trashed = await listRecordings({ limit: LIST_LIMIT, trashed: true });
    setTrashRecordings(trashed);
  }

  async function loadActionItemsState() {
    const response = await listActionItems({ limit: LIST_LIMIT });
    setActionItems(response);
  }

  async function loadEntitiesState() {
    const response = await listEntities();
    setEntities(response);
  }

  async function loadAccountSettings() {
    setSettingsLoading(true);
    try {
      const [settingsResponse, telegramResponse] = await Promise.all([
        getSettings(),
        getTelegramLinkStatus(),
      ]);
      setAccountSettings(settingsResponse);
      setTelegramStatus(telegramResponse);
      setSettingsLoadedOnce(true);
      setSettingsLoading(false);
    } catch (error: unknown) {
      setMessage(formatError(error));
      setSettingsLoadedOnce(true);
      setSettingsLoading(false);
    }
  }

  async function initialize(options?: { preserveView?: boolean }) {
    const preserveView = options?.preserveView ?? false;
    try {
      if (preserveView) {
        setRefreshing(true);
      } else {
        setInitializing(true);
      }
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      await Promise.all([loadRecordingsState(), loadActionItemsState(), loadEntitiesState()]);
    } catch (error: unknown) {
      const text = formatError(error);
      if (error instanceof ApiError && error.status === 401) {
        router.replace("/login");
        return;
      }
      setMessage(text);
    } finally {
      setInitializing(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void initialize();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (view !== "settings" || settingsLoadedOnce || settingsLoading) return;
    void loadAccountSettings();
  }, [view, settingsLoadedOnce, settingsLoading]);

  useEffect(() => {
    if (view !== "settings" || telegramStatus?.linked || !telegramPairing) return;
    function refreshTelegramStatus() {
      void handleRefreshTelegramStatus({ silent: true });
    }
    const interval = window.setInterval(refreshTelegramStatus, 2000);
    window.addEventListener("focus", refreshTelegramStatus);
    document.addEventListener("visibilitychange", refreshTelegramStatus);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshTelegramStatus);
      document.removeEventListener("visibilitychange", refreshTelegramStatus);
    };
  }, [view, telegramStatus?.linked, telegramPairing]);

  async function handleCreateRecording(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    try {
      await createRecording({
        title: recordingTitle.length > 0 ? recordingTitle : null,
        type: recordingType,
        language: "multi",
      });
      setRecordingTitle("");
      await loadRecordingsState();
      setView("library");
      setMessage(copy.msg.recordingCreated);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleSelectRecording(recordingId: string, mode: DetailMode = "active") {
    setMessage(null);
    try {
      const detail = await getRecording(recordingId);
      setSelectedRecording(detail);
      setSelectedMode(mode);
      setView(mode === "trash" ? "trash" : "library");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleDeleteRecording(recordingId: string, options?: { permanent?: boolean }) {
    setMessage(null);
    try {
      if (options) {
        await deleteRecording(recordingId, options);
      } else {
        await deleteRecording(recordingId);
      }
      if (selectedRecording?.id === recordingId) {
        setSelectedRecording(null);
      }
      await Promise.all([
        loadRecordingsState(),
        options?.permanent ? loadTrashRecordingsState() : Promise.resolve(),
        loadActionItemsState(),
      ]);
      setMessage(
        options?.permanent
          ? copy.msg.recordingDeletedPermanently
          : copy.msg.recordingTrashed,
      );
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleRestoreRecording(recordingId: string) {
    setMessage(null);
    try {
      await restoreRecording(recordingId);
      if (selectedRecording?.id === recordingId) {
        setSelectedRecording(null);
      }
      await Promise.all([loadRecordingsState(), loadTrashRecordingsState()]);
      setMessage(copy.msg.recordingRestored);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleGenerateSummary(recordingId: string) {
    setMessage(null);
    try {
      await generateSummary(recordingId);
      const detail = await getRecording(recordingId);
      setSelectedRecording(detail);
      setSelectedMode("active");
      await loadActionItemsState();
      setMessage(copy.msg.summaryGenerated);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchQuery.trim();
    setMessage(null);
    if (query.length === 0) {
      setSearchResponse(null);
      setMessage(copy.search.enterQuery);
      return;
    }
    try {
      if (searchMode === "hybrid") {
        setSearchResponse(await search({ q: query, limit: 25, offset: 0 }));
        return;
      }
      if (searchMode === "semantic") {
        setSearchResponse(await semanticSearch({ q: query, limit: 25, threshold: 0.3 }));
        return;
      }
      setSearchResponse(await fulltextSearch({ q: query, limit: 25, offset: 0 }));
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleUpdateAction(itemId: string, status: ActionItem["status"]) {
    setMessage(null);
    try {
      await updateActionItem(itemId, { status });
      await loadActionItemsState();
      setMessage(copy.actions.updated);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleCreateEntity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    try {
      await createEntity({ type: "topic", name: entityName, metadata: { source: "web" } });
      setEntityName("");
      await loadEntitiesState();
      setMessage(copy.topics.created);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleDeleteEntity(entityId: string) {
    setMessage(null);
    try {
      await deleteEntity(entityId);
      await loadEntitiesState();
      setMessage(copy.topics.deleted);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleChangePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    try {
      const response = await changePassword(accountHasPassword ? currentPassword : "", newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setUser((current) => current ? { ...current, has_password: true } : current);
      setMessage(response.message);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleUpdateAccountSettings(patch: Partial<UserSettings>) {
    setMessage(null);
    setSettingsSaving(true);
    try {
      const updated = await updateSettings(patch);
      setAccountSettings(updated);
      setMessage(copy.settings.settingsUpdated);
    } catch (error: unknown) {
      setMessage(formatError(error));
    } finally {
      setSettingsSaving(false);
    }
  }

  async function handleStartTelegramLink() {
    setTelegramLoading(true);
    setMessage(null);
    try {
      const response = await startTelegramLink();
      setTelegramPairing(response);
      window.location.href = response.deep_link;
      setMessage(copy.telegram.opened);
    } catch (error: unknown) {
      setMessage(formatError(error));
    } finally {
      setTelegramLoading(false);
    }
  }

  async function handleRefreshTelegramStatus(options: { silent?: boolean } = {}) {
    if (!options.silent) setTelegramLoading(true);
    if (!options.silent) setMessage(null);
    try {
      const status = await getTelegramLinkStatus();
      setTelegramStatus(status);
      if (status.linked || !options.silent) {
        setTelegramPairing(null);
        if (status.linked) {
          setTelegramLinkCode("");
          setMessage(copy.telegram.linked);
        }
      }
    } catch (error: unknown) {
      if (!options.silent) setMessage(formatError(error));
    } finally {
      if (!options.silent) setTelegramLoading(false);
    }
  }

  async function handleClaimTelegramLinkCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = telegramLinkCode.trim();
    if (!code) {
      setMessage(copy.telegram.enterCode);
      return;
    }
    setTelegramLoading(true);
    setMessage(null);
    try {
      setTelegramStatus(await claimTelegramLinkCode(code));
      setTelegramPairing(null);
      setTelegramLinkCode("");
      setMessage(copy.telegram.linked);
    } catch (error: unknown) {
      setMessage(formatError(error));
    } finally {
      setTelegramLoading(false);
    }
  }

  async function handleUnlinkTelegram() {
    setTelegramLoading(true);
    setMessage(null);
    try {
      await unlinkTelegram();
      setTelegramPairing(null);
      setTelegramLinkCode("");
      setTelegramStatus(await getTelegramLinkStatus());
    } catch (error: unknown) {
      setMessage(formatError(error));
    } finally {
      setTelegramLoading(false);
    }
  }

  async function handleLogout() {
    setMessage(null);
    try {
      await logout();
      router.replace("/login");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  if (initializing) {
    return (
      <div className="loading-screen">
        <p data-testid="dashboard-loading">{copy.loadingDashboard}</p>
      </div>
    );
  }

  const navigation = [
    { key: "wai", label: copy.nav.wai.label, detail: copy.nav.wai.detail, count: null },
    {
      key: "library",
      label: copy.nav.library.label,
      detail: copy.nav.library.detail,
      count: displayCount(recordings.length),
    },
    {
      key: "trash",
      label: copy.nav.trash.label,
      detail: copy.nav.trash.detail,
      count: displayCount(trashRecordings.length),
    },
    { key: "search", label: copy.nav.search.label, detail: copy.nav.search.detail, count: null },
    {
      key: "actions",
      label: copy.nav.actions.label,
      detail: copy.nav.actions.detail,
      count: displayCount(actionItems.length, pendingActionCount),
    },
    {
      key: "topics",
      label: copy.nav.topics.label,
      detail: copy.nav.topics.detail,
      count: displayCount(entities.length),
    },
    {
      key: "settings",
      label: copy.nav.settings.label,
      detail: copy.nav.settings.detail,
      count: null,
    },
  ] as const;

  return (
    <div className="web-app-shell">
      <aside className="app-sidebar" aria-label="WaiComputer navigation">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true" />
          <div>
            <h1>WaiComputer</h1>
            <p data-testid="user-email">{user?.email ?? copy.noUser}</p>
          </div>
        </div>

        <nav className="sidebar-nav">
          {navigation.map((item) => (
            <button
              key={item.key}
              data-testid={`tab-${item.key}`}
              type="button"
              className="sidebar-nav__item"
              aria-current={view === item.key ? "page" : undefined}
              onClick={() => {
                setView(item.key);
                if (item.key === "trash") {
                  void loadTrashRecordingsState();
                }
              }}
            >
              <span>
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
              </span>
              {item.count !== null ? <em>{item.count}</em> : null}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button
            data-testid="reload-dashboard"
            type="button"
            className="ghost-button"
            onClick={() => void initialize({ preserveView: true })}
            disabled={refreshing}
          >
            {refreshing ? copy.reloading : copy.reload}
          </button>
          <button
            data-testid="logout-button"
            type="button"
            className="ghost-button danger-button"
            onClick={handleLogout}
          >
            {copy.logout}
          </button>
        </div>
      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div>
            <h2>{navigation.find((item) => item.key === view)?.label ?? copy.fallbackTitle}</h2>
          </div>
          {refreshing ? <p data-testid="dashboard-refreshing">{copy.refreshing}</p> : null}
        </header>

        {message ? (
          <p className="dashboard-message" data-testid="dashboard-message" role="status">
            {message}
          </p>
        ) : null}

        {view === "wai" ? <WaiView recordings={recordings} locale={locale} /> : null}
        {view === "library" ? renderLibrary("active", recordings) : null}
        {view === "trash" ? renderLibrary("trash", trashRecordings) : null}
        {view === "search" ? renderSearchView() : null}
        {view === "actions" ? renderActionsView() : null}
        {view === "topics" ? renderTopicsView() : null}
        {view === "settings" ? renderSettingsView() : null}
      </main>
    </div>
  );

  function renderLibrary(mode: DetailMode, items: Recording[]) {
    const isTrash = mode === "trash";
    const title = isTrash ? copy.library.trashTitle : copy.library.title;

    return (
      <div className="library-grid">
        <section className="recording-list-panel" aria-label={title}>
          <header className="panel-header">
            <div>
              <h3>{title}</h3>
              <p>{copy.library.recordingsCount(items.length)}</p>
            </div>
            {!isTrash ? (
              <button
                type="button"
                className="ghost-button compact-button"
                onClick={() => {
                  setSelectedRecording(null);
                  setSelectedMode("active");
                }}
              >
                {copy.library.newButton}
              </button>
            ) : null}
          </header>

          {items.length === 0 ? (
            <div className="empty-state">
              <h3>{isTrash ? copy.library.trashEmptyTitle : copy.library.emptyTitle}</h3>
              <p>{isTrash ? copy.library.trashEmptyBody : copy.library.emptyBody}</p>
            </div>
          ) : (
            <ul className="recording-list" data-testid="recording-list">
              {items.map((recording) => {
                const status = statusText(recording, copy);
                return (
                  <li key={recording.id}>
                    <button
                      type="button"
                      className="recording-row"
                      aria-current={
                        selectedRecording?.id === recording.id && selectedMode === mode
                          ? "true"
                          : undefined
                      }
                      onClick={() => void handleSelectRecording(recording.id, mode)}
                      data-testid={`select-recording-${recording.id}`}
                    >
                      <span className="recording-row__main">
                        <strong>{recording.title ?? copy.library.untitled}</strong>
                        <small>
                          {typeLabel(recording.type, copy)} / {formatDate(recording.created_at, locale)}
                          {recording.duration_seconds
                            ? ` / ${formatDuration(recording.duration_seconds)}`
                            : ""}
                        </small>
                      </span>
                      {status ? <span className="status-pill">{status}</span> : null}
                    </button>

                    {!isTrash ? (
                      <div className="row-actions">
                        <button
                          type="button"
                          className="ghost-button compact-button"
                          onClick={() => void handleGenerateSummary(recording.id)}
                          data-testid={`generate-summary-${recording.id}`}
                        >
                          {copy.library.summarize}
                        </button>
                        <button
                          type="button"
                          className="ghost-button compact-button danger-button"
                          onClick={() => void handleDeleteRecording(recording.id)}
                          data-testid={`delete-recording-${recording.id}`}
                        >
                          {copy.library.trashAction}
                        </button>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="recording-detail-area" aria-label="Recording detail">
          {selectedRecording && selectedMode === mode ? (
            <RecordingDetailPanel
              recording={selectedRecording}
              mode={mode}
              onRecordingUpdate={setSelectedRecording}
              onRestore={(recordingId) => void handleRestoreRecording(recordingId)}
              onDelete={(recordingId) =>
                void handleDeleteRecording(recordingId, { permanent: isTrash })
              }
            />
          ) : isTrash ? (
            <div className="empty-state empty-state--center">
              <h3>{copy.library.selectTitle}</h3>
              <p>{copy.library.selectTrashBody}</p>
            </div>
          ) : (
            <NewRecordingPane
              title={recordingTitle}
              type={recordingType}
              copy={copy}
              onTitleChange={setRecordingTitle}
              onTypeChange={setRecordingType}
              onSubmit={handleCreateRecording}
              onComplete={async (detail) => {
                setSelectedRecording(detail);
                setSelectedMode("active");
                await loadRecordingsState();
              }}
              onError={setMessage}
            />
          )}
        </section>
      </div>
    );
  }

  function renderSearchView() {
    return (
      <section className="tool-panel">
        <form className="search-form" onSubmit={handleSearch}>
          <input
            data-testid="search-query"
            placeholder={copy.search.placeholder}
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
          <select
            data-testid="search-mode"
            value={searchMode}
            onChange={(event) => {
              setSearchMode(event.target.value as SearchMode);
              setSearchResponse(null);
            }}
          >
            <option value="hybrid">{copy.search.hybrid}</option>
            <option value="semantic">{copy.search.semantic}</option>
            <option value="fts">{copy.search.fts}</option>
          </select>
          <button data-testid="search-submit" type="submit">
            {copy.search.submit}
          </button>
        </form>

        <p data-testid="search-total" className="muted-text">
          {copy.search.total(searchResponse?.total ?? 0)}
        </p>
        {searchResponse?.results && searchResponse.results.length > 0 ? (
          <ul className="search-results" data-testid="search-results">
            {searchResponse.results.map((result) => (
              <li key={result.segment_id} data-testid={`search-result-${result.segment_id}`}>
                <strong>{result.recording_title ?? copy.library.untitled}</strong>
                <p>{result.content}</p>
                <div className="search-result-footer">
                  <small>
                    {result.speaker ? `${result.speaker} / ` : ""}
                    {copy.search.score} {result.score.toFixed(2)}
                  </small>
                  <button
                    type="button"
                    className="ghost-button compact-button"
                    onClick={() => void handleSelectRecording(result.recording_id)}
                  >
                    {copy.search.open}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : searchResponse && searchResponse.total === 0 ? (
          <div className="empty-state" data-testid="search-no-results">
            <h3>{copy.search.noResultsTitle}</h3>
            <p>{copy.search.noResultsBody}</p>
          </div>
        ) : null}
      </section>
    );
  }

  function renderActionsView() {
    return (
      <section className="tool-panel">
        {actionItems.length === 0 ? (
          <div className="empty-state">
            <h3>{copy.actions.emptyTitle}</h3>
            <p>{copy.actions.emptyBody}</p>
          </div>
        ) : (
          <ul className="action-list" data-testid="action-item-list">
            {actionItems.map((item) => (
              <li key={item.id} className="action-list__item">
                <div>
                  <strong>{item.task}</strong>
                  <p className="metadata-row">
                    <span>{item.status.replace("_", " ")}</span>
                    {item.priority ? <span>{item.priority}</span> : null}
                    {item.owner ? <span>{item.owner}</span> : null}
                  </p>
                </div>
                <div className="row-actions">
                  <button
                    type="button"
                    data-testid={`set-complete-${item.id}`}
                    className="ghost-button compact-button"
                    onClick={() => void handleUpdateAction(item.id, "completed")}
                  >
                    {copy.actions.complete}
                  </button>
                  <button
                    type="button"
                    data-testid={`set-pending-${item.id}`}
                    className="ghost-button compact-button"
                    onClick={() => void handleUpdateAction(item.id, "pending")}
                  >
                    {copy.actions.pending}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  function renderTopicsView() {
    return (
      <section className="tool-panel">
        <form className="search-form" onSubmit={handleCreateEntity}>
          <input
            data-testid="entity-name"
            placeholder={copy.topics.placeholder}
            value={entityName}
            onChange={(event) => setEntityName(event.target.value)}
            required
          />
          <button data-testid="create-entity" type="submit">
            {copy.topics.create}
          </button>
        </form>
        <ul className="topic-list" data-testid="entity-list">
          {entities.map((entity) => (
            <li key={entity.id}>
              <span>{entity.name}</span>
              <button
                type="button"
                className="ghost-button compact-button danger-button"
                onClick={() => void handleDeleteEntity(entity.id)}
                data-testid={`delete-entity-${entity.id}`}
              >
                {copy.topics.delete}
              </button>
            </li>
          ))}
        </ul>
      </section>
    );
  }

  function renderSettingsView() {
    return (
      <section className="tool-panel settings-panel">
        <div className="settings-form">
          <h3>{copy.settings.dictationHeading}</h3>
          {settingsLoading ? (
            <p className="settings-note">{copy.settings.loadingSettings}</p>
          ) : null}
          {accountSettings ? (
            <label className="settings-checkbox-field">
              <input
                type="checkbox"
                checked={accountSettings.dictation_post_filter_enabled}
                disabled={settingsSaving}
                onChange={(event) =>
                  void handleUpdateAccountSettings({
                    dictation_post_filter_enabled: event.target.checked,
                  })
                }
              />
              <span>{copy.settings.cleanupCheckbox}</span>
            </label>
          ) : settingsLoadedOnce && !settingsLoading ? (
            <button
              type="button"
              className="ghost-button compact-button"
              onClick={() => void loadAccountSettings()}
            >
              {copy.retryLoadSettings}
            </button>
          ) : null}
        </div>

        <form className="settings-form" onSubmit={handleChangePassword}>
          <h3>{copy.settings.accountHeading}</h3>
          {!accountHasPassword ? (
            <p className="settings-note" data-testid="set-password-note">
              {copy.settings.magicLinkNote}
            </p>
          ) : (
            <label>
              <span>{copy.settings.currentPassword}</span>
              <input
                data-testid="current-password"
                type="password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                required
              />
            </label>
          )}
          <label>
            <span>{copy.settings.newPassword}</span>
            <input
              data-testid="new-password"
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              required
            />
          </label>
          <button data-testid="change-password" type="submit">
            {accountHasPassword ? copy.settings.changePassword : copy.settings.setPassword}
          </button>
        </form>

        <div className="settings-form">
          <h3>{copy.telegram.heading}</h3>
          <p className="settings-note">{copy.telegram.intro}</p>
          {telegramStatus?.linked ? (
            <div className="telegram-link-card">
              <p>
                {copy.telegram.linkedAs}{" "}
                <strong>
                  {telegramStatus.username
                    ? `@${telegramStatus.username}`
                    : [telegramStatus.first_name, telegramStatus.last_name]
                        .filter(Boolean)
                        .join(" ") || "Telegram"}
                </strong>
              </p>
              <button
                type="button"
                className="ghost-button compact-button danger-button"
                disabled={telegramLoading}
                onClick={() => void handleUnlinkTelegram()}
              >
                {copy.telegram.disconnect}
              </button>
            </div>
          ) : (
            <div className="telegram-link-card">
              <p className="settings-note">{copy.telegram.instructions}</p>
              <button
                type="button"
                className="ghost-button compact-button"
                disabled={telegramLoading}
                onClick={() => void handleStartTelegramLink()}
              >
                {telegramLoading ? copy.telegram.linkOpening : copy.telegram.linkButton}
              </button>
              {telegramPairing ? (
                <p className="settings-note">{copy.telegram.awaitingStart}</p>
              ) : null}
              <form className="telegram-code-form" onSubmit={handleClaimTelegramLinkCode}>
                <label>
                  <span>{copy.telegram.codeLabel}</span>
                  <small>{copy.telegram.codeHelp}</small>
                  <input
                    type="text"
                    value={telegramLinkCode}
                    onChange={(event) => setTelegramLinkCode(event.target.value)}
                    placeholder={copy.telegram.codePlaceholder}
                    autoComplete="one-time-code"
                    disabled={telegramLoading}
                  />
                </label>
                <button
                  type="submit"
                  className="ghost-button compact-button"
                  disabled={telegramLoading}
                >
                  {copy.telegram.linkByCodeButton}
                </button>
              </form>
            </div>
          )}
        </div>

        <McpConnectSection />
        <ApiKeysSection />
      </section>
    );
  }
}

function WaiView({ recordings, locale }: { recordings: Recording[]; locale: Locale }) {
  return (
    <div className="wai-panel">
      <CompanionPanel recordings={recordings} locale={locale} />
    </div>
  );
}

function NewRecordingPane({
  title,
  type,
  copy,
  onTitleChange,
  onTypeChange,
  onSubmit,
  onComplete,
  onError,
}: {
  title: string;
  type: RecordingType;
  copy: DashboardCopy;
  onTitleChange: (value: string) => void;
  onTypeChange: (value: RecordingType) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onComplete: (detail: RecordingDetail) => void | Promise<void>;
  onError: (message: string) => void;
}) {
  return (
    <section className="new-recording-panel">
      <div className="new-recording-panel__intro">
        <div className="app-glyph" aria-hidden="true" />
        <h3>{copy.library.newRecordingHeading}</h3>
      </div>

      <div className="recording-options">
        <RecorderPanel onRecordingComplete={onComplete} onError={onError} />
        <AudioUpload onUploadComplete={onComplete} onError={onError} />
      </div>

      <form className="manual-note-form" onSubmit={onSubmit}>
        <input
          data-testid="recording-title"
          placeholder={copy.library.titlePlaceholder}
          value={title}
          onChange={(event) => onTitleChange(event.target.value)}
        />
        <select
          data-testid="recording-type"
          value={type}
          onChange={(event) => onTypeChange(event.target.value as RecordingType)}
        >
          <option value="note">{copy.library.typeNote}</option>
          <option value="meeting">{copy.library.typeMeeting}</option>
          <option value="reflection">{copy.library.typeReflection}</option>
        </select>
        <button data-testid="create-recording" type="submit">
          {copy.library.create}
        </button>
      </form>
    </section>
  );
}
