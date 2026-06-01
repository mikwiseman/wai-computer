"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getBrainGraph } from "@/lib/api";
import type { BrainGraph, BrainGraphNode } from "@/lib/types";
import { BrainGraphView } from "@/components/BrainGraphView";

interface BrainPanelProps {
  locale?: string;
  onError?: (message: string) => void;
}

type BrainTab = "index" | "graph";

const ENTITY_KINDS: Array<{ key: string; en: string; ru: string }> = [
  { key: "person", en: "People", ru: "Люди" },
  { key: "topic", en: "Topics", ru: "Темы" },
  { key: "project", en: "Projects", ru: "Проекты" },
];

/**
 * The Brain section: a knowledge graph of the people / topics / projects across
 * everything captured. Two views — a calm scannable Index (default) and the
 * Obsidian-style force Graph — both built from `GET /api/brain/graph`. `focus`
 * refetches the backend ego graph around a clicked entity. Honest empty + error
 * states (no silent fallback).
 */
export function BrainPanel({ locale = "en", onError }: BrainPanelProps) {
  const [graph, setGraph] = useState<BrainGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<BrainTab>("index");
  const [focus, setFocus] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(true);

  const t = useCallback(
    (en: string, ru: string) => (locale === "ru" ? ru : en),
    [locale],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setGraph(
        await getBrainGraph({
          focus: focus ?? undefined,
          include_sources: true,
          limit: 300,
        }),
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't load your brain.";
      setError(message);
      onError?.(message);
    } finally {
      setLoading(false);
    }
  }, [focus, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const byKind = useMemo(() => {
    const map: Record<string, BrainGraphNode[]> = {};
    for (const node of graph?.nodes ?? []) {
      if (node.kind === "item" || node.kind === "recording") continue;
      (map[node.kind] ??= []).push(node);
    }
    for (const list of Object.values(map)) list.sort((a, b) => b.degree - a.degree);
    return map;
  }, [graph]);

  const stats = graph?.stats ?? {};
  const isEmpty = (graph?.nodes.length ?? 0) === 0;

  const indexBody = (
    <>
      <div className="brain-panel__stats">
        <span>
          {stats.people ?? 0} {t("people", "людей")}
        </span>
        <span>
          {stats.topics ?? 0} {t("topics", "тем")}
        </span>
        <span>
          {(stats.items ?? 0) + (stats.recordings ?? 0)} {t("sources", "источников")}
        </span>
      </div>
      {ENTITY_KINDS.map(({ key, en, ru }) => {
        const list = byKind[key] ?? [];
        if (list.length === 0) return null;
        return (
          <section key={key} className="brain-panel__group">
            <h3 className="brain-panel__group-title">{t(en, ru)}</h3>
            <ul className="brain-panel__chips">
              {list.map((node) => (
                <li
                  key={node.id}
                  className="brain-panel__chip"
                  title={`${node.degree} ${t("mentions", "упоминаний")}`}
                >
                  <span>{node.label}</span>
                  <em>{node.degree}</em>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </>
  );

  return (
    <div className="brain-panel">
      <header className="brain-panel__header">
        <h2 className="brain-panel__title">{t("Brain", "Мозг")}</h2>
        <p className="brain-panel__subtitle">
          {t(
            "People, topics and projects across everything you've captured.",
            "Люди, темы и проекты по всему, что вы сохранили.",
          )}
        </p>
      </header>

      <div className="brain-panel__tabs" role="tablist" aria-label={t("Brain views", "Виды мозга")}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "index"}
          className={`brain-panel__tab ${tab === "index" ? "brain-panel__tab--active" : ""}`}
          onClick={() => setTab("index")}
        >
          {t("Index", "Индекс")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "graph"}
          className={`brain-panel__tab ${tab === "graph" ? "brain-panel__tab--active" : ""}`}
          onClick={() => setTab("graph")}
        >
          {t("Graph", "Граф")}
        </button>
      </div>

      {loading ? (
        <p className="brain-panel__status">{t("Loading…", "Загрузка…")}</p>
      ) : error ? (
        <div className="brain-panel__error">
          <p>{t("Couldn't load your brain.", "Не удалось загрузить мозг.")}</p>
          <p className="brain-panel__error-detail">{error}</p>
          <button type="button" className="wai-primary-button" onClick={() => void load()}>
            {t("Retry", "Повторить")}
          </button>
        </div>
      ) : isEmpty ? (
        <p className="brain-panel__empty">
          {t(
            "Your brain is empty — add materials or record, and the people & topics they mention will appear here.",
            "Ваш мозг пуст — добавьте материалы или записи, и здесь появятся люди и темы из них.",
          )}
        </p>
      ) : tab === "index" ? (
        indexBody
      ) : (
        <BrainGraphView
          graph={graph as BrainGraph}
          showSources={showSources}
          onToggleSources={setShowSources}
          onFocusEntity={(id) => setFocus(id)}
          focused={focus !== null}
          onResetFocus={() => setFocus(null)}
          locale={locale}
        />
      )}
    </div>
  );
}
