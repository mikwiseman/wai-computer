"use client";

import { useState } from "react";

import { deleteAccount } from "@/lib/api";

type Locale = "en" | "ru";

interface Copy {
  heading: string;
  body: string;
  button: string;
  confirmTitle: string;
  confirmBody: string;
  confirm: string;
  cancel: string;
  deleting: string;
  failed: string;
}

const COPY: Record<Locale, Copy> = {
  en: {
    heading: "Danger zone",
    body: "Permanently delete your account and all recordings, folders, and summaries.",
    button: "Delete account",
    confirmTitle: "Delete account permanently?",
    confirmBody:
      "This permanently deletes your account, recordings, folders, and summaries. This cannot be undone.",
    confirm: "Delete account",
    cancel: "Cancel",
    deleting: "Deleting…",
    failed: "Could not delete the account. Please try again.",
  },
  ru: {
    heading: "Опасная зона",
    body: "Безвозвратно удалить аккаунт и все записи, папки и саммари.",
    button: "Удалить аккаунт",
    confirmTitle: "Удалить аккаунт навсегда?",
    confirmBody:
      "Это безвозвратно удалит ваш аккаунт, записи, папки и саммари. Отменить будет нельзя.",
    confirm: "Удалить аккаунт",
    cancel: "Отмена",
    deleting: "Удаляем…",
    failed: "Не удалось удалить аккаунт. Попробуйте ещё раз.",
  },
};

export interface DeleteAccountSectionProps {
  /** Called after the account is deleted (caller redirects to sign-in). */
  onDeleted: () => void;
  locale?: Locale;
}

export function DeleteAccountSection({ onDeleted, locale = "en" }: DeleteAccountSectionProps) {
  const copy = COPY[locale];
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    try {
      await deleteAccount();
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : copy.failed);
      setDeleting(false);
    }
  }

  return (
    <div className="settings-form" data-testid="delete-account-section">
      <h3>{copy.heading}</h3>
      <p className="settings-note">{copy.body}</p>
      {error ? (
        <p className="inline-alert" role="alert">
          {error}
        </p>
      ) : null}
      <button
        type="button"
        className="ghost-button compact-button danger-button"
        data-testid="delete-account"
        onClick={() => setOpen(true)}
      >
        {copy.button}
      </button>

      {open ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          data-testid="confirm-delete-account"
          onClick={(event) => {
            if (event.target === event.currentTarget && !deleting) setOpen(false);
          }}
        >
          <div className="modal-card">
            <h3>{copy.confirmTitle}</h3>
            <p>{copy.confirmBody}</p>
            <div className="modal-actions">
              <button
                type="button"
                className="ghost-button"
                disabled={deleting}
                onClick={() => setOpen(false)}
              >
                {copy.cancel}
              </button>
              <button
                type="button"
                className="ghost-button danger-button"
                data-testid="confirm-delete-account-action"
                disabled={deleting}
                onClick={() => void handleDelete()}
              >
                {deleting ? copy.deleting : copy.confirm}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
