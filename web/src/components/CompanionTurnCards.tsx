"use client";

import { Fragment, type ReactNode, useState } from "react";

import type {
  CompanionActionProposal,
  CompanionActionResolution,
  CompanionToolAction,
  CompanionTurnItem,
} from "@/lib/companionTimeline";
import type { CompanionWebCitation } from "@/lib/types";

type Locale = "en" | "ru";
type Decision = "once" | "always" | "reject";

function toolLabel(tool: string, ru: boolean): string {
  switch (tool) {
    case "search":
    case "search_transcripts":
      return ru ? "Поиск по записям" : "Searched your brain";
    case "web_search":
      return ru ? "Поиск в интернете" : "Searched the web";
    case "fetch":
    case "get_recording_summary":
      return ru ? "Чтение записи" : "Read a recording";
    case "list_recordings":
      return ru ? "Список записей" : "Listed recordings";
    case "list_folders":
      return ru ? "Список папок" : "Listed folders";
    case "list_action_items":
    case "get_action_items":
      return ru ? "Задачи" : "Checked tasks";
    case "get_highlights":
      return ru ? "Ключевые моменты" : "Checked highlights";
    case "search_people":
      return ru ? "Поиск по людям" : "Searched people";
    default:
      return tool;
  }
}

export function CompanionTimeline({
  items,
  isLive,
  locale,
  onResolve,
}: {
  items: CompanionTurnItem[];
  isLive: boolean;
  locale: Locale;
  onResolve?: (actionId: string, decision: Decision) => void;
}) {
  return (
    <div className="wai-timeline">
      {items.map((item) => {
        switch (item.kind) {
          case "thinking":
            return <ThinkingCard key={item.id} text={item.text} isLive={isLive} locale={locale} />;
          case "tools":
            return (
              <ToolActionsCard key={item.id} actions={item.actions} isLive={isLive} locale={locale} />
            );
          case "plan":
            return <PlanCard key={item.id} steps={item.steps} locale={locale} />;
          case "artifact":
            return <ArtifactCard key={item.id} artifact={item.artifact} locale={locale} />;
          case "web_citations":
            return <WebCitationsCard key={item.id} citations={item.citations} locale={locale} />;
          case "text":
            return <Markdown key={item.id} text={item.markdown} />;
          case "action":
            return (
              <ActionCard
                key={item.id}
                proposal={item.proposal}
                resolution={item.resolution}
                locale={locale}
                onResolve={onResolve}
              />
            );
          default:
            return null;
        }
      })}
    </div>
  );
}

function ThinkingCard({
  text,
  isLive,
  locale,
}: {
  text: string;
  isLive: boolean;
  locale: Locale;
}) {
  return (
    <details className="wai-card wai-thinking" open={isLive} data-testid="wai-thinking-card">
      <summary>
        <span className="wai-card-icon wai-card-icon--thinking" aria-hidden />
        {locale === "ru" ? "Размышляю" : "Thinking"}
        {isLive ? " …" : ""}
      </summary>
      <div className="wai-thinking-body">{text}</div>
    </details>
  );
}

function ToolActionsCard({
  actions,
  isLive,
  locale,
}: {
  actions: CompanionToolAction[];
  isLive: boolean;
  locale: Locale;
}) {
  const ru = locale === "ru";
  const n = actions.length;
  const title = ru ? `Действия · ${n}` : `Tool actions · ${n} ${n === 1 ? "step" : "steps"}`;
  return (
    <details className="wai-card wai-tools" open={isLive} data-testid="wai-tool-actions-card">
      <summary>
        <span className="wai-card-icon wai-card-icon--tools" aria-hidden />
        {title}
      </summary>
      <ul className="wai-tool-list">
        {actions.map((a) => (
          <li key={a.call_id}>
            <span
              className={`wai-tool-status ${
                a.summary === null
                  ? "wai-tool-status--running"
                  : a.ok === false
                    ? "wai-tool-status--failed"
                    : "wai-tool-status--done"
              }`}
              aria-hidden
            />
            <span>{toolLabel(a.tool, ru)}</span>
            {a.summary ? <span className="wai-tool-summary">· {a.summary}</span> : null}
          </li>
        ))}
      </ul>
    </details>
  );
}

