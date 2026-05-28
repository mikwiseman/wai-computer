"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  createPersonalizationTerm,
  deletePersonalizationTerm,
  importPersonalizationFile,
  importPersonalizationText,
  listPersonalizationTerms,
  updatePersonalizationTerm,
} from "@/lib/api";
import type { PersonalizationTerm } from "@/lib/types";

interface PersonalizationPanelProps {
  locale: "en" | "ru";
  onError?: (message: string) => void;
}

const COPY = {
  en: {
    title: "Personal terminology",
    subtitle: "Approved terms are used by transcription and summaries.",
    termPlaceholder: "Term",
    replacementPlaceholder: "Preferred spelling",
    add: "Add",
    importPlaceholder: "Paste domain text to extract candidate terms",
    import: "Extract",
    upload: "Upload text",
    active: "Active",
    candidates: "Candidates",
    approve: "Approve",
    reject: "Reject",
    delete: "Delete",
    empty: "No terms yet.",
    loading: "Loading terminology...",
  },
  ru: {
    title: "Персональная терминология",
    subtitle: "Утверждённые термины используются в расшифровке и саммари.",
    termPlaceholder: "Термин",
    replacementPlaceholder: "Предпочтительное написание",
    add: "Добавить",
    importPlaceholder: "Вставьте текст предметной области для извлечения терминов",
    import: "Извлечь",
    upload: "Загрузить текст",
    active: "Активные",
    candidates: "Кандидаты",
    approve: "Утвердить",
    reject: "Отклонить",
    delete: "Удалить",
    empty: "Терминов пока нет.",
    loading: "Загружаем терминологию...",
  },
} as const;

export function PersonalizationPanel({ locale, onError }: PersonalizationPanelProps) {
  const copy = COPY[locale] ?? COPY.en;
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [terms, setTerms] = useState<PersonalizationTerm[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [term, setTerm] = useState("");
  const [replacement, setReplacement] = useState("");
  const [importText, setImportText] = useState("");

  async function loadTerms() {
    setLoading(true);
    try {
      setTerms(await listPersonalizationTerms({ status: "all" }));
    } catch (error) {
      onError?.(error instanceof Error ? error.message : "Failed to load terminology");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTerms();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanTerm = term.trim();
    if (!cleanTerm) return;
    setSaving(true);
    try {
      await createPersonalizationTerm({
        term: cleanTerm,
        replacement: replacement.trim() || null,
      });
      setTerm("");
      setReplacement("");
      await loadTerms();
    } catch (error) {
      onError?.(error instanceof Error ? error.message : "Failed to add term");
    } finally {
      setSaving(false);
    }
  }

  async function handleImportText() {
    const cleanText = importText.trim();
    if (!cleanText) return;
    setSaving(true);
    try {
      await importPersonalizationText(cleanText);
      setImportText("");
      await loadTerms();
    } catch (error) {
      onError?.(error instanceof Error ? error.message : "Failed to import terminology");
    } finally {
      setSaving(false);
    }
  }

  async function handleFile(file: File | null | undefined) {
    if (!file) return;
    setSaving(true);
    try {
      await importPersonalizationFile(file);
      await loadTerms();
    } catch (error) {
      onError?.(error instanceof Error ? error.message : "Failed to import terminology file");
    } finally {
      setSaving(false);
    }
  }

  async function handleUpdate(id: string, status: "active" | "rejected") {
    setSaving(true);
    try {
      await updatePersonalizationTerm(id, { status });
      await loadTerms();
    } catch (error) {
      onError?.(error instanceof Error ? error.message : "Failed to update term");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    setSaving(true);
    try {
      await deletePersonalizationTerm(id);
      await loadTerms();
    } catch (error) {
      onError?.(error instanceof Error ? error.message : "Failed to delete term");
    } finally {
      setSaving(false);
    }
  }

  const activeTerms = terms.filter((item) => item.status === "active");
  const candidates = terms.filter((item) => item.status === "candidate");

  return (
    <section className="settings-form personalization-panel" data-testid="personalization-panel">
      <div className="section-heading-row">
        <div>
          <h3>{copy.title}</h3>
          <p className="settings-note">{copy.subtitle}</p>
        </div>
      </div>

      <form className="dictionary-inline-form" onSubmit={handleAdd}>
        <input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder={copy.termPlaceholder}
          disabled={saving}
        />
        <input
          value={replacement}
          onChange={(event) => setReplacement(event.target.value)}
          placeholder={copy.replacementPlaceholder}
          disabled={saving}
        />
        <button type="submit" disabled={saving}>
          {copy.add}
        </button>
      </form>

      <div className="personalization-import">
        <textarea
          value={importText}
          onChange={(event) => setImportText(event.target.value)}
          placeholder={copy.importPlaceholder}
          rows={4}
          disabled={saving}
        />
        <div className="metadata-row">
          <button type="button" onClick={handleImportText} disabled={saving || !importText.trim()}>
            {copy.import}
          </button>
          <button type="button" onClick={() => fileInputRef.current?.click()} disabled={saving}>
            {copy.upload}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.md,.csv"
            hidden
            onChange={(event) => {
              void handleFile(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </div>
      </div>

      {loading ? <p className="settings-note">{copy.loading}</p> : null}
      {!loading && terms.length === 0 ? <p className="settings-note">{copy.empty}</p> : null}

      {activeTerms.length > 0 ? (
        <TermList
          title={copy.active}
          terms={activeTerms}
          deleteLabel={copy.delete}
          onDelete={handleDelete}
        />
      ) : null}

      {candidates.length > 0 ? (
        <TermList
          title={copy.candidates}
          terms={candidates}
          approveLabel={copy.approve}
          rejectLabel={copy.reject}
          onApprove={(id) => handleUpdate(id, "active")}
          onReject={(id) => handleUpdate(id, "rejected")}
        />
      ) : null}
    </section>
  );
}

function TermList({
  title,
  terms,
  approveLabel,
  rejectLabel,
  deleteLabel,
  onApprove,
  onReject,
  onDelete,
}: {
  title: string;
  terms: PersonalizationTerm[];
  approveLabel?: string;
  rejectLabel?: string;
  deleteLabel?: string;
  onApprove?: (id: string) => void;
  onReject?: (id: string) => void;
  onDelete?: (id: string) => void;
}) {
  return (
    <div className="personalization-terms">
      <h4>{title}</h4>
      <ul className="dictionary-list">
        {terms.map((item) => (
          <li key={item.id}>
            <strong>{item.term}</strong>
            <span>{item.replacement ?? ""}</span>
            <span className="metadata-row">
              {onApprove && approveLabel ? (
                <button type="button" className="ghost-button compact-button" onClick={() => onApprove(item.id)}>
                  {approveLabel}
                </button>
              ) : null}
              {onReject && rejectLabel ? (
                <button type="button" className="ghost-button compact-button" onClick={() => onReject(item.id)}>
                  {rejectLabel}
                </button>
              ) : null}
              {onDelete && deleteLabel ? (
                <button type="button" className="ghost-button compact-button" onClick={() => onDelete(item.id)}>
                  {deleteLabel}
                </button>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
