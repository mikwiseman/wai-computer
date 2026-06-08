import SwiftUI
import WaiComputerKit

/// An inline node-graph of a Brain map projection (lens / source / entity / gap
/// cards joined by curved edges). A faithful port of the macOS
/// `MacBrainMapCanvasView` — pure SwiftUI `Canvas` + `.position`, so it is fully
/// cross-platform. Openable nodes push the relevant detail instead of invoking
/// the macOS Inbox open-source closures.
struct BrainMapCanvasView: View {
    let projection: BrainMapProjection
    let apiClient: APIClient
    var layout: [String: BrainMapPosition]? = nil
    let compact: Bool

    private var maxSources: Int { compact ? 2 : 3 }
    private var maxEntities: Int { compact ? 5 : 8 }
    private var maxGaps: Int { compact ? 0 : 1 }

    private var displayNodes: [BrainMapNode] {
        let lens = projection.nodes.filter { $0.kind == "lens" }.prefix(1)
        let sources = projection.nodes.filter { $0.kind == "source" }.prefix(maxSources)
        let entities = projection.nodes
            .filter { $0.kind == "entity" }
            .sorted {
                if $0.citationIds.count != $1.citationIds.count {
                    return $0.citationIds.count > $1.citationIds.count
                }
                return $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending
            }
            .prefix(maxEntities)
        let gaps = projection.nodes.filter { $0.kind == "gap" }.prefix(maxGaps)
        return Array(lens) + Array(sources) + Array(entities) + Array(gaps)
    }

    private var displayNodeIds: Set<String> { Set(displayNodes.map(\.id)) }

    private var displayEdges: [BrainMapEdge] {
        projection.edges
            .filter { displayNodeIds.contains($0.source) && displayNodeIds.contains($0.target) }
            .prefix(18)
            .map { $0 }
    }