function ArtifactCard({
  artifact,
  locale,
}: {
  artifact: { artifact_id: string; title: string; kind: string; content: string; language?: string };
  locale: Locale;
}) {
  const ru = locale === "ru";
  function copy() {
    void navigator.clipboard?.writeText(artifact.content).catch(() => {});
  }
  return (
    <div className="wai-card wai-artifact" data-testid="wai-artifact-card">
      <div className="wai-artifact-head">
        <span className="wai-card-icon wai-card-icon--artifact" aria-hidden />
        <span className="wai-artifact-title">
          {artifact.title || (ru ? "Артефакт" : "Artifact")}
        </span>
        <span className="wai-artifact-kind">{artifact.kind.toUpperCase()}</span>
        <span style={{ flex: 1 }} />
        <button type="button" className="ghost-button compact-button" onClick={copy}>
          {ru ? "Копировать" : "Copy"}
        </button>
      </div>
      {artifact.kind === "html" ? (
        <iframe
          className="wai-artifact-preview"
          title={artifact.title || "preview"}
          sandbox="allow-scripts"
          srcDoc={artifact.content}
        />
      ) : artifact.kind === "code" ? (
        <pre className="wai-md-code wai-artifact-code">{artifact.content}</pre>
      ) : (
        <Markdown text={artifact.content} />
      )}
    </div>
  );
}

