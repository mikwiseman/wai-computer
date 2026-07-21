"use client";

import { useState } from "react";

import type {
  SummaryStyle,
  TranscriptionModelOption,
  TranscriptionOptions,
  UserSettings,
} from "@/lib/types";

type Locale = "en" | "ru";

// Mirrors macOS `DictationLanguageStore.all` (15 languages, same order) so the
// web default-language picker matches the Mac app 1:1.
const LANGUAGES: { code: string; en: string; native: string }[] = [
  { code: "en", en: "English", native: "English" },
  { code: "ru", en: "Russian", native: "Русский" },
  { code: "es", en: "Spanish", native: "Español" },
  { code: "de", en: "German", native: "Deutsch" },
  { code: "fr", en: "French", native: "Français" },
  { code: "it", en: "Italian", native: "Italiano" },
  { code: "pt", en: "Portuguese", native: "Português" },
  { code: "ja", en: "Japanese", native: "日本語" },
  { code: "ko", en: "Korean", native: "한국어" },
  { code: "hi", en: "Hindi", native: "हिन्दी" },
  { code: "ar", en: "Arabic", native: "العربية" },
  { code: "uk", en: "Ukrainian", native: "Українська" },
  { code: "pl", en: "Polish", native: "Polski" },
  { code: "nl", en: "Dutch", native: "Nederlands" },
  { code: "tr", en: "Turkish", native: "Türkçe" },
];

const SUMMARY_STYLES: SummaryStyle[] = ["brief", "medium", "detailed"];

interface Copy {
  heading: string;
  defaultLanguage: string;
  autoDetect: string;
  summaryLanguage: string;
  matchRecording: string;
  summaryStyle: string;
  styles: Record<SummaryStyle, string>;
  summaryInstructions: string;
  instructionsPlaceholder: string;
  automaticTitles: string;
  automaticTitlesHelp: string;
  models: string;
  modelDictation: string;
  modelRecording: string;
  modelFiles: string;
  modelsNote: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    heading: "Transcription & summaries",
    defaultLanguage: "Default language",
    autoDetect: "Auto-detect (multilingual)",
    summaryLanguage: "Summary language",
    matchRecording: "Match recording",
    summaryStyle: "Summary detail",
    styles: { brief: "Brief", medium: "Medium", detailed: "Detailed" },
    summaryInstructions: "Custom instructions",
    instructionsPlaceholder: "e.g. Always call out action items and decisions.",
    automaticTitles: "Name recordings automatically",
    automaticTitlesHelp: "Only recordings started in the app. File names and manual edits never change.",
    models: "Transcription models",
    modelDictation: "Dictation",
    modelRecording: "Live recording",
    modelFiles: "File uploads",
    modelsNote: "Models are managed by WaiComputer and tuned automatically.",
  },
  ru: {
    heading: "Транскрипция и саммари",
    defaultLanguage: "Язык по умолчанию",
    autoDetect: "Автоопределение (мультиязычно)",
    summaryLanguage: "Язык саммари",
    matchRecording: "Как в записи",
    summaryStyle: "Детализация саммари",
    styles: { brief: "Кратко", medium: "Средне", detailed: "Подробно" },
    summaryInstructions: "Свои инструкции",
    instructionsPlaceholder: "напр. Всегда выделяй задачи и решения.",
    automaticTitles: "Автоматически называть записи",
    automaticTitlesHelp: "Только для записей, начатых в приложении. Имена файлов и ручные правки не меняются.",
    models: "Модели транскрипции",
    modelDictation: "Диктовка",
    modelRecording: "Живая запись",
    modelFiles: "Загрузка файлов",
    modelsNote: "Моделями управляет WaiComputer и настраивает их автоматически.",
  },
};

function languageLabel(code: string, locale: Locale): string {
  const entry = LANGUAGES.find((l) => l.code === code);
  if (!entry) return code.toUpperCase();
  if (locale === "ru" || entry.en === entry.native) return entry.native;
  return `${entry.en} (${entry.native})`;
}

// All curated language codes, plus the current value prepended if it's a
// real code we don't enumerate — so the select always reflects the stored
// value rather than silently falling back. `sentinel` is the picker's
// auto/match option value (default_language uses "multi", summary_language
// uses "auto" per the backend) and is excluded so it isn't double-listed.
function languageCodes(current: string, sentinel: string): string[] {
  const codes = LANGUAGES.map((l) => l.code);
  if (current && current !== sentinel && !codes.includes(current)) {
    return [current, ...codes];
  }
  return codes;
}

