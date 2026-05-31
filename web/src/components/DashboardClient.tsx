"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  assignRecordingToFolder,
  changePassword,
  claimTelegramLinkCode,
  createDictionaryWord,
  createFolder,
  createRecording,
  deleteDictationEntry,
  deleteDictionaryWord,
  deleteFolder,
  deleteRecording,
  fulltextSearch,
  getCurrentUser,
  getRecording,
  getSettings,
  getTelegramLinkStatus,
  getTranscriptionOptions,
  listDictationEntries,
  listDictionaryWords,
  listFolders,
  listRecordings,
  logout,
  renameFolder,
  restoreRecording,
  search,
  semanticSearch,
  startSummaryGeneration,
  startTelegramLink,
  updateSettings,
  unlinkTelegram,
} from "@/lib/api";
import { CompanionPanel } from "@/components/CompanionPanel";
import { RecordingDetailPanel } from "@/components/RecordingDetailPanel";
import { AudioUpload } from "@/components/AudioUpload";
import { RecorderPanel } from "@/components/RecorderPanel";
import { McpConnectSection } from "@/components/McpConnectSection";
import { ApiKeysSection } from "@/components/ApiKeysSection";
import { IdentityAndVoicePanel } from "@/components/IdentityAndVoicePanel";
import { ThemeAccentPicker } from "@/components/ThemeAccentPicker";
import { TranscriptionSettingsPanel } from "@/components/TranscriptionSettingsPanel";
import { DictationStatsHeader } from "@/components/DictationStatsHeader";
import { PasswordField } from "@/components/PasswordField";
import { Skeleton } from "@/components/Skeleton";
import { ApiError } from "@/lib/http";
import type {
  DictationDictionaryWord,
  DictationEntry,
  Folder,
  Recording,
  RecordingDetail,
  RecordingType,
  SearchResponse,
  TelegramLinkStatus,
  TelegramPairing,
  TranscriptionOptions,
  User,
  UserSettings,
} from "@/lib/types";