function PlanCard({
  steps,
  locale,
}: {
  steps: { title: string; status: string }[];
  locale: Locale;
}) {
  return (
    <div className="wai-card wai-plan" data-testid="wai-plan-card">
      <div className="wai-plan-head">
        <span className="wai-card-icon wai-card-icon--plan" aria-hidden />
        {locale === "ru" ? "План" : "Plan"}
      </div>
      <ul className="wai-plan-list">
        {steps.map((s, i) => (
          <li key={i} className={`wai-plan-step wai-plan-${s.status}`}>
            <span aria-hidden>
              {s.status === "done"
                ? "☑︎"
                : s.status === "failed"
                  ? "×"
                  : s.status === "in_progress"
                    ? "◐"
                    : "○"}
            </span>
            <span style={{ textDecoration: s.status === "done" ? "line-through" : undefined }}>
              {s.title}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function WebCitationsCard({
  citations,
  locale,
}: {
  citations: CompanionWebCitation[];
  locale: Locale;
}) {
  const ru = locale === "ru";
  return (
    <div className="wai-card wai-web-citations" data-testid="wai-web-citations-card">
      <div className="wai-web-citations-head">
        <span className="wai-card-icon wai-card-icon--web-citations" aria-hidden />
        {ru ? "Источники" : "Sources"}
      </div>
      <ul className="wai-web-citation-list">
        {citations.map((citation, i) => (
          <li key={`${citation.url}-${i}`}>
            <a href={citation.url} target="_blank" rel="noopener noreferrer">
              <span>{citation.title}</span>
              <span className="wai-web-citation-arrow" aria-hidden>
                ↗
              </span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function resolvedLabel(status: string, ru: boolean): string {
  switch (status) {
    case "executed":
      return ru ? "Готово" : "Done";
    case "dispatched":
      return ru ? "Отправлено на Mac" : "Sent to your Mac";
    case "rejected":
      return ru ? "Отклонено" : "Rejected";
    case "expired":
      return ru ? "Истекло" : "Expired";
    case "failed":
      return ru ? "Не удалось" : "Failed";
    default:
      return status;
  }
}

function ActionCard({
  proposal,
  resolution,
  locale,
  onResolve,
}: {
  proposal: CompanionActionProposal;
  resolution: CompanionActionResolution | null;
  locale: Locale;
  onResolve?: (actionId: string, decision: Decision) => void;
}) {
  const ru = locale === "ru";
  const [pending, setPending] = useState<Decision | null>(null);

  function trigger(decision: Decision) {
    setPending(decision);
    onResolve?.(proposal.action_id, decision);
  }

  return (
    <div className="wai-card wai-action" data-testid="wai-action-card">
      <div className="wai-action-head">
        <span
          className={`wai-card-icon ${
            proposal.tool.startsWith("desktop_")
              ? "wai-card-icon--desktop"
              : "wai-card-icon--action"
          }`}
          aria-hidden
        />
        {ru ? "Нужно подтверждение" : "Approval needed"}
      </div>
      <div className="wai-action-preview">{proposal.preview}</div>
      {proposal.recipient ? (
        <div className="wai-action-recipient">{(ru ? "Кому: " : "To: ") + proposal.recipient}</div>
      ) : null}
      {resolution ? (
        <div className="wai-action-result" data-testid="wai-action-result">
          {resolution.state === "executing"
            ? ru
              ? "Выполняю…"
              : "Working…"
            : resolvedLabel(resolution.status, ru)}
        </div>
      ) : onResolve ? (
        <div className="wai-action-buttons">
          <button
            type="button"
            className="ghost-button compact-button danger-button"
            disabled={pending !== null}
            onClick={() => trigger("reject")}
            data-testid="wai-action-reject"
          >
            {ru ? "Отклонить" : "Reject"}
          </button>
          <span style={{ flex: 1 }} />
          <button
            type="button"
            className="ghost-button compact-button"
            disabled={pending !== null}
            onClick={() => trigger("always")}
          >
            {ru ? "Всегда" : "Always"}
          </button>
          <button
            type="button"
            className="ghost-button compact-button"
            disabled={pending !== null}
            onClick={() => trigger("once")}
            data-testid="wai-action-approve"
          >
            {pending === "once" ? "…" : ru ? "Подтвердить" : "Approve"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

// MARK: - Minimal markdown

type MdBlock =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "bullets"; items: string[] }
  | { kind: "ordered"; items: string[] }
  | { kind: "code"; text: string };

export function Markdown({ text }: { text: string }) {
  return (
    <div className="wai-markdown">
      {parseMarkdown(text).map((block, i) => (
        <Fragment key={i}>{renderBlock(block)}</Fragment>
      ))}
    </div>
  );
}

function renderBlock(block: MdBlock): ReactNode {
  switch (block.kind) {
    case "heading": {
      const content = renderInline(block.text);
      if (block.level <= 1) return <h3 className="wai-md-heading">{content}</h3>;
      if (block.level === 2) return <h4 className="wai-md-heading">{content}</h4>;
      return <h5 className="wai-md-heading">{content}</h5>;
    }
    case "paragraph":
      return <p className="wai-md-p">{renderInline(block.text)}</p>;
    case "bullets":
      return (
        <ul className="wai-md-ul">
          {block.items.map((it, i) => (
            <li key={i}>{renderInline(it)}</li>
          ))}
        </ul>
      );
    case "ordered":
      return (
        <ol className="wai-md-ol">
          {block.items.map((it, i) => (
            <li key={i}>{renderInline(it)}</li>
          ))}
        </ol>
      );
    case "code":
      return <pre className="wai-md-code">{block.text}</pre>;
    default:
      return null;
  }
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const regex = /(\*\*([^*]+)\*\*|`([^`]+)`|\*([^*]+)\*|\[([^\]]+)\]\(([^)\s]+)\))/g;
  let lastIndex = 0;
  let key = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    if (match[2] !== undefined) nodes.push(<strong key={key++}>{match[2]}</strong>);
    else if (match[3] !== undefined) nodes.push(<code key={key++}>{match[3]}</code>);
    else if (match[4] !== undefined) nodes.push(<em key={key++}>{match[4]}</em>);
    else if (match[5] !== undefined)
      nodes.push(
        <a key={key++} href={match[6]} target="_blank" rel="noreferrer">
          {match[5]}
        </a>,
      );
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function parseMarkdown(text: string): MdBlock[] {
  const blocks: MdBlock[] = [];
  const lines = text.split("\n");
  let i = 0;
  let paragraph: string[] = [];

  const flush = () => {
    if (paragraph.length > 0) {
      const joined = paragraph.join(" ").trim();
      if (joined) blocks.push({ kind: "paragraph", text: joined });
      paragraph = [];
    }
  };
  const isBullet = (s: string) => /^[-*•]\s+/.test(s);
  const isOrdered = (s: string) => /^\d+\.\s+/.test(s);

  while (i < lines.length) {
    const trimmed = lines[i].trim();
    if (trimmed.startsWith("```")) {
      flush();
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1;
      blocks.push({ kind: "code", text: code.join("\n") });
      continue;
    }
    if (trimmed.length === 0) {
      flush();
      i += 1;
      continue;
    }
    if (trimmed.startsWith("#")) {
      flush();
      const hashes = trimmed.match(/^#+/)?.[0].length ?? 1;
      blocks.push({ kind: "heading", level: Math.min(hashes, 3), text: trimmed.slice(hashes).trim() });
      i += 1;
      continue;
    }
    if (isBullet(trimmed)) {
      flush();
      const items: string[] = [];
      while (i < lines.length && isBullet(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*•]\s+/, ""));
        i += 1;
      }
      blocks.push({ kind: "bullets", items });
      continue;
    }
    if (isOrdered(trimmed)) {
      flush();
      const items: string[] = [];
      while (i < lines.length && isOrdered(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push({ kind: "ordered", items });
      continue;
    }
    paragraph.push(trimmed);
    i += 1;
  }
  flush();
  return blocks;
}
