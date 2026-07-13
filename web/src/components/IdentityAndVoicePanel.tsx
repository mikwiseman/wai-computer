"use client";

import { useCallback, useEffect, useState } from "react";
import {
  disableVoiceSharing,
  enableVoiceSharing,
  getIdentity,
  getVoiceSharing,
  updateIdentity,
  type UserIdentity,
  type VoiceSharingState,
} from "@/lib/api";

type Locale = "en" | "ru";

type Copy = {
  heading: string;
  description: string;
  firstName: string;
  lastName: string;
  firstNamePlaceholder: string;
  lastNamePlaceholder: string;
  save: string;
  saving: string;
  voiceSharing: string;
  voiceSharingOn: string;
  voiceSharingOff: string;
  needsName: string;
  needsVoiceprint: string;
  needsBoth: string;
  visibleAs: (name: string) => string;
  confirmTitle: string;
  confirmBody: (name: string) => string;
  cancel: string;
  share: string;
  errorLoad: string;
  errorSave: string;
  errorToggleOn: string;
  errorToggleOff: string;
};

const COPY: Record<Locale, Copy> = {
  en: {
    heading: "Identity & Voice",
    description:
      "Your name and voiceprint are private until you turn on sharing. We never share audio or transcripts.",
    firstName: "First name",
    lastName: "Last name",
    firstNamePlaceholder: "e.g. Alex",
    lastNamePlaceholder: "e.g. Rivera",
    save: "Save",
    saving: "Saving…",
    voiceSharing: "Share my voice in the WaiComputer directory",
    voiceSharingOn:
      "On. Other WaiComputer users will see your name when their recordings include your voice.",
    voiceSharingOff:
      "Off. Other users will not see your name in their recordings.",
    needsName: "Add a first and last name to enable sharing.",
    needsVoiceprint: "Enroll your voice from the macOS or iOS app to enable sharing.",
    needsBoth:
      "Add a first and last name AND enroll your voice to enable sharing.",
    visibleAs: (name) => `Visible to others as “${name}”.`,
    confirmTitle: "Share your voice in WaiComputer?",
    confirmBody: (name) =>
      `Other WaiComputer users will see “${name}” in their recordings when your voice is detected. We share your name and a voice fingerprint only — never your audio or transcripts. You can turn this off any time.`,
    cancel: "Cancel",
    share: "Share",
    errorLoad: "Could not load identity settings.",
    errorSave: "Could not save your name.",
    errorToggleOn: "Could not turn on voice sharing.",
    errorToggleOff: "Could not turn off voice sharing.",
  },
  ru: {
    heading: "Идентификация и голос",
    description:
      "Имя и голосовой отпечаток остаются приватными, пока вы не включите шеринг. Аудио и расшифровки никогда не передаются.",
    firstName: "Имя",
    lastName: "Фамилия",
    firstNamePlaceholder: "Например, Алекс",
    lastNamePlaceholder: "Например, Ривера",
    save: "Сохранить",
    saving: "Сохраняем…",
    voiceSharing: "Делиться голосом в каталоге WaiComputer",
    voiceSharingOn:
      "Включено. Другие пользователи WaiComputer увидят ваше имя, когда ваш голос появится в их записях.",
    voiceSharingOff:
      "Выключено. Другие пользователи не увидят вашего имени в своих записях.",
    needsName: "Добавьте имя и фамилию, чтобы включить шеринг.",
    needsVoiceprint:
      "Запишите образец голоса в приложении для macOS или iOS, чтобы включить шеринг.",
    needsBoth:
      "Добавьте имя и фамилию и запишите образец голоса, чтобы включить шеринг.",
    visibleAs: (name) => `Видно другим как «${name}».`,
    confirmTitle: "Поделиться голосом в WaiComputer?",
    confirmBody: (name) =>
      `Другие пользователи WaiComputer увидят «${name}» в своих записях, когда ваш голос будет распознан. Мы делимся только именем и голосовым отпечатком — аудио и расшифровки не передаются. Вы можете выключить это в любой момент.`,
    cancel: "Отмена",
    share: "Поделиться",
    errorLoad: "Не удалось загрузить настройки идентификации.",
    errorSave: "Не удалось сохранить имя.",
    errorToggleOn: "Не удалось включить шеринг голоса.",
    errorToggleOff: "Не удалось выключить шеринг голоса.",
  },
};

export interface IdentityAndVoicePanelProps {
  locale?: Locale;
}

