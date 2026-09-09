import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (name: string) => readFileSync(join(process.cwd(), "public/school-static", name), "utf8");

describe("public school content", () => {
  it.each(["index.html", "projects.html", "mentors/dima.html", "mentors/darya.html", "offer.html", "privacy.html", "contact.html"])("keeps %s English, public, and self-contained", (name) => {
    const html = read(name);
    expect(html).toContain('<html lang="en">');
    expect(html).not.toMatch(/[\u0400-\u04ff]/);
    expect(html).not.toMatch(/(?:pi_|ch_|py_|cus_|sk_live_|whsec_)[A-Za-z0-9]+/);
    expect(html).not.toMatch(/\/report\/|notion\.so|zoom\.us\/|\?s=/);
    expect(html).not.toMatch(/\b(?:Vanya|Platon|Semyon|Gleb|Vova|Miron|Kristofer)\b/i);
    expect(html).toContain('rel="canonical"');
    expect(html).toContain("WaiWai, LLC");
    expect(html).toContain("Delaware");
    expect(html).not.toMatch(/wai(?:[ .]|<span[^>]*>\.<\/span>)school/i);
    expect(html).not.toContain("hello@mail.waiwai.is");
    expect(html).not.toMatch(/Russia|Moscow|RUB\b|₽|Severstal|Severgroup|MIPT|Rosatom|IIDF|Netology|Alfa-Bank|Samolet|Pike Media|https?:\/\/[^\s"<>]*\.ru\b/i);
  });
  it("uses the Delaware course offers and an English enquiry path", () => {
    const html = read("index.html");
    expect(html).toContain("€700");
    expect(read("offer.html")).toContain("€2,500");
    expect(read("offer.html")).toContain("ten individual lessons");
    expect(html).not.toMatch(/buy\.stripe\.com|<form|checkout|subscribe/i);
    expect(html).not.toContain("cal.com");
    expect(html).toContain('href="/school/contact"');
    expect(read("contact.html")).toContain("mailto:hi@wai.computer");
  });
  it("supports reduced motion without hiding content", () => {
    expect(read("index.html")).toContain("prefers-reduced-motion: reduce");
    expect(read("projects.html")).toContain("prefers-reduced-motion: reduce");
  });
  it("ships every referenced school asset and all twelve student projects", () => {
    for (const name of ["index.html", "projects.html", "mentors/dima.html", "mentors/darya.html"]) {
      for (const match of read(name).matchAll(/\/school-static\/([a-zA-Z0-9_./-]+\.(?:png|jpg|jpeg|webp|avif|svg|ico|woff2|css|js))/g)) {
        expect(existsSync(join(process.cwd(), "public/school-static", match[1])), `${name}: ${match[1]}`).toBe(true);
      }
    }
    const gallery = read("projects.html");
    expect(gallery.match(/class="pcard reveal"/g)).toHaveLength(12);
    expect(gallery).toContain("Student projects");
  });
});
