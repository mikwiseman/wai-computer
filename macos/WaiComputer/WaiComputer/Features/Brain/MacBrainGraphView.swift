import SwiftUI
import WaiComputerKit

/// Obsidian-style knowledge graph drawn in a SwiftUI Canvas with real graph
/// controls and an inspector. Canvas stays responsible for the dense drawing;
/// the surrounding SwiftUI controls make the graph searchable, filterable, and
/// accessible as a list/detail surface.
struct MacBrainGraphView: View {
    let graph: BrainGraph
    var onOpenEntity: (BrainGraphNode) -> Void
    var onOpenSource: (InboxDetailRef) -> Void = { _ in }

    @EnvironmentObject private var languageManager: LanguageManager
    @State private var layout: [String: CGPoint] = [:]
    @State private var selectedNodeId: String?
    @State private var query = ""
    @State private var showSources = true
    @State private var minimumSharedSources = 1
    @State private var includedEntityKinds: Set<String> = [
        "person", "topic", "project", "organization"
    ]

    private var filters: MacBrainGraphFilters {
        MacBrainGraphFilters(
            query: query,
            showSources: showSources,
            includedEntityKinds: includedEntityKinds,
            minimumCooccurrenceWeight: minimumSharedSources
        )
    }

    private var presentation: MacBrainGraphPresentation {
        MacBrainGraphPresentation(
            graph: graph,
            filters: filters,
            selectedNodeId: selectedNodeId
        )
    }

    private var renderNodes: [BrainGraphNode] {
        presentation.visibleNodes.filter { layout[$0.id] != nil }
    }

    private var selectedDetails: MacBrainGraphNodeDetails? {
        guard let selectedNodeId else { return nil }
        return presentation.details(for: selectedNodeId)
    }

    var body: some View {
        VStack(spacing: 0) {
            graphToolbar
            Divider()
            HStack(spacing: 0) {
                graphCanvas
                Divider()
                inspector
            }
        }
        .onChange(of: presentation.layoutSignature) { _ in
            guard
                let selectedNodeId,
                !presentation.visibleNodes.contains(where: { $0.id == selectedNodeId })
            else { return }
            self.selectedNodeId = nil
        }
    }

    private var graphToolbar: some View {
        HStack(spacing: Spacing.md) {
            searchField
                .frame(width: 220)
            kindButton(kind: "person", label: t("People", "Люди"), systemImage: "person")
            kindButton(kind: "topic", label: t("Topics", "Темы"), systemImage: "tag")
            kindButton(kind: "project", label: t("Projects", "Проекты"), systemImage: "folder")
            Toggle(isOn: $showSources) {
                Label(t("Sources", "Источники"), systemImage: "doc.text")
                    .font(Typography.label)
            }
            .toggleStyle(.checkbox)
            Stepper(value: $minimumSharedSources, in: 1...10) {
                Text(t(
                    "Shared \(minimumSharedSources)+",
                    "\(minimumSharedSources)+ общих"
                ))
                .font(Typography.label)
                .foregroundStyle(Palette.textSecondary)
            }
            .frame(width: 136)
            Spacer()
            Text(summaryText)
                .font(Typography.label)
                .foregroundStyle(Palette.textTertiary)
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm)
    }