export function IdentityAndVoicePanel({ locale = "en" }: IdentityAndVoicePanelProps) {
  const copy = COPY[locale];

  const [, setIdentity] = useState<UserIdentity | null>(null);
  const [sharing, setSharing] = useState<VoiceSharingState | null>(null);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingNames, setSavingNames] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [ident, share] = await Promise.all([getIdentity(), getVoiceSharing()]);
      setIdentity(ident);
      setSharing(share);
      setFirstName(ident.first_name ?? "");
      setLastName(ident.last_name ?? "");
      setError(null);
    } catch {
      setError(copy.errorLoad);
    } finally {
      setLoading(false);
    }
  }, [copy.errorLoad]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const saveNames = useCallback(async () => {
    if (savingNames) return;
    setSavingNames(true);
    try {
      const updated = await updateIdentity({
        first_name: firstName,
        last_name: lastName,
      });
      setIdentity(updated);
      setFirstName(updated.first_name ?? "");
      setLastName(updated.last_name ?? "");
      setSharing(await getVoiceSharing());
      setError(null);
    } catch {
      setError(copy.errorSave);
    } finally {
      setSavingNames(false);
    }
  }, [firstName, lastName, savingNames, copy.errorSave]);

  const flipSharing = useCallback(
    async (enabled: boolean) => {
      if (toggling) return;
      setToggling(true);
      try {
        const next = enabled
          ? await enableVoiceSharing()
          : await disableVoiceSharing();
        setSharing(next);
        setError(null);
      } catch {
        setError(enabled ? copy.errorToggleOn : copy.errorToggleOff);
      } finally {
        setToggling(false);
      }
    },
    [toggling, copy.errorToggleOn, copy.errorToggleOff],
  );

  const sharedNamePreview =
    [firstName, lastName]
      .map((part) => part.trim())
      .filter(Boolean)
      .join(" ") || (locale === "ru" ? "ваше имя" : "your name");

  const isOn = sharing?.enabled === true;
  const canToggle = sharing?.can_enable === true;

  const subtitle = (): string => {
    if (!sharing) return "";
    if (sharing.enabled) {
      return sharing.shared_name
        ? copy.visibleAs(sharing.shared_name)
        : copy.voiceSharingOn;
    }
    if (sharing.can_enable) return copy.voiceSharingOff;
    if (!sharing.has_voiceprint && (!sharing.has_first_name || !sharing.has_last_name)) {
      return copy.needsBoth;
    }
    if (!sharing.has_voiceprint) return copy.needsVoiceprint;
    return copy.needsName;
  };

  return (
    <section className="settings-form" data-testid="identity-voice-panel">
      <h3>{copy.heading}</h3>
      <p className="settings-note">{copy.description}</p>

      {loading ? (
        <p className="settings-note">…</p>
      ) : (
        <>
          <label className="settings-text-field">
            <span>{copy.firstName}</span>
            <input
              type="text"
              value={firstName}
              placeholder={copy.firstNamePlaceholder}
              maxLength={120}
              disabled={savingNames}
              onChange={(event) => setFirstName(event.target.value)}
              onBlur={() => void saveNames()}
              data-testid="identity-first-name"
            />
          </label>

          <label className="settings-text-field">
            <span>{copy.lastName}</span>
            <input
              type="text"
              value={lastName}
              placeholder={copy.lastNamePlaceholder}
              maxLength={120}
              disabled={savingNames}
              onChange={(event) => setLastName(event.target.value)}
              onBlur={() => void saveNames()}
              data-testid="identity-last-name"
            />
          </label>

          {savingNames ? (
            <p className="settings-note">{copy.saving}</p>
          ) : null}

          <label className="settings-checkbox-field">
            <input
              type="checkbox"
              checked={isOn}
              disabled={(!canToggle && !isOn) || toggling}
              onChange={(event) => {
                if (event.target.checked) {
                  setConfirmOpen(true);
                } else {
                  void flipSharing(false);
                }
              }}
              data-testid="voice-sharing-toggle"
            />
            <span>{copy.voiceSharing}</span>
          </label>
          <p className="settings-note">{subtitle()}</p>

          {error ? (
            <p className="settings-note" style={{ color: "var(--danger)" }}>
              {error}
            </p>
          ) : null}

          {confirmOpen ? (
            <div
              role="dialog"
              aria-modal="true"
              aria-label={copy.confirmTitle}
              data-testid="voice-sharing-confirm"
              style={{
                marginTop: "1rem",
                padding: "0.75rem 1rem",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
              }}
            >
              <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>
                {copy.confirmTitle}
              </p>
              <p style={{ margin: "0 0 0.75rem", fontSize: "0.875rem" }}>
                {copy.confirmBody(sharedNamePreview)}
              </p>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => {
                    setConfirmOpen(false);
                    void flipSharing(true);
                  }}
                  data-testid="voice-sharing-confirm-share"
                >
                  {copy.share}
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => setConfirmOpen(false)}
                  data-testid="voice-sharing-confirm-cancel"
                >
                  {copy.cancel}
                </button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
