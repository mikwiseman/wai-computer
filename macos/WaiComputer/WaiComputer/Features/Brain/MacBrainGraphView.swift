import SwiftUI
import WaiComputerKit

/// Obsidian-style knowledge graph drawn in a SwiftUI Canvas.
///
/// The layout is a Fruchterman–Reingold force simulation computed ONCE to a
/// settled state (deterministic — no live animation, so it can't diverge on
/// screen), then scaled to fit the view. Nodes are coloured by kind and sized
/// by degree; tap a node to open it. Heavy fan-out is capped to the top nodes
/// by degree so the O(n²) settle stays cheap.
struct MacBrainGraphView: View {
    let graph: BrainGraph
    var onSelect: (BrainGraphNode) -> Void

    @State private var layout: [String: CGPoint] = [:]

    private var renderNodes: [BrainGraphNode] {
        graph.nodes.filter { layout[$0.id] != nil }
    }

    var body: some View {
        GeometryReader { geo in
            let fitted = fit(layout, into: geo.size)
            Canvas { context, _ in
                for edge in graph.edges {
                    guard let a = fitted[edge.source], let b = fitted[edge.target] else { continue }
                    var path = Path()
                    path.move(to: a)
                    path.addLine(to: b)
                    context.stroke(
                        path,
                        with: .color(Color.gray.opacity(edge.type == "mention" ? 0.16 : 0.28)),
                        lineWidth: edge.type == "mention" ? 0.5 : 1.0
                    )
                }
                for node in renderNodes {
                    guard let p = fitted[node.id] else { continue }
                    let r = nodeRadius(node)
                    context.fill(
                        Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2)),
                        with: .color(nodeColor(node.kind))
                    )
                    if node.degree >= 2 {
                        context.draw(
                            Text(node.label)
                                .font(.system(size: 9))
                                .foregroundColor(Palette.textSecondary),
                            at: CGPoint(x: p.x, y: p.y + r + 7)
                        )
                    }
                }
            }
            .contentShape(Rectangle())
            .gesture(
                SpatialTapGesture().onEnded { value in
                    if let node = nearestNode(to: value.location, fitted: fitted) {
                        onSelect(node)
                    }
                }
            )
            .task(id: graph.nodes.count) {
                layout = Self.computeLayout(graph)
            }
        }
    }

    // MARK: - Rendering helpers

    private func nodeRadius(_ node: BrainGraphNode) -> CGFloat {
        4 + min(CGFloat(node.degree), 12) * 0.9
    }

    private func nodeColor(_ kind: String) -> Color {
        switch kind {
        case "person": return .blue
        case "topic": return Palette.accent
        case "project": return .orange
        case "recording": return .purple
        case "item": return .gray
        default: return .secondary
        }
    }

    private func nearestNode(to point: CGPoint, fitted: [String: CGPoint]) -> BrainGraphNode? {
        var best: BrainGraphNode?
        var bestDist = CGFloat.greatestFiniteMagnitude
        for node in renderNodes {
            guard let p = fitted[node.id] else { continue }
            let d = hypot(p.x - point.x, p.y - point.y)
            let hit = nodeRadius(node) + 10
            if d < hit && d < bestDist {
                bestDist = d
                best = node
            }
        }
        return best
    }

    /// Scale the abstract settled layout to fit `size` with padding, centred.
    private func fit(_ layout: [String: CGPoint], into size: CGSize) -> [String: CGPoint] {
        guard !layout.isEmpty, size.width > 0, size.height > 0 else { return [:] }
        let xs = layout.values.map(\.x)
        let ys = layout.values.map(\.y)
        let minX = xs.min() ?? 0, maxX = xs.max() ?? 1
        let minY = ys.min() ?? 0, maxY = ys.max() ?? 1
        let spanX = max(maxX - minX, 1), spanY = max(maxY - minY, 1)
        let pad: CGFloat = 40
        let availW = max(size.width - pad * 2, 1), availH = max(size.height - pad * 2, 1)
        let scale = min(availW / spanX, availH / spanY)
        let offX = pad + (availW - spanX * scale) / 2
        let offY = pad + (availH - spanY * scale) / 2
        var out: [String: CGPoint] = [:]
        out.reserveCapacity(layout.count)
        for (id, p) in layout {
            out[id] = CGPoint(x: offX + (p.x - minX) * scale, y: offY + (p.y - minY) * scale)
        }
        return out
    }

    // MARK: - Force layout (Fruchterman–Reingold, settled once)

    static func computeLayout(_ graph: BrainGraph) -> [String: CGPoint] {
        var nodes = graph.nodes
        guard !nodes.isEmpty else { return [:] }
        // Safety cap: settle only the most-connected nodes if the graph is huge.
        if nodes.count > 200 {
            nodes = Array(nodes.sorted { $0.degree > $1.degree }.prefix(200))
        }
        let n = nodes.count
        let index = Dictionary(uniqueKeysWithValues: nodes.enumerated().map { ($1.id, $0) })
        let edges: [(Int, Int)] = graph.edges.compactMap { e in
            guard let a = index[e.source], let b = index[e.target], a != b else { return nil }
            return (a, b)
        }

        let area = 1_000_000.0
        let k = (area / Double(n)).squareRoot()
        var px = [Double](repeating: 0, count: n)
        var py = [Double](repeating: 0, count: n)
        // Deterministic seeded spiral so no two nodes start coincident.
        for i in 0..<n {
            let angle = 2.0 * Double.pi * Double(i) / Double(n)
            let radius = 300.0 + Double(i % 11) * 13.0
            px[i] = cos(angle) * radius
            py[i] = sin(angle) * radius
        }

        let iterations = 300
        var temp = 120.0
        let cool = temp / Double(iterations + 1)
        var dx = [Double](repeating: 0, count: n)
        var dy = [Double](repeating: 0, count: n)

        for _ in 0..<iterations {
            for i in 0..<n { dx[i] = 0; dy[i] = 0 }
            // Repulsion (every pair pushes apart).
            for i in 0..<n {
                for j in (i + 1)..<n {
                    var ddx = px[i] - px[j]
                    var ddy = py[i] - py[j]
                    var dist = (ddx * ddx + ddy * ddy).squareRoot()
                    if dist < 0.01 {
                        // Coincident — nudge deterministically by index to break the tie.
                        ddx = Double((i % 3) - 1) + 0.01
                        ddy = Double((j % 3) - 1) + 0.01
                        dist = (ddx * ddx + ddy * ddy).squareRoot()
                    }
                    let force = (k * k) / dist
                    let ux = ddx / dist, uy = ddy / dist
                    dx[i] += ux * force; dy[i] += uy * force
                    dx[j] -= ux * force; dy[j] -= uy * force
                }
            }
            // Attraction along edges (connected nodes pull together).
            for (a, b) in edges {
                let ddx = px[a] - px[b]
                let ddy = py[a] - py[b]
                let dist = max((ddx * ddx + ddy * ddy).squareRoot(), 0.01)
                let force = (dist * dist) / k
                let ux = ddx / dist, uy = ddy / dist
                dx[a] -= ux * force; dy[a] -= uy * force
                dx[b] += ux * force; dy[b] += uy * force
            }
            // Apply, capped by the cooling temperature.
            for i in 0..<n {
                let len = max((dx[i] * dx[i] + dy[i] * dy[i]).squareRoot(), 0.01)
                let step = min(len, temp)
                px[i] += (dx[i] / len) * step
                py[i] += (dy[i] / len) * step
            }
            temp -= cool
        }

        var out: [String: CGPoint] = [:]
        out.reserveCapacity(n)
        for i in 0..<n {
            out[nodes[i].id] = CGPoint(x: px[i], y: py[i])
        }
        return out
    }
}