type SearchMode = "hybrid" | "semantic" | "fts";
type DashboardView =
  | "wai"
  | "library"
  | "folder"
  | "trash"
  | "search"
  | "history"
  | "dictionary"
  | "settings";
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
    folders: { label: string };
    trash: { label: string; detail: string };
    search: { label: string; detail: string };
    history: { label: string; detail: string };
    dictionary: { label: string; detail: string };
    settings: { label: string; detail: string };
  };
  // Folder management
  folders: {
    addAriaLabel: string;
    addPlaceholder: string;
    addSubmit: string;
    addCancel: string;
    addError: string;
    rename: string;
    delete: string;
    deleteConfirmTitle: (name: string) => string;
    deleteConfirmBody: string;
    deleteConfirmAction: string;
    deleteConfirmCancel: string;
    renameTitle: (name: string) => string;
    renameAction: string;
    renameCancel: string;
    created: string;
    renamed: string;
    deleted: string;
    emptyHint: string;
    folderEmptyTitle: string;
    folderEmptyBody: string;
  };
  // Dictation history view
  history: {
    title: string;
    subtitle: string;
    emptyTitle: string;
    emptyBody: string;
    notAvailableTitle: string;
    notAvailableBody: string;
    durationLabel: string;
    wordsLabel: (n: number) => string;
    refresh: string;
    clearAll: string;
    clearAllConfirm: string;
    clearAllCancel: string;
    clearAllPrompt: string;
    deleted: string;
    deleteEntry: string;
  };
  // Dictionary view
  dictionary: {
    title: string;
    subtitle: string;
    explainer: string;
    helper: string;
    overuseWarning: string;
    biasBadge: string;
    biasLegend: string;
    replaceBadge: string;
    replaceLegend: string;
    duplicate: string;
    searchPlaceholder: string;
    addPlaceholderWord: string;
    addPlaceholderReplacement: string;
    addAction: string;
    deleteAction: string;
    created: string;
    deleted: string;
    emptyTitle: string;
    emptyBody: string;
    notAvailableTitle: string;
    notAvailableBody: string;
    refresh: string;
    enterWord: string;
    inputWordsRow: string;
  };
  // Keyboard shortcuts cheatsheet
  shortcuts: {
    open: string;
    title: string;
    close: string;
    rows: Array<{ keys: string; description: string }>;
    notice: string;
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
    summaryQueued: string;
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
      folders: { label: "Folders" },
      trash: { label: "Trash", detail: "Restore or delete forever" },
      search: { label: "Search", detail: "Find a moment across transcripts" },
      history: { label: "Dictation History", detail: "Voice to text inserts" },
      dictionary: { label: "Dictionary", detail: "Custom dictation replacements" },
      settings: { label: "Settings", detail: "Account, dictation, and integrations" },
    },
    folders: {
      addAriaLabel: "New folder",
      addPlaceholder: "Folder name",
      addSubmit: "Create",
      addCancel: "Cancel",
      addError: "Enter a folder name.",
      rename: "Rename",
      delete: "Delete",
      deleteConfirmTitle: (name) => `Delete folder “${name}”?`,
      deleteConfirmBody:
        "Recordings inside this folder will be moved out of it. The recordings themselves are kept.",
      deleteConfirmAction: "Delete folder",
      deleteConfirmCancel: "Cancel",
      renameTitle: (name) => `Rename “${name}”`,
      renameAction: "Save",
      renameCancel: "Cancel",
      created: "Folder created.",
      renamed: "Folder renamed.",
      deleted: "Folder deleted.",
      emptyHint: "No folders yet — create one to organize recordings.",
      folderEmptyTitle: "No Recordings in This Folder",
      folderEmptyBody: "Move a recording into this folder from the recording detail view.",
    },
    history: {
      title: "Dictation History",
      subtitle: "Every voice-to-text insert from Mac, Windows, and Linux.",
      emptyTitle: "No Dictation Yet",
      emptyBody: "Open WaiComputer on Mac or Windows to start dictating.",
      notAvailableTitle: "Dictation History Unavailable",
      notAvailableBody:
        "Couldn't reach the dictation service. Try refreshing in a moment.",
      durationLabel: "duration",
      wordsLabel: (n) => `${n} ${n === 1 ? "word" : "words"}`,
      refresh: "Refresh",
      clearAll: "Clear All",
      clearAllConfirm: "Clear all dictation history?",
      clearAllCancel: "Cancel",
      clearAllPrompt:
        "Every insert from your Mac, Windows, and Linux clients will be removed. This cannot be undone.",
      deleted: "Entry removed.",
      deleteEntry: "Delete entry",
    },
    dictionary: {
      title: "Dictionary",
      subtitle: "Custom replacements applied to your dictated text.",
      explainer:
        "Each entry biases the recognizer toward the word you'd usually mishear. Add an optional replacement to also auto-correct after transcription.",
      helper:
        "Leave the right field empty to add a vocabulary booster only.",
      overuseWarning:
        "Long dictionaries can confuse the recognizer — keep entries focused.",
      biasBadge: "BIAS",
      biasLegend: "Word boosts recognition",
      replaceBadge: "REPLACE",
      replaceLegend: "Auto-corrects to replacement",
      duplicate: "Already in your dictionary.",
      searchPlaceholder: "Search dictionary",
      addPlaceholderWord: "Word or phrase",
      addPlaceholderReplacement: "Replace with… (optional)",
      addAction: "Add",
      deleteAction: "Delete",
      created: "Word added.",
      deleted: "Word removed.",
      emptyTitle: "No Custom Words",
      emptyBody: "Add words you want corrected or auto-replaced when dictating.",
      notAvailableTitle: "Dictionary Unavailable",
      notAvailableBody:
        "Couldn't reach the dictionary service. Try refreshing in a moment.",
      refresh: "Refresh",
      enterWord: "Enter a word.",
      inputWordsRow: "Add a dictionary word",
    },
    shortcuts: {
      open: "Keyboard shortcuts",
      title: "Keyboard shortcuts",
      close: "Close",
      rows: [
        { keys: "/", description: "Focus search" },
        { keys: "n", description: "New recording" },
        { keys: "Esc", description: "Clear selection / close dialogs" },
        { keys: "?", description: "Show this cheatsheet" },
      ],
      notice: "Shortcuts are disabled while typing in inputs.",
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
      summaryQueued: "Summary generation queued.",
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
      folders: { label: "Папки" },
      trash: { label: "Корзина", detail: "Восстановить или удалить навсегда" },
      search: { label: "Поиск", detail: "Найти момент по всем расшифровкам" },
      history: { label: "История диктовки", detail: "Голос превращённый в текст" },
      dictionary: { label: "Словарь", detail: "Свои замены для диктовки" },
      settings: { label: "Настройки", detail: "Аккаунт, диктовка и интеграции" },
    },
    folders: {
      addAriaLabel: "Новая папка",
      addPlaceholder: "Название папки",
      addSubmit: "Создать",
      addCancel: "Отмена",
      addError: "Введите название папки.",
      rename: "Переименовать",
      delete: "Удалить",
      deleteConfirmTitle: (name) => `Удалить папку «${name}»?`,
      deleteConfirmBody:
        "Записи из этой папки останутся, но будут вынесены за её пределы.",
      deleteConfirmAction: "Удалить папку",
      deleteConfirmCancel: "Отмена",
      renameTitle: (name) => `Переименовать «${name}»`,
      renameAction: "Сохранить",
      renameCancel: "Отмена",
      created: "Папка создана.",
      renamed: "Папка переименована.",
      deleted: "Папка удалена.",
      emptyHint: "Папок пока нет — создайте, чтобы упорядочить записи.",
      folderEmptyTitle: "В этой папке записей нет",
      folderEmptyBody: "Перенесите запись в эту папку из карточки записи.",
    },
    history: {
      title: "История диктовки",
      subtitle: "Каждый текст, продиктованный голосом, из Mac, Windows и Linux.",
      emptyTitle: "Истории пока нет",
      emptyBody: "Откройте WaiComputer на Mac или Windows, чтобы начать.",
      notAvailableTitle: "История диктовки недоступна",
      notAvailableBody:
        "Не удалось загрузить историю. Попробуйте обновить через минуту.",
      durationLabel: "длительность",
      wordsLabel: (n) =>
        `${n} ${n === 1 ? "слово" : n >= 2 && n <= 4 ? "слова" : "слов"}`,
      refresh: "Обновить",
      clearAll: "Очистить",
      clearAllConfirm: "Очистить всю историю диктовки?",
      clearAllCancel: "Отмена",
      clearAllPrompt:
        "Все записи из приложений Mac, Windows и Linux будут удалены. Это нельзя отменить.",
      deleted: "Запись удалена.",
      deleteEntry: "Удалить запись",
    },
    dictionary: {
      title: "Словарь",
      subtitle: "Свои замены, применяемые к продиктованному тексту.",
      explainer:
        "Каждая запись подсказывает распознавателю слово, которое он часто слышит неверно. Добавьте замену, чтобы также автоматически исправлять текст.",
      helper:
        "Оставьте правое поле пустым, чтобы только подсказать слово распознавателю.",
      overuseWarning:
        "Длинный список может запутать распознаватель — оставляйте только нужное.",
      biasBadge: "ПОДСКАЗКА",
      biasLegend: "Слово помогает распознаванию",
      replaceBadge: "ЗАМЕНА",
      replaceLegend: "Автозамена на новый текст",
      duplicate: "Это слово уже есть в словаре.",
      searchPlaceholder: "Поиск по словарю",
      addPlaceholderWord: "Слово или фраза",
      addPlaceholderReplacement: "Заменить на… (необязательно)",
      addAction: "Добавить",
      deleteAction: "Удалить",
      created: "Слово добавлено.",
      deleted: "Слово удалено.",
      emptyTitle: "Своих слов пока нет",
      emptyBody: "Добавьте слова, которые нужно исправлять или заменять при диктовке.",
      notAvailableTitle: "Словарь недоступен",
      notAvailableBody:
        "Не удалось загрузить словарь. Попробуйте обновить через минуту.",
      refresh: "Обновить",
      enterWord: "Введите слово.",
      inputWordsRow: "Добавить слово в словарь",
    },
    shortcuts: {
      open: "Горячие клавиши",
      title: "Горячие клавиши",
      close: "Закрыть",
      rows: [
        { keys: "/", description: "Сфокусировать поиск" },
        { keys: "n", description: "Новая запись" },
        { keys: "Esc", description: "Сбросить выбор / закрыть диалоги" },
        { keys: "?", description: "Показать этот список" },
      ],
      notice: "Горячие клавиши не срабатывают, когда вы печатаете в полях.",
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
      summaryQueued: "Саммари поставлено в очередь.",
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

function recordingNeedsRefresh(recording: RecordingDetail | null): boolean {
  if (!recording) return false;
  if (["pending_upload", "uploading", "processing"].includes(recording.status)) return true;
  const summaryStatus = recording.summary_generation?.status;
  return summaryStatus === "queued" || summaryStatus === "running";
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

  // Folders
  const [folders, setFolders] = useState<Folder[]>([]);
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
  const [isFolderCreatorOpen, setIsFolderCreatorOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [folderRenameTarget, setFolderRenameTarget] = useState<Folder | null>(null);
  const [folderRenameValue, setFolderRenameValue] = useState("");
  const [folderDeleteTarget, setFolderDeleteTarget] = useState<Folder | null>(null);

  // Dictation history
  const [dictationEntries, setDictationEntries] = useState<DictationEntry[]>([]);
  const [dictationEntriesLoading, setDictationEntriesLoading] = useState(false);
  const [dictationEntriesLoadedOnce, setDictationEntriesLoadedOnce] = useState(false);
  const [dictationEntriesUnavailable, setDictationEntriesUnavailable] = useState(false);
  const [historyConfirmClear, setHistoryConfirmClear] = useState(false);

  // Dictionary words
  const [dictionaryWords, setDictionaryWords] = useState<DictationDictionaryWord[]>([]);
  const [dictionaryLoading, setDictionaryLoading] = useState(false);
  const [dictionaryLoadedOnce, setDictionaryLoadedOnce] = useState(false);
  const [dictionaryUnavailable, setDictionaryUnavailable] = useState(false);
  const [newWord, setNewWord] = useState("");
  const [newReplacement, setNewReplacement] = useState("");
  const [dictionaryQuery, setDictionaryQuery] = useState("");

  // Keyboard / shortcut affordances
  const [isShortcutCheatsheetOpen, setIsShortcutCheatsheetOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const recorderPaneRef = useRef<HTMLDivElement | null>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [view, setView] = useState<DashboardView>("wai");
  const [accountSettings, setAccountSettings] = useState<UserSettings | null>(null);
  const [transcriptionOptions, setTranscriptionOptions] = useState<TranscriptionOptions | null>(
    null,
  );
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

  const accountHasPassword = user?.has_password !== false;

  async function loadRecordingsState() {
    const active = await listRecordings({ limit: LIST_LIMIT });
    setRecordings(active);
  }

  async function loadTrashRecordingsState() {
    const trashed = await listRecordings({ limit: LIST_LIMIT, trashed: true });
    setTrashRecordings(trashed);
  }

  async function loadFoldersState() {
    try {
      const folderList = await listFolders();
      setFolders(folderList);
    } catch (error: unknown) {
      // 404 means the route isn't deployed yet — keep folders empty rather
      // than blowing up the dashboard. Other errors surface as a message.
      if (error instanceof ApiError && error.status === 404) {
        setFolders([]);
        return;
      }
      throw error;
    }
  }

  async function loadDictationEntriesState() {
    setDictationEntriesLoading(true);
    try {
      const entries = await listDictationEntries();
      setDictationEntries(entries);
      setDictationEntriesUnavailable(false);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 404) {
        setDictationEntries([]);
        setDictationEntriesUnavailable(true);
      } else {
        setMessage(formatError(error));
      }
    } finally {
      setDictationEntriesLoading(false);
      setDictationEntriesLoadedOnce(true);
    }
  }

  async function loadDictionaryState() {
    setDictionaryLoading(true);
    try {
      const words = await listDictionaryWords();
      setDictionaryWords(words);
      setDictionaryUnavailable(false);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 404) {
        setDictionaryWords([]);
        setDictionaryUnavailable(true);
      } else {
        setMessage(formatError(error));
      }
    } finally {
      setDictionaryLoading(false);
      setDictionaryLoadedOnce(true);
    }
  }

  async function loadAccountSettings() {
    setSettingsLoading(true);
    try {
      const [settingsResponse, telegramResponse, optionsResponse] = await Promise.all([
        getSettings(),
        getTelegramLinkStatus(),
        // Cosmetic model labels — degrade to "provider · model" if unavailable.
        getTranscriptionOptions().catch(() => null),
      ]);
      setAccountSettings(settingsResponse);
      setTelegramStatus(telegramResponse);
      setTranscriptionOptions(optionsResponse);
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
      await Promise.all([
        loadRecordingsState(),
        loadFoldersState(),
      ]);
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

  useEffect(() => {
    if (view !== "history" || dictationEntriesLoadedOnce || dictationEntriesLoading) return;
    void loadDictationEntriesState();
  }, [view, dictationEntriesLoadedOnce, dictationEntriesLoading]);

  useEffect(() => {
    if (view !== "dictionary" || dictionaryLoadedOnce || dictionaryLoading) return;
    void loadDictionaryState();
  }, [view, dictionaryLoadedOnce, dictionaryLoading]);

  useEffect(() => {
    if (!recordingNeedsRefresh(selectedRecording)) return;
    let cancelled = false;
    async function refreshSelectedRecording() {
      if (!selectedRecording) return;
      try {
        const detail = await getRecording(selectedRecording.id);
        if (cancelled) return;
        setSelectedRecording(detail);
        setRecordings((current) =>
          current.map((recording) =>
            recording.id === detail.id
              ? {
                  ...recording,
                  title: detail.title,
                  status: detail.status,
                  duration_seconds: detail.duration_seconds,
                  uploaded_at: detail.uploaded_at,
                }
              : recording,
          ),
        );
        if (!recordingNeedsRefresh(detail)) {
          await loadRecordingsState();
        }
      } catch (error: unknown) {
        if (!cancelled) setMessage(formatError(error));
      }
    }
    const interval = window.setInterval(refreshSelectedRecording, 2500);
    window.addEventListener("focus", refreshSelectedRecording);
    void refreshSelectedRecording();
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshSelectedRecording);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedRecording?.id,
    selectedRecording?.status,
    selectedRecording?.summary_generation?.status,
  ]);

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
      handleRecordingDetailUpdate(detail);
      setSelectedMode(mode);
      setView(mode === "trash" ? "trash" : "library");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  function handleRecordingDetailUpdate(detail: RecordingDetail) {
    setSelectedRecording(detail);
    setRecordings((current) =>
      current.map((recording) =>
        recording.id === detail.id
          ? {
              ...recording,
              title: detail.title,
              type: detail.type,
              status: detail.status,
              duration_seconds: detail.duration_seconds,
              folder_id: detail.folder_id,
              uploaded_at: detail.uploaded_at,
            }
          : recording,
      ),
    );
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
      await startSummaryGeneration(recordingId, { instructions: null });
      const detail = await getRecording(recordingId);
      handleRecordingDetailUpdate(detail);
      setSelectedMode("active");
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

  // Folder handlers ---------------------------------------------------------
  async function handleCreateFolder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = newFolderName.trim();
    if (!trimmed) {
      setMessage(copy.folders.addError);
      return;
    }
    setMessage(null);
    try {
      const folder = await createFolder(trimmed);
      setFolders((current) =>
        [...current, folder].sort((a, b) => a.name.localeCompare(b.name)),
      );
      setNewFolderName("");
      setIsFolderCreatorOpen(false);
      setMessage(copy.folders.created);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleConfirmRenameFolder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!folderRenameTarget) return;
    const trimmed = folderRenameValue.trim();
    if (!trimmed) {
      setMessage(copy.folders.addError);
      return;
    }
    setMessage(null);
    try {
      const updated = await renameFolder(folderRenameTarget.id, trimmed);
      setFolders((current) =>
        current
          .map((folder) => (folder.id === updated.id ? updated : folder))
          .sort((a, b) => a.name.localeCompare(b.name)),
      );
      setFolderRenameTarget(null);
      setFolderRenameValue("");
      setMessage(copy.folders.renamed);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  async function handleConfirmDeleteFolder() {
    if (!folderDeleteTarget) return;
    setMessage(null);
    try {
      await deleteFolder(folderDeleteTarget.id);
      setFolders((current) =>
        current.filter((folder) => folder.id !== folderDeleteTarget.id),
      );
      if (activeFolderId === folderDeleteTarget.id) {
        setActiveFolderId(null);
        setView("library");
      }
      await loadRecordingsState();
      setFolderDeleteTarget(null);
      setMessage(copy.folders.deleted);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  function openFolder(folderId: string) {
    setActiveFolderId(folderId);
    setView("folder");
    setSelectedRecording(null);
    setSelectedMode("active");
  }

  // Move a recording to a folder (or out of any folder when folderId is null).
  // Optimistically update local state so the row disappears from "All
  // recordings" filters and the sidebar badge updates immediately, then refetch
  // from the API so the canonical state lands.
  async function handleAssignRecordingToFolder(
    recordingId: string,
    folderId: string | null,
  ) {
    setMessage(null);
    // Optimistic local update so the sidebar count and folder filter respond
    // before the network round-trip.
    setRecordings((current) =>
      current.map((recording) =>
        recording.id === recordingId
          ? { ...recording, folder_id: folderId }
          : recording,
      ),
    );
    if (selectedRecording?.id === recordingId) {
      setSelectedRecording({ ...selectedRecording, folder_id: folderId });
    }
    try {
      await assignRecordingToFolder(recordingId, folderId);
      await loadRecordingsState();
    } catch (error: unknown) {
      setMessage(formatError(error));
      // Reload to reconcile the optimistic state with the canonical truth.
      await loadRecordingsState();
    }
  }

  // Dictation history handlers ---------------------------------------------
  async function handleDeleteDictationEntry(entryId: string) {
    setMessage(null);
    const previous = dictationEntries;
    setDictationEntries((current) =>
      current.filter((entry) => entry.client_entry_id !== entryId),
    );
    try {
      await deleteDictationEntry(entryId);
      setMessage(copy.history.deleted);
    } catch (error: unknown) {
      setDictationEntries(previous);
      setMessage(formatError(error));
    }
  }

  async function handleClearAllDictation() {
    setMessage(null);
    const previous = dictationEntries;
    setDictationEntries([]);
    try {
      await Promise.all(
        previous.map((entry) => deleteDictationEntry(entry.client_entry_id)),
      );
      setMessage(copy.history.deleted);
    } catch (error: unknown) {
      setDictationEntries(previous);
      setMessage(formatError(error));
    }
  }

  // Dictionary handlers -----------------------------------------------------
  async function handleCreateDictionaryWord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = newWord.trim();
    if (!trimmed) {
      setMessage(copy.dictionary.enterWord);
      return;
    }
    // Client-side dedupe (Mac parity: rejects duplicates by lowercase word).
    const lower = trimmed.toLowerCase();
    if (dictionaryWords.some((w) => w.word.toLowerCase() === lower)) {
      setMessage(copy.dictionary.duplicate);
      return;
    }
    setMessage(null);
    try {
      const word = await createDictionaryWord({
        word: trimmed,
        replacement: newReplacement.trim() || null,
      });
      setDictionaryWords((current) => [...current, word]);
      setNewWord("");
      setNewReplacement("");
      setMessage(copy.dictionary.created);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 404) {
        setDictionaryUnavailable(true);
      }
      setMessage(formatError(error));
    }
  }

  async function handleDeleteDictionaryWord(wordId: string) {
    setMessage(null);
    try {
      await deleteDictionaryWord(wordId);
      setDictionaryWords((current) =>
        current.filter((word) => word.client_word_id !== wordId),
      );
      setMessage(copy.dictionary.deleted);
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }

  // Keyboard shortcut wiring ------------------------------------------------
  const focusSearchInput = useCallback(() => {
    setView("search");
    setIsShortcutCheatsheetOpen(false);
    setTimeout(() => {
      searchInputRef.current?.focus();
    }, 0);
  }, []);

  const focusRecorder = useCallback(() => {
    setView("library");
    setSelectedRecording(null);
    setSelectedMode("active");
    setIsShortcutCheatsheetOpen(false);
    setTimeout(() => {
      const node = recorderPaneRef.current?.querySelector<HTMLElement>(
        "input, button, [tabindex]",
      );
      node?.focus();
    }, 0);
  }, []);

  const clearAll = useCallback(() => {
    if (isShortcutCheatsheetOpen) {
      setIsShortcutCheatsheetOpen(false);
      return;
    }
    if (folderRenameTarget) {
      setFolderRenameTarget(null);
      setFolderRenameValue("");
      return;
    }
    if (folderDeleteTarget) {
      setFolderDeleteTarget(null);
      return;
    }
    if (isFolderCreatorOpen) {
      setIsFolderCreatorOpen(false);
      setNewFolderName("");
      return;
    }
    setSelectedRecording(null);
  }, [
    isShortcutCheatsheetOpen,
    folderRenameTarget,
    folderDeleteTarget,
    isFolderCreatorOpen,
  ]);

  const toggleCheatsheet = useCallback(() => {
    setIsShortcutCheatsheetOpen((current) => !current);
  }, []);

  useKeyboardShortcuts({
    "/": focusSearchInput,
    n: focusRecorder,
    Escape: clearAll,
    "?": toggleCheatsheet,
  });

  // Count active recordings per folder. Drag-and-drop and optimistic detail
  // updates both flow through `recordings`, so this only depends on local state.
  const folderCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const folder of folders) counts[folder.id] = 0;
    for (const recording of recordings) {
      if (
        recording.folder_id
        && Object.prototype.hasOwnProperty.call(counts, recording.folder_id)
        && !recording.deleted_at
      ) {
        counts[recording.folder_id] += 1;
      }
    }
    return counts;
  }, [recordings, folders]);

  if (initializing) {
    return (
      <div className="loading-screen">
        <p data-testid="dashboard-loading" className="visually-hidden">
          {copy.loadingDashboard}
        </p>
        <div className="dashboard-skeleton" aria-hidden="true">
          <Skeleton width="60%" height="1.4rem" />
          <Skeleton height="0.8rem" lines={3} />
          <Skeleton height="0.8rem" lines={3} />
        </div>
      </div>
    );
  }

  // Sidebar sections mirror MacContentView's grouped layout:
  // Library / Recording Folders / Dictation / Wai.
  type NavItem = {
    key: Exclude<DashboardView, "folder">;
    label: string;
    count: string | null;
  };
  const navSections: Array<{ header: string; items: NavItem[] }> = [
    {
      header: locale === "ru" ? "Библиотека" : "Library",
      items: [
        {
          key: "library",
          label: copy.nav.library.label,
          count: displayCount(recordings.length),
        },
        {
          key: "trash",
          label: copy.nav.trash.label,
          count: displayCount(trashRecordings.length),
        },
      ],
    },
    {
      header: locale === "ru" ? "Диктовка" : "Dictation",
      items: [
        { key: "history", label: copy.nav.history.label, count: null },
        { key: "dictionary", label: copy.nav.dictionary.label, count: null },
      ],
    },
    {
      header: "Wai",
      items: [
        { key: "wai", label: copy.nav.wai.label, count: null },
        { key: "search", label: copy.nav.search.label, count: null },
        { key: "settings", label: copy.nav.settings.label, count: null },
      ],
    },
  ];
  const allNavItems: NavItem[] = navSections.flatMap((section) => section.items);

  const currentFolder = activeFolderId
    ? folders.find((folder) => folder.id === activeFolderId) ?? null
    : null;
  const folderFilteredRecordings = recordings.filter(
    (recording) => recording.folder_id === activeFolderId,
  );
  const workspaceTitle =
    view === "folder" && currentFolder
      ? currentFolder.name
      : allNavItems.find((item) => item.key === view)?.label ?? copy.fallbackTitle;

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
          {navSections.map((section, index) => (
            <div key={section.header} className="sidebar-section">
              <small className="sidebar-section__header">{section.header}</small>
              {section.items.map((item) => (
                <button
                  key={item.key}
                  data-testid={`tab-${item.key}`}
                  type="button"
                  className="sidebar-nav__item"
                  aria-current={view === item.key ? "page" : undefined}
                  onClick={() => {
                    setActiveFolderId(null);
                    setView(item.key);
                    if (item.key === "trash") {
                      void loadTrashRecordingsState();
                    }
                  }}
                >
                  <span>
                    <strong>{item.label}</strong>
                  </span>
                  {item.count !== null ? <em>{item.count}</em> : null}
                </button>
              ))}

              {/* Folders block lives right after the Library section. */}
              {index === 0 ? (
                <div className="sidebar-folder-group">
                  <div className="sidebar-folder-group__header">
                  <small data-testid="sidebar-folders-label">
                    {copy.nav.folders.label}
                  </small>
                  <button
                    type="button"
                    data-testid="open-create-folder"
                    className="ghost-button compact-button"
                    aria-label={copy.folders.addAriaLabel}
                    onClick={() => {
                      setIsFolderCreatorOpen(true);
                      setNewFolderName("");
                    }}
                  >
                    +
                  </button>
                </div>
                {isFolderCreatorOpen ? (
                  <form
                    className="sidebar-folder-create"
                    data-testid="create-folder-form"
                    onSubmit={handleCreateFolder}
                  >
                    <input
                      type="text"
                      data-testid="new-folder-name"
                      placeholder={copy.folders.addPlaceholder}
                      aria-label={copy.folders.addAriaLabel}
                      value={newFolderName}
                      onChange={(event) => setNewFolderName(event.target.value)}
                    />
                    <div className="row-actions">
                      <button
                        type="submit"
                        data-testid="submit-create-folder"
                        className="ghost-button compact-button"
                      >
                        {copy.folders.addSubmit}
                      </button>
                      <button
                        type="button"
                        className="ghost-button compact-button"
                        onClick={() => {
                          setIsFolderCreatorOpen(false);
                          setNewFolderName("");
                        }}
                      >
                        {copy.folders.addCancel}
                      </button>
                    </div>
                  </form>
                ) : null}
                <ul className="sidebar-folder-list" data-testid="sidebar-folder-list">
                  {folders.length === 0 && !isFolderCreatorOpen ? (
                    <li className="sidebar-folder-list__empty">
                      <small>{copy.folders.emptyHint}</small>
                    </li>
                  ) : null}
                  {folders.map((folder) => {
                    const rawCount = folderCounts[folder.id] ?? 0;
                    const folderCountLabel = displayCount(rawCount);
                    return (
                      <li
                        key={folder.id}
                        className="sidebar-folder-list__item"
                        data-testid={`sidebar-folder-${folder.id}`}
                        onDragOver={(event) => {
                          event.preventDefault();
                          event.dataTransfer.dropEffect = "move";
                        }}
                        onDragEnter={(event) => {
                          event.preventDefault();
                          event.currentTarget.setAttribute(
                            "data-drop-target",
                            "true",
                          );
                        }}
                        onDragLeave={(event) => {
                          event.currentTarget.removeAttribute("data-drop-target");
                        }}
                        onDrop={(event) => {
                          event.preventDefault();
                          event.currentTarget.removeAttribute("data-drop-target");
                          const id = event.dataTransfer.getData(
                            "application/x-wai-recording",
                          );
                          if (!id) return;
                          void handleAssignRecordingToFolder(id, folder.id);
                        }}
                      >
                        <button
                          type="button"
                          data-testid={`open-folder-${folder.id}`}
                          className="sidebar-folder-list__open"
                          aria-current={
                            view === "folder" && activeFolderId === folder.id
                              ? "page"
                              : undefined
                          }
                          onClick={() => openFolder(folder.id)}
                        >
                          {folder.name}
                        </button>
                        <em
                          className="sidebar-folder-list__count"
                          data-testid={`folder-count-${folder.id}`}
                        >
                          {folderCountLabel}
                        </em>
                        <div className="row-actions">
                          <button
                            type="button"
                            data-testid={`rename-folder-${folder.id}`}
                            className="ghost-button compact-button"
                            onClick={() => {
                              setFolderRenameTarget(folder);
                              setFolderRenameValue(folder.name);
                            }}
                          >
                            {copy.folders.rename}
                          </button>
                          <button
                            type="button"
                            data-testid={`delete-folder-${folder.id}`}
                            className="ghost-button compact-button danger-button"
                            onClick={() => setFolderDeleteTarget(folder)}
                          >
                            {copy.folders.delete}
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
                </div>
              ) : null}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button
            data-testid="open-shortcuts"
            type="button"
            className="ghost-button"
            onClick={toggleCheatsheet}
          >
            {copy.shortcuts.open}
          </button>
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

      <main className="workspace" id="main">
        <header className="workspace-header">
          <div>
            <h2 data-testid="workspace-title">{workspaceTitle}</h2>
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
        {view === "folder"
          ? renderLibrary("active", folderFilteredRecordings, { isFolder: true })
          : null}
        {view === "trash" ? renderLibrary("trash", trashRecordings) : null}
        {view === "search" ? renderSearchView() : null}
        {view === "history" ? renderHistoryView() : null}
        {view === "dictionary" ? renderDictionaryView() : null}
        {view === "settings" ? renderSettingsView() : null}
      </main>

      {folderRenameTarget ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          data-testid="folder-rename-modal"
        >
          <form className="modal-card" onSubmit={handleConfirmRenameFolder}>
            <h3>{copy.folders.renameTitle(folderRenameTarget.name)}</h3>
            <input
              type="text"
              data-testid="folder-rename-input"
              value={folderRenameValue}
              onChange={(event) => setFolderRenameValue(event.target.value)}
            />
            <div className="row-actions">
              <button
                type="submit"
                data-testid="folder-rename-submit"
                className="ghost-button compact-button"
              >
                {copy.folders.renameAction}
              </button>
              <button
                type="button"
                className="ghost-button compact-button"
                onClick={() => {
                  setFolderRenameTarget(null);
                  setFolderRenameValue("");
                }}
              >
                {copy.folders.renameCancel}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {folderDeleteTarget ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          data-testid="folder-delete-modal"
        >
          <div className="modal-card">
            <h3>{copy.folders.deleteConfirmTitle(folderDeleteTarget.name)}</h3>
            <p>{copy.folders.deleteConfirmBody}</p>
            <div className="row-actions">
              <button
                type="button"
                data-testid="folder-delete-confirm"
                className="ghost-button compact-button danger-button"
                onClick={() => void handleConfirmDeleteFolder()}
              >
                {copy.folders.deleteConfirmAction}
              </button>
              <button
                type="button"
                className="ghost-button compact-button"
                onClick={() => setFolderDeleteTarget(null)}
              >
                {copy.folders.deleteConfirmCancel}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {isShortcutCheatsheetOpen ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          data-testid="shortcuts-modal"
        >
          <div className="modal-card">
            <h3>{copy.shortcuts.title}</h3>
            <ul className="shortcut-list">
              {copy.shortcuts.rows.map((row) => (
                <li key={row.keys}>
                  <kbd>{row.keys}</kbd>
                  <span>{row.description}</span>
                </li>
              ))}
            </ul>
            <p className="settings-note">{copy.shortcuts.notice}</p>
            <div className="row-actions">
              <button
                type="button"
                data-testid="shortcuts-close"
                className="ghost-button compact-button"
                onClick={() => setIsShortcutCheatsheetOpen(false)}
              >
                {copy.shortcuts.close}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );

  function renderLibrary(
    mode: DetailMode,
    items: Recording[],
    options?: { isFolder?: boolean },
  ) {
    const isTrash = mode === "trash";
    const isFolder = options?.isFolder ?? false;
    const title = isFolder
      ? currentFolder?.name ?? copy.library.title
      : isTrash
        ? copy.library.trashTitle
        : copy.library.title;
    const emptyTitle = isFolder
      ? copy.folders.folderEmptyTitle
      : isTrash
        ? copy.library.trashEmptyTitle
        : copy.library.emptyTitle;
    const emptyBody = isFolder
      ? copy.folders.folderEmptyBody
      : isTrash
        ? copy.library.trashEmptyBody
        : copy.library.emptyBody;

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
              <h3>{emptyTitle}</h3>
              <p>{emptyBody}</p>
            </div>
          ) : (
            <ul className="recording-list" data-testid="recording-list">
              {items.map((recording) => {
                const status = statusText(recording, copy);
                // Trashed recordings cannot be moved into folders, so only
                // active rows are draggable. Folders also stay hidden in trash.
                const draggable = !isTrash;
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
                      draggable={draggable}
                      onDragStart={
                        draggable
                          ? (event) => {
                              event.dataTransfer.setData(
                                "application/x-wai-recording",
                                recording.id,
                              );
                              event.dataTransfer.effectAllowed = "move";
                            }
                          : undefined
                      }
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
              folders={folders}
              locale={locale}
              onAssignFolder={(recordingId, folderId) =>
                void handleAssignRecordingToFolder(recordingId, folderId)
              }
              onRecordingUpdate={handleRecordingDetailUpdate}
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
            <div ref={recorderPaneRef}>
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
            </div>
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
            ref={searchInputRef}
            data-testid="search-query"
            placeholder={copy.search.placeholder}
            aria-label={copy.search.placeholder}
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
          <select
            data-testid="search-mode"
            aria-label={copy.search.submit}
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

  function renderHistoryView() {
    return (
      <section className="tool-panel" data-testid="history-panel">
        <header className="panel-header">
          <div>
            <h3>{copy.history.title}</h3>
            <p className="muted-text">{copy.history.subtitle}</p>
          </div>
          <div className="row-actions">
            {dictationEntries.length > 0 ? (
              <button
                type="button"
                className="ghost-button compact-button danger-button"
                data-testid="history-clear-all"
                onClick={() => setHistoryConfirmClear(true)}
              >
                {copy.history.clearAll}
              </button>
            ) : null}
            <button
              type="button"
              className="ghost-button compact-button"
              data-testid="history-refresh"
              disabled={dictationEntriesLoading}
              onClick={() => void loadDictationEntriesState()}
            >
              {copy.history.refresh}
            </button>
          </div>
        </header>
        <DictationStatsHeader entries={dictationEntries} locale={locale} />
        {dictationEntriesUnavailable ? (
          <div className="empty-state" data-testid="history-unavailable">
            <h3>{copy.history.notAvailableTitle}</h3>
            <p>{copy.history.notAvailableBody}</p>
          </div>
        ) : dictationEntriesLoading && dictationEntries.length === 0 ? (
          <div data-testid="history-loading" className="dashboard-skeleton">
            <Skeleton height="0.8rem" lines={3} />
            <Skeleton height="0.8rem" lines={3} />
          </div>
        ) : dictationEntries.length === 0 ? (
          <div className="empty-state" data-testid="history-empty">
            <h3>{copy.history.emptyTitle}</h3>
            <p>{copy.history.emptyBody}</p>
          </div>
        ) : (
          <ul className="dictation-history-list" data-testid="history-list">
            {dictationEntries.map((entry) => (
              <li
                key={entry.client_entry_id}
                data-testid={`history-entry-${entry.client_entry_id}`}
              >
                <div className="dictation-history__body">
                  <p className="dictation-history__text">
                    {entry.cleaned_text ?? entry.raw_text}
                  </p>
                  <p className="metadata-row">
                    <span>{formatDate(entry.occurred_at, locale)}</span>
                    {entry.duration_seconds > 0 ? (
                      <span>
                        {copy.history.durationLabel} {formatDuration(Math.round(entry.duration_seconds))}
                      </span>
                    ) : null}
                    <span>{copy.history.wordsLabel(entry.word_count)}</span>
                  </p>
                </div>
                <button
                  type="button"
                  className="ghost-button compact-button danger-button"
                  aria-label={copy.history.deleteEntry}
                  data-testid={`delete-history-${entry.client_entry_id}`}
                  onClick={() =>
                    void handleDeleteDictationEntry(entry.client_entry_id)
                  }
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}

        {historyConfirmClear ? (
          <div
            className="modal-backdrop"
            role="dialog"
            aria-modal="true"
            data-testid="history-confirm-clear"
            onClick={(event) => {
              if (event.target === event.currentTarget) {
                setHistoryConfirmClear(false);
              }
            }}
          >
            <div className="modal-card">
              <h3>{copy.history.clearAllConfirm}</h3>
              <p>{copy.history.clearAllPrompt}</p>
              <div className="modal-actions">
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => setHistoryConfirmClear(false)}
                >
                  {copy.history.clearAllCancel}
                </button>
                <button
                  type="button"
                  className="ghost-button danger-button"
                  data-testid="history-confirm-clear-action"
                  onClick={() => {
                    setHistoryConfirmClear(false);
                    void handleClearAllDictation();
                  }}
                >
                  {copy.history.clearAll}
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </section>
    );
  }

  function renderDictionaryView() {
    const query = dictionaryQuery.trim().toLowerCase();
    const sorted = [...dictionaryWords].sort((a, b) =>
      a.word.localeCompare(b.word, undefined, { sensitivity: "base" }),
    );
    const filtered = query
      ? sorted.filter(
          (w) =>
            w.word.toLowerCase().includes(query) ||
            (w.replacement ?? "").toLowerCase().includes(query),
        )
      : sorted;
    const overused = dictionaryWords.length >= 30;

    return (
      <section className="tool-panel" data-testid="dictionary-panel">
        <header className="panel-header">
          <div>
            <h3>{copy.dictionary.title}</h3>
            <p className="muted-text">{copy.dictionary.subtitle}</p>
          </div>
          <button
            type="button"
            className="ghost-button compact-button"
            data-testid="dictionary-refresh"
            disabled={dictionaryLoading}
            onClick={() => void loadDictionaryState()}
          >
            {copy.dictionary.refresh}
          </button>
        </header>

        <p className="dictionary-explainer">{copy.dictionary.explainer}</p>
        <p className="dictionary-legend">
          <span className="badge badge--bias">{copy.dictionary.biasBadge}</span>
          <span className="muted-text">{copy.dictionary.biasLegend}</span>
          <span className="badge badge--replace">{copy.dictionary.replaceBadge}</span>
          <span className="muted-text">{copy.dictionary.replaceLegend}</span>
        </p>

        {overused ? (
          <p className="inline-alert" role="status" data-testid="dictionary-overuse">
            {copy.dictionary.overuseWarning}
          </p>
        ) : null}

        <form
          className="search-form dictionary-add"
          onSubmit={handleCreateDictionaryWord}
          aria-label={copy.dictionary.inputWordsRow}
        >
          <input
            type="text"
            data-testid="new-dictionary-word"
            placeholder={copy.dictionary.addPlaceholderWord}
            value={newWord}
            onChange={(event) => setNewWord(event.target.value)}
          />
          <input
            type="text"
            data-testid="new-dictionary-replacement"
            placeholder={copy.dictionary.addPlaceholderReplacement}
            value={newReplacement}
            onChange={(event) => setNewReplacement(event.target.value)}
          />
          <button data-testid="add-dictionary-word" type="submit">
            {copy.dictionary.addAction}
          </button>
        </form>
        <p className="dictionary-helper muted-text">{copy.dictionary.helper}</p>

        {dictionaryWords.length > 0 ? (
          <input
            type="search"
            className="dictionary-search"
            data-testid="dictionary-search"
            placeholder={copy.dictionary.searchPlaceholder}
            value={dictionaryQuery}
            onChange={(event) => setDictionaryQuery(event.target.value)}
            aria-label={copy.dictionary.searchPlaceholder}
          />
        ) : null}

        {dictionaryUnavailable ? (
          <div className="empty-state" data-testid="dictionary-unavailable">
            <h3>{copy.dictionary.notAvailableTitle}</h3>
            <p>{copy.dictionary.notAvailableBody}</p>
          </div>
        ) : dictionaryLoading && dictionaryWords.length === 0 ? (
          <div data-testid="dictionary-loading" className="dashboard-skeleton">
            <Skeleton height="0.8rem" lines={3} />
          </div>
        ) : dictionaryWords.length === 0 ? (
          <div className="empty-state" data-testid="dictionary-empty">
            <h3>{copy.dictionary.emptyTitle}</h3>
            <p>{copy.dictionary.emptyBody}</p>
          </div>
        ) : (
          <ul className="dictionary-list" data-testid="dictionary-list">
            {filtered.map((word) => {
              const hasReplacement =
                !!word.replacement && word.replacement !== word.word;
              return (
                <li
                  key={word.client_word_id}
                  data-testid={`dictionary-word-${word.client_word_id}`}
                  className="dictionary-row"
                >
                  <span className="dictionary-row__word">{word.word}</span>
                  <span className="dictionary-row__arrow" aria-hidden="true">
                    →
                  </span>
                  <span className="dictionary-row__replacement">
                    {hasReplacement ? word.replacement : ""}
                  </span>
                  <span
                    className={`badge ${hasReplacement ? "badge--replace" : "badge--bias"}`}
                  >
                    {hasReplacement
                      ? copy.dictionary.replaceBadge
                      : copy.dictionary.biasBadge}
                  </span>
                  <button
                    type="button"
                    className="ghost-button compact-button danger-button"
                    aria-label={copy.dictionary.deleteAction}
                    data-testid={`delete-dictionary-${word.client_word_id}`}
                    onClick={() =>
                      void handleDeleteDictionaryWord(word.client_word_id)
                    }
                  >
                    ×
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    );
  }

  function renderSettingsView() {
    return (
      <section className="tool-panel settings-panel">
        <section className="settings-form" data-testid="appearance-settings">
          <h3>{locale === "ru" ? "Внешний вид" : "Appearance"}</h3>
          <ThemeAccentPicker locale={locale} />
        </section>

        <IdentityAndVoicePanel locale={locale} />

        {accountSettings ? (
          <TranscriptionSettingsPanel
            settings={accountSettings}
            transcriptionOptions={transcriptionOptions}
            onUpdate={(patch) => void handleUpdateAccountSettings(patch)}
            busy={settingsSaving}
            locale={locale}
          />
        ) : null}

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
            <PasswordField
              id="settings-current-password"
              data-testid="current-password"
              label={copy.settings.currentPassword}
              value={currentPassword}
              onChange={setCurrentPassword}
              locale={locale}
              required
              autoComplete="current-password"
            />
          )}
          <PasswordField
            id="settings-new-password"
            data-testid="new-password"
            label={copy.settings.newPassword}
            value={newPassword}
            onChange={setNewPassword}
            locale={locale}
            showStrength
            required
            autoComplete="new-password"
          />
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
          aria-label={copy.library.newRecordingHeading}
          value={title}
          onChange={(event) => onTitleChange(event.target.value)}
        />
        <select
          aria-label={copy.library.newRecordingHeading}
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

// useKeyboardShortcuts ----------------------------------------------------
// Maps single-character keys (case-insensitive) to handlers.
// Skips firing when the user is typing in inputs, textareas, contenteditable
// elements, or while holding modifiers (Cmd/Ctrl/Alt) that would steal the
// keypress for the browser.

type KeyboardShortcutMap = Record<string, () => void>;

function useKeyboardShortcuts(shortcuts: KeyboardShortcutMap): void {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      const target = event.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
          return;
        }
        if (target.isContentEditable) {
          return;
        }
      }

      const candidates: string[] = [event.key];
      // Accept "?" both as direct event.key on US keyboards and as
      // Shift+/ which is the OS-level chord.
      if (event.key === "/" && event.shiftKey) {
        candidates.push("?");
      }
      // Normalize Escape to a single canonical key.
      if (event.key === "Esc") {
        candidates.push("Escape");
      }

      for (const candidate of candidates) {
        const handler = shortcuts[candidate];
        if (handler) {
          event.preventDefault();
          handler();
          return;
        }
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shortcuts]);
}
