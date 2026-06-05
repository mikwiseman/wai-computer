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
  bulkRecordingOperation,
  changePassword,
  claimTelegramLinkCode,
  createBrainMap,
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
  listInbox,
  listDictationEntries,
  listDictionaryWords,
  listFolders,
  listRecordings,
  logout,
  renameFolder,
  restoreRecording,
  search,
  semanticSearch,
  startTelegramLink,
  unifiedSearch,
  updateSettings,
  unlinkTelegram,
} from "@/lib/api";
import { CompanionPanel } from "@/components/CompanionPanel";
import { RecordingDetailPanel } from "@/components/RecordingDetailPanel";
import { ItemDetail } from "@/components/ItemDetail";
import { AudioUpload } from "@/components/AudioUpload";
import { LiveRecorder } from "@/components/LiveRecorder";
import { McpConnectSection } from "@/components/McpConnectSection";
import { ApiKeysSection } from "@/components/ApiKeysSection";
import { ServerDataSection } from "@/components/ServerDataSection";
import { IdentityAndVoicePanel } from "@/components/IdentityAndVoicePanel";
import { ThemeAccentPicker } from "@/components/ThemeAccentPicker";
import { TranscriptionSettingsPanel } from "@/components/TranscriptionSettingsPanel";
import { DictationStatsHeader } from "@/components/DictationStatsHeader";
import { DeleteAccountSection } from "@/components/DeleteAccountSection";
import { AddAnythingPanel } from "@/components/AddAnythingPanel";
import { BrainPanel } from "@/components/BrainPanel";
import { DictatePanel } from "@/components/DictatePanel";
import { PasswordField } from "@/components/PasswordField";
import { Skeleton } from "@/components/Skeleton";
import { ApiError } from "@/lib/http";
import { createChat } from "@/lib/companion";
import type {
  BulkAction,
  DictationCleanupLevel,
  DictationDictionaryWord,
  DictationEntry,
  Folder,
  InboxRow,
  InboxSourceKind,
  InboxStatusFilter,
  CompanionScope,
  Recording,
  RecordingDetail,
  RecordingType,
  SearchResponse,
  UnifiedSearchResponse,
  TelegramLinkStatus,
  TelegramPairing,
  TranscriptionOptions,
  User,
  UserSettings,
} from "@/lib/types";

type SearchMode = "hybrid" | "semantic" | "fts" | "everything";
type DashboardView =
  | "inbox"
  | "wai"
  | "add"
  | "content"
  | "brain"
  | "library"
  | "folder"
  | "trash"
  | "search"
  | "dictate"
  | "history"
  | "dictionary"
  | "settings";
type DetailMode = "active" | "trash";
type Locale = "en" | "ru";
type OpenableInboxSourceKind = Extract<InboxSourceKind, "recording" | "item" | "chat">;
type PendingInboxSource = {
  sourceKind: OpenableInboxSourceKind;
  sourceId: string;
  nonce: number;
};

const LIST_LIMIT = 100;
const DASHBOARD_VIEW_KEYS = [
  "inbox",
  "wai",
  "add",
  "content",
  "brain",
  "library",
  "trash",
  "search",
  "dictate",
  "history",
  "dictionary",
  "settings",
] as const;

function isDashboardView(value: string | null): value is DashboardView {
  return DASHBOARD_VIEW_KEYS.includes(value as (typeof DASHBOARD_VIEW_KEYS)[number]);
}

function canonicalDashboardView(value: DashboardView): DashboardView {
  if (
    value === "add"
    || value === "content"
    || value === "library"
    || value === "wai"
  ) {
    return "inbox";
  }
  return value;
}

