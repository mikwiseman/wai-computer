import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const root = join(process.cwd(), "public/school-static/student-projects");
const projects = ["hallownest", "block-modz", "rifflegg", "qfa-26", "bouquet", "mathai", "escape-room", "escape", "bug-battle", "bunker-zombie", "striker", "checkmedia"];
const files = readdirSync(root, { recursive: true }).map(String).filter((p) => /\.(html|js)$/.test(p));

describe("English editions of student projects", () => {
  it("anonymizes the public project document", () => {
    expect(readFileSync(join(root, "checkmedia/PROJECT.md"), "utf8")).not.toMatch(/[\u0400-\u04ff]|Kristofer|Russia/);
  });
  it.each(projects)("publishes the %s entry page", (project) => {
    expect(existsSync(join(root, project, "index.html"))).toBe(true);
  });
  it.each(files)("keeps text and scripts valid in %s", (file) => {
    const source = readFileSync(join(root, file), "utf8");
    const scripts: string[] = [];
    expect(/[\u0400-\u04ff]|Russia|Moscow|₽/.test(source)).toBe(false);
    if (file.endsWith(".html")) {
      expect(source.startsWith("<!DOCTYPE html>")).toBe(true);
      const doc = new DOMParser().parseFromString(source, "text/html");
      expect(doc.documentElement.lang).toBe("en");
      expect(doc.querySelector("base")?.getAttribute("href")).toMatch(/^\/school\/projects\//);
      expect(doc.querySelector('script[src="/analytics.js"]')).toBeNull();
      doc.querySelectorAll("script").forEach((s) => {
        if (!s.src && s.type !== "application/ld+json") scripts.push(s.textContent ?? "");
        s.remove();
      });
      doc.querySelectorAll("style").forEach((s) => s.remove());
      expect(/[\u0400-\u04ff]/.test(doc.body.textContent ?? "")).toBe(false);
    } else scripts.push(source);
    for (const script of scripts) {
      const parsed = ts.createSourceFile(file, script, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
      const result = ts.transpileModule(script, { reportDiagnostics: true, compilerOptions: { target: ts.ScriptTarget.ESNext, allowJs: true } });
      expect((result.diagnostics ?? []).filter((d) => d.category === ts.DiagnosticCategory.Error)).toHaveLength(0);
      const untranslated: string[] = [];
      const walk = (node: ts.Node) => {
        if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) && /[\u0400-\u04ff]/.test(node.text)) untranslated.push(node.text);
        ts.forEachChild(node, walk);
      };
      walk(parsed);
      expect(untranslated).toEqual([]);
    }
  });
});
