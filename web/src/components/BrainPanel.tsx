"use client";

import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  acceptBrainReviewPack,
  addBrainSpaceMember,
  askBrain,
  createBrainMap,
  exportBrainSpace,
  getBrainMirror,
  getBrainSpaceHome,
  listBrainMaps,
  listBrainReviewPacks,
  listBrainSpaces,
  listEntities,
  refreshBrainMap,
  rejectBrainReviewPack,
  updateBrainMap,
} from "@/lib/api";
import type {
  BrainAnswer,
  BrainAnswerCitation,
  BrainMap,
  BrainMapBriefing,
  BrainMapBriefingEntity,
  BrainMapBriefingSource,
  BrainMapDiff,
  BrainMapNode,
  BrainMapPosition,
  BrainMapProjection,
  BrainReviewPack,
  BrainSpace,
  BrainSpaceHome,
  BrainSpaceSourceSummary,
  Entity,
  EntityType,
} from "@/lib/types";
import { EntityWikiView } from "@/components/EntityWikiView";

interface BrainPanelProps {
  locale?: string;
  initialMapId?: string | null;
  onError?: (message: string) => void;
  onOpenSource?: (sourceKind: "recording" | "item", sourceId: string) => void;
  onOpenInbox?: () => void;
  onOpenWai?: (brain: { spaceId: string; spaceName: string }) => void | Promise<void>;
}

type PageFilter = "all" | "person" | "project" | "topic";
type Translator = (en: string, ru: string) => string;

const FILTERS: { key: PageFilter; en: string; ru: string }[] = [
  { key: "all", en: "All", ru: "Все" },
  { key: "person", en: "People", ru: "Люди" },
  { key: "project", en: "Projects", ru: "Проекты" },
  { key: "topic", en: "Topics", ru: "Темы" },
];

const DIAGRAM_TEMPLATES = [
  {
    key: "projects",
    titleEn: "Projects",
    titleRu: "Проекты",
    subtitleEn: "owners, risks, next steps",
    subtitleRu: "ответственные, риски, шаги",
    promptEn: "Map my active projects with owners, risks, decisions, and next steps",
    promptRu: "Сделай карту активных проектов: ответственные, риски, решения и следующие шаги",
  },
  {
    key: "decisions",
    titleEn: "Decisions",
    titleRu: "Решения",
    subtitleEn: "options, tradeoffs, blockers",
    subtitleRu: "варианты, компромиссы, блокеры",
    promptEn: "Map recent decisions with options, tradeoffs, blockers, and open questions",
    promptRu: "Сделай карту последних решений: варианты, компромиссы, блокеры и открытые вопросы",
  },
  {
    key: "relationships",
    titleEn: "Relationships",
    titleRu: "Связи",
    subtitleEn: "people, projects, sources",
    subtitleRu: "люди, проекты, источники",
    promptEn: "Map people, projects, and relationships that matter right now",
    promptRu: "Сделай карту людей, проектов и связей, которые сейчас важны",
  },
  {
    key: "timeline",
    titleEn: "Timeline",
    titleRu: "Хронология",
    subtitleEn: "what changed and when",
    subtitleRu: "что изменилось и когда",
    promptEn: "Create a timeline of the important changes, commitments, and deadlines",
    promptRu: "Сделай хронологию важных изменений, обещаний и дедлайнов",
  },
];

type MapNodeData = {
  node: BrainMapNode;
  citationCount: number;
  onOpen?: () => void;
};

type BrainMapCanvasFocus = {
  projection: BrainMapProjection;
  hiddenNodeCount: number;
};

type BrainMapCanvasColumn = "sources" | "center" | "signals" | "knowledge" | "questions";

const CANVAS_FOCUS_LIMIT = 10;
const CANVAS_COLUMN_ORDER: BrainMapCanvasColumn[] = ["center", "signals", "sources", "knowledge", "questions"];
const CANVAS_COLUMN_LIMITS: Record<BrainMapCanvasColumn, number> = {
  sources: 3,
  center: 1,
  signals: 4,
  knowledge: 2,
  questions: 2,
};
const CANVAS_COLUMN_X: Record<BrainMapCanvasColumn, number> = {
  sources: -420,
  center: 0,
  signals: 420,
  knowledge: 420,
  questions: 210,
};
const SCENARIO_SIGNAL_NODE_KINDS = new Set([
  "decision",
  "tradeoff",
  "risk",
  "next_step",
  "open_question",
  "timeline_event",
  "deadline",
  "commitment",
]);

function entityGlyph(type: EntityType | string): string {
  if (type === "person") return "P";
  if (type === "project") return "F";
  if (type === "organization") return "O";
  return "#";
}

function mapTypeLabel(type: string, t: Translator): string {
  if (type === "live_mirror") return t("Live Mirror", "Живое зеркало");
  if (type === "project_state") return t("Project state", "Состояние проекта");
  if (type === "decision") return t("Decision", "Решение");
  if (type === "relationship") return t("Relationships", "Связи");
  if (type === "timeline") return t("Timeline", "Хронология");
  if (type === "comparison") return t("Comparison", "Сравнение");
  if (type === "open_questions") return t("Open questions", "Открытые вопросы");
  return type.replaceAll("_", " ");
}

function sourceKindLabel(kind: string, t: Translator): string {
  if (kind === "recording") return t("recording", "запись");
  if (kind === "item") return t("material", "материал");
  return kind;
}

function entityTypeLabel(type: string, t: Translator): string {
  if (type === "person") return t("person", "человек");
  if (type === "project") return t("project", "проект");
  if (type === "organization") return t("organization", "организация");
  if (type === "topic") return t("topic", "тема");
  return type;
}

