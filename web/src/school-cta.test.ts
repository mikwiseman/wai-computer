import { readFileSync } from "node:fs";
import { join } from "node:path";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";

const read = (name: string) => readFileSync(join(process.cwd(), "public/school-static", name), "utf8");
const html = read("index.html");
const componentSource = html.slice(html.indexOf("class Component {"), html.indexOf("\n  const root = document.querySelector"));

function frame(progress: number) {
  const el = document.createElement("div");
  Object.defineProperty(el, "offsetHeight", { value: 7920 });
  el.getBoundingClientRect = () => ({ top: -7200 * progress, bottom: 7920 - 7200 * progress }) as DOMRect;
  return el;
}

function card() {
  const el = document.createElement("div");
  Object.defineProperty(el, "inert", { value: true, writable: true });
  return el;
}

describe("school enquiry navigation", () => {
  it.each([0.02, 0.045, 0.055, 0.105, 0.125])("keeps the visible hero CTA interactive at scene progress %s", (progress) => {
    const Component = runInNewContext(componentSource + "\nComponent", { window: { innerWidth: 1280, innerHeight: 720 } });
    const component = new Component({});
    const heroCard = card();
    component.unit = 1;
    component.refs2 = { sceneRoot: frame(progress), heroCard };
    component.tickDesktop();
    expect(heroCard.style.visibility).toBe("visible");
    expect(heroCard.style.pointerEvents).toBe("auto");
    expect(heroCard.getAttribute("aria-hidden")).toBe("false");
    expect(heroCard.inert).toBe(false);
  });

  it.each([0, 0.14, 0.4])("keeps the hidden hero CTA inactive at scene progress %s", (progress) => {
    const Component = runInNewContext(componentSource + "\nComponent", { window: { innerWidth: 1280, innerHeight: 720 } });
    const component = new Component({});
    const heroCard = card();
    component.unit = 1;
    component.refs2 = { sceneRoot: frame(progress), heroCard };
    component.tickDesktop();
    expect(heroCard.style.visibility).toBe("hidden");
    expect(heroCard.style.pointerEvents).toBe("none");
    expect(heroCard.inert).toBe(true);
  });

  it.each([0.55, 0.69, 0.8])("keeps the visible closing CTA interactive at progress %s", (progress) => {
    const Component = runInNewContext(componentSource + "\nComponent", { window: { innerWidth: 1280, innerHeight: 720 } });
    const component = new Component({});
    const finCta = card();
    component.unit = 1;
    component.refs2 = { finalWrap: frame(progress), finCta };
    component.tickDesktop();
    expect(finCta.style.visibility).toBe("visible");
    expect(finCta.style.pointerEvents).toBe("auto");
    expect(finCta.inert).toBe(false);
  });

  it.each(["index.html", "projects.html", "mentors/dima.html", "mentors/darya.html", "offer.html", "privacy.html", "contact.html"])("opens enquiry links from %s in the same tab", (name) => {
    const page = new DOMParser().parseFromString(read(name), "text/html");
    const links = page.querySelectorAll('a[href="/school/contact"]');
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect(link.getAttribute("target")).toBeNull();
  });
});
