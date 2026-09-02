import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (name: string) => readFileSync(join(process.cwd(), "public/school-static", name), "utf8");

describe("public school content", () => {
  it.each(["index.html", "projects.html"])("keeps %s English, public, and self-contained", (name) => {
    const html = read(name);
    expect(html).toContain('<html lang="en">');
    expect(html).not.toMatch(/[\u0400-\u04ff]/);
    expect(html).not.toMatch(/(?:pi_|ch_|py_|cus_|sk_live_|whsec_)[A-Za-z0-9]+/);
    expect(html).not.toMatch(/\/report\/|notion\.so|zoom\.us\/|\?s=/);
    expect(html).toContain("WaiWai, LLC");
    expect(html).toContain("hello@mail.waiwai.is");
    expect(html).toContain('href="/school-static/style.css"');
    expect(html).toContain('rel="canonical"');
  });
  it("states the exact approved offers without introducing checkout", () => {
    const html = read("index.html");
    expect(html).toContain("€700");
    expect(html).toContain("Four-week course");
    expect(html).toContain("€2,500");
    expect(html).toContain("Ten individual lessons");
    expect(html).not.toMatch(/buy\.stripe\.com|<form|checkout|subscribe/i);
    expect(html).toContain("Confirm the teaching language");
  });
  it("supports reduced motion without hiding content", () => {
    expect(read("style.css")).toContain("prefers-reduced-motion: reduce");
    expect(read("school.js")).toContain("prefers-reduced-motion: reduce");
  });
  it("ships every referenced school asset and labels translated examples", () => {
    for (const name of ["index.html", "projects.html", "style.css"]) {
      for (const match of read(name).matchAll(/\/school-static\/assets\/([a-z0-9.-]+)/g)) {
        expect(existsSync(join(process.cwd(), "public/school-static/assets", match[1]))).toBe(true);
      }
    }
    const gallery = read("projects.html");
    expect(gallery).toContain("English translation of the original interface");
    expect(gallery).toContain("The original project is in Russian");
  });
});
