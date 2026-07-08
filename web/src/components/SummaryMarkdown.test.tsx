import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SummaryMarkdown, parseSummaryBlocks } from "@/components/SummaryMarkdown";

const SUMMARY = `**Формат встречи:** еженедельный созвон команды.

**Рынок и метрики (SAM/SOM)**
- Оценка рынка \`60-70 млрд руб.\`, пока **не очищена**
- Переход SAM → SOM задан допущением \`1-3%\`

Открытые вопросы остаются.`;

describe("parseSummaryBlocks", () => {
  it("splits headings, lists and paragraphs", () => {
    const blocks = parseSummaryBlocks(SUMMARY);
    expect(blocks.map((b) => b.kind)).toEqual([
      "paragraph",
      "heading",
      "list",
      "paragraph",
    ]);
  });
});

describe("SummaryMarkdown", () => {
  it("renders sections, inline bold and monospace metrics as markup", () => {
    render(<SummaryMarkdown text={SUMMARY} />);

    expect(
      screen.getByRole("heading", { level: 3, name: "Рынок и метрики (SAM/SOM)" }),
    ).toBeInTheDocument();
    expect(screen.getByText("60-70 млрд руб.").tagName).toBe("CODE");
    expect(screen.getByText("не очищена").tagName).toBe("STRONG");
    expect(screen.getByText("Формат встречи:").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    // No literal markdown survives.
    expect(document.body.textContent).not.toContain("**");
    expect(document.body.textContent).not.toContain("`");
  });
});
