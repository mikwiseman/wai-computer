import { memo, useMemo, type ReactNode } from "react";

/**
 * Renders the lightweight markdown the summarizer emits (bold section
 * headers, "- " bullets, **bold** emphasis, `monospace` metrics) as real
 * markup. Mirrors backend/app/core/telegram_format.py so a summary reads the
 * same in Telegram and on the web. React elements only — model output is
 * never injected as HTML.
 */

const BOLD_RE = /\*\*(.+?)\*\*|__(.+?)__/;
// No lookbehind — it is a parse-time SyntaxError on Safari < 16.4 and this
// component ships on the public /share page.
const ITALIC_RE = /(^|[^*\w])\*([^\s*](?:[^*\n]*?[^\s*])?)\*(?!\*)/;
const CODE_RE = /`([^`\n]+)`/;
const HEADING_RE = /^#{1,6}\s+/;
const BULLET_RE = /^[-*•–]\s+/;

function renderEmphasis(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let remaining = text;
  let index = 0;
  while (remaining.length > 0) {
    const boldMatch = BOLD_RE.exec(remaining);
    const italicMatch = ITALIC_RE.exec(remaining);
    const boldAt = boldMatch ? boldMatch.index : -1;
    const italicAt = italicMatch
      ? italicMatch.index + italicMatch[1].length
      : -1;

    if (boldMatch && (italicAt === -1 || boldAt <= italicAt)) {
      if (boldAt > 0) nodes.push(remaining.slice(0, boldAt));
      nodes.push(
        <strong key={`${keyPrefix}-b${index}`}>
          {boldMatch[1] ?? boldMatch[2]}
        </strong>,
      );
      remaining = remaining.slice(boldAt + boldMatch[0].length);
    } else if (italicMatch) {
      const start = italicMatch.index + italicMatch[1].length;
      if (start > 0) nodes.push(remaining.slice(0, start));
      nodes.push(<em key={`${keyPrefix}-i${index}`}>{italicMatch[2]}</em>);
      remaining = remaining.slice(start + italicMatch[0].length - italicMatch[1].length);
    } else {
      nodes.push(remaining);
      break;
    }
    index += 1;
  }
  return nodes;
}

export function renderSummaryInline(text: string, keyPrefix = "s"): ReactNode[] {
  const nodes: ReactNode[] = [];
  let remaining = text;
  let index = 0;
  while (remaining.length > 0) {
    const codeMatch = CODE_RE.exec(remaining);
    if (!codeMatch) {
      nodes.push(...renderEmphasis(remaining, `${keyPrefix}-t${index}`));
      break;
    }
    if (codeMatch.index > 0) {
      nodes.push(
        ...renderEmphasis(
          remaining.slice(0, codeMatch.index),
          `${keyPrefix}-t${index}`,
        ),
      );
    }
    nodes.push(
      <code key={`${keyPrefix}-c${index}`} className="mono">
        {codeMatch[1]}
      </code>,
    );
    remaining = remaining.slice(codeMatch.index + codeMatch[0].length);
    index += 1;
  }
  return nodes;
}

type SummaryBlock =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; lines: string[] }
  | { kind: "list"; items: string[] };

function isHeadingLine(line: string): boolean {
  if (HEADING_RE.test(line)) return true;
  const boldOnly = /^\*\*(.+)\*\*:?$/.exec(line);
  if (boldOnly) return true;
  return !BULLET_RE.test(line) && line.endsWith(":") && !BOLD_RE.test(line);
}

function headingText(line: string): string {
  const hashless = line.replace(HEADING_RE, "");
  const boldOnly = /^\*\*(.+)\*\*(:?)$/.exec(hashless);
  if (boldOnly) return `${boldOnly[1]}${boldOnly[2]}`;
  return hashless;
}

export function parseSummaryBlocks(text: string): SummaryBlock[] {
  const blocks: SummaryBlock[] = [];
  let list: string[] | null = null;
  let paragraph: string[] | null = null;

  const flush = () => {
    if (list && list.length) blocks.push({ kind: "list", items: list });
    if (paragraph && paragraph.length)
      blocks.push({ kind: "paragraph", lines: paragraph });
    list = null;
    paragraph = null;
  };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) {
      flush();
      continue;
    }
    const bullet = BULLET_RE.exec(line);
    if (bullet) {
      if (!list) {
        if (paragraph) flush();
        list = [];
      }
      list.push(line.slice(bullet[0].length));
      continue;
    }
    if (isHeadingLine(line)) {
      flush();
      blocks.push({ kind: "heading", text: headingText(line) });
      continue;
    }
    if (list) flush();
    paragraph = paragraph ?? [];
    paragraph.push(line);
  }
  flush();
  return blocks;
}

// Memoized: summaries are multi-KB and the panels hosting them re-render on
// polls, notices, and keystrokes. Parsing must only re-run when text changes.
export const SummaryMarkdown = memo(function SummaryMarkdown({ text }: { text: string }) {
  const blocks = useMemo(() => parseSummaryBlocks(text), [text]);
  return (
    <div className="summary-markdown">
      {blocks.map((block, i) => {
        if (block.kind === "heading") {
          return <h3 key={i}>{renderSummaryInline(block.text, `h${i}`)}</h3>;
        }
        if (block.kind === "list") {
          return (
            <ul key={i} className="reading-list">
              {block.items.map((item, j) => (
                <li key={j}>{renderSummaryInline(item, `l${i}-${j}`)}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i}>
            {block.lines.map((line, j) => (
              <span key={j}>
                {j > 0 ? <br /> : null}
                {renderSummaryInline(line, `p${i}-${j}`)}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
});