function modelLabel(
  options: TranscriptionModelOption[] | undefined,
  provider: string,
  model: string,
): string {
  const match = options?.find((o) => o.provider === provider && o.model === model);
  return match?.label ?? `${provider} · ${model}`;
}

export interface TranscriptionSettingsPanelProps {
  settings: UserSettings;
  transcriptionOptions: TranscriptionOptions | null;
  onUpdate: (patch: Partial<UserSettings>) => void;
  busy?: boolean;
  locale?: Locale;
}

export function TranscriptionSettingsPanel({
  settings,
  transcriptionOptions,
  onUpdate,
  busy = false,
  locale = "en",
}: TranscriptionSettingsPanelProps) {
  const copy = COPY[locale];
  const [instructions, setInstructions] = useState(settings.summary_instructions ?? "");
  const [syncedInstructions, setSyncedInstructions] = useState(
    settings.summary_instructions ?? "",
  );

  // Reset the local draft when the stored value changes externally — React's
  // recommended "adjust state during render" pattern (no effect, no cascade).
  if ((settings.summary_instructions ?? "") !== syncedInstructions) {
    setSyncedInstructions(settings.summary_instructions ?? "");
    setInstructions(settings.summary_instructions ?? "");
  }

  function commitInstructions() {
    const next = instructions.trim() ? instructions.trim() : null;
    if ((settings.summary_instructions ?? "") !== (next ?? "")) {
      onUpdate({ summary_instructions: next });
    }
  }

  return (
    <div className="settings-form" data-testid="transcription-settings">
      <h3>{copy.heading}</h3>

      <label className="settings-switch-row">
        <input
          type="checkbox"
          checked={settings.automatic_recording_titles !== false}
          disabled={busy}
          onChange={(event) => onUpdate({ automatic_recording_titles: event.target.checked })}
        />
        <span>
          <strong>{copy.automaticTitles}</strong>
          <small>{copy.automaticTitlesHelp}</small>
        </span>
      </label>

      <label className="settings-field">
        <span>{copy.defaultLanguage}</span>
        <select
          value={settings.default_language}
          disabled={busy}
          onChange={(event) => onUpdate({ default_language: event.target.value })}
        >
          <option value="multi">{copy.autoDetect}</option>
          {languageCodes(settings.default_language, "multi").map((code) => (
            <option key={code} value={code}>
              {languageLabel(code, locale)}
            </option>
          ))}
        </select>
      </label>

      <label className="settings-field">
        <span>{copy.summaryLanguage}</span>
        <select
          value={settings.summary_language}
          disabled={busy}
          onChange={(event) => onUpdate({ summary_language: event.target.value })}
        >
          <option value="auto">{copy.matchRecording}</option>
          {languageCodes(settings.summary_language, "auto").map((code) => (
            <option key={code} value={code}>
              {languageLabel(code, locale)}
            </option>
          ))}
        </select>
      </label>

      <label className="settings-field">
        <span>{copy.summaryStyle}</span>
        <select
          value={settings.summary_style}
          disabled={busy}
          onChange={(event) => onUpdate({ summary_style: event.target.value as SummaryStyle })}
        >
          {SUMMARY_STYLES.map((style) => (
            <option key={style} value={style}>
              {copy.styles[style]}
            </option>
          ))}
        </select>
      </label>

      <label className="settings-field">
        <span>{copy.summaryInstructions}</span>
        <textarea
          value={instructions}
          disabled={busy}
          placeholder={copy.instructionsPlaceholder}
          rows={3}
          onChange={(event) => setInstructions(event.target.value)}
          onBlur={commitInstructions}
        />
      </label>

      <div className="settings-field">
        <span>{copy.models}</span>
        <dl className="settings-model-list" data-testid="transcription-models">
          <div>
            <dt>{copy.modelDictation}</dt>
            <dd>
              {modelLabel(
                transcriptionOptions?.dictation_live_stt,
                settings.dictation_live_stt_provider,
                settings.dictation_live_stt_model,
              )}
            </dd>
          </div>
          <div>
            <dt>{copy.modelRecording}</dt>
            <dd>
              {modelLabel(
                transcriptionOptions?.recording_live_stt,
                settings.recording_live_stt_provider,
                settings.recording_live_stt_model,
              )}
            </dd>
          </div>
          <div>
            <dt>{copy.modelFiles}</dt>
            <dd>
              {modelLabel(
                transcriptionOptions?.file_stt,
                settings.file_stt_provider,
                settings.file_stt_model,
              )}
            </dd>
          </div>
        </dl>
        <p className="settings-note">{copy.modelsNote}</p>
      </div>
    </div>
  );
}