    var body: some View {
        GeometryReader { geometry in
            let positions = fittedPositions(in: geometry.size)
            ZStack {
                Canvas { context, _ in
                    for edge in displayEdges {
                        guard let source = positions[edge.source], let target = positions[edge.target] else { continue }
                        var path = Path()
                        path.move(to: source)
                        path.addCurve(
                            to: target,
                            control1: CGPoint(x: source.x + 90, y: source.y),
                            control2: CGPoint(x: target.x - 90, y: target.y)
                        )
                        context.stroke(
                            path,
                            with: .color(edgeColor(edge).opacity(0.58)),
                            lineWidth: edge.kind == "supports" ? 1.8 : 1.2
                        )
                    }
                }

                ForEach(displayNodes) { node in
                    if let position = positions[node.id] {
                        nodeButton(node)
                            .position(position)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.035)))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Palette.border, lineWidth: 1))
        }
    }

    @ViewBuilder
    private func nodeButton(_ node: BrainMapNode) -> some View {
        if node.kind == "source", node.sourceKind == "recording", let id = node.sourceId {
            NavigationLink { RecordingDetailView(recording: Recording(id: id, type: .meeting, createdAt: Date())) } label: { nodeCard(node) }.buttonStyle(.plain)
        } else if node.kind == "source", node.sourceKind == "item", let id = node.sourceId {
            NavigationLink { ItemDetailView(itemId: id, apiClient: apiClient) {} } label: { nodeCard(node) }.buttonStyle(.plain)
        } else if node.kind == "entity", let id = node.entityId {
            NavigationLink { EntityPageView(entityId: id, name: node.title, apiClient: apiClient) } label: { nodeCard(node) }.buttonStyle(.plain)
        } else {
            nodeCard(node)
        }
    }

    private func nodeCard(_ node: BrainMapNode) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 5) {
                Circle().fill(nodeColor(node.kind)).frame(width: 7, height: 7)
                Text(node.kind.replacingOccurrences(of: "_", with: " ").uppercased())
                    .font(.system(size: compact ? 8 : 9, weight: .semibold))
                    .foregroundStyle(Palette.textTertiary)
            }
            Text(node.title)
                .font(compact ? Typography.labelSmall.weight(.semibold) : Typography.bodySmall.weight(.semibold))
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(compact ? 1 : (node.kind == "lens" ? 2 : 1))
                .truncationMode(.tail)
            if !compact, let body = node.body, !body.isEmpty {
                Text(body).font(Typography.labelSmall).foregroundStyle(Palette.textSecondary)
                    .lineLimit(node.kind == "lens" ? 2 : 1)
            }
            if !compact, !node.citationIds.isEmpty {
                Text("\(node.citationIds.count) source\(node.citationIds.count == 1 ? "" : "s")")
                    .font(.system(size: 10, weight: .medium)).foregroundStyle(Palette.accent)
            }
        }
        .frame(width: node.kind == "lens" ? (compact ? 190 : 210) : (compact ? 142 : 164), alignment: .leading)
        .frame(minHeight: node.kind == "lens" ? (compact ? 58 : 76) : (compact ? 50 : 64), alignment: .leading)
        .padding(compact ? Spacing.xs : Spacing.sm)
        .background(node.kind == "lens" ? Palette.accentSubtle : Palette.surfaceSubtle)
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(nodeColor(node.kind).opacity(0.24), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .shadow(color: .black.opacity(0.06), radius: 10, x: 0, y: 5)
    }

    // MARK: - Layout (ported from MacBrainMapCanvasView)

    private func fittedPositions(in size: CGSize) -> [String: CGPoint] {
        let nodes = displayNodes
        guard !nodes.isEmpty else { return [:] }
        if !compact, nodes.count <= 6 {
            return fittedPositionsFromSuppliedLayout(in: size)
        }

        let width = max(size.width, compact ? 720 : 760)
        let topY: CGFloat = compact ? 50 : 74
        let rowY: [CGFloat] = compact ? [132, 214, 286] : [170, 260, 350, 440]
        var positions: [String: CGPoint] = [:]
        let lens = nodes.first { $0.kind == "lens" }
        if let lens {
            positions[lens.id] = CGPoint(x: width * 0.50, y: topY)
        }

        let sources = nodes.filter { $0.kind == "source" }
        for (index, node) in sources.enumerated() {
            positions[node.id] = CGPoint(x: width * 0.18, y: rowY[min(index, rowY.count - 1)])
        }

        let entities = nodes.filter { $0.kind == "entity" }
        let entityXs = compact ? [width * 0.44, width * 0.70] : [width * 0.42, width * 0.64]
        for (index, node) in entities.enumerated() {
            positions[node.id] = CGPoint(
                x: entityXs[index % entityXs.count],
                y: rowY[min(index / entityXs.count, rowY.count - 1)]
            )
        }

        let gaps = nodes.filter { $0.kind == "gap" }
        for (index, node) in gaps.enumerated() {
            positions[node.id] = CGPoint(x: width * 0.84, y: rowY[min(index + 1, rowY.count - 1)])
        }

        return positions.mapValues { point in
            let horizontalInset: CGFloat = compact ? 76 : 96
            let verticalInset: CGFloat = compact ? 40 : 64
            return CGPoint(
                x: min(max(point.x, horizontalInset), max(horizontalInset, size.width - horizontalInset)),
                y: min(max(point.y, verticalInset), max(verticalInset, size.height - verticalInset))
            )
        }
    }

    private func fittedPositionsFromSuppliedLayout(in size: CGSize) -> [String: CGPoint] {
        let raw = rawPositions()
        guard !raw.isEmpty else { return [:] }
        let minX = raw.values.map(\.x).min() ?? 0
        let maxX = raw.values.map(\.x).max() ?? minX
        let minY = raw.values.map(\.y).min() ?? 0
        let maxY = raw.values.map(\.y).max() ?? minY
        let width = max(1, maxX - minX)
        let height = max(1, maxY - minY)
        let availableWidth = max(1, size.width - 240)
        let availableHeight = max(1, size.height - 140)
        let scale = min(1.0, availableWidth / width, availableHeight / height)
        let centerX = minX + width / 2
        let centerY = minY + height / 2
        return raw.mapValues { point in
            CGPoint(
                x: (point.x - centerX) * scale + size.width / 2,
                y: (point.y - centerY) * scale + size.height / 2
            )
        }
    }

    private func rawPositions() -> [String: CGPoint] {
        var laneCounts: [String: Int] = [:]
        return Dictionary(uniqueKeysWithValues: displayNodes.enumerated().map { index, node in
            if displayNodes.count <= 6 {
                if let persisted = layout?[node.id] {
                    return (node.id, CGPoint(x: persisted.x, y: persisted.y))
                }
                if let supplied = node.position {
                    return (node.id, CGPoint(x: supplied.x, y: supplied.y))
                }
            }
            let lane = node.lane ?? "center"
            let laneIndex = laneCounts[lane, default: 0]
            laneCounts[lane] = laneIndex + 1
            let x: CGFloat
            switch lane {
            case "sources": x = -360
            case "related": x = 360
            default: x = node.kind == "lens" ? 0 : CGFloat((index % 3) - 1) * 220
            }
            let y = node.kind == "lens" ? 0 : CGFloat(-170 + laneIndex * 130)
            return (node.id, CGPoint(x: x, y: y))
        })
    }

    private func nodeColor(_ kind: String) -> Color {
        switch kind {
        case "lens": return Palette.accent
        case "source": return .blue
        case "entity": return .green
        case "gap": return .orange
        default: return Palette.textTertiary
        }
    }

    private func edgeColor(_ edge: BrainMapEdge) -> Color {
        switch edge.kind {
        case "mentions": return Palette.accent
        case "related_to": return Palette.textTertiary
        default: return Palette.textSecondary
        }
    }
}
