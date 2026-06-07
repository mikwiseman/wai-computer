import { describe, expect, it } from "vitest";
import { buildForceGraph, sourceRefFromGraphNode } from "./BrainGraphView";

function graph() {
  return {
    nodes: [
      { id: "p1", label: "Anna", kind: "person", degree: 3 },
      { id: "t1", label: "GPU", kind: "topic", degree: 1 },
      { id: "item:i1", label: "Note", kind: "item", degree: 0 },
      { id: "chat:c1", label: "Wai thread", kind: "chat", degree: 0 },
    ],
    edges: [
      { source: "p1", target: "t1", type: "cooccurrence", weight: 2 },
      { source: "item:i1", target: "p1", type: "mention", weight: 1 },
      { source: "chat:c1", target: "p1", type: "mention", weight: 1 },
    ],
    stats: {},
  };
}

describe("buildForceGraph", () => {
  it("drops source nodes + their edges when showSources is false", () => {
    const { nodes, links } = buildForceGraph(graph(), false);
    expect(nodes.map((n) => n.id).sort()).toEqual(["p1", "t1"]);
    // The mention edge to the dropped item node is gone; only the entity edge remains.
    expect(links).toHaveLength(1);
    expect(links[0]).toMatchObject({ source: "p1", target: "t1", type: "cooccurrence" });
  });

  it("includes source nodes + mention edges when showSources is true", () => {
    const { nodes, links } = buildForceGraph(graph(), true);
    expect(nodes.map((n) => n.id)).toContain("item:i1");
    expect(nodes.map((n) => n.id)).toContain("chat:c1");
    expect(links).toHaveLength(3);
  });

  it("sizes nodes by degree and colors by kind", () => {
    const { nodes } = buildForceGraph(graph(), false);
    const anna = nodes.find((n) => n.id === "p1");
    expect(anna?.color).toBe("#e0823d"); // person
    expect(anna?.val).toBeCloseTo(1 + Math.log2(4)); // 1 + log2(degree + 1)
  });

  it("marks connected entities for persistent canvas labels", () => {
    const { nodes } = buildForceGraph(graph(), true);
    expect(nodes.find((n) => n.id === "p1")?.showLabel).toBe(true);
    expect(nodes.find((n) => n.id === "t1")?.showLabel).toBe(true);
    expect(nodes.find((n) => n.id === "item:i1")?.showLabel).toBe(false);
  });

  it("extracts source ids from graph source nodes", () => {
    expect(sourceRefFromGraphNode({ id: "item:i1", kind: "item" })).toEqual({
      sourceKind: "item",
      sourceId: "i1",
    });
    expect(sourceRefFromGraphNode({ id: "recording:r1", kind: "recording" })).toEqual({
      sourceKind: "recording",
      sourceId: "r1",
    });
    expect(sourceRefFromGraphNode({ id: "chat:c1", kind: "chat" })).toEqual({
      sourceKind: "chat",
      sourceId: "c1",
    });
    expect(sourceRefFromGraphNode({ id: "p1", kind: "person" })).toBeNull();
  });
});