    private var searchField: some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 11))
                .foregroundStyle(Palette.textTertiary)
            TextField(t("Search graph", "Поиск по графу"), text: $query)
                .textFieldStyle(.plain)
                .font(Typography.bodySmall)
            if !query.isEmpty {
                Button {
                    query = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 12))
                }
                .buttonStyle(.plain)
                .foregroundStyle(Palette.textTertiary)
                .accessibilityLabel(t("Clear search", "Очистить поиск"))
            }
        }
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, 6)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 7))
    }

    private func kindButton(kind: String, label: String, systemImage: String) -> some View {
        let isOn = includedEntityKinds.contains(kind)
        return Button {
            if isOn {
                includedEntityKinds.remove(kind)
            } else {
                includedEntityKinds.insert(kind)
            }
        } label: {
            Label(label, systemImage: systemImage)
                .font(Typography.label)
                .foregroundStyle(isOn ? Palette.textPrimary : Palette.textSecondary)
                .padding(.horizontal, Spacing.sm)
                .padding(.vertical, 5)
                .background(isOn ? Palette.accentSubtle : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 7))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    @ViewBuilder
    private var graphCanvas: some View {
        if presentation.visibleNodes.isEmpty {
            ContentUnavailableViewCompat(
                t("No matching graph", "Нет совпадений в графе"),
                systemImage: "point.3.connected.trianglepath.dotted",
                description: Text(t(
                    "No people, topics, projects or sources match the current filters.",
                    "Люди, темы, проекты и источники не совпадают с текущими фильтрами."
                ))
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            GeometryReader { geo in
                let fitted = fit(layout, into: geo.size)
                ZStack(alignment: .topLeading) {
                    Canvas { context, _ in
                        drawEdges(context: &context, fitted: fitted)
                        drawNodes(context: &context, fitted: fitted)
                    }
                    .contentShape(Rectangle())
                    .gesture(
                        SpatialTapGesture().onEnded { value in
                            if let node = nearestNode(to: value.location, fitted: fitted) {
                                selectedNodeId = node.id
                            }
                        }
                    )
                    legend
                        .padding(Spacing.md)
                }
                .task(id: presentation.layoutSignature) {
                    layout = Self.computeLayout(
                        nodes: presentation.visibleNodes,
                        edges: presentation.visibleEdges
                    )
                }
            }
        }
    }

    private func drawEdges(context: inout GraphicsContext, fitted: [String: CGPoint]) {
        for edge in presentation.visibleEdges {
            guard let a = fitted[edge.source], let b = fitted[edge.target] else { continue }
            let highlighted = presentation.isHighlighted(edge: edge)
            var path = Path()
            path.move(to: a)
            path.addLine(to: b)
            context.stroke(
                path,
                with: .color(edgeColor(edge, highlighted: highlighted)),
                lineWidth: edgeLineWidth(edge, highlighted: highlighted)
            )
        }
    }

    private func drawNodes(context: inout GraphicsContext, fitted: [String: CGPoint]) {
        for node in renderNodes {
            guard let p = fitted[node.id] else { continue }
            let r = nodeRadius(node)
            let highlighted = presentation.isHighlighted(nodeId: node.id)
            let selected = selectedNodeId == node.id
            let shape = nodePath(node: node, center: p, radius: r)
            context.fill(shape, with: .color(nodeColor(node.kind).opacity(highlighted ? 1.0 : 0.28)))
            if selected {
                context.stroke(shape, with: .color(Palette.textPrimary.opacity(0.86)), lineWidth: 2)
            } else if highlighted && selectedNodeId != nil {
                context.stroke(shape, with: .color(nodeColor(node.kind).opacity(0.55)), lineWidth: 1)
            }
            if shouldShowLabel(node, highlighted: highlighted) {
                context.draw(
                    Text(node.label)
                        .font(.system(size: selected ? 11 : 10, weight: selected ? .semibold : .regular))
                        .foregroundColor(highlighted ? Palette.textPrimary : Palette.textSecondary),
                    at: CGPoint(x: p.x, y: p.y + r + 9)
                )
            }
        }
    }

    private var inspector: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            if let selectedDetails {
                nodeInspector(selectedDetails)
            } else {
                overviewInspector
            }
            Spacer(minLength: 0)
        }
        .frame(width: 304, alignment: .topLeading)
        .padding(Spacing.lg)
        .background(Color.primary.opacity(0.025))
    }

    private var overviewInspector: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Text(t("Overview", "Обзор"))
                .font(Typography.headingSmall)
            metricGrid(summary: presentation.summary)
            if !presentation.topEntityNodes.isEmpty {
                Divider()
                Text(t("Most connected", "Самые связанные"))
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)
                VStack(alignment: .leading, spacing: 1) {
                    ForEach(presentation.topEntityNodes) { node in
                        inspectorNodeButton(node, trailing: "\(node.degree)")
                    }
                }
            }
        }
    }

    private func nodeInspector(_ details: MacBrainGraphNodeDetails) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .top, spacing: Spacing.sm) {
                Circle()
                    .fill(nodeColor(details.node.kind))
                    .frame(width: 10, height: 10)
                    .padding(.top, 5)
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(details.node.label)
                        .font(Typography.headingMedium)
                        .lineLimit(3)
                    Text(kindLabel(details.node.kind))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                }
            }

            if MacBrainGraphPresentation.isEntity(details.node.kind) {
                Button {
                    onOpenEntity(details.node)
                } label: {
                    Label(t("Open Wiki", "Открыть вики"), systemImage: "doc.text.magnifyingglass")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            }

            if let source = sourceDetail(for: details.node) {
                Button {
                    onOpenSource(source)
                } label: {
                    Label(t("Open source", "Открыть источник"), systemImage: "arrow.up.right.square")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            }

            metricGrid(summary: MacBrainGraphSummary(
                entities: details.entityNeighbors.count,
                sources: details.sourceNeighbors.count,
                links: details.entityNeighbors.count + details.sourceNeighbors.count,
                people: details.entityNeighbors.filter { $0.node.kind == "person" }.count,
                topics: details.entityNeighbors.filter { $0.node.kind == "topic" }.count,
                projects: details.entityNeighbors.filter { $0.node.kind == "project" }.count
            ))

            if !details.entityNeighbors.isEmpty {
                neighborSection(
                    title: MacBrainGraphPresentation.isSource(details.node.kind)
                        ? t("Entities", "Сущности")
                        : t("Related", "Связанные"),
                    neighbors: details.entityNeighbors
                )
            }

            if !details.sourceNeighbors.isEmpty {
                neighborSection(
                    title: t("Sources", "Источники"),
                    neighbors: details.sourceNeighbors
                )
            }
        }
    }

    private func neighborSection(
        title: String,
        neighbors: [MacBrainGraphNeighbor]
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Divider()
            Text(title)
                .font(Typography.label)
                .foregroundStyle(Palette.textSecondary)
            VStack(alignment: .leading, spacing: 1) {
                ForEach(neighbors.prefix(10)) { neighbor in
                    inspectorNodeButton(
                        neighbor.node,
                        trailing: neighbor.edge.type == "cooccurrence"
                            ? "\(neighbor.sharedCount)"
                            : kindLabel(neighbor.node.kind)
                    )
                }
            }
        }
    }

    private func inspectorNodeButton(_ node: BrainGraphNode, trailing: String) -> some View {
        Button {
            selectedNodeId = node.id
        } label: {
            HStack(spacing: Spacing.xs) {
                Image(systemName: entityIcon(node.kind))
                    .font(.system(size: 10))
                    .foregroundStyle(nodeColor(node.kind))
                    .frame(width: 14)
                Text(node.label)
                    .font(Typography.bodySmall)
                    .lineLimit(1)
                Spacer(minLength: Spacing.sm)
                Text(trailing)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
            .padding(.vertical, 5)
            .padding(.horizontal, Spacing.xs)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func sourceDetail(for node: BrainGraphNode) -> InboxDetailRef? {
        guard node.kind == "recording" || node.kind == "item",
              let sourceKind = InboxSourceKind(rawValue: node.kind)
        else { return nil }
        let prefix = "\(node.kind):"
        let sourceId = node.id.hasPrefix(prefix) ? String(node.id.dropFirst(prefix.count)) : node.id
        return InboxDetailRef(kind: sourceKind, id: sourceId)
    }

    private func metricGrid(summary: MacBrainGraphSummary) -> some View {
        VStack(spacing: Spacing.xs) {
            HStack {
                metric(t("Entities", "Сущности"), "\(summary.entities)")
                metric(t("Sources", "Источники"), "\(summary.sources)")
            }
            HStack {
                metric(t("Links", "Связи"), "\(summary.links)")
                metric(t("Topics", "Темы"), "\(summary.topics)")
            }
        }
    }

    private func metric(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(value)
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textPrimary)
            Text(label)
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.sm)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 7))
    }

    private var legend: some View {
        HStack(spacing: Spacing.sm) {
            legendItem(color: .blue, label: t("People", "Люди"))
            legendItem(color: Palette.accent, label: t("Topics", "Темы"))
            legendItem(color: .orange, label: t("Projects", "Проекты"))
            if showSources {
                legendItem(color: .gray, label: t("Sources", "Источники"))
            }
        }
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, 6)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func legendItem(color: Color, label: String) -> some View {
        HStack(spacing: 5) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(label)
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textSecondary)
        }
    }

    // MARK: - Rendering helpers

    private func nodeRadius(_ node: BrainGraphNode) -> CGFloat {
        let base: CGFloat = MacBrainGraphPresentation.isSource(node.kind) ? 4 : 5
        return base + min(CGFloat(node.degree), 12) * 0.9
    }

    private func nodePath(node: BrainGraphNode, center: CGPoint, radius: CGFloat) -> Path {
        let rect = CGRect(
            x: center.x - radius,
            y: center.y - radius,
            width: radius * 2,
            height: radius * 2
        )
        if MacBrainGraphPresentation.isSource(node.kind) {
            return Path(roundedRect: rect, cornerRadius: 3)
        }
        return Path(ellipseIn: rect)
    }

    private func shouldShowLabel(_ node: BrainGraphNode, highlighted: Bool) -> Bool {
        guard highlighted else { return false }
        if selectedNodeId == node.id { return true }
        if !filters.normalizedQuery.isEmpty { return true }
        if presentation.visibleNodes.count <= 36 { return MacBrainGraphPresentation.isEntity(node.kind) }
        return node.degree >= 2 && MacBrainGraphPresentation.isEntity(node.kind)
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

    private func edgeColor(_ edge: BrainGraphEdge, highlighted: Bool) -> Color {
        let base = edge.type == "mention" ? Color.gray : Palette.textSecondary
        if selectedNodeId == nil {
            return base.opacity(edge.type == "mention" ? 0.18 : 0.30)
        }
        return base.opacity(highlighted ? (edge.type == "mention" ? 0.34 : 0.52) : 0.055)
    }

    private func edgeLineWidth(_ edge: BrainGraphEdge, highlighted: Bool) -> CGFloat {
        let base = edge.type == "mention" ? 0.6 : 0.9 + min(CGFloat(edge.weight), 4) * 0.35
        return highlighted ? base + 0.45 : base
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

    private var summaryText: String {
        let summary = presentation.summary
        return t(
            "\(summary.entities) entities · \(summary.sources) sources · \(summary.links) links",
            "\(summary.entities) сущн. · \(summary.sources) источн. · \(summary.links) связей"
        )
    }

    private func kindLabel(_ kind: String) -> String {
        switch kind {
        case "person": return t("Person", "Человек")
        case "topic": return t("Topic", "Тема")
        case "project": return t("Project", "Проект")
        case "organization": return t("Organization", "Организация")
        case "item": return t("Material", "Материал")
        case "recording": return t("Recording", "Запись")
        default: return kind.capitalized
        }
    }

    private func entityIcon(_ type: String) -> String {
        switch type {
        case "person": return "person"
        case "project": return "folder"
        case "organization": return "building.2"
        case "recording": return "waveform"
        case "item": return "doc.text"
        default: return "tag"
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    // MARK: - Force layout (Fruchterman–Reingold, settled once)

    static func computeLayout(
        nodes inputNodes: [BrainGraphNode],
        edges inputEdges: [BrainGraphEdge]
    ) -> [String: CGPoint] {
        var nodes = inputNodes
        guard !nodes.isEmpty else { return [:] }
        // Safety cap: settle only the most-connected nodes if the graph is huge.
        if nodes.count > 200 {
            nodes = Array(nodes.sorted { $0.degree > $1.degree }.prefix(200))
        }
        let n = nodes.count
        let index = Dictionary(uniqueKeysWithValues: nodes.enumerated().map { ($1.id, $0) })
        let edges: [(Int, Int)] = inputEdges.compactMap { e in
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