function viewFromCurrentLocation(): DashboardView | null {
  if (typeof window === "undefined") return null;

  const params = new URLSearchParams(window.location.search);
  const requested = params.get("view") ?? params.get("tab");
  if (requested === "agents") return "inbox";
  if (isDashboardView(requested)) return canonicalDashboardView(requested);

  const hash = window.location.hash.replace(/^#/, "");
  if (hash === "server-data" || hash === "settings") return "settings";
  if (hash === "agents") return "inbox";
  if (isDashboardView(hash)) return canonicalDashboardView(hash);
  return null;
}

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
    inbox: { label: string; detail: string };
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
  // Recording archive and trash copy
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
    everything: string;
    total: (n: number) => string;
    enterQuery: string;
    noResultsTitle: string;
    noResultsBody: string;
    score: string;
    open: string;
  };
  // Settings
  settings: {
    workspaceGroupTitle: string;
    workspaceGroupBody: string;
    voiceGroupTitle: string;
    voiceGroupBody: string;
    accountGroupTitle: string;
    accountGroupBody: string;
    developerGroupTitle: string;
    developerGroupBody: string;
    dictationHeading: string;
    loadingSettings: string;
    cleanupLevel: string;
    cleanupLevels: Record<DictationCleanupLevel, { label: string; description: string }>;
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
      inbox: { label: "Inbox", detail: "Recordings, materials, and chats" },
      wai: { label: "Inbox", detail: "Recordings, materials, and chats" },
      library: { label: "Inbox", detail: "Recordings, materials, and chats" },
      folders: { label: "Folders" },
      trash: { label: "Trash", detail: "Restore or delete forever" },
      search: { label: "Search", detail: "Find a moment across transcripts" },
      history: { label: "Dictation History", detail: "Voice to text inserts" },
      dictionary: { label: "Dictionary", detail: "Custom dictation replacements" },
      settings: { label: "Settings", detail: "Account, data, and integrations" },
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
        "Inbox items inside this folder will be moved out of it. The items themselves are kept.",
      deleteConfirmAction: "Delete folder",
      deleteConfirmCancel: "Cancel",
      renameTitle: (name) => `Rename “${name}”`,
      renameAction: "Save",
      renameCancel: "Cancel",
      created: "Folder created.",
      renamed: "Folder renamed.",
      deleted: "Folder deleted.",
      emptyHint: "No folders yet — create one to organize Inbox items.",
      folderEmptyTitle: "No Items in This Folder",
      folderEmptyBody: "Add a recording, file, link, text, or chat to this folder.",
    },
    history: {
      title: "Dictation History",
      subtitle: "Every voice-to-text insert from Mac and web.",
      emptyTitle: "No Dictation Yet",
      emptyBody: "Open WaiComputer on Mac or web to start dictating.",
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
        "Every insert from your Mac and web clients will be removed. This cannot be undone.",
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
        { keys: "n", description: "Add to Inbox" },
        { keys: "d", description: "Dictate" },
        { keys: "l", description: "Inbox" },
        { keys: "w", description: "Inbox" },
        { keys: "Esc", description: "Clear selection / close dialogs" },
        { keys: "?", description: "Show this cheatsheet" },
      ],
      notice: "Shortcuts are disabled while typing in inputs.",
    },
    library: {
      title: "Inbox",
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
      everything: "Everything",
      total: (n) => `Total: ${n}`,
      enterQuery: "Enter a search query.",
      noResultsTitle: "No Results",
      noResultsBody: "No matching transcript segments found.",
      score: "Score",
      open: "Open",
    },
    settings: {
      workspaceGroupTitle: "Inbox & sources",
      workspaceGroupBody:
        "Choose where WaiComputer runs, connect sources, and keep every recording, material, and chat flowing into Inbox.",
      voiceGroupTitle: "Voice, summaries & appearance",
      voiceGroupBody:
        "Tune language, voice identity, dictation cleanup, summaries, and the visual theme.",
      accountGroupTitle: "Account",
      accountGroupBody: "Password and account controls live here so everyday setup stays focused.",
      developerGroupTitle: "Developer access",
      developerGroupBody:
        "Connect AI tools through MCP or create read-only tokens for automation.",
      dictationHeading: "Dictation",
      loadingSettings: "Loading account settings...",
      cleanupLevel: "Cleanup level",
      cleanupLevels: {
        none: {
          label: "None",
          description: "Insert dictated text after dictionary replacements.",
        },
        light: {
          label: "Light",
          description: "Remove filler words and fix grammar.",
        },
        medium: {
          label: "Medium",
          description: "Edit for clarity and conciseness.",
        },
        high: {
          label: "High",
          description: "Rewrite for brevity and polish.",
        },
      },
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
        "Link @waicomputer_bot to send voice, video, and text questions. Media is transcribed, summarized, and saved to your Inbox.",
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
      inbox: { label: "Инбокс", detail: "Записи, материалы и чаты" },
      wai: { label: "Инбокс", detail: "Записи, материалы и чаты" },
      library: { label: "Инбокс", detail: "Записи, материалы и чаты" },
      folders: { label: "Папки" },
      trash: { label: "Корзина", detail: "Восстановить или удалить навсегда" },
      search: { label: "Поиск", detail: "Найти момент по всем расшифровкам" },
      history: { label: "История диктовки", detail: "Голос превращённый в текст" },
      dictionary: { label: "Словарь", detail: "Свои замены для диктовки" },
      settings: { label: "Настройки", detail: "Аккаунт, данные и интеграции" },
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
        "Объекты Инбокса из этой папки останутся, но будут вынесены за её пределы.",
      deleteConfirmAction: "Удалить папку",
      deleteConfirmCancel: "Отмена",
      renameTitle: (name) => `Переименовать «${name}»`,
      renameAction: "Сохранить",
      renameCancel: "Отмена",
      created: "Папка создана.",
      renamed: "Папка переименована.",
      deleted: "Папка удалена.",
      emptyHint: "Папок пока нет — создайте, чтобы упорядочить объекты Инбокса.",
      folderEmptyTitle: "В этой папке пока нет объектов",
      folderEmptyBody: "Добавьте запись, файл, ссылку, текст или чат в эту папку.",
    },
    history: {
      title: "История диктовки",
      subtitle: "Каждый текст, продиктованный голосом, из Mac и Web.",
      emptyTitle: "Истории пока нет",
      emptyBody: "Откройте WaiComputer на Mac или в Web, чтобы начать.",
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
        "Все записи из приложений Mac и Web будут удалены. Это нельзя отменить.",
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
        { keys: "n", description: "Добавить в Инбокс" },
        { keys: "d", description: "Диктовка" },
        { keys: "l", description: "Инбокс" },
        { keys: "w", description: "Инбокс" },
        { keys: "Esc", description: "Сбросить выбор / закрыть диалоги" },
        { keys: "?", description: "Показать этот список" },
      ],
      notice: "Горячие клавиши не срабатывают, когда вы печатаете в полях.",
    },
    library: {
      title: "Инбокс",
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
      everything: "Везде",
      total: (n) => `Всего: ${n}`,
      enterQuery: "Введите поисковый запрос.",
      noResultsTitle: "Ничего не найдено",
      noResultsBody: "Не нашли подходящих фрагментов транскрипта.",
      score: "Релевантность",
      open: "Открыть",
    },
    settings: {
      workspaceGroupTitle: "Инбокс и источники",
      workspaceGroupBody:
        "Выберите, где работает WaiComputer, подключите источники и отправляйте записи, материалы и чаты в Инбокс.",
      voiceGroupTitle: "Голос, саммари и внешний вид",
      voiceGroupBody:
        "Настройте язык, голосовой профиль, очистку диктовки, саммари и тему.",
      accountGroupTitle: "Аккаунт",
      accountGroupBody:
        "Пароль и управление аккаунтом собраны отдельно, чтобы основная настройка не распухала.",
      developerGroupTitle: "Доступ для разработчиков",
      developerGroupBody:
        "Подключите AI-инструменты через MCP или создайте read-only токены для автоматизации.",
      dictationHeading: "Диктовка",
      loadingSettings: "Загружаем настройки аккаунта...",
      cleanupLevel: "Уровень очистки",
      cleanupLevels: {
        none: {
          label: "Нет",
          description: "Вставляет текст после замен из словаря.",
        },
        light: {
          label: "Лёгкая",
          description: "Убирает слова-паразиты и правит грамматику.",
        },
        medium: {
          label: "Средняя",
          description: "Делает текст яснее и короче.",
        },
        high: {
          label: "Сильная",
          description: "Переписывает текст кратко и гладко.",
        },
      },
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
        "Привяжите @waicomputer_bot, чтобы отправлять голосовые, видео и вопросы текстом. Медиа расшифровываются, суммаризируются и сохраняются в Инбокс.",
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
  const audioStatus = recording.summary_audio?.status;
  return (
    summaryStatus === "queued" ||
    summaryStatus === "running" ||
    audioStatus === "queued" ||
    audioStatus === "running"
  );
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
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectedMode, setSelectedMode] = useState<DetailMode>("active");

  const [searchMode, setSearchMode] = useState<SearchMode>("hybrid");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null);
  const [unifiedResponse, setUnifiedResponse] = useState<UnifiedSearchResponse | null>(null);

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
  const [, setItemsReloadKey] = useState(0);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [view, setView] = useState<DashboardView>("inbox");
  const [pendingInboxSource, setPendingInboxSource] = useState<PendingInboxSource | null>(
    null,
  );
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

  useEffect(() => {
    const requestedView = viewFromCurrentLocation();
    if (!requestedView) return;
    setActiveFolderId(null);
    setSelectedRecording(null);
    setView(requestedView);
  }, []);

  useEffect(() => {
    if (view !== "settings" || window.location.hash !== "#server-data") return;
    window.requestAnimationFrame(() => {
      document.getElementById("server-data")?.scrollIntoView({ block: "start" });
    });
  }, [view]);

  const accountHasPassword = user?.has_password !== false;

  async function loadRecordingsState() {
    const active = await listRecordings({ limit: LIST_LIMIT });
    setRecordings(active);
  }

  async function loadTrashRecordingsState() {
    const trashed = await listRecordings({ limit: LIST_LIMIT, trashed: true });
    setTrashRecordings(trashed);
  }

  function toggleSelected(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function exitSelectMode() {
    setSelectMode(false);
    setSelectedIds(new Set());
  }

  async function handleBulk(action: BulkAction, folderId?: string | null) {
    if (selectedIds.size === 0) return;
    const ids = [...selectedIds];
    setMessage(null);
    try {
      await bulkRecordingOperation(ids, action, folderId);
      await Promise.all([loadRecordingsState(), loadTrashRecordingsState()]);
      if (selectedRecording && selectedIds.has(selectedRecording.id)) {
        setSelectedRecording(null);
      }
      exitSelectMode();
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
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

  const handleRefreshTelegramStatus = useCallback(
    async (options: { silent?: boolean } = {}) => {
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
    },
    [copy.telegram.linked],
  );

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
  }, [handleRefreshTelegramStatus, view, telegramStatus?.linked, telegramPairing]);

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
    selectedRecording?.summary_audio?.status,
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
      setSelectedRecording(null);
      setSelectedMode("active");
      setView("inbox");
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
      setView(mode === "trash" ? "trash" : "inbox");
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

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchQuery.trim();
    setMessage(null);
    if (query.length === 0) {
      setSearchResponse(null);
      setUnifiedResponse(null);
      setMessage(copy.search.enterQuery);
      return;
    }
    try {
      setUnifiedResponse(null);
      if (searchMode === "everything") {
        setSearchResponse(null);
        setUnifiedResponse(await unifiedSearch({ q: query, limit: 25 }));
        return;
      }
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
        setView("inbox");
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
    setView("inbox");
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

  const goToView = useCallback((next: DashboardView) => {
    setView(canonicalDashboardView(next));
    setSelectedRecording(null);
    setIsShortcutCheatsheetOpen(false);
  }, []);

  const handlePendingInboxSourceConsumed = useCallback(() => {
    setPendingInboxSource(null);
  }, []);

  const handleNewChat = useCallback(async (scope?: CompanionScope) => {
    setMessage(null);
    try {
      const chat = await createChat(scope);
      setActiveFolderId(null);
      setSelectedRecording(null);
      setSelectedMode("active");
      setPendingInboxSource({
        sourceKind: "chat",
        sourceId: chat.id,
        nonce: Date.now(),
      });
      setView("inbox");
    } catch (error: unknown) {
      setMessage(formatError(error));
    }
  }, []);

  useKeyboardShortcuts({
    "/": focusSearchInput,
    n: focusRecorder,
    d: () => goToView("dictate"),
    l: () => goToView("inbox"),
    w: () => goToView("inbox"),
    Escape: clearAll,
    "?": toggleCheatsheet,
  });

  // Count active local recordings per folder; uploaded material counts arrive
  // through the folder-scoped Inbox once it refreshes.
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

  // Sidebar sections mirror MacContentView's simplified grouped layout:
  // Workspace / Folders / Dictation / Tools.
  type NavItem = {
    key: Exclude<DashboardView, "folder">;
    label: string;
    count: string | null;
  };
  const navSections: Array<{ header: string; items: NavItem[] }> = [
    {
      header: locale === "ru" ? "Рабочее" : "Workspace",
      items: [
        {
          key: "inbox",
          label: copy.nav.inbox.label,
          count: null,
        },
        {
          key: "brain",
          label: locale === "ru" ? "Мозг" : "Brain",
          count: null,
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
        { key: "dictate", label: locale === "ru" ? "Диктовать" : "Dictate", count: null },
        { key: "history", label: copy.nav.history.label, count: null },
        { key: "dictionary", label: copy.nav.dictionary.label, count: null },
      ],
    },
    {
      header: locale === "ru" ? "Инструменты" : "Tools",
      items: [
        { key: "search", label: copy.nav.search.label, count: null },
        { key: "settings", label: copy.nav.settings.label, count: null },
      ],
    },
  ];
  const allNavItems: NavItem[] = navSections.flatMap((section) => section.items);

  const currentFolder = activeFolderId
    ? folders.find((folder) => folder.id === activeFolderId) ?? null
    : null;
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
                    setSelectedRecording(null);
                    setSelectedMode("active");
                    setView(canonicalDashboardView(item.key));
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

              {/* Folders block lives right after the Workspace section. */}
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

        {view === "inbox" ? (
          <UniversalInboxPanel
            locale={locale}
            copy={copy}
            folderId={null}
            folderName={null}
            pendingSource={pendingInboxSource}
            onPendingSourceConsumed={handlePendingInboxSourceConsumed}
            initialRecording={selectedRecording}
            recordings={recordings}
            folders={folders}
            recordingTitle={recordingTitle}
            recordingType={recordingType}
            onRecordingTitleChange={setRecordingTitle}
            onRecordingTypeChange={setRecordingType}
            onRecordingUpdate={handleRecordingDetailUpdate}
            onAssignRecordingToFolder={handleAssignRecordingToFolder}
            onDeleteRecording={handleDeleteRecording}
            onRefreshRecordings={loadRecordingsState}
            onItemsChanged={() => setItemsReloadKey((key) => key + 1)}
            onError={setMessage}
            onOpenBrain={() => setView("brain")}
          />
        ) : null}
        {view === "library" || view === "wai" || view === "add" || view === "content" ? (
          <UniversalInboxPanel
            locale={locale}
            copy={copy}
            folderId={null}
            folderName={null}
            initialRecording={selectedRecording}
            recordings={recordings}
            folders={folders}
            recordingTitle={recordingTitle}
            recordingType={recordingType}
            onRecordingTitleChange={setRecordingTitle}
            onRecordingTypeChange={setRecordingType}
            onRecordingUpdate={handleRecordingDetailUpdate}
            onAssignRecordingToFolder={handleAssignRecordingToFolder}
            onDeleteRecording={handleDeleteRecording}
            onRefreshRecordings={loadRecordingsState}
            onItemsChanged={() => setItemsReloadKey((key) => key + 1)}
            onError={setMessage}
            onOpenBrain={() => setView("brain")}
          />
        ) : null}
        {view === "folder" && currentFolder ? (
          <UniversalInboxPanel
            locale={locale}
            copy={copy}
            folderId={currentFolder.id}
            folderName={currentFolder.name}
            recordings={recordings}
            folders={folders}
            recordingTitle={recordingTitle}
            recordingType={recordingType}
            onRecordingTitleChange={setRecordingTitle}
            onRecordingTypeChange={setRecordingType}
            onRecordingUpdate={handleRecordingDetailUpdate}
            onAssignRecordingToFolder={handleAssignRecordingToFolder}
            onDeleteRecording={handleDeleteRecording}
            onRefreshRecordings={loadRecordingsState}
            onItemsChanged={() => setItemsReloadKey((key) => key + 1)}
            onError={setMessage}
            onOpenBrain={() => setView("brain")}
          />
        ) : null}
        {view === "trash" ? renderLibrary("trash", trashRecordings) : null}
        {view === "search" ? renderSearchView() : null}
        {view === "brain" ? (
          <section className="tool-panel">
            <BrainPanel
              locale={locale}
              onError={setMessage}
              onOpenInbox={() => setView("inbox")}
              onOpenWai={({ spaceId }) => handleNewChat({ brain_space_id: spaceId })}
              onOpenSource={(sourceKind, sourceId) => {
                setActiveFolderId(null);
                setSelectedRecording(null);
                setSelectedMode("active");
                setPendingInboxSource({
                  sourceKind,
                  sourceId,
                  nonce: Date.now(),
                });
                setView("inbox");
              }}
            />
          </section>
        ) : null}
        {view === "dictate" ? <DictatePanel locale={locale} /> : null}
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

  function renderLibrary(mode: DetailMode, items: Recording[]) {
    const isTrash = mode === "trash";
    const title = isTrash ? copy.library.trashTitle : copy.library.title;
    const emptyTitle = isTrash ? copy.library.trashEmptyTitle : copy.library.emptyTitle;
    const emptyBody = isTrash ? copy.library.trashEmptyBody : copy.library.emptyBody;

    return (
      <div className="library-grid">
        <section className="recording-list-panel" aria-label={title}>
          <header className="panel-header">
            <div>
              <h3>{title}</h3>
              <p>{copy.library.recordingsCount(items.length)}</p>
            </div>
            <div className="row-actions">
              {items.length > 0 ? (
                <button
                  type="button"
                  className="ghost-button compact-button"
                  data-testid="select-mode-toggle"
                  onClick={() => (selectMode ? exitSelectMode() : setSelectMode(true))}
                >
                  {selectMode
                    ? locale === "ru"
                      ? "Готово"
                      : "Done"
                    : locale === "ru"
                      ? "Выбрать"
                      : "Select"}
                </button>
              ) : null}
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
            </div>
          </header>

          {selectMode && selectedIds.size > 0 ? (
            <div className="bulk-bar" data-testid="bulk-bar">
              <span className="bulk-bar__count">
                {locale === "ru"
                  ? `Выбрано: ${selectedIds.size}`
                  : `${selectedIds.size} selected`}
              </span>
              {isTrash ? (
                <button
                  type="button"
                  className="ghost-button compact-button"
                  data-testid="bulk-restore"
                  onClick={() => void handleBulk("restore")}
                >
                  {locale === "ru" ? "Восстановить" : "Restore"}
                </button>
              ) : (
                <>
                  {folders.length > 0 ? (
                    <select
                      className="select-button"
                      data-testid="bulk-move-folder"
                      aria-label={locale === "ru" ? "Переместить в папку" : "Move to folder"}
                      defaultValue=""
                      onChange={(event) => {
                        if (event.target.value) void handleBulk("move", event.target.value);
                        event.target.value = "";
                      }}
                    >
                      <option value="" disabled>
                        {locale === "ru" ? "В папку…" : "Move to…"}
                      </option>
                      {folders.map((folder) => (
                        <option key={folder.id} value={folder.id}>
                          {folder.name}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  <button
                    type="button"
                    className="ghost-button compact-button danger-button"
                    data-testid="bulk-trash"
                    onClick={() => void handleBulk("delete")}
                  >
                    {locale === "ru" ? "В корзину" : "Move to Trash"}
                  </button>
                </>
              )}
            </div>
          ) : null}

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
                  <li key={recording.id} className="recording-list__item">
                    {selectMode ? (
                      <input
                        type="checkbox"
                        className="recording-select-checkbox"
                        aria-label={locale === "ru" ? "Выбрать запись" : "Select recording"}
                        checked={selectedIds.has(recording.id)}
                        onChange={() => toggleSelected(recording.id)}
                        data-testid={`select-checkbox-${recording.id}`}
                      />
                    ) : null}
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
                locale={locale}
                folderId={null}
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
              setUnifiedResponse(null);
            }}
          >
            <option value="hybrid">{copy.search.hybrid}</option>
            <option value="semantic">{copy.search.semantic}</option>
            <option value="fts">{copy.search.fts}</option>
            <option value="everything">{copy.search.everything}</option>
          </select>
          <button data-testid="search-submit" type="submit">
            {copy.search.submit}
          </button>
        </form>

        <p data-testid="search-total" className="muted-text">
          {copy.search.total(
            (searchMode === "everything" ? unifiedResponse?.total : searchResponse?.total) ?? 0,
          )}
        </p>
        {searchMode === "everything" && unifiedResponse?.results ? (
          unifiedResponse.results.length > 0 ? (
            <ul className="search-results" data-testid="unified-search-results">
              {unifiedResponse.results.map((hit) => (
                <li key={hit.chunk_id} data-testid={`unified-result-${hit.chunk_id}`}>
                  <strong>{hit.title ?? copy.library.untitled}</strong>
                  <p>{hit.snippet}</p>
                  <div className="search-result-footer">
                    <small>
                      {(hit.source_kind === "item" ? hit.kind : "recording").toUpperCase()} /{" "}
                      {copy.search.score} {hit.score.toFixed(2)}
                    </small>
                    <button
                      type="button"
                      className="ghost-button compact-button"
                      onClick={() => {
                        if (hit.source_kind === "recording") {
                          void handleSelectRecording(hit.parent_id);
                        } else {
                          setView("inbox");
                        }
                      }}
                    >
                      {copy.search.open}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="empty-state" data-testid="search-no-results">
              <h3>{copy.search.noResultsTitle}</h3>
              <p>{copy.search.noResultsBody}</p>
            </div>
          )
        ) : searchResponse?.results && searchResponse.results.length > 0 ? (
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
        <div className="settings-group" data-testid="settings-group-workspace">
          <header className="settings-group__header">
            <h2>{copy.settings.workspaceGroupTitle}</h2>
            <p>{copy.settings.workspaceGroupBody}</p>
          </header>
          <ServerDataSection locale={locale} />
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
                <details className="settings-disclosure">
                  <summary>{copy.telegram.codeHelp}</summary>
                  <form className="telegram-code-form" onSubmit={handleClaimTelegramLinkCode}>
                    <label>
                      <span>{copy.telegram.codeLabel}</span>
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
                </details>
              </div>
            )}
          </div>
        </div>

        <div className="settings-group" data-testid="settings-group-voice">
          <header className="settings-group__header">
            <h2>{copy.settings.voiceGroupTitle}</h2>
            <p>{copy.settings.voiceGroupBody}</p>
          </header>
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
              <div className="settings-field cleanup-level-field">
                <span>{copy.settings.cleanupLevel}</span>
                <div
                  className="cleanup-level-options"
                  role="radiogroup"
                  aria-label={copy.settings.cleanupLevel}
                >
                  {(["none", "light", "medium", "high"] as const).map((level) => (
                    <label
                      key={level}
                      className={`cleanup-level-option${
                        accountSettings.dictation_cleanup_level === level ? " selected" : ""
                      }`}
                    >
                      <input
                        type="radio"
                        name="dictation-cleanup-level"
                        value={level}
                        checked={accountSettings.dictation_cleanup_level === level}
                        disabled={settingsSaving}
                        onChange={() =>
                          void handleUpdateAccountSettings({
                            dictation_cleanup_level: level,
                          })
                        }
                      />
                      <strong>{copy.settings.cleanupLevels[level].label}</strong>
                      <small>{copy.settings.cleanupLevels[level].description}</small>
                    </label>
                  ))}
                </div>
              </div>
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
        </div>

        <div className="settings-group" data-testid="settings-group-account">
          <header className="settings-group__header">
            <h2>{copy.settings.accountGroupTitle}</h2>
            <p>{copy.settings.accountGroupBody}</p>
          </header>
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
          <DeleteAccountSection onDeleted={() => router.replace("/login")} locale={locale} />
        </div>

        <div className="settings-group" data-testid="settings-group-developer">
          <header className="settings-group__header">
            <h2>{copy.settings.developerGroupTitle}</h2>
            <p>{copy.settings.developerGroupBody}</p>
          </header>
          <McpConnectSection />
          <ApiKeysSection />
        </div>
      </section>
    );
  }
}

type InboxFilterKind = "all" | InboxSourceKind;
type InboxFilterStatus = "all" | InboxStatusFilter;

function inboxTitle(row: InboxRow, locale: Locale): string {
  const title = row.title?.trim();
  if (title) return title;
  if (row.source_kind === "recording") {
    return locale === "ru" ? "Без названия" : "Untitled recording";
  }
  if (row.source_kind === "chat") {
    return "Wai";
  }
  return locale === "ru" ? "Без названия" : "Untitled material";
}

function inboxStatusLabel(row: InboxRow, locale: Locale): string | null {
  if (row.status === "ready") return null;
  if (locale === "ru") {
    if (row.status === "processing") return "обработка";
    if (row.status === "needs_input") return "нужен ввод";
    if (row.status === "failed") return "ошибка";
    return "архив";
  }
  if (row.status === "processing") return "processing";
  if (row.status === "needs_input") return "needs input";
  if (row.status === "failed") return "failed";
  return "archived";
}

function sourceLabel(kind: InboxSourceKind, locale: Locale): string {
  if (locale === "ru") {
    if (kind === "recording") return "Запись";
    if (kind === "item") return "Материал";
    return "Wai";
  }
  if (kind === "recording") return "Recording";
  if (kind === "item") return "Material";
  return "Wai";
}

function inboxSublabel(row: InboxRow, locale: Locale): string | null {
  if (!row.sublabel) return null;
  if (row.source_kind === "chat" && row.sublabel === "Agent thread") {
    return locale === "ru" ? "Агентская сессия" : "Agent session";
  }
  return row.sublabel;
}

function recordingRowFromDetail(detail: RecordingDetail): InboxRow {
  return {
    id: `recording:${detail.id}`,
    source_kind: "recording",
    source_id: detail.id,
    detail: { kind: "recording", id: detail.id },
    title: detail.title,
    source_label: "Recording",
    sublabel: detail.type,
    activity_at: detail.created_at,
    created_at: detail.created_at,
    updated_at: detail.updated_at ?? detail.created_at,
    occurred_at: detail.uploaded_at,
    status:
      detail.status === "ready"
        ? "ready"
        : detail.status === "failed"
          ? "failed"
          : "processing",
    source_status: detail.status,
    error: detail.failure_code
      ? {
          code: detail.failure_code,
          message: detail.failure_message ?? "",
        }
      : null,
    folder_id: detail.folder_id,
    duration_seconds: detail.duration_seconds,
    language: detail.language,
    has_summary: detail.summary !== null,
    is_starred: detail.starred_at !== null,
    is_pinned: false,
    is_archived: false,
    is_trashed: false,
  };
}

function InboxKindIcon({ kind }: { kind: InboxSourceKind }) {
  if (kind === "recording") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 12v-2" />
        <path d="M8 17V7" />
        <path d="M12 20V4" />
        <path d="M16 17V7" />
        <path d="M20 14v-4" />
      </svg>
    );
  }
  if (kind === "item") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M7 3h7l4 4v14H7z" />
        <path d="M14 3v5h5" />
        <path d="M9 13h6" />
        <path d="M9 17h4" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 6.5h14v9H9l-4 3z" />
      <path d="M8 10h8" />
      <path d="M8 13h5" />
    </svg>
  );
}

function UniversalInboxPanel({
  locale,
  copy,
  folderId,
  folderName,
  pendingSource,
  onPendingSourceConsumed,
  initialRecording,
  recordings,
  folders,
  recordingTitle,
  recordingType,
  onRecordingTitleChange,
  onRecordingTypeChange,
  onRecordingUpdate,
  onAssignRecordingToFolder,
  onDeleteRecording,
  onRefreshRecordings,
  onItemsChanged,
  onError,
  onOpenBrain,
}: {
  locale: Locale;
  copy: DashboardCopy;
  folderId?: string | null;
  folderName?: string | null;
  pendingSource?: PendingInboxSource | null;
  onPendingSourceConsumed?: () => void;
  initialRecording?: RecordingDetail | null;
  recordings: Recording[];
  folders: Folder[];
  recordingTitle: string;
  recordingType: RecordingType;
  onRecordingTitleChange: (value: string) => void;
  onRecordingTypeChange: (value: RecordingType) => void;
  onRecordingUpdate: (detail: RecordingDetail) => void;
  onAssignRecordingToFolder: (
    recordingId: string,
    folderId: string | null,
  ) => Promise<void>;
  onDeleteRecording: (
    recordingId: string,
    options?: { permanent?: boolean },
  ) => Promise<void>;
  onRefreshRecordings: () => Promise<void>;
  onItemsChanged: () => void;
  onError: (message: string | null) => void;
  onOpenBrain?: () => void;
}) {
  const [rows, setRows] = useState<InboxRow[]>([]);
  const [selectedRow, setSelectedRow] = useState<InboxRow | null>(null);
  const [selectedRecording, setSelectedRecording] = useState<RecordingDetail | null>(
    null,
  );
  const [sourceKind, setSourceKind] = useState<InboxFilterKind>("all");
  const [statusFilter, setStatusFilter] = useState<InboxFilterStatus>("all");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [creatingBrainMapSourceId, setCreatingBrainMapSourceId] = useState<string | null>(null);
  const inboxRequestId = useRef(0);

  const selectInboxSource = useCallback(
    async (source: PendingInboxSource) => {
      setLoading(true);
      setLoadError(null);
      setShowCreate(false);
      const requestId = inboxRequestId.current + 1;
      inboxRequestId.current = requestId;
      try {
        let cursor: string | null = null;
        const collected: InboxRow[] = [];
        for (let page = 0; page < 5; page += 1) {
          const response = await listInbox({
            limit: 100,
            cursor,
            source_kind: source.sourceKind,
            folder_id: folderId ?? undefined,
          });
          collected.push(...response.rows);
          const row = response.rows.find(
            (candidate) =>
              candidate.source_kind === source.sourceKind &&
              candidate.source_id === source.sourceId,
          );
          if (row) {
            if (requestId !== inboxRequestId.current) return;
            setRows(collected);
            setNextCursor(response.next_cursor);
            setSelectedRow(row);
            setSelectedRecording(null);
            return;
          }
          cursor = response.next_cursor;
          if (!cursor) break;
        }
        if (requestId !== inboxRequestId.current) return [];
        setRows(collected);
        setNextCursor(cursor);
        const message =
          locale === "ru"
            ? "Источник больше не найден в Инбоксе."
            : "Source is no longer available in the Inbox.";
        setLoadError(message);
        onError(message);
      } catch (error: unknown) {
        if (requestId === inboxRequestId.current) {
          const message = formatError(error);
          setLoadError(message);
          onError(message);
        }
      } finally {
        if (requestId === inboxRequestId.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [folderId, locale, onError],
  );

  const loadInbox = useCallback(
    async (mode: "replace" | "append" = "replace") => {
      if (mode === "append") {
        if (!nextCursor || loadingMore) return rows;
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      const requestId = inboxRequestId.current + 1;
      inboxRequestId.current = requestId;
      try {
        const response = await listInbox({
          limit: 50,
          cursor: mode === "append" ? nextCursor : null,
          source_kind: sourceKind === "all" ? undefined : sourceKind,
          status: statusFilter === "all" ? undefined : statusFilter,
          folder_id: folderId ?? undefined,
        });
        if (requestId !== inboxRequestId.current) return rows;
        setLoadError(null);
        setRows((current) =>
          mode === "append" ? [...current, ...response.rows] : response.rows,
        );
        setNextCursor(response.next_cursor);
        return response.rows;
      } catch (error: unknown) {
        if (requestId === inboxRequestId.current) {
          const message = formatError(error);
          setLoadError(message);
          onError(message);
        }
      } finally {
        if (requestId === inboxRequestId.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
      return rows;
    },
    [folderId, loadingMore, nextCursor, onError, rows, sourceKind, statusFilter],
  );

  useEffect(() => {
    setSelectedRow(null);
    setSelectedRecording(null);
    setShowCreate(false);
    setLoadError(null);
    void loadInbox("replace");
  // The first page reloads when filters change. Cursor changes are driven by
  // explicit "Load more" clicks and must not restart the list.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folderId, sourceKind, statusFilter]);

  useEffect(() => {
    if (!initialRecording || initialRecording.deleted_at) return;
    setSelectedRecording(initialRecording);
    setSelectedRow(recordingRowFromDetail(initialRecording));
    setShowCreate(false);
  }, [initialRecording]);

  useEffect(() => {
    if (!pendingSource) return;
    void selectInboxSource(pendingSource).finally(() => onPendingSourceConsumed?.());
  }, [onPendingSourceConsumed, pendingSource, selectInboxSource]);

  useEffect(() => {
    if (selectedRow?.source_kind !== "recording") {
      setSelectedRecording(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const detail = await getRecording(selectedRow.source_id);
        if (cancelled) return;
        setSelectedRecording(detail);
        onRecordingUpdate(detail);
      } catch (error: unknown) {
        if (!cancelled) onError(formatError(error));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onError, onRecordingUpdate, selectedRow]);

  const hasProcessing = useMemo(
    () => rows.some((row) => row.status === "processing"),
    [rows],
  );

  useEffect(() => {
    if (!hasProcessing) return undefined;
    const id = window.setInterval(() => void loadInbox("replace"), 5000);
    return () => window.clearInterval(id);
  }, [hasProcessing, loadInbox]);

  async function handleCreateInboxRecording(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onError(null);
    try {
      const created = await createRecording({
        title: recordingTitle.length > 0 ? recordingTitle : null,
        type: recordingType,
        language: "multi",
        folder_id: folderId ?? undefined,
      });
      onRecordingTitleChange("");
      await onRefreshRecordings();
      await loadInbox("replace");
      const detail = await getRecording(created.id);
      setSelectedRecording(detail);
      setSelectedRow(recordingRowFromDetail(detail));
      onRecordingUpdate(detail);
      setShowCreate(false);
    } catch (error: unknown) {
      onError(formatError(error));
    }
  }

  async function handleRecordingComplete(detail: RecordingDetail) {
    onRecordingUpdate(detail);
    await onRefreshRecordings();
    await loadInbox("replace");
    setSelectedRow(recordingRowFromDetail(detail));
    setSelectedRecording(detail);
    setShowCreate(false);
  }

  async function handleRecordingQueued(recordingId: string) {
    await onRefreshRecordings();
    await loadInbox("replace");
    try {
      const detail = await getRecording(recordingId);
      setSelectedRecording(detail);
      setSelectedRow(recordingRowFromDetail(detail));
      onRecordingUpdate(detail);
      setShowCreate(false);
    } catch (error: unknown) {
      onError(formatError(error));
    }
  }

  async function handleNewChat() {
    onError(null);
    try {
      const chat = await createChat();
      await loadInbox("replace");
      setSelectedRow({
        id: `chat:${chat.id}`,
        source_kind: "chat",
        source_id: chat.id,
        detail: { kind: "chat", id: chat.id },
        title: chat.title,
        source_label: "Wai",
        sublabel: "Agent session",
        activity_at: chat.last_message_at ?? chat.created_at,
        created_at: chat.created_at,
        updated_at: chat.updated_at,
        occurred_at: chat.last_message_at,
        status: "ready",
        source_status: null,
        error: null,
        folder_id: null,
        duration_seconds: null,
        language: null,
        has_summary: null,
        is_starred: false,
        is_pinned: chat.pinned_at !== null,
        is_archived: false,
        is_trashed: false,
      });
      setShowCreate(false);
    } catch (error: unknown) {
      onError(formatError(error));
    }
  }

  async function handleCreateBrainMapFromSelectedSource() {
    if (
      !selectedRow ||
      (selectedRow.source_kind !== "recording" && selectedRow.source_kind !== "item") ||
      creatingBrainMapSourceId
    ) {
      return;
    }
    onError(null);
    setCreatingBrainMapSourceId(selectedRow.id);
    try {
      const title = inboxTitle(selectedRow, locale);
      await createBrainMap({
        prompt: locale === "ru" ? `Сделай карту: ${title}` : `Map this source: ${title}`,
        origin: "inbox",
        source_scope: {
          sources: [
            {
              source_kind: selectedRow.source_kind,
              source_id: selectedRow.source_id,
            },
          ],
        },
      });
      onOpenBrain?.();
    } catch (error: unknown) {
      onError(formatError(error));
    } finally {
      setCreatingBrainMapSourceId(null);
    }
  }

  const sourceFilters: Array<{ key: InboxFilterKind; label: string }> = [
    { key: "all", label: locale === "ru" ? "Все" : "All" },
    { key: "recording", label: locale === "ru" ? "Записи" : "Recordings" },
    { key: "item", label: locale === "ru" ? "Материалы" : "Materials" },
    { key: "chat", label: "Wai" },
  ];
  const statusFilters: Array<{ key: InboxFilterStatus; label: string }> = [
    { key: "all", label: locale === "ru" ? "Любой статус" : "Any status" },
    { key: "ready", label: locale === "ru" ? "Готово" : "Ready" },
    { key: "processing", label: locale === "ru" ? "В работе" : "Processing" },
    {
      key: "needs_attention",
      label: locale === "ru" ? "Нужно внимание" : "Needs attention",
    },
  ];

  return (
    <div className="inbox-grid">
      <section className="inbox-list-panel" aria-label={copy.nav.inbox.label}>
        <header className="panel-header inbox-panel-header">
          <div>
            <h3>{copy.nav.inbox.label}</h3>
            <p>
              {loading
                ? locale === "ru"
                  ? "Загрузка..."
                  : "Loading..."
                : folderName
                  ? locale === "ru"
                    ? `${folderName} / ${rows.length} объектов`
                    : `${folderName} / ${rows.length} items`
                : locale === "ru"
                  ? `${rows.length} объектов`
                  : `${rows.length} items`}
            </p>
          </div>
          <button
            type="button"
            className="ghost-button compact-button"
            onClick={() => {
              setSelectedRow(null);
              setSelectedRecording(null);
              setShowCreate(true);
            }}
          >
            {locale === "ru" ? "+ Добавить" : "+ Add"}
          </button>
        </header>

        <div className="inbox-filters" aria-label={locale === "ru" ? "Фильтры" : "Filters"}>
          <div
            className="inbox-segmented"
            role="group"
            aria-label={locale === "ru" ? "Тип объектов" : "Item type"}
          >
            {sourceFilters.map((filter) => (
              <button
                key={filter.key}
                type="button"
                aria-pressed={sourceKind === filter.key}
                onClick={() => setSourceKind(filter.key)}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <select
            aria-label={locale === "ru" ? "Фильтр статуса" : "Status filter"}
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as InboxFilterStatus)}
          >
            {statusFilters.map((filter) => (
              <option key={filter.key} value={filter.key}>
                {filter.label}
              </option>
            ))}
          </select>
        </div>

        {loadError ? (
          <div className="inbox-error" role="alert">
            <h3>{locale === "ru" ? "Не удалось загрузить Инбокс" : "Could not load Inbox"}</h3>
            <p>{loadError}</p>
            <button
              type="button"
              className="ghost-button compact-button"
              onClick={() => void loadInbox("replace")}
            >
              {locale === "ru" ? "Повторить" : "Retry"}
            </button>
          </div>
        ) : loading ? (
          <div className="inbox-loading">
            <Skeleton height="0.8rem" lines={6} />
          </div>
        ) : rows.length === 0 ? (
          <div className="empty-state">
            <h3>{locale === "ru" ? "Пока пусто" : "Nothing here yet"}</h3>
            <p>
              {locale === "ru"
                ? "Добавьте запись, файл, ссылку, текст или диалог Wai."
                : "Add a recording, file, link, text, or Wai thread."}
            </p>
          </div>
        ) : (
          <ul className="inbox-list">
            {rows.map((row) => {
              const statusLabel = inboxStatusLabel(row, locale);
              const sublabel = inboxSublabel(row, locale);
              return (
                <li key={row.id}>
                  <button
                    type="button"
                    className="inbox-row"
                    aria-current={selectedRow?.id === row.id ? "true" : undefined}
                    data-testid={
                      row.source_kind === "recording"
                        ? `select-recording-${row.source_id}`
                        : undefined
                    }
                    onClick={() => {
                      setShowCreate(false);
                      setSelectedRow(row);
                    }}
                    >
                    <span className="inbox-row__icon" data-kind={row.source_kind}>
                      <InboxKindIcon kind={row.source_kind} />
                    </span>
                    <span className="inbox-row__main">
                      <strong>{inboxTitle(row, locale)}</strong>
                      <small>
                        {sourceLabel(row.source_kind, locale)}
                        {sublabel ? ` / ${sublabel}` : ""} /{" "}
                        {formatDate(row.activity_at, locale)}
                        {row.duration_seconds
                          ? ` / ${formatDuration(row.duration_seconds)}`
                          : ""}
                      </small>
                    </span>
                    {statusLabel ? (
                      <span
                        className={`inbox-status inbox-status--${row.status}`}
                        title={row.error?.message ?? undefined}
                      >
                        {statusLabel}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        {nextCursor ? (
          <div className="inbox-load-more">
            <button
              type="button"
              className="ghost-button compact-button"
              disabled={loadingMore}
              onClick={() => void loadInbox("append")}
            >
              {loadingMore
                ? locale === "ru"
                  ? "Загрузка..."
                  : "Loading..."
                : locale === "ru"
                  ? "Показать ещё"
                  : "Load more"}
            </button>
          </div>
        ) : null}
      </section>

      <section className="inbox-detail-area" aria-label="Inbox detail">
        {!showCreate &&
        selectedRow &&
        (selectedRow.source_kind === "recording" || selectedRow.source_kind === "item") ? (
          <div className="inbox-detail-actions">
            <span>{sourceLabel(selectedRow.source_kind, locale)}</span>
            <button
              type="button"
              className="ghost-button compact-button"
              disabled={creatingBrainMapSourceId === selectedRow.id}
              onClick={() => void handleCreateBrainMapFromSelectedSource()}
            >
              {creatingBrainMapSourceId === selectedRow.id
                ? locale === "ru"
                  ? "Создаю..."
                  : "Creating..."
                : locale === "ru"
                  ? "Создать линзу"
                  : "Create Lens"}
            </button>
          </div>
        ) : null}
        {showCreate || !selectedRow ? (
          <div className="inbox-create">
            <header className="inbox-create__header">
              <div className="inbox-create__glyph" aria-hidden="true" />
              <div>
                <h3>{locale === "ru" ? "Добавить в Инбокс" : "Add to Inbox"}</h3>
                <p>
                  {locale === "ru"
                    ? "Запишите, загрузите файл, вставьте ссылку или дайте Wai задачу."
                    : "Record, upload a file, paste a link, or give Wai a task."}
                </p>
              </div>
              <button
                type="button"
                className="ghost-button compact-button"
                onClick={() => void loadInbox("replace")}
              >
                {locale === "ru" ? "Обновить" : "Refresh"}
              </button>
            </header>

            <div className="inbox-create__grid">
              <section className="inbox-command-card">
                <div>
                  <h4>{locale === "ru" ? "Записать" : "Record"}</h4>
                  <p>
                    {locale === "ru"
                      ? "Быстрая запись из браузера."
                      : "Quick browser recording."}
                  </p>
                </div>
                <LiveRecorder
                  onRecordingComplete={(detail) => void handleRecordingComplete(detail)}
                  onError={onError}
                  locale={locale}
                  folderId={folderId}
                />
              </section>

              <section className="inbox-command-card inbox-command-card--wide">
                <div>
                  <h4>{locale === "ru" ? "Файл, ссылка или текст" : "File, link, or text"}</h4>
                  <p>
                    {locale === "ru"
                      ? "PDF, DOCX, аудио, видео, ссылка или заметка."
                      : "PDF, DOCX, audio, video, link, or note."}
                  </p>
                </div>
                <AddAnythingPanel
                  locale={locale}
                  captureMode="inbox"
                  folderId={folderId}
                  onCreated={(item) => {
                    onItemsChanged();
                    void (async () => {
                      const refreshedRows = await loadInbox("replace");
                      const row = refreshedRows.find(
                        (candidate) =>
                          candidate.source_kind === "item" &&
                          candidate.source_id === item.id,
                      );
                      if (row) {
                        setSelectedRow(row);
                        setShowCreate(false);
                      }
                    })();
                  }}
                  onRecordingQueued={(recordingId) => void handleRecordingQueued(recordingId)}
                  onError={onError}
                />
              </section>

              <section className="inbox-command-card">
                <div>
                  <h4>Wai</h4>
                  <p>
                    {locale === "ru"
                      ? "Искать, помнить, планировать или действовать."
                      : "Search, remember, plan, or act."}
                  </p>
                </div>
                <button
                  type="button"
                  className="wai-primary-button"
                  onClick={() => void handleNewChat()}
                >
                  {locale === "ru" ? "Новая сессия" : "New session"}
                </button>
              </section>
            </div>

            <details className="inbox-manual-recording">
              <summary>{locale === "ru" ? "Создать пустую запись" : "Create empty recording"}</summary>
              <NewRecordingPane
                title={recordingTitle}
                type={recordingType}
                copy={copy}
                locale={locale}
                folderId={folderId}
                onTitleChange={onRecordingTitleChange}
                onTypeChange={onRecordingTypeChange}
                onSubmit={handleCreateInboxRecording}
                onComplete={(detail) => void handleRecordingComplete(detail)}
                onError={onError}
              />
            </details>
          </div>
        ) : selectedRow.source_kind === "recording" ? (
          selectedRecording ? (
            <RecordingDetailPanel
              recording={selectedRecording}
              mode="active"
              folders={folders}
              locale={locale}
              onAssignFolder={(recordingId, folderId) =>
                void onAssignRecordingToFolder(recordingId, folderId)
              }
              onRecordingUpdate={(detail) => {
                setSelectedRecording(detail);
                onRecordingUpdate(detail);
              }}
              onRestore={() => undefined}
              onDelete={(recordingId) => {
                void (async () => {
                  await onDeleteRecording(recordingId, { permanent: false });
                  setSelectedRow(null);
                  setSelectedRecording(null);
                  await loadInbox("replace");
                })();
              }}
            />
          ) : (
            <div className="inbox-loading">
              <Skeleton height="0.8rem" lines={6} />
            </div>
          )
        ) : selectedRow.source_kind === "item" ? (
          <ItemDetail
            itemId={selectedRow.source_id}
            onError={onError}
            onDeleted={() => {
              setSelectedRow(null);
              onItemsChanged();
              void loadInbox("replace");
            }}
            onItemChange={() => void loadInbox("replace")}
          />
        ) : (
          <CompanionPanel
            recordings={recordings}
            locale={locale}
            initialChatId={selectedRow.source_id}
            onChatCreated={() => void loadInbox("replace")}
            viewingFolderId={folderId}
            embedded
          />
        )}
      </section>
    </div>
  );
}

function NewRecordingPane({
  title,
  type,
  copy,
  locale,
  folderId,
  onTitleChange,
  onTypeChange,
  onSubmit,
  onComplete,
  onError,
}: {
  title: string;
  type: RecordingType;
  copy: DashboardCopy;
  locale: "en" | "ru";
  folderId?: string | null;
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
        <LiveRecorder
          onRecordingComplete={onComplete}
          onError={onError}
          locale={locale}
          folderId={folderId}
        />
        <AudioUpload onUploadComplete={onComplete} onError={onError} folderId={folderId} />
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