function formatMs(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function brainCitationLabel(citation: BrainAnswerCitation, t: Translator): string {
  const title = citation.title || sourceKindLabel(citation.source_kind, t);
  return citation.start_ms !== null ? `${title} · ${formatMs(citation.start_ms)}` : title;
}

function diffText(diff: BrainMapDiff | null, t: Translator): string {
  if (!diff || !diff.changed) return t("Current", "Актуально");
  const parts = [
    diff.sources_added ? t(`+${diff.sources_added} sources`, `+${diff.sources_added} источн.`) : "",
    diff.nodes_added ? t(`+${diff.nodes_added} cards`, `+${diff.nodes_added} карточек`) : "",
    diff.edges_added ? t(`+${diff.edges_added} links`, `+${diff.edges_added} связей`) : "",
  ].filter(Boolean);
  return parts.join(" · ") || t("Updated", "Обновлено");
}

function briefingFocusText(briefing: BrainMapBriefing, t: Translator): string {
  if (briefing.mode === "empty") return t("No matching evidence yet.", "Подходящих источников пока нет.");
  if (briefing.mode === "focused") {
    return t(
      `Showing ${briefing.coverage.visible_sources} of ${briefing.coverage.total_sources} sources and ${briefing.coverage.visible_entities} of ${briefing.coverage.total_entities} nodes.`,
      `Показано ${briefing.coverage.visible_sources} из ${briefing.coverage.total_sources} источн. и ${briefing.coverage.visible_entities} из ${briefing.coverage.total_entities} узлов.`,
    );
  }
  return t(
    `Showing all ${briefing.coverage.total_sources} sources and ${briefing.coverage.total_entities} nodes.`,
    `Показаны все источники: ${briefing.coverage.total_sources}, узлы: ${briefing.coverage.total_entities}.`,
  );
}

function briefingFreshnessText(projection: BrainMapProjection, t: Translator): string {
  if (projection.freshness.stale && projection.freshness.weeks_since !== null) {
    return t(
      `Newest evidence is ${projection.freshness.weeks_since} week(s) old.`,
      `Самому новому источнику ${projection.freshness.weeks_since} нед.`,
    );
  }
  if (!projection.freshness.newest_source_at) return t("No dated source yet.", "Пока нет источника с датой.");
  return t("Evidence is current.", "Источники актуальны.");
}

function answerFreshnessText(answer: BrainAnswer, t: Translator): string {
  if (answer.freshness.stale && answer.freshness.weeks_since !== null) {
    return t(
      `Newest cited source is ${answer.freshness.weeks_since} week(s) old.`,
      `Самому новому источнику в ответе ${answer.freshness.weeks_since} нед.`,
    );
  }
  if (!answer.freshness.newest_source_at) return t("No dated source in this answer.", "В ответе нет источника с датой.");
  return t("Answer is tied to current sources.", "Ответ привязан к актуальным источникам.");
}

function hiddenFocusCount(briefing: BrainMapBriefing): number {
  return Math.max(0, briefing.coverage.total_sources - briefing.coverage.visible_sources)
    + Math.max(0, briefing.coverage.total_entities - briefing.coverage.visible_entities);
}

function localizedSuggestedQuestions(
  mapType: string,
  fallback: string[],
  t: Translator,
): string[] {
  if (mapType === "decision") {
    return [
      t("What changed since this decision?", "Что изменилось после этого решения?"),
      t("Which sources disagree or add risk?", "Какие источники спорят или добавляют риск?"),
      t("What is still open?", "Что ещё открыто?"),
    ];
  }
  if (mapType === "timeline") {
    return [
      t("What changed most recently?", "Что изменилось недавно?"),
      t("Which deadlines or commitments are implied?", "Какие дедлайны или обещания следуют из этого?"),
      t("What has not been updated in a while?", "Что давно не обновлялось?"),
    ];
  }
  if (mapType === "relationship") {
    return [
      t("Who is connected to this work?", "Кто связан с этой работой?"),
      t("Which relationship has the strongest evidence?", "Какая связь подтверждена сильнее всего?"),
      t("Where are the missing links?", "Где не хватает связей?"),
    ];
  }
  if (mapType === "comparison") {
    return [
      t("What are the strongest differences?", "Какие различия самые сильные?"),
      t("Which option has the best evidence?", "У какого варианта лучшие доказательства?"),
      t("What evidence is missing before choosing?", "Каких источников не хватает для выбора?"),
    ];
  }
  if (mapType === "open_questions") {
    return [
      t("Which question blocks progress?", "Какой вопрос блокирует прогресс?"),
      t("Who or what source can answer it?", "Кто или какой источник может ответить?"),
      t("What should Wai watch for next?", "За чем Wai следить дальше?"),
    ];
  }
  const localized = [
    t("What are the active risks?", "Какие сейчас активные риски?"),
    t("What changed since the last update?", "Что изменилось с последнего обновления?"),
    t("What should happen next?", "Что должно произойти дальше?"),
  ];
  return mapType === "project_state" || fallback.length === 0 ? localized : fallback;
}

function BrainAskPanel({
  question,
  answer,
  error,
  asking,
  creatingLens,
  onQuestionChange,
  onAsk,
  onMap,
  onOpenCitation,
  t,
}: {
  question: string;
  answer: BrainAnswer | null;
  error: string | null;
  asking: boolean;
  creatingLens: boolean;
  onQuestionChange: (value: string) => void;
  onAsk: () => void;
  onMap: () => void;
  onOpenCitation: (citation: BrainAnswerCitation) => void;
  t: Translator;
}) {
  const canSubmit = Boolean(question.trim()) && !asking;
  return (
    <section className="brain-ask-panel" aria-label={t("Ask Brain", "Спросить мозг")}>
      <form
        className="brain-ask-panel__form"
        onSubmit={(event) => {
          event.preventDefault();
          onAsk();
        }}
      >
        <label>
          <span>{t("Ask Brain", "Спросить мозг")}</span>
          <textarea
            value={question}
            aria-label={t("Question for Brain", "Вопрос к мозгу")}
            placeholder={t("What changed? What is blocked? Who owns the next step?", "Что изменилось? Что блокирует? Кто отвечает за следующий шаг?")}
            rows={2}
            onChange={(event) => onQuestionChange(event.target.value)}
          />
        </label>
        <div className="brain-ask-panel__actions">
          <button type="submit" className="wai-primary-button" disabled={!canSubmit}>
            {asking ? t("Asking…", "Спрашиваю…") : t("Ask Brain", "Спросить")}
          </button>
          <button
            type="button"
            className="wai-secondary-button"
            disabled={!question.trim() || creatingLens}
            onClick={onMap}
          >
            {creatingLens ? t("Mapping…", "Строю…") : t("Map it", "Карта")}
          </button>
        </div>
      </form>

      {error ? <p className="brain-panel__error-text">{error}</p> : null}

      {answer ? (
        <article className="brain-ask-answer" aria-label={t("Brain answer", "Ответ мозга")}>
          {answer.answer ? <p className="brain-ask-answer__text">{answer.answer}</p> : null}
          <small>{answerFreshnessText(answer, t)}</small>
          {answer.citations.length > 0 ? (
            <div className="brain-ask-answer__citations" aria-label={t("Citations", "Источники")}>
              {answer.citations.map((citation) => (
                <button
                  key={citation.id}
                  type="button"
                  onClick={() => onOpenCitation(citation)}
                >
                  {brainCitationLabel(citation, t)}
                </button>
              ))}
            </div>
          ) : null}
          {answer.gaps.length > 0 ? (
            <ul className="brain-ask-answer__gaps" aria-label={t("Gaps", "Пробелы")}>
              {answer.gaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          ) : null}
        </article>
      ) : null}
    </section>
  );
}

function BriefingMetric({
  value,
  label,
}: {
  value: string;
  label: string;
}) {
  return (
    <span className="brain-map-briefing__metric">
      <strong>{value}</strong>
      <em>{label}</em>
    </span>
  );
}

function BriefingSourceRow({
  source,
  onOpen,
  t,
}: {
  source: BrainMapBriefingSource;
  onOpen: (source: BrainMapBriefingSource) => void;
  t: Translator;
}) {
  const kindLabel = sourceKindLabel(source.source_kind, t);
  return (
    <button
      type="button"
      className="brain-map-briefing__row"
      aria-label={`${source.title} ${kindLabel}`}
      onClick={() => onOpen(source)}
    >
      <strong>{source.title}</strong>
      <em>{kindLabel}</em>
    </button>
  );
}

function BriefingEntityRow({
  entity,
  onOpen,
  t,
}: {
  entity: BrainMapBriefingEntity;
  onOpen: (entity: BrainMapBriefingEntity) => void;
  t: Translator;
}) {
  const typeLabel = entityTypeLabel(entity.type, t);
  return (
    <button
      type="button"
      className="brain-map-briefing__row"
      aria-label={`${entity.name} ${typeLabel}`}
      onClick={() => onOpen(entity)}
    >
      <strong>{entity.name}</strong>
      <em>
        {typeLabel} · {entity.citation_count} {t("source(s)", "источн.")}
      </em>
    </button>
  );
}

function BrainMapBriefingPanel({
  projection,
  selectedSpace,
  creatingLens,
  onAskNext,
  onAskWai,
  onOpenSource,
  onOpenEntity,
  t,
}: {
  projection: BrainMapProjection;
  selectedSpace: BrainSpace | null;
  creatingLens: boolean;
  onAskNext: (prompt: string) => void;
  onAskWai?: (brain: { spaceId: string; spaceName: string }) => void | Promise<void>;
  onOpenSource: (kind: string, id: string) => void;
  onOpenEntity: (id: string, name: string) => void;
  t: Translator;
}) {
  const briefing = projection.briefing;
  if (!briefing) return null;

  const questions = localizedSuggestedQuestions(
    projection.map_type,
    briefing.suggested_questions,
    t,
  );
  const hiddenCount = hiddenFocusCount(briefing);

  return (
    <section className="brain-map-briefing" aria-label={t("Map briefing", "Бриф карты")}>
      <div className="brain-map-briefing__top">
        <div>
          <span className="brain-map-briefing__type">{mapTypeLabel(projection.map_type, t)}</span>
          <h3>{briefingFocusText(briefing, t)}</h3>
          <p>{briefingFreshnessText(projection, t)}</p>
        </div>
        {selectedSpace && onAskWai ? (
          <button
            type="button"
            className="wai-secondary-button"
            onClick={() => void onAskWai({ spaceId: selectedSpace.id, spaceName: selectedSpace.name })}
          >
            {t("Ask Wai", "Спросить Wai")}
          </button>
        ) : null}
      </div>

      <div className="brain-map-briefing__metrics">
        <BriefingMetric
          value={`${briefing.coverage.visible_sources}/${briefing.coverage.total_sources}`}
          label={t("sources in focus", "источн. в фокусе")}
        />
        <BriefingMetric
          value={`${briefing.coverage.visible_entities}/${briefing.coverage.total_entities}`}
          label={t("nodes in focus", "узлов в фокусе")}
        />
        {hiddenCount > 0 ? (
          <BriefingMetric
            value={`${hiddenCount}`}
            label={t("kept outside canvas", "вне canvas")}
          />
        ) : null}
      </div>

      <div className="brain-map-briefing__evidence">
        <div>
          <h4>{t("Evidence", "Источники")}</h4>
          {briefing.top_sources.length > 0 ? (
            briefing.top_sources.slice(0, 4).map((source) => (
              <BriefingSourceRow
                key={source.id}
                source={source}
                onOpen={(next) => onOpenSource(next.source_kind, next.source_id)}
                t={t}
              />
            ))
          ) : (
            <p className="brain-panel__empty">{t("No matching sources yet.", "Подходящих источников пока нет.")}</p>
          )}
        </div>
        <div>
          <h4>{t("Key nodes", "Ключевые узлы")}</h4>
          {briefing.top_entities.length > 0 ? (
            briefing.top_entities.slice(0, 5).map((entity) => (
              <BriefingEntityRow
                key={entity.id}
                entity={entity}
                onOpen={(next) => onOpenEntity(next.id, next.name)}
                t={t}
              />
            ))
          ) : (
            <p className="brain-panel__empty">{t("No linked pages yet.", "Связанных страниц пока нет.")}</p>
          )}
        </div>
      </div>

      {questions.length > 0 ? (
        <div className="brain-map-briefing__questions">
          <h4>{t("Ask next", "Следующие вопросы")}</h4>
          <div>
            {questions.slice(0, 3).map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => onAskNext(question)}
                disabled={creatingLens}
              >
                {question}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function BrainLensTemplatesPanel({
  creatingLens,
  onCreate,
  t,
}: {
  creatingLens: boolean;
  onCreate: (prompt: string) => void;
  t: Translator;
}) {
  return (
    <section className="brain-lens-templates" aria-label={t("Focus diagrams", "Фокусные диаграммы")}>
      <div className="brain-lens-templates__head">
        <div>
          <h3>{t("Focus diagrams", "Фокусные диаграммы")}</h3>
          <p>
            {t(
              "Start from a real question. Wai will generate a map and keep it tied to sources.",
              "Начните с реального вопроса. Wai создаст карту и привяжет её к источникам.",
            )}
          </p>
        </div>
      </div>
      <div className="brain-lens-templates__grid">
        {DIAGRAM_TEMPLATES.map((template) => {
          const title = t(template.titleEn, template.titleRu);
          const subtitle = t(template.subtitleEn, template.subtitleRu);
          const prompt = t(template.promptEn, template.promptRu);
          return (
            <button
              key={template.key}
              type="button"
              aria-label={`${title}: ${subtitle}`}
              disabled={creatingLens}
              onClick={() => onCreate(prompt)}
            >
              <strong>{title}</strong>
              <span>{subtitle}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function MapNodeCard(props: NodeProps) {
  const data = props.data as MapNodeData;
  const node = data.node;
  return (
    <button
      type="button"
      className={`brain-map-node brain-map-node--${node.kind}`}
      onClick={data.onOpen}
      disabled={!data.onOpen}
    >
      <Handle type="target" position={Position.Left} />
      <span className="brain-map-node__kind">{nodeKindLabel(node)}</span>
      <strong>{node.title}</strong>
      {node.body ? <small>{node.body}</small> : null}
      {data.citationCount > 0 ? (
        <em>
          {data.citationCount} {data.citationCount === 1 ? "source" : "sources"}
        </em>
      ) : null}
      <Handle type="source" position={Position.Right} />
    </button>
  );
}

const nodeTypes = { brainMapNode: MapNodeCard };

function isScenarioSignalNode(node: BrainMapNode): boolean {
  return SCENARIO_SIGNAL_NODE_KINDS.has(node.kind.toLowerCase());
}

function nodeKindLabel(node: BrainMapNode): string {
  const kind = node.kind.toLowerCase();
  if (kind === "next_step") return "next step";
  if (kind === "open_question") return "open question";
  if (kind === "timeline_event") return "event";
  return kind.replaceAll("_", " ");
}

function canvasColumnForNode(node: BrainMapNode): BrainMapCanvasColumn {
  const lane = (node.lane ?? "").toLowerCase();
  const kind = node.kind.toLowerCase();
  if (kind === "source" || lane === "sources") return "sources";
  if (kind === "lens" || lane === "center") return "center";
  if (isScenarioSignalNode(node)) return "signals";
  if (kind === "gap" || kind === "open_question" || lane.includes("gap") || lane.includes("question")) {
    return "questions";
  }
  return "knowledge";
}

function briefingSourceKey(source: BrainMapBriefingSource): string {
  return `${source.source_kind}:${source.source_id}`;
}

function nodeFocusScore(
  node: BrainMapNode,
  index: number,
  briefing: BrainMapBriefing | null | undefined,
): number {
  let score = index / 1000;
  if (node.kind === "lens") score -= 1000;

  const sourceKey = node.source_kind && node.source_id ? `${node.source_kind}:${node.source_id}` : null;
  if (sourceKey && briefing?.top_sources.some((source) => briefingSourceKey(source) === sourceKey)) {
    score -= 200;
  }
  if (node.entity_id && briefing?.top_entities.some((entity) => entity.id === node.entity_id)) {
    score -= 200;
  }
  score -= Math.min(node.citation_ids.length, 8) * 10;
  return score;
}

function focusBrainMapProjection(projection: BrainMapProjection): BrainMapCanvasFocus {
  if (projection.nodes.length <= CANVAS_FOCUS_LIMIT) {
    return { projection, hiddenNodeCount: 0 };
  }

  const sortedNodes = projection.nodes
    .map((node, index) => ({
      node,
      column: canvasColumnForNode(node),
      score: nodeFocusScore(node, index, projection.briefing),
    }))
    .sort((a, b) => a.score - b.score);
  const selectedIds = new Set<string>();

  CANVAS_COLUMN_ORDER.forEach((column) => {
    sortedNodes
      .filter((entry) => entry.column === column)
      .slice(0, CANVAS_COLUMN_LIMITS[column])
      .forEach((entry) => {
        if (selectedIds.size < CANVAS_FOCUS_LIMIT) selectedIds.add(entry.node.id);
      });
  });

  sortedNodes.forEach((entry) => {
    if (selectedIds.size < CANVAS_FOCUS_LIMIT) selectedIds.add(entry.node.id);
  });

  const nodes = projection.nodes.filter((node) => selectedIds.has(node.id));
  const edges = projection.edges.filter(
    (edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target),
  );
  return {
    projection: { ...projection, nodes, edges },
    hiddenNodeCount: projection.nodes.length - nodes.length,
  };
}

function hasReadableProjectionPositions(nodes: BrainMapNode[]): boolean {
  if (nodes.length <= 1) return true;
  const positions = nodes.map((node) => node.position).filter((position): position is BrainMapPosition => Boolean(position));
  if (positions.length !== nodes.length) return false;

  const xs = positions.map((position) => position.x);
  const ys = positions.map((position) => position.y);
  const width = Math.max(...xs) - Math.min(...xs);
  const height = Math.max(...ys) - Math.min(...ys);
  if (nodes.length > 4 && (width < 420 || height < 180)) return false;

  let crowdedPairs = 0;
  for (let i = 0; i < positions.length; i += 1) {
    for (let j = i + 1; j < positions.length; j += 1) {
      if (
        Math.abs(positions[i].x - positions[j].x) < 190 &&
        Math.abs(positions[i].y - positions[j].y) < 95
      ) {
        crowdedPairs += 1;
      }
    }
  }

  return crowdedPairs <= Math.max(1, Math.floor(nodes.length / 4));
}

function diagramPosition(
  node: BrainMapNode,
  columnIndex: number,
  columnCount: number,
  columnCounts: Record<BrainMapCanvasColumn, number>,
): BrainMapPosition {
  const column = canvasColumnForNode(node);
  const spacing = column === "center" ? 150 : 146;
  const y = (columnIndex - (columnCount - 1) / 2) * spacing;
  const x = column === "knowledge" && columnCounts.signals > 0 ? 660 : CANVAS_COLUMN_X[column];
  return {
    x,
    y: Math.round(column === "questions" ? y + 340 : y),
  };
}

function toFlowNodes(
  projection: BrainMapProjection,
  layout: Record<string, BrainMapPosition> | null | undefined,
  handlers: {
    openSource: (kind: string, id: string) => void;
    openEntity: (id: string, name: string) => void;
  },
): Node<MapNodeData>[] {
  const columnCounts = projection.nodes.reduce<Record<BrainMapCanvasColumn, number>>(
    (counts, node) => {
      const column = canvasColumnForNode(node);
      counts[column] += 1;
      return counts;
    },
    { sources: 0, center: 0, signals: 0, knowledge: 0, questions: 0 },
  );
  const columnIndexes: Record<BrainMapCanvasColumn, number> = {
    sources: 0,
    center: 0,
    signals: 0,
    knowledge: 0,
    questions: 0,
  };
  const useProjectionPositions = hasReadableProjectionPositions(projection.nodes);
  return projection.nodes.map((node) => {
    const column = canvasColumnForNode(node);
    const columnIndex = columnIndexes[column];
    columnIndexes[column] = columnIndex + 1;
    const override = layout?.[node.id];
    const fallback = useProjectionPositions && node.position
      ? node.position
      : diagramPosition(node, columnIndex, columnCounts[column], columnCounts);
    const onOpen =
      node.source_kind && node.source_id
        ? () => handlers.openSource(node.source_kind as string, node.source_id as string)
        : node.kind === "entity" && node.entity_id
          ? () => handlers.openEntity(node.entity_id as string, node.title)
          : undefined;
    return {
      id: node.id,
      type: "brainMapNode",
      position: override ?? fallback,
      data: {
        node,
        citationCount: node.citation_ids.length,
        onOpen,
      },
      draggable: true,
      selectable: true,
      zIndex: node.kind === "lens" ? 3 : isScenarioSignalNode(node) ? 2 : 1,
    } satisfies Node<MapNodeData>;
  });
}

function toFlowEdges(projection: BrainMapProjection): Edge[] {
  return projection.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: "smoothstep",
    animated: false,
    style: {
      stroke:
        edge.kind === "mentions"
          ? "var(--accent)"
          : edge.kind === "related_to"
            ? "var(--ink-faint)"
            : "var(--ink-soft)",
      strokeWidth: edge.kind === "supports" ? 1.6 : 1.1,
    },
  }));
}

function BrainMapCanvas({
  projection,
  layout,
  onOpenSource,
  onOpenEntity,
  onLayoutChange,
  t,
}: {
  projection: BrainMapProjection;
  layout?: Record<string, BrainMapPosition> | null;
  onOpenSource: (kind: string, id: string) => void;
  onOpenEntity: (id: string, name: string) => void;
  onLayoutChange?: (layout: Record<string, BrainMapPosition>) => void;
  t: Translator;
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<MapNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const nodesRef = useRef<Node<MapNodeData>[]>([]);
  const focused = useMemo(() => focusBrainMapProjection(projection), [projection]);

  useEffect(() => {
    const nextNodes = toFlowNodes(focused.projection, layout, { openSource: onOpenSource, openEntity: onOpenEntity });
    setNodes(nextNodes);
    setEdges(toFlowEdges(focused.projection));
  }, [focused.projection, layout, onOpenEntity, onOpenSource, setEdges, setNodes]);

  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

  const persistLayout = useCallback(() => {
    if (!onLayoutChange) return;
    const next = { ...(layout ?? {}) };
    nodesRef.current.forEach((node) => {
      next[node.id] = { x: Math.round(node.position.x), y: Math.round(node.position.y) };
    });
    onLayoutChange(next);
  }, [layout, onLayoutChange]);

  return (
    <div className="brain-map-canvas" data-testid="brain-map-canvas">
      {focused.hiddenNodeCount > 0 ? (
        <div className="brain-map-canvas__status" aria-live="polite">
          {t(
            `${focused.projection.nodes.length} on canvas · ${focused.hiddenNodeCount} more in Brain`,
            `${focused.projection.nodes.length} на canvas · ещё ${focused.hiddenNodeCount} в Мозге`,
          )}
        </div>
      ) : null}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDragStop={persistLayout}
        fitView
        fitViewOptions={{ padding: 0.22 }}
        minZoom={0.25}
        maxZoom={1.7}
        onlyRenderVisibleElements
      >
        <Controls />
        <Background gap={18} size={1} />
      </ReactFlow>
    </div>
  );
}

export function BrainPanel({
  locale = "en",
  initialMapId,
  onError,
  onOpenSource,
  onOpenInbox,
  onOpenWai,
}: BrainPanelProps) {
  const t = useCallback((en: string, ru: string) => (locale === "ru" ? ru : en), [locale]);

  const [mirror, setMirror] = useState<BrainMapProjection | null>(null);
  const [maps, setMaps] = useState<BrainMap[]>([]);
  const [activeMapId, setActiveMapId] = useState<string>("mirror");
  const [lensPrompt, setLensPrompt] = useState("");
  const [showLensForm, setShowLensForm] = useState(false);
  const [creatingLens, setCreatingLens] = useState(false);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [brainQuestion, setBrainQuestion] = useState("");
  const [brainAnswer, setBrainAnswer] = useState<BrainAnswer | null>(null);
  const [askingBrain, setAskingBrain] = useState(false);
  const [brainAskError, setBrainAskError] = useState<string | null>(null);

  const [entities, setEntities] = useState<Entity[]>([]);
  const [filter, setFilter] = useState<PageFilter>("all");
  const [search, setSearch] = useState("");
  const [selectedEntity, setSelectedEntity] = useState<{ id: string; name: string } | null>(null);

  const [spaces, setSpaces] = useState<BrainSpace[]>([]);
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null);
  const [spaceHome, setSpaceHome] = useState<BrainSpaceHome | null>(null);
  const [reviewPacks, setReviewPacks] = useState<BrainReviewPack[]>([]);
  const [actingReviewPackIds, setActingReviewPackIds] = useState<Set<string>>(new Set());
  const [shareEmail, setShareEmail] = useState("");
  const [shareRole, setShareRole] = useState<"viewer" | "editor">("viewer");
  const [shareMessage, setShareMessage] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const [exportMessage, setExportMessage] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [curatedError, setCuratedError] = useState<string | null>(null);
  const hasLoadedRef = useRef(false);

  const selectedSpace = spaces.find((s) => s.id === selectedSpaceId) ?? null;
  const activeMap = maps.find((map) => map.id === activeMapId) ?? null;
  const activeProjection = activeMap?.current_revision?.projection ?? mirror;
  const activeDiff = activeMap?.current_revision?.diff ?? null;
  const activeProjectionKey = `${activeMap?.id ?? "mirror"}:${activeProjection?.source_fingerprint ?? activeProjection?.title ?? "empty"}`;

  const openSource = useCallback(
    (sourceKind: string, sourceId: string) => {
      if (sourceKind !== "recording" && sourceKind !== "item") return;
      onOpenSource?.(sourceKind, sourceId);
    },
    [onOpenSource],
  );

  const loadCurated = useCallback(
    async (spaceId: string | null) => {
      if (!spaceId) {
        setSpaceHome(null);
        setReviewPacks([]);
        return;
      }
      const [home, packs] = await Promise.all([
        getBrainSpaceHome(spaceId),
        listBrainReviewPacks(spaceId, { status: "pending" }),
      ]);
      setSpaceHome(home);
      setReviewPacks(packs.review_packs);
    },
    [],
  );

  const load = useCallback(async () => {
    if (!hasLoadedRef.current) setLoading(true);
    setError(null);
    try {
      const [mirrorProjection, mapList, entityList, spaceList] = await Promise.all([
        getBrainMirror({ limit: 60 }),
        listBrainMaps({ limit: 50 }),
        listEntities({ limit: 200 }),
        listBrainSpaces(),
      ]);
      setMirror(mirrorProjection);
      setMaps(mapList.maps);
      if (initialMapId && mapList.maps.some((map) => map.id === initialMapId)) {
        setActiveMapId(initialMapId);
      }
      setEntities(entityList);
      setSpaces(spaceList.spaces);
      const nextSpaceId =
        selectedSpaceId && spaceList.spaces.some((space) => space.id === selectedSpaceId)
          ? selectedSpaceId
          : (spaceList.spaces[0]?.id ?? null);
      setSelectedSpaceId(nextSpaceId);
      await loadCurated(nextSpaceId);
      setCuratedError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't load your Brain.";
      setError(message);
      onError?.(message);
    } finally {
      hasLoadedRef.current = true;
      setLoading(false);
    }
  }, [initialMapId, loadCurated, onError, selectedSpaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!initialMapId || !maps.some((map) => map.id === initialMapId)) return;
    setActiveMapId(initialMapId);
  }, [initialMapId, maps]);

  useEffect(() => {
    if (!hasLoadedRef.current) return;
    void loadCurated(selectedSpaceId).catch((err) => {
      const message = err instanceof Error ? err.message : "Couldn't load curated Brain.";
      setCuratedError(message);
      onError?.(message);
    });
  }, [loadCurated, onError, selectedSpaceId]);

  const createLens = useCallback(async (promptOverride?: string) => {
    const prompt = (promptOverride ?? lensPrompt).trim();
    if (!prompt || creatingLens) return;
    setCreatingLens(true);
    try {
      const created = await createBrainMap({ prompt, origin: "brain" });
      setMaps((current) => [created, ...current.filter((map) => map.id !== created.id)]);
      setActiveMapId(created.id);
      setLensPrompt("");
      setShowLensForm(false);
      setError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't create this lens.";
      setError(message);
      onError?.(message);
    } finally {
      setCreatingLens(false);
    }
  }, [creatingLens, lensPrompt, onError]);

  const askBrainQuestion = useCallback(async () => {
    const question = brainQuestion.trim();
    if (!question || askingBrain) return;
    setAskingBrain(true);
    try {
      const answer = await askBrain(question);
      setBrainAnswer(answer);
      setBrainAskError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't answer from Brain.";
      setBrainAskError(message);
      onError?.(message);
    } finally {
      setAskingBrain(false);
    }
  }, [askingBrain, brainQuestion, onError]);

  const persistLayout = useCallback(
    async (layout: Record<string, BrainMapPosition>) => {
      if (!activeMap) return;
      try {
        const updated = await updateBrainMap(activeMap.id, { layout });
        setMaps((current) => current.map((map) => (map.id === updated.id ? updated : map)));
      } catch (err) {
        const message = err instanceof Error ? err.message : "Couldn't save map layout.";
        setError(message);
        onError?.(message);
      }
    },
    [activeMap, onError],
  );

  const saveActiveMap = useCallback(async () => {
    if (!activeMap) return;
    try {
      const updated = await updateBrainMap(activeMap.id, { status: "saved" });
      setMaps((current) => current.map((map) => (map.id === updated.id ? updated : map)));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't save this map.";
      setError(message);
      onError?.(message);
    }
  }, [activeMap, onError]);

  const refreshActiveMap = useCallback(async () => {
    if (!activeMap || refreshingId) return;
    setRefreshingId(activeMap.id);
    try {
      const revision = await refreshBrainMap(activeMap.id);
      setMaps((current) =>
        current.map((map) =>
          map.id === activeMap.id
            ? { ...map, current_revision_id: revision.id, current_revision: revision }
            : map,
        ),
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't refresh this map.";
      setError(message);
      onError?.(message);
    } finally {
      setRefreshingId(null);
    }
  }, [activeMap, onError, refreshingId]);

  const decideReviewPack = useCallback(
    async (id: string, decision: "accept" | "reject") => {
      if (!selectedSpaceId || actingReviewPackIds.has(id)) return;
      setActingReviewPackIds((cur) => new Set(cur).add(id));
      try {
        if (decision === "accept") await acceptBrainReviewPack(selectedSpaceId, id);
        else await rejectBrainReviewPack(selectedSpaceId, id);
        setReviewPacks((cur) => cur.filter((p) => p.id !== id));
        setCuratedError(null);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Couldn't update this suggestion.";
        setCuratedError(message);
        onError?.(message);
      } finally {
        setActingReviewPackIds((cur) => {
          const next = new Set(cur);
          next.delete(id);
          return next;
        });
      }
    },
    [actingReviewPackIds, onError, selectedSpaceId],
  );

  const shareSpace = useCallback(async () => {
    const email = shareEmail.trim();
    if (!selectedSpaceId || !email || sharing) return;
    setSharing(true);
    setShareMessage(null);
    try {
      await addBrainSpaceMember(selectedSpaceId, { email, role: shareRole });
      setShareEmail("");
      setShareMessage(t(`Shared with ${email} as ${shareRole}.`, `Доступ открыт: ${email} (${shareRole}).`));
      setCuratedError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't share this Brain.";
      setCuratedError(message);
      onError?.(message);
    } finally {
      setSharing(false);
    }
  }, [onError, selectedSpaceId, shareEmail, shareRole, sharing, t]);

  const runExport = useCallback(
    async (profile: string) => {
      if (!selectedSpaceId) return;
      setExportMessage(null);
      try {
        const exported = await exportBrainSpace(selectedSpaceId, profile);
        const n = exported.files.length;
        setExportMessage(
          n === 0
            ? t("No files yet.", "Пока нет файлов.")
            : n === 1
              ? t("1 Markdown file is ready.", "Готов 1 Markdown-файл.")
              : t(`${n} Markdown files are ready.`, `Готово Markdown-файлов: ${n}.`),
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : "Couldn't export this Brain.";
        setCuratedError(message);
        onError?.(message);
      }
    },
    [onError, selectedSpaceId, t],
  );

  const visiblePages = useMemo(() => {
    const q = search.trim().toLowerCase();
    return entities.filter(
      (e) =>
        (filter === "all" || e.type === filter) &&
        (q === "" || e.name.toLowerCase().includes(q)),
    );
  }, [entities, filter, search]);

  const approvedKnowledgeCount = Object.values(spaceHome?.claim_counts ?? {}).reduce(
    (sum, n) => sum + n,
    0,
  );
  const sources = spaceHome?.sources ?? [];
  const hasAnything =
    entities.length > 0 ||
    maps.length > 0 ||
    approvedKnowledgeCount > 0 ||
    reviewPacks.length > 0 ||
    sources.length > 0 ||
    Boolean(mirror?.nodes.length);

  const pageRow = (entity: Entity) => (
    <button
      key={entity.id}
      type="button"
      className="brain-panel__entity-row"
      onClick={() => setSelectedEntity({ id: entity.id, name: entity.name })}
    >
      <span className="brain-panel__entity-icon">{entityGlyph(entity.type)}</span>
      <span>
        <strong>{entity.name}</strong>
        <em>{entity.type}</em>
      </span>
      <small>
        {entity.source_count ?? 0}{" "}
        {(entity.source_count ?? 0) === 1 ? t("source", "источн.") : t("sources", "источн.")}
      </small>
    </button>
  );

  const sourceRow = (source: BrainSpaceSourceSummary) => (
    <button
      key={source.id}
      type="button"
      className="brain-panel__source-row brain-panel__source-row--button"
      onClick={() => openSource(source.source_kind, source.source_id)}
    >
      <strong>{source.source_title ?? t("Untitled source", "Источник без названия")}</strong>
      <em>{source.source_kind === "recording" ? t("recording", "запись") : t("material", "материал")}</em>
    </button>
  );

  if (loading) {
    return (
      <section className="brain-panel brain-panel--loading">
        <div className="brain-panel__loading">{t("Loading Brain…", "Загружаю Мозг…")}</div>
      </section>
    );
  }

  if (selectedEntity) {
    return (
      <section className="brain-panel">
        <button
          type="button"
          className="brain-panel__back"
          onClick={() => setSelectedEntity(null)}
        >
          ← {t("Back to Mirror", "Назад к Зеркалу")}
        </button>
        <EntityWikiView
          entityId={selectedEntity.id}
          locale={locale}
          onOpenSource={openSource}
          onNavigate={(id, name) => setSelectedEntity({ id, name })}
        />
      </section>
    );
  }

  return (
    <section className="brain-panel brain-panel--mirror">
      <header className="brain-panel__hero">
        <div>
          <p className="brain-panel__eyebrow">{t("Live Mirror", "Живое зеркало")}</p>
          <h2>{t("Brain", "Мозг")}</h2>
          {activeProjection ? <p>{activeProjection.summary}</p> : null}
        </div>
        <div className="brain-panel__hero-actions">
          <button
            type="button"
            className="wai-secondary-button"
            onClick={() => setShowLensForm((value) => !value)}
          >
            {t("Create Lens", "Создать линзу")}
          </button>
          {activeMap ? (
            <>
              <button
                type="button"
                className="wai-secondary-button"
                onClick={() => void refreshActiveMap()}
                disabled={refreshingId === activeMap.id}
              >
                {refreshingId === activeMap.id ? t("Refreshing…", "Обновляю…") : t("Refresh", "Обновить")}
              </button>
              {activeMap.status === "draft" ? (
                <button type="button" className="wai-primary-button" onClick={() => void saveActiveMap()}>
                  {t("Keep", "Сохранить")}
                </button>
              ) : null}
            </>
          ) : null}
        </div>
      </header>

      {showLensForm ? (
        <form
          className="brain-lens-form"
          onSubmit={(event) => {
            event.preventDefault();
            void createLens();
          }}
        >
          <input
            value={lensPrompt}
            onChange={(event) => setLensPrompt(event.target.value)}
            placeholder={t("Map a project, decision, relationship, timeline…", "Карта проекта, решения, связей, хронологии…")}
            aria-label={t("Lens prompt", "Запрос линзы")}
          />
          <button type="submit" className="wai-primary-button" disabled={creatingLens || !lensPrompt.trim()}>
            {creatingLens ? t("Generating…", "Создаю…") : t("Generate", "Создать")}
          </button>
        </form>
      ) : null}

      {error ? (
        <div className="brain-panel__error">
          <span>{error}</span>
          <button type="button" onClick={() => void load()}>
            {t("Retry", "Повторить")}
          </button>
        </div>
      ) : null}

      {!hasAnything ? (
        <div className="brain-panel__empty-state">
          <h3>{t("Start with sources", "Начните с источников")}</h3>
          <p>{t("Add recordings or materials from Inbox to build your Brain.", "Добавьте записи или материалы из инбокса.")}</p>
          {onOpenInbox ? (
            <button type="button" className="wai-secondary-button" onClick={onOpenInbox}>
              {t("Open Inbox", "Открыть инбокс")}
            </button>
          ) : null}
        </div>
      ) : (
        <div className="brain-workspace">
          <main className="brain-workspace__main">
            <div className="brain-map-toolbar">
              <div>
                <strong>{activeProjection?.title ?? t("Live Mirror", "Живое зеркало")}</strong>
                <span>{activeProjection ? mapTypeLabel(activeProjection.map_type, t) : ""}</span>
              </div>
              <div className="brain-map-toolbar__stats">
                <span>{activeProjection?.nodes.length ?? 0} {t("cards", "карточек")}</span>
                <span>{activeProjection?.edges.length ?? 0} {t("links", "связей")}</span>
                <span>{activeProjection?.citations.length ?? 0} {t("sources", "источн.")}</span>
              </div>
            </div>
            <BrainAskPanel
              question={brainQuestion}
              answer={brainAnswer}
              error={brainAskError}
              asking={askingBrain}
              creatingLens={creatingLens}
              onQuestionChange={setBrainQuestion}
              onAsk={() => void askBrainQuestion()}
              onMap={() => void createLens(brainQuestion)}
              onOpenCitation={(citation) => openSource(citation.source_kind, citation.source_id)}
              t={t}
            />
            {activeMap && activeProjection ? (
              <BrainMapBriefingPanel
                projection={activeProjection}
                selectedSpace={selectedSpace}
                creatingLens={creatingLens}
                onAskNext={(prompt) => void createLens(prompt)}
                onAskWai={onOpenWai}
                onOpenSource={openSource}
                onOpenEntity={(id, name) => setSelectedEntity({ id, name })}
                t={t}
              />
            ) : null}
            {!activeMap && activeProjection ? (
              <BrainLensTemplatesPanel
                creatingLens={creatingLens}
                onCreate={(prompt) => void createLens(prompt)}
                t={t}
              />
            ) : null}
            {activeProjection ? (
              <BrainMapCanvas
                key={activeProjectionKey}
                projection={activeProjection}
                layout={activeMap?.layout}
                onOpenSource={openSource}
                onOpenEntity={(id, name) => setSelectedEntity({ id, name })}
                onLayoutChange={activeMap ? (layout) => void persistLayout(layout) : undefined}
                t={t}
              />
            ) : null}
          </main>

          <aside className="brain-workspace__side">
            <section className="brain-panel__section">
              <div className="brain-panel__section-head">
                <h3>{t("Maps", "Карты")}</h3>
                <span>{maps.length}</span>
              </div>
              <div className="brain-map-list">
                <button
                  type="button"
                  className={`brain-map-list__item ${activeMapId === "mirror" ? "brain-map-list__item--active" : ""}`}
                  onClick={() => setActiveMapId("mirror")}
                >
                  <strong>{t("Live Mirror", "Живое зеркало")}</strong>
                  <small>{t("always current", "всегда актуально")}</small>
                </button>
                {maps.map((map) => (
                  <button
                    key={map.id}
                    type="button"
                    className={`brain-map-list__item ${activeMapId === map.id ? "brain-map-list__item--active" : ""}`}
                    onClick={() => setActiveMapId(map.id)}
                  >
                    <strong>{map.title}</strong>
                    <small>
                      {map.status} · {diffText(map.current_revision?.diff ?? null, t)}
                    </small>
                  </button>
                ))}
              </div>
            </section>

            {activeMap ? (
              <section className="brain-panel__section brain-diff">
                <h3>{t("Freshness", "Актуальность")}</h3>
                <p>{diffText(activeDiff, t)}</p>
                {activeMap.current_revision?.freshness.stale ? (
                  <small>
                    {t(
                      `Newest source is ${activeMap.current_revision.freshness.weeks_since} weeks old.`,
                      `Новому источнику недель: ${activeMap.current_revision.freshness.weeks_since}.`,
                    )}
                  </small>
                ) : null}
              </section>
            ) : null}

            <section className="brain-panel__section">
              <div className="brain-panel__section-head">
                <h3>{t("Pages", "Страницы")}</h3>
                <div className="brain-pages__filters" role="tablist" aria-label={t("Filter pages", "Фильтр страниц")}>
                  {FILTERS.map((f) => (
                    <button
                      key={f.key}
                      type="button"
                      role="tab"
                      aria-selected={filter === f.key}
                      className={`brain-pages__filter ${filter === f.key ? "brain-pages__filter--active" : ""}`}
                      onClick={() => setFilter(f.key)}
                    >
                      {t(f.en, f.ru)}
                    </button>
                  ))}
                </div>
              </div>
              <input
                className="brain-pages__search"
                value={search}
                placeholder={t("Search pages…", "Поиск страниц…")}
                aria-label={t("Search pages", "Поиск страниц")}
                onChange={(event) => setSearch(event.target.value)}
              />
              {visiblePages.length > 0 ? (
                <div className="brain-panel__rows brain-panel__rows--spaced">
                  {visiblePages.slice(0, 16).map(pageRow)}
                </div>
              ) : (
                <p className="brain-panel__empty">{t("No pages yet.", "Пока нет страниц.")}</p>
              )}
            </section>

            <details className="brain-panel__context-preview">
              <summary>{t("Curated knowledge · Sources", "Подтверждённые знания · Источники")}</summary>

              {spaces.length > 1 ? (
                <label className="brain-panel__space-toolbar">
                  <span>{t("Brain", "Мозг")}</span>
                  <select
                    value={selectedSpaceId ?? ""}
                    onChange={(event) => setSelectedSpaceId(event.target.value || null)}
                  >
                    {spaces.map((space) => (
                      <option key={space.id} value={space.id}>
                        {space.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}

              {curatedError ? <p className="brain-panel__error-text">{curatedError}</p> : null}

              <div className="brain-panel__mini-section">
                <h4>{t("Review", "Проверка")}</h4>
                {reviewPacks.length > 0 ? (
                  reviewPacks.map((pack) => (
                    <div key={pack.id} className="brain-review-pack">
                      <strong>{pack.title}</strong>
                      <p>{pack.summary}</p>
                      <div>
                        <button
                          type="button"
                          className="wai-secondary-button"
                          disabled={actingReviewPackIds.has(pack.id)}
                          onClick={() => void decideReviewPack(pack.id, "reject")}
                        >
                          {t("Ignore", "Игнорировать")}
                        </button>
                        <button
                          type="button"
                          className="wai-primary-button"
                          disabled={actingReviewPackIds.has(pack.id)}
                          onClick={() => void decideReviewPack(pack.id, "accept")}
                        >
                          {t("Approve", "Подтвердить")}
                        </button>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="brain-panel__empty">{t("Nothing waiting for review.", "Нет знаний на проверку.")}</p>
                )}
              </div>

              <div className="brain-panel__mini-section">
                <h4>{t("Sources", "Источники")}</h4>
                {sources.length > 0 ? sources.slice(0, 8).map(sourceRow) : (
                  <p className="brain-panel__empty">{t("No curated sources yet.", "Пока нет источников.")}</p>
                )}
              </div>

              <div className="brain-panel__mini-section">
                <h4>{t("Share · Export", "Доступ · Экспорт")}</h4>
                <div className="brain-panel__share-row">
                  <input
                    value={shareEmail}
                    placeholder="teammate@example.com"
                    onChange={(event) => setShareEmail(event.target.value)}
                  />
                  <select value={shareRole} onChange={(event) => setShareRole(event.target.value as "viewer" | "editor")}>
                    <option value="viewer">{t("Viewer", "Читатель")}</option>
                    <option value="editor">{t("Editor", "Редактор")}</option>
                  </select>
                  <button type="button" className="wai-secondary-button" disabled={sharing || !shareEmail.trim()} onClick={() => void shareSpace()}>
                    {sharing ? t("Sharing…", "Открываю…") : t("Invite", "Пригласить")}
                  </button>
                </div>
                {shareMessage ? <p className="brain-panel__empty">{shareMessage}</p> : null}
                {spaceHome ? (
                  <div className="brain-panel__export-row">
                    {spaceHome.engine_profiles.map((profile) => (
                      <button key={profile} type="button" className="wai-secondary-button" onClick={() => void runExport(profile)}>
                        {profile === "obsidian" ? "Obsidian" : profile === "gbrain" ? "GBrain" : profile === "mempalace" ? "MemPalace" : profile}
                      </button>
                    ))}
                  </div>
                ) : null}
                {exportMessage ? <p className="brain-panel__empty">{exportMessage}</p> : null}
              </div>
            </details>

            {selectedSpace && onOpenWai ? (
              <button
                type="button"
                className="brain-panel__open-wai wai-secondary-button"
                onClick={() => void onOpenWai({ spaceId: selectedSpace.id, spaceName: selectedSpace.name })}
              >
                {t("Open in Wai", "Открыть в Wai")}
              </button>
            ) : null}
          </aside>
        </div>
      )}
    </section>
  );
}
