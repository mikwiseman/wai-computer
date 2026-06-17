import SwiftUI
import WaiComputerKit

struct MacSchemesView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacSchemesViewModel

    init(apiClient: APIClient) {
        _model = StateObject(wrappedValue: MacSchemesViewModel(apiClient: apiClient))
    }

    var body: some View {
        VStack(spacing: 0) {
            header

            WaiDivider()

            if let message = model.errorMessage {
                HStack(spacing: Spacing.sm) {
                    Image(systemName: "exclamationmark.triangle")
                        .foregroundStyle(Palette.recording)
                    Text(message)
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                    Spacer()
                    Button(t("Dismiss", "Скрыть")) {
                        model.errorMessage = nil
                    }
                    .buttonStyle(WaiGhostButtonStyle())
                }
                .padding(.horizontal, Spacing.lg)
                .padding(.vertical, Spacing.sm)
                .background(Palette.recording.opacity(0.08))

                WaiDivider()
            }

            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .task {
            await model.load()
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .firstTextBaseline, spacing: Spacing.md) {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(t("Schemes", "Схемы"))
                        .font(Typography.displaySmall)
                    Text(t(
                        "Decisions, projects, timelines, and open questions.",
                        "Решения, проекты, таймлайны и открытые вопросы."
                    ))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                }

                Spacer()

                if model.isLoading {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            HStack(spacing: Spacing.sm) {
                TextField(
                    t("Project, decision, timeline, or question", "Проект, решение, таймлайн или вопрос"),
                    text: $model.prompt
                )
                .textFieldStyle(.plain)
                .font(Typography.bodyLarge)
                .padding(Spacing.md)
                .background(Palette.surfaceSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .onSubmit {
                    Task { await model.create() }
                }
                .accessibilityIdentifier("schemes-prompt-field")

                Button {
                    Task { await model.create() }
                } label: {
                    Label(
                        model.isCreating ? t("Creating", "Создаем") : t("Create", "Создать"),
                        systemImage: "plus"
                    )
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isCreating)
                .accessibilityIdentifier("schemes-create-button")
            }
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    @ViewBuilder
    private var content: some View {
        if model.isLoading && model.schemes.isEmpty {
            ProgressView(t("Loading Schemes...", "Загружаем схемы..."))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if model.schemes.isEmpty {
            ContentUnavailableViewCompat(
                t("No Schemes Yet", "Схем пока нет"),
                systemImage: "square.grid.3x3",
                description: Text(t(
                    "Create a scheme from a prompt.",
                    "Создайте схему из запроса."
                ))
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            HStack(spacing: 0) {
                schemeList
                    .frame(width: 280)

                Palette.border
                    .frame(width: 1)

                detail
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    private var schemeList: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: Spacing.xs) {
                ForEach(model.schemes) { scheme in
                    Button {
                        Task { await model.select(scheme) }
                    } label: {
                        MacSchemeListRow(
                            scheme: scheme,
                            isSelected: model.selectedScheme?.id == scheme.id,
                            language: languageManager.current
                        )
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("scheme-row-\(scheme.id)")
                }
            }
            .padding(Spacing.md)
        }
        .background(Palette.surfaceSubtle.opacity(0.5))
    }

    @ViewBuilder
    private var detail: some View {
        if let scheme = model.selectedScheme {
            VStack(spacing: 0) {
                boardToolbar(scheme: scheme)
                WaiDivider()
                MacSchemeBoard(
                    projection: scheme.currentRevision?.projection,
                    layout: $model.layout,
                    language: languageManager.current,
                    onCommit: { layout in
                        Task {
                            await model.updateLayout(layout)
                        }
                    }
                )
                .id(scheme.id)
            }
        } else {
            ContentUnavailableViewCompat(
                t("Select a Scheme", "Выберите схему"),
                systemImage: "square.grid.3x3",
                description: Text(t(
                    "Choose a scheme from the list.",
                    "Выберите схему из списка."
                ))
            )
        }
    }

    private func boardToolbar(scheme: Scheme) -> some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(scheme.title)
                    .font(Typography.headingLarge)
                    .lineLimit(1)
                Text(scheme.currentRevision?.projection.summary ?? scheme.prompt)
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(2)
            }

            Spacer()

            Text(sourceText(scheme.currentRevision?.sourceCount ?? 0))
                .font(Typography.label)
                .foregroundStyle(Palette.textSecondary)

            Button {
                Task { await model.refreshSelected() }
            } label: {
                Label(t("Refresh", "Обновить"), systemImage: "arrow.clockwise")
            }
            .buttonStyle(.bordered)
            .disabled(model.isRefreshing)
            .accessibilityIdentifier("schemes-refresh-button")
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.md)
    }

    private func sourceText(_ count: Int) -> String {
        if languageManager.current == .russian {
            return "\(count) источн."
        }
        return "\(count) source\(count == 1 ? "" : "s")"
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct MacSchemeListRow: View {
    let scheme: Scheme
    let isSelected: Bool
    let language: LanguageManager.SupportedLanguage

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(scheme.title)
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(2)

            HStack(spacing: Spacing.xs) {
                Text(scheme.schemeType.replacingOccurrences(of: "_", with: " "))
                Text("/")
                Text(sourceText)
            }
            .font(Typography.caption)
            .foregroundStyle(Palette.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.md)
        .background(isSelected ? Palette.accentSubtle : Color.clear)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(isSelected ? Palette.accent.opacity(0.4) : Palette.border, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var sourceText: String {
        let count = scheme.currentRevision?.sourceCount ?? 0
        if language == .russian {
            return "\(count) источн."
        }
        return "\(count) source\(count == 1 ? "" : "s")"
    }
}

private enum MacSchemeTool: String, CaseIterable, Identifiable {
    case select
    case pan
    case draw
    case sticky
    case text
    case rectangle
    case ellipse
    case frame
    case connector

    var id: String { rawValue }

    func title(language: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .select:
            return OnboardingL10n.text("Select", "Выбор", language: language)
        case .pan:
            return OnboardingL10n.text("Hand", "Рука", language: language)
        case .draw:
            return OnboardingL10n.text("Draw", "Рисовать", language: language)
        case .sticky:
            return OnboardingL10n.text("Sticky", "Стикер", language: language)
        case .text:
            return OnboardingL10n.text("Text", "Текст", language: language)
        case .rectangle:
            return OnboardingL10n.text("Box", "Блок", language: language)
        case .ellipse:
            return OnboardingL10n.text("Oval", "Овал", language: language)
        case .frame:
            return OnboardingL10n.text("Frame", "Фрейм", language: language)
        case .connector:
            return OnboardingL10n.text("Connect", "Связь", language: language)
        }
    }

    var icon: String {
        switch self {
        case .select: return "cursorarrow"
        case .pan: return "hand.draw"
        case .draw: return "pencil.tip"
        case .sticky: return "note.text"
        case .text: return "textformat"
        case .rectangle: return "rectangle"
        case .ellipse: return "oval"
        case .frame: return "rectangle.dashed"
        case .connector: return "point.topleft.down.curvedto.point.bottomright.up"
        }
    }
}

private struct MacSchemeBoard: View {
    private struct ItemDragState {
        let id: String
        let origin: SchemePosition
    }

    private struct BoardHandle: Equatable {
        let id: String
    }

    private enum LayerAction {
        case front
        case forward
        case backward
        case back
    }

    let projection: SchemeProjection?
    @Binding var layout: SchemeCanvasLayout
    let language: LanguageManager.SupportedLanguage
    let onCommit: (SchemeCanvasLayout) -> Void

    @State private var tool: MacSchemeTool = .select
    @State private var panStart: SchemeViewport?
    @State private var nodeDrag: ItemDragState?
    @State private var cardDrag: ItemDragState?
    @State private var shapeDrag: ItemDragState?
    @State private var frameDrag: ItemDragState?
    @State private var textDrag: ItemDragState?
    @State private var draftStrokeId: String?
    @State private var selectedItemId: String?
    @State private var pendingConnector: BoardHandle?
    @State private var undoStack: [SchemeCanvasLayout] = []
    @State private var redoStack: [SchemeCanvasLayout] = []
    @State private var editingItemId: String?

    private let nodeWidth: CGFloat = 232
    private let nodeHeight: CGFloat = 132
    private let stickyWidth: Double = 220
    private let stickyHeight: Double = 150
    private let shapeWidth: Double = 220
    private let shapeHeight: Double = 130
    private let frameWidth: Double = 560
    private let frameHeight: Double = 360
    private let textWidth: Double = 260
    private let textHeight: Double = 120

    var body: some View {
        VStack(spacing: 0) {
            controls

            GeometryReader { proxy in
                ZStack(alignment: .topLeading) {
                    Canvas { context, size in
                        drawBoard(context: context, size: size)
                    }
                    .zIndex(0)

                    ForEach(layout.frames) { frame in
                        MacSchemeFrameView(frame: frame)
                            .frame(width: CGFloat(frame.width), height: CGFloat(frame.height))
                            .overlay(selectionOverlay(id: frame.id))
                            .position(screenPoint(for: frameCenter(frame), in: proxy.size))
                            .zIndex(layerZIndex(frame.zIndex))
                            .highPriorityGesture(frameGesture(for: frame))
                            .accessibilityIdentifier("scheme-frame-\(frame.id)")
                    }

                    ForEach(layout.texts) { text in
                        MacSchemeTextBlockView(text: text)
                            .frame(width: CGFloat(text.width), height: CGFloat(text.height))
                            .overlay(selectionOverlay(id: text.id))
                            .position(screenPoint(for: textCenter(text), in: proxy.size))
                            .zIndex(layerZIndex(text.zIndex))
                            .highPriorityGesture(textGesture(for: text))
                            .accessibilityIdentifier("scheme-text-\(text.id)")
                    }

                    ForEach(positionedNodes) { node in
                        MacSchemeNodeCard(node: node)
                            .frame(width: nodeWidth, height: nodeHeight)
                            .overlay(selectionOverlay(id: node.id))
                            .position(screenPoint(for: nodeCenter(node), in: proxy.size))
                            .zIndex(20)
                            .highPriorityGesture(nodeGesture(for: node))
                            .accessibilityIdentifier("scheme-node-\(node.id)")
                    }

                    ForEach(layout.cards) { card in
                        MacSchemeStickyCard(card: card)
                            .frame(width: CGFloat(card.width), height: CGFloat(card.height))
                            .overlay(selectionOverlay(id: card.id))
                            .position(screenPoint(for: cardCenter(card), in: proxy.size))
                            .zIndex(layerZIndex(card.zIndex))
                            .highPriorityGesture(cardGesture(for: card))
                            .accessibilityIdentifier("scheme-card-\(card.id)")
                    }

                    ForEach(layout.shapes) { shape in
                        MacSchemeShapeView(shape: shape)
                            .frame(
                                width: CGFloat(shape.width) * CGFloat(layout.viewport.zoom),
                                height: CGFloat(shape.height) * CGFloat(layout.viewport.zoom)
                            )
                            .overlay(selectionOverlay(id: shape.id))
                            .position(screenPoint(for: shapeCenter(shape), in: proxy.size))
                            .zIndex(layerZIndex(shape.zIndex))
                            .highPriorityGesture(shapeGesture(for: shape))
                            .accessibilityIdentifier("scheme-shape-\(shape.id)")
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(boardBackground)
                .contentShape(Rectangle())
                .gesture(boardGesture(size: proxy.size))
            }
        }
    }

    private var controls: some View {
        HStack(spacing: Spacing.sm) {
            ForEach(MacSchemeTool.allCases) { candidate in
                Button {
                    tool = candidate
                    pendingConnector = nil
                } label: {
                    Label(candidate.title(language: language), systemImage: candidate.icon)
                        .labelStyle(.iconOnly)
                        .frame(width: 30, height: 30)
                        .foregroundStyle(candidate == tool ? Palette.onAccent : Palette.accent)
                        .background(candidate == tool ? Palette.accent : Color.clear)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                .buttonStyle(.plain)
                .help(candidate.title(language: language))
            }

            Divider()
                .frame(height: 22)

            Button {
                undoLayout()
            } label: {
                Image(systemName: "arrow.uturn.backward")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .disabled(undoStack.isEmpty)
            .help(t("Undo", "Отменить"))

            Button {
                redoLayout()
            } label: {
                Image(systemName: "arrow.uturn.forward")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .disabled(redoStack.isEmpty)
            .help(t("Redo", "Повторить"))

            Button {
                duplicateSelected()
            } label: {
                Image(systemName: "square.on.square")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .disabled(!canDuplicateSelected)
            .help(t("Duplicate", "Дублировать"))

            Button {
                toggleSelectedLock()
            } label: {
                Image(systemName: isSelectedLocked ? "lock.open" : "lock")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .disabled(!canLockSelected)
            .help(isSelectedLocked ? t("Unlock", "Разблокировать") : t("Lock", "Заблокировать"))

            Button {
                arrangeSelected(.front)
            } label: {
                Image(systemName: "square.3.layers.3d.top.filled")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .disabled(!canArrangeSelected)
            .help(t("Bring to Front", "На передний план"))

            Button {
                arrangeSelected(.forward)
            } label: {
                Image(systemName: "square.2.layers.3d.top.filled")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .disabled(!canArrangeSelected)
            .help(t("Bring Forward", "Поднять на слой"))

            Button {
                arrangeSelected(.backward)
            } label: {
                Image(systemName: "square.2.layers.3d.bottom.filled")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .disabled(!canArrangeSelected)
            .help(t("Send Backward", "Опустить на слой"))

            Button {
                arrangeSelected(.back)
            } label: {
                Image(systemName: "square.3.layers.3d.bottom.filled")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .disabled(!canArrangeSelected)
            .help(t("Send to Back", "На задний план"))

            Divider()
                .frame(height: 22)

            Button {
                layout.viewport.zoom = max(0.25, layout.viewport.zoom - 0.12)
                onCommit(layout)
            } label: {
                Image(systemName: "minus.magnifyingglass")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .help(t("Zoom Out", "Отдалить"))

            Button {
                layout.viewport.zoom = min(2.8, layout.viewport.zoom + 0.12)
                onCommit(layout)
            } label: {
                Image(systemName: "plus.magnifyingglass")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .help(t("Zoom In", "Приблизить"))

            Button {
                layout.viewport = SchemeViewport()
                onCommit(layout)
            } label: {
                Image(systemName: "arrow.counterclockwise")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .help(t("Reset View", "Сбросить вид"))

            Button {
                deleteSelected()
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .disabled(!canDeleteSelected)
            .help(t("Delete", "Удалить"))

            if pendingConnector != nil {
                Text(t("Click another object to connect.", "Нажмите второй объект для связи."))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
            }

            if selectedCardId != nil {
                TextField(t("Sticky text", "Текст стикера"), text: selectedCardText)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 220)
                    .disabled(isSelectedLocked)
                    .onSubmit {
                        editingItemId = nil
                        onCommit(layout)
                    }

                Button {
                    editingItemId = nil
                    onCommit(layout)
                } label: {
                    Image(systemName: "checkmark")
                }
                .buttonStyle(WaiGhostButtonStyle())
                .help(t("Save Sticky", "Сохранить стикер"))
            }

            if selectedFrameId != nil {
                TextField(t("Frame title", "Название фрейма"), text: selectedFrameTitle)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 220)
                    .disabled(isSelectedLocked)
                    .onSubmit {
                        editingItemId = nil
                        onCommit(layout)
                    }

                Button {
                    editingItemId = nil
                    onCommit(layout)
                } label: {
                    Image(systemName: "checkmark")
                }
                .buttonStyle(WaiGhostButtonStyle())
                .help(t("Save Frame", "Сохранить фрейм"))
            }

            if selectedTextId != nil {
                TextField(t("Canvas text", "Текст на доске"), text: selectedTextValue)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 220)
                    .disabled(isSelectedLocked)
                    .onSubmit {
                        editingItemId = nil
                        onCommit(layout)
                    }

                Button {
                    editingItemId = nil
                    onCommit(layout)
                } label: {
                    Image(systemName: "checkmark")
                }
                .buttonStyle(WaiGhostButtonStyle())
                .help(t("Save Text", "Сохранить текст"))
            }

            Spacer()
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm)
        .background(Palette.surfaceSubtle)
    }

    private var boardBackground: some View {
        ZStack {
            Color(nsColor: .textBackgroundColor)
            Palette.surfaceSubtle.opacity(0.55)
        }
    }

    private var positionedNodes: [SchemeNode] {
        (projection?.nodes ?? []).map { node in
            guard let override = layout.nodePositions[node.id] else { return node }
            return SchemeNodeProxy.node(node, position: override)
        }
    }

    private var nodeById: [String: SchemeNode] {
        Dictionary(uniqueKeysWithValues: positionedNodes.map { ($0.id, $0) })
    }

    private var selectedCardId: String? {
        guard let selectedItemId,
              layout.cards.contains(where: { $0.id == selectedItemId })
        else { return nil }
        return selectedItemId
    }

    private var selectedFrameId: String? {
        guard let selectedItemId,
              layout.frames.contains(where: { $0.id == selectedItemId })
        else { return nil }
        return selectedItemId
    }

    private var selectedTextId: String? {
        guard let selectedItemId,
              layout.texts.contains(where: { $0.id == selectedItemId })
        else { return nil }
        return selectedItemId
    }

    private var canDeleteSelected: Bool {
        guard let selectedItemId else { return false }
        if isItemLocked(selectedItemId) { return false }
        return layout.cards.contains { $0.id == selectedItemId }
            || layout.shapes.contains { $0.id == selectedItemId }
            || layout.frames.contains { $0.id == selectedItemId }
            || layout.texts.contains { $0.id == selectedItemId }
            || layout.strokes.contains { $0.id == selectedItemId }
            || layout.connectors.contains { $0.id == selectedItemId }
    }

    private var canDuplicateSelected: Bool {
        guard let selectedItemId else { return false }
        if isItemLocked(selectedItemId) { return false }
        return layout.cards.contains { $0.id == selectedItemId }
            || layout.shapes.contains { $0.id == selectedItemId }
            || layout.frames.contains { $0.id == selectedItemId }
            || layout.texts.contains { $0.id == selectedItemId }
            || layout.strokes.contains { $0.id == selectedItemId }
    }

    private var canLockSelected: Bool {
        guard let selectedItemId else { return false }
        return layout.cards.contains { $0.id == selectedItemId }
            || layout.shapes.contains { $0.id == selectedItemId }
            || layout.frames.contains { $0.id == selectedItemId }
            || layout.texts.contains { $0.id == selectedItemId }
            || layout.strokes.contains { $0.id == selectedItemId }
            || layout.connectors.contains { $0.id == selectedItemId }
    }

    private var isSelectedLocked: Bool {
        guard let selectedItemId else { return false }
        return isItemLocked(selectedItemId)
    }

    private var canArrangeSelected: Bool {
        guard let selectedItemId, canLockSelected else { return false }
        return !isItemLocked(selectedItemId)
    }

    private var selectedCardText: Binding<String> {
        Binding(
            get: {
                guard let selectedCardId,
                      let card = layout.cards.first(where: { $0.id == selectedCardId })
                else { return "" }
                return card.text
            },
            set: { next in
                guard let selectedCardId,
                      let index = layout.cards.firstIndex(where: { $0.id == selectedCardId })
                else { return }
                guard !layout.cards[index].locked else { return }
                beginInlineEdit(selectedCardId)
                layout.cards[index].text = next
            }
        )
    }

    private var selectedFrameTitle: Binding<String> {
        Binding(
            get: {
                guard let selectedFrameId,
                      let frame = layout.frames.first(where: { $0.id == selectedFrameId })
                else { return "" }
                return frame.title
            },
            set: { next in
                guard let selectedFrameId,
                      let index = layout.frames.firstIndex(where: { $0.id == selectedFrameId })
                else { return }
                guard !layout.frames[index].locked else { return }
                beginInlineEdit(selectedFrameId)
                layout.frames[index].title = next
            }
        )
    }

    private var selectedTextValue: Binding<String> {
        Binding(
            get: {
                guard let selectedTextId,
                      let text = layout.texts.first(where: { $0.id == selectedTextId })
                else { return "" }
                return text.text
            },
            set: { next in
                guard let selectedTextId,
                      let index = layout.texts.firstIndex(where: { $0.id == selectedTextId })
                else { return }
                guard !layout.texts[index].locked else { return }
                beginInlineEdit(selectedTextId)
                layout.texts[index].text = next
            }
        )
    }

    private func pushUndoSnapshot() {
        if undoStack.last != layout {
            undoStack.append(layout)
            if undoStack.count > 80 {
                undoStack.removeFirst(undoStack.count - 80)
            }
        }
        redoStack.removeAll()
    }

    private func undoLayout() {
        guard let previous = undoStack.popLast() else { return }
        redoStack.append(layout)
        restoreLayout(previous)
    }

    private func redoLayout() {
        guard let next = redoStack.popLast() else { return }
        undoStack.append(layout)
        restoreLayout(next)
    }

    private func restoreLayout(_ nextLayout: SchemeCanvasLayout) {
        selectedItemId = nil
        pendingConnector = nil
        editingItemId = nil
        draftStrokeId = nil
        panStart = nil
        nodeDrag = nil
        cardDrag = nil
        shapeDrag = nil
        frameDrag = nil
        textDrag = nil
        layout = nextLayout
        onCommit(layout)
    }

    private func beginInlineEdit(_ itemId: String) {
        guard !isItemLocked(itemId) else { return }
        guard editingItemId != itemId else { return }
        pushUndoSnapshot()
        editingItemId = itemId
    }

    private func isItemLocked(_ id: String) -> Bool {
        layout.cards.contains { $0.id == id && $0.locked }
            || layout.shapes.contains { $0.id == id && $0.locked }
            || layout.frames.contains { $0.id == id && $0.locked }
            || layout.texts.contains { $0.id == id && $0.locked }
            || layout.strokes.contains { $0.id == id && $0.locked }
            || layout.connectors.contains { $0.id == id && $0.locked }
    }

    private func layerZIndex(_ zIndex: Int) -> Double {
        Double(10 + zIndex)
    }

    private func layoutLayerItems() -> [(id: String, zIndex: Int)] {
        layout.connectors.map { ($0.id, $0.zIndex) }
            + layout.strokes.map { ($0.id, $0.zIndex) }
            + layout.shapes.map { ($0.id, $0.zIndex) }
            + layout.frames.map { ($0.id, $0.zIndex) }
            + layout.texts.map { ($0.id, $0.zIndex) }
            + layout.cards.map { ($0.id, $0.zIndex) }
    }

    private func nextLayerIndex() -> Int {
        (layoutLayerItems().map(\.zIndex).max() ?? 0) + 1
    }

    private func normaliseLayerIndexes() {
        let highestExistingIndex = layoutLayerItems().map(\.zIndex).filter { $0 != 0 }.max() ?? 0
        var nextIndex = max(highestExistingIndex + 1, 1)
        for connector in layout.connectors.indices where layout.connectors[connector].zIndex == 0 {
            layout.connectors[connector].zIndex = nextIndex
            nextIndex += 1
        }
        for stroke in layout.strokes.indices where layout.strokes[stroke].zIndex == 0 {
            layout.strokes[stroke].zIndex = nextIndex
            nextIndex += 1
        }
        for shape in layout.shapes.indices where layout.shapes[shape].zIndex == 0 {
            layout.shapes[shape].zIndex = nextIndex
            nextIndex += 1
        }
        for frame in layout.frames.indices where layout.frames[frame].zIndex == 0 {
            layout.frames[frame].zIndex = nextIndex
            nextIndex += 1
        }
        for text in layout.texts.indices where layout.texts[text].zIndex == 0 {
            layout.texts[text].zIndex = nextIndex
            nextIndex += 1
        }
        for card in layout.cards.indices where layout.cards[card].zIndex == 0 {
            layout.cards[card].zIndex = nextIndex
            nextIndex += 1
        }
    }

    private func selectionOverlay(id: String) -> some View {
        RoundedRectangle(cornerRadius: 8)
            .stroke(selectedItemId == id ? Palette.accent : Color.clear, lineWidth: 2)
            .padding(-3)
    }

    private func boardGesture(size: CGSize) -> some Gesture {
        DragGesture(minimumDistance: tool == .draw ? 1 : 0)
            .onChanged { value in
                let world = worldPoint(for: value.location, in: size)
                switch tool {
                case .draw:
                    if let draftStrokeId {
                        appendPoint(world, toStroke: draftStrokeId)
                    } else {
                        pushUndoSnapshot()
                        let stroke = SchemeStroke(
                            id: "stroke:\(UUID().uuidString)",
                            points: [world, world],
                            zIndex: nextLayerIndex()
                        )
                        layout.strokes.append(stroke)
                        draftStrokeId = stroke.id
                        selectedItemId = stroke.id
                    }
                case .pan, .select:
                    if panStart == nil {
                        panStart = layout.viewport
                    }
                    let origin = panStart ?? layout.viewport
                    layout.viewport = SchemeViewport(
                        x: origin.x + Double(value.translation.width),
                        y: origin.y + Double(value.translation.height),
                        zoom: origin.zoom
                    )
                case .sticky, .text, .rectangle, .ellipse, .frame, .connector:
                    break
                }
            }
            .onEnded { value in
                let world = worldPoint(for: value.location, in: size)
                switch tool {
                case .sticky:
                    addCard(at: world)
                case .text:
                    addText(at: world)
                case .rectangle:
                    addShape(kind: "rectangle", at: world)
                case .ellipse:
                    addShape(kind: "ellipse", at: world)
                case .frame:
                    addFrame(at: world)
                case .draw:
                    draftStrokeId = nil
                    onCommit(layout)
                case .pan, .select:
                    panStart = nil
                    onCommit(layout)
                case .connector:
                    pendingConnector = nil
                }
            }
    }

    private func nodeGesture(for node: SchemeNode) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                if nodeDrag?.id != node.id {
                    pushUndoSnapshot()
                    nodeDrag = ItemDragState(id: node.id, origin: node.position)
                    selectedItemId = node.id
                }
                let origin = nodeDrag?.origin ?? node.position
                layout.nodePositions[node.id] = SchemePosition(
                    x: origin.x + Double(value.translation.width / CGFloat(layout.viewport.zoom)),
                    y: origin.y + Double(value.translation.height / CGFloat(layout.viewport.zoom))
                )
            }
            .onEnded { value in
                if tool == .connector {
                    handleConnectorTap(id: node.id)
                    return
                }
                guard tool == .select else { return }
                let origin = nodeDrag?.origin ?? node.position
                layout.nodePositions[node.id] = SchemePosition(
                    x: origin.x + Double(value.translation.width / CGFloat(layout.viewport.zoom)),
                    y: origin.y + Double(value.translation.height / CGFloat(layout.viewport.zoom))
                )
                selectedItemId = node.id
                nodeDrag = nil
                onCommit(layout)
            }
    }

    private func cardGesture(for card: SchemeCanvasCard) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                guard !card.locked else {
                    selectedItemId = card.id
                    return
                }
                if cardDrag?.id != card.id {
                    pushUndoSnapshot()
                    cardDrag = ItemDragState(id: card.id, origin: SchemePosition(x: card.x, y: card.y))
                    selectedItemId = card.id
                }
                let origin = cardDrag?.origin ?? SchemePosition(x: card.x, y: card.y)
                updateCard(card.id) {
                    $0.x = origin.x + Double(value.translation.width / CGFloat(layout.viewport.zoom))
                    $0.y = origin.y + Double(value.translation.height / CGFloat(layout.viewport.zoom))
                }
            }
            .onEnded { value in
                guard !card.locked else {
                    selectedItemId = card.id
                    cardDrag = nil
                    return
                }
                if tool == .connector {
                    handleConnectorTap(id: card.id)
                    return
                }
                guard tool == .select else { return }
                let origin = cardDrag?.origin ?? SchemePosition(x: card.x, y: card.y)
                updateCard(card.id) {
                    $0.x = origin.x + Double(value.translation.width / CGFloat(layout.viewport.zoom))
                    $0.y = origin.y + Double(value.translation.height / CGFloat(layout.viewport.zoom))
                }
                selectedItemId = card.id
                cardDrag = nil
                onCommit(layout)
            }
    }

    private func shapeGesture(for shape: SchemeCanvasShape) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                guard !shape.locked else {
                    selectedItemId = shape.id
                    return
                }
                if shapeDrag?.id != shape.id {
                    pushUndoSnapshot()
                    shapeDrag = ItemDragState(id: shape.id, origin: SchemePosition(x: shape.x, y: shape.y))
                    selectedItemId = shape.id
                }
                let origin = shapeDrag?.origin ?? SchemePosition(x: shape.x, y: shape.y)
                updateShape(shape.id) {
                    $0.x = origin.x + Double(value.translation.width / CGFloat(layout.viewport.zoom))
                    $0.y = origin.y + Double(value.translation.height / CGFloat(layout.viewport.zoom))
                }
            }
            .onEnded { value in
                guard !shape.locked else {
                    selectedItemId = shape.id
                    shapeDrag = nil
                    return
                }
                if tool == .connector {
                    handleConnectorTap(id: shape.id)
                    return
                }
                guard tool == .select else { return }
                let origin = shapeDrag?.origin ?? SchemePosition(x: shape.x, y: shape.y)
                updateShape(shape.id) {
                    $0.x = origin.x + Double(value.translation.width / CGFloat(layout.viewport.zoom))
                    $0.y = origin.y + Double(value.translation.height / CGFloat(layout.viewport.zoom))
                }
                selectedItemId = shape.id
                shapeDrag = nil
                onCommit(layout)
            }
    }

    private func frameGesture(for frame: SchemeCanvasFrame) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                guard !frame.locked else {
                    selectedItemId = frame.id
                    return
                }
                if frameDrag?.id != frame.id {
                    pushUndoSnapshot()
                    frameDrag = ItemDragState(id: frame.id, origin: SchemePosition(x: frame.x, y: frame.y))
                    selectedItemId = frame.id
                }
                let origin = frameDrag?.origin ?? SchemePosition(x: frame.x, y: frame.y)
                updateFrame(frame.id) {
                    $0.x = origin.x + Double(value.translation.width / CGFloat(layout.viewport.zoom))
                    $0.y = origin.y + Double(value.translation.height / CGFloat(layout.viewport.zoom))
                }
            }
            .onEnded { value in
                guard !frame.locked else {
                    selectedItemId = frame.id
                    frameDrag = nil
                    return
                }
                if tool == .connector {
                    handleConnectorTap(id: frame.id)
                    return
                }
                guard tool == .select else { return }
                let origin = frameDrag?.origin ?? SchemePosition(x: frame.x, y: frame.y)
                updateFrame(frame.id) {
                    $0.x = origin.x + Double(value.translation.width / CGFloat(layout.viewport.zoom))
                    $0.y = origin.y + Double(value.translation.height / CGFloat(layout.viewport.zoom))
                }
                selectedItemId = frame.id
                frameDrag = nil
                onCommit(layout)
            }
    }

    private func textGesture(for text: SchemeTextBlock) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                guard !text.locked else {
                    selectedItemId = text.id
                    return
                }
                if textDrag?.id != text.id {
                    pushUndoSnapshot()
                    textDrag = ItemDragState(id: text.id, origin: SchemePosition(x: text.x, y: text.y))
                    selectedItemId = text.id
                }
                let origin = textDrag?.origin ?? SchemePosition(x: text.x, y: text.y)
                updateText(text.id) {
                    $0.x = origin.x + Double(value.translation.width / CGFloat(layout.viewport.zoom))
                    $0.y = origin.y + Double(value.translation.height / CGFloat(layout.viewport.zoom))
                }
            }
            .onEnded { value in
                guard !text.locked else {
                    selectedItemId = text.id
                    textDrag = nil
                    return
                }
                if tool == .connector {
                    handleConnectorTap(id: text.id)
                    return
                }
                guard tool == .select else { return }
                let origin = textDrag?.origin ?? SchemePosition(x: text.x, y: text.y)
                updateText(text.id) {
                    $0.x = origin.x + Double(value.translation.width / CGFloat(layout.viewport.zoom))
                    $0.y = origin.y + Double(value.translation.height / CGFloat(layout.viewport.zoom))
                }
                selectedItemId = text.id
                textDrag = nil
                onCommit(layout)
            }
    }

    private func drawBoard(context: GraphicsContext, size: CGSize) {
        drawProjectionEdges(context: context, size: size)
        drawConnectors(context: context, size: size)
        drawStrokes(context: context, size: size)
    }

    private func drawProjectionEdges(context: GraphicsContext, size: CGSize) {
        var path = Path()
        for edge in projection?.edges ?? [] {
            guard let source = nodeById[edge.source],
                  let target = nodeById[edge.target]
            else { continue }
            path.move(to: screenPoint(for: nodeCenter(source), in: size))
            path.addLine(to: screenPoint(for: nodeCenter(target), in: size))
        }
        context.stroke(path, with: .color(Palette.border), lineWidth: 1.5)
    }

    private func drawConnectors(context: GraphicsContext, size: CGSize) {
        for connector in layout.connectors.sorted(by: { $0.zIndex < $1.zIndex }) {
            let points = connectorPoints(connector)
            guard points.count >= 2 else { continue }
            var path = Path()
            path.move(to: screenPoint(for: points[0], in: size))
            for point in points.dropFirst() {
                path.addLine(to: screenPoint(for: point, in: size))
            }
            context.stroke(
                path,
                with: .color(schemeColor(connector.color, defaultColor: Palette.textSecondary).opacity(connector.locked ? 0.45 : 1)),
                lineWidth: 2
            )
        }
    }

    private func drawStrokes(context: GraphicsContext, size: CGSize) {
        for stroke in layout.strokes.sorted(by: { $0.zIndex < $1.zIndex }) where stroke.points.count >= 2 {
            var path = Path()
            path.move(to: screenPoint(for: stroke.points[0], in: size))
            for point in stroke.points.dropFirst() {
                path.addLine(to: screenPoint(for: point, in: size))
            }
            context.stroke(
                path,
                with: .color(schemeColor(stroke.color, defaultColor: Palette.textPrimary).opacity(stroke.locked ? 0.45 : 1)),
                style: StrokeStyle(lineWidth: CGFloat(stroke.width) * CGFloat(layout.viewport.zoom), lineCap: .round, lineJoin: .round)
            )
        }
    }

    private func addCard(at point: SchemePosition) {
        pushUndoSnapshot()
        let card = SchemeCanvasCard(
            id: "card:\(UUID().uuidString)",
            x: point.x - stickyWidth / 2,
            y: point.y - stickyHeight / 2,
            width: stickyWidth,
            height: stickyHeight,
            text: t("Note", "Заметка"),
            zIndex: nextLayerIndex()
        )
        layout.cards.append(card)
        selectedItemId = card.id
        onCommit(layout)
    }

    private func addShape(kind: String, at point: SchemePosition) {
        pushUndoSnapshot()
        let shape = SchemeCanvasShape(
            id: "shape:\(UUID().uuidString)",
            kind: kind,
            x: point.x - shapeWidth / 2,
            y: point.y - shapeHeight / 2,
            width: shapeWidth,
            height: shapeHeight,
            color: kind == "ellipse" ? "#7c3aed" : "#2563eb",
            zIndex: nextLayerIndex()
        )
        layout.shapes.append(shape)
        selectedItemId = shape.id
        onCommit(layout)
    }

    private func addFrame(at point: SchemePosition) {
        pushUndoSnapshot()
        let frame = SchemeCanvasFrame(
            id: "frame:\(UUID().uuidString)",
            x: point.x - frameWidth / 2,
            y: point.y - frameHeight / 2,
            width: frameWidth,
            height: frameHeight,
            title: t("Frame", "Фрейм"),
            zIndex: nextLayerIndex()
        )
        layout.frames.append(frame)
        selectedItemId = frame.id
        onCommit(layout)
    }

    private func addText(at point: SchemePosition) {
        pushUndoSnapshot()
        let text = SchemeTextBlock(
            id: "text:\(UUID().uuidString)",
            x: point.x - textWidth / 2,
            y: point.y - textHeight / 2,
            width: textWidth,
            height: textHeight,
            text: t("Text", "Текст"),
            fontSize: 22,
            zIndex: nextLayerIndex()
        )
        layout.texts.append(text)
        selectedItemId = text.id
        onCommit(layout)
    }

    private func appendPoint(_ point: SchemePosition, toStroke strokeId: String) {
        guard let index = layout.strokes.firstIndex(where: { $0.id == strokeId }) else { return }
        layout.strokes[index].points.append(point)
    }

    private func handleConnectorTap(id: String) {
        selectedItemId = id
        guard !isItemLocked(id) else {
            pendingConnector = nil
            return
        }
        let handle = BoardHandle(id: id)
        if let pendingConnector {
            guard pendingConnector.id != handle.id else { return }
            pushUndoSnapshot()
            let connector = SchemeConnector(
                id: "connector:\(UUID().uuidString)",
                sourceId: pendingConnector.id,
                targetId: handle.id,
                zIndex: nextLayerIndex()
            )
            layout.connectors.append(connector)
            self.pendingConnector = nil
            selectedItemId = connector.id
            onCommit(layout)
        } else {
            pendingConnector = handle
        }
    }

    private func deleteSelected() {
        guard let selectedItemId, canDeleteSelected else { return }
        pushUndoSnapshot()
        layout.cards.removeAll { $0.id == selectedItemId }
        layout.shapes.removeAll { $0.id == selectedItemId }
        layout.frames.removeAll { $0.id == selectedItemId }
        layout.texts.removeAll { $0.id == selectedItemId }
        layout.strokes.removeAll { $0.id == selectedItemId }
        layout.connectors.removeAll {
            $0.id == selectedItemId || $0.sourceId == selectedItemId || $0.targetId == selectedItemId
        }
        self.selectedItemId = nil
        onCommit(layout)
    }

    private func toggleSelectedLock() {
        guard let selectedItemId, canLockSelected else { return }
        pushUndoSnapshot()
        let locked = !isItemLocked(selectedItemId)

        updateCard(selectedItemId) { $0.locked = locked }
        updateShape(selectedItemId) { $0.locked = locked }
        updateFrame(selectedItemId) { $0.locked = locked }
        updateText(selectedItemId) { $0.locked = locked }
        updateStroke(selectedItemId) { $0.locked = locked }
        updateConnector(selectedItemId) { $0.locked = locked }

        onCommit(layout)
    }

    private func arrangeSelected(_ action: LayerAction) {
        guard let selectedItemId, canArrangeSelected else { return }
        pushUndoSnapshot()
        normaliseLayerIndexes()

        let items = layoutLayerItems().sorted { $0.zIndex < $1.zIndex }
        guard let index = items.firstIndex(where: { $0.id == selectedItemId }) else { return }

        switch action {
        case .front:
            setItemZIndex(selectedItemId, zIndex: (items.last?.zIndex ?? 0) + 1)
        case .back:
            setItemZIndex(selectedItemId, zIndex: (items.first?.zIndex ?? 0) - 1)
        case .forward:
            let nextIndex = index + 1
            guard nextIndex < items.count else {
                onCommit(layout)
                return
            }
            let current = items[index]
            let next = items[nextIndex]
            setItemZIndex(current.id, zIndex: next.zIndex)
            setItemZIndex(next.id, zIndex: current.zIndex)
        case .backward:
            let previousIndex = index - 1
            guard previousIndex >= 0 else {
                onCommit(layout)
                return
            }
            let current = items[index]
            let previous = items[previousIndex]
            setItemZIndex(current.id, zIndex: previous.zIndex)
            setItemZIndex(previous.id, zIndex: current.zIndex)
        }

        onCommit(layout)
    }

    private func duplicateSelected() {
        guard let selectedItemId, canDuplicateSelected else { return }
        pushUndoSnapshot()
        let offset = 32.0

        if var card = layout.cards.first(where: { $0.id == selectedItemId }) {
            card.id = "card:\(UUID().uuidString)"
            card.x += offset
            card.y += offset
            card.zIndex = nextLayerIndex()
            layout.cards.append(card)
            self.selectedItemId = card.id
            onCommit(layout)
            return
        }

        if var shape = layout.shapes.first(where: { $0.id == selectedItemId }) {
            shape.id = "shape:\(UUID().uuidString)"
            shape.x += offset
            shape.y += offset
            shape.zIndex = nextLayerIndex()
            layout.shapes.append(shape)
            self.selectedItemId = shape.id
            onCommit(layout)
            return
        }

        if var frame = layout.frames.first(where: { $0.id == selectedItemId }) {
            frame.id = "frame:\(UUID().uuidString)"
            frame.x += offset
            frame.y += offset
            frame.zIndex = nextLayerIndex()
            layout.frames.append(frame)
            self.selectedItemId = frame.id
            onCommit(layout)
            return
        }

        if var text = layout.texts.first(where: { $0.id == selectedItemId }) {
            text.id = "text:\(UUID().uuidString)"
            text.x += offset
            text.y += offset
            text.zIndex = nextLayerIndex()
            layout.texts.append(text)
            self.selectedItemId = text.id
            onCommit(layout)
            return
        }

        if var stroke = layout.strokes.first(where: { $0.id == selectedItemId }) {
            stroke.id = "stroke:\(UUID().uuidString)"
            stroke.points = stroke.points.map { point in
                SchemePosition(x: point.x + offset, y: point.y + offset)
            }
            stroke.zIndex = nextLayerIndex()
            layout.strokes.append(stroke)
            self.selectedItemId = stroke.id
            onCommit(layout)
        }
    }

    private func updateCard(_ id: String, mutate: (inout SchemeCanvasCard) -> Void) {
        guard let index = layout.cards.firstIndex(where: { $0.id == id }) else { return }
        mutate(&layout.cards[index])
    }

    private func updateShape(_ id: String, mutate: (inout SchemeCanvasShape) -> Void) {
        guard let index = layout.shapes.firstIndex(where: { $0.id == id }) else { return }
        mutate(&layout.shapes[index])
    }

    private func updateFrame(_ id: String, mutate: (inout SchemeCanvasFrame) -> Void) {
        guard let index = layout.frames.firstIndex(where: { $0.id == id }) else { return }
        mutate(&layout.frames[index])
    }

    private func updateText(_ id: String, mutate: (inout SchemeTextBlock) -> Void) {
        guard let index = layout.texts.firstIndex(where: { $0.id == id }) else { return }
        mutate(&layout.texts[index])
    }

    private func updateStroke(_ id: String, mutate: (inout SchemeStroke) -> Void) {
        guard let index = layout.strokes.firstIndex(where: { $0.id == id }) else { return }
        mutate(&layout.strokes[index])
    }

    private func updateConnector(_ id: String, mutate: (inout SchemeConnector) -> Void) {
        guard let index = layout.connectors.firstIndex(where: { $0.id == id }) else { return }
        mutate(&layout.connectors[index])
    }

    private func setItemZIndex(_ id: String, zIndex: Int) {
        updateCard(id) { $0.zIndex = zIndex }
        updateShape(id) { $0.zIndex = zIndex }
        updateFrame(id) { $0.zIndex = zIndex }
        updateText(id) { $0.zIndex = zIndex }
        updateStroke(id) { $0.zIndex = zIndex }
        updateConnector(id) { $0.zIndex = zIndex }
    }

    private func nodeCenter(_ node: SchemeNode) -> SchemePosition {
        SchemePosition(
            x: node.position.x + Double(nodeWidth / 2),
            y: node.position.y + Double(nodeHeight / 2)
        )
    }

    private func cardCenter(_ card: SchemeCanvasCard) -> SchemePosition {
        SchemePosition(x: card.x + card.width / 2, y: card.y + card.height / 2)
    }

    private func shapeCenter(_ shape: SchemeCanvasShape) -> SchemePosition {
        SchemePosition(x: shape.x + shape.width / 2, y: shape.y + shape.height / 2)
    }

    private func frameCenter(_ frame: SchemeCanvasFrame) -> SchemePosition {
        SchemePosition(x: frame.x + frame.width / 2, y: frame.y + frame.height / 2)
    }

    private func textCenter(_ text: SchemeTextBlock) -> SchemePosition {
        SchemePosition(x: text.x + text.width / 2, y: text.y + text.height / 2)
    }

    private func connectorPoints(_ connector: SchemeConnector) -> [SchemePosition] {
        if let source = itemCenter(connector.sourceId),
           let target = itemCenter(connector.targetId) {
            return [source, target]
        }
        return connector.points
    }

    private func itemCenter(_ id: String?) -> SchemePosition? {
        guard let id else { return nil }
        if let node = nodeById[id] {
            return nodeCenter(node)
        }
        if let card = layout.cards.first(where: { $0.id == id }) {
            return cardCenter(card)
        }
        if let shape = layout.shapes.first(where: { $0.id == id }) {
            return shapeCenter(shape)
        }
        if let frame = layout.frames.first(where: { $0.id == id }) {
            return frameCenter(frame)
        }
        if let text = layout.texts.first(where: { $0.id == id }) {
            return textCenter(text)
        }
        return nil
    }

    private func screenPoint(for position: SchemePosition, in size: CGSize) -> CGPoint {
        CGPoint(
            x: (size.width / 2) + CGFloat(layout.viewport.x) + CGFloat(position.x) * CGFloat(layout.viewport.zoom),
            y: (size.height / 2) + CGFloat(layout.viewport.y) + CGFloat(position.y) * CGFloat(layout.viewport.zoom)
        )
    }

    private func worldPoint(for point: CGPoint, in size: CGSize) -> SchemePosition {
        SchemePosition(
            x: Double((point.x - size.width / 2 - CGFloat(layout.viewport.x)) / CGFloat(layout.viewport.zoom)),
            y: Double((point.y - size.height / 2 - CGFloat(layout.viewport.y)) / CGFloat(layout.viewport.zoom))
        )
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: language)
    }
}

private enum SchemeNodeProxy {
    static func node(_ source: SchemeNode, position: SchemePosition) -> SchemeNode {
        SchemeNode(
            id: source.id,
            kind: source.kind,
            title: source.title,
            body: source.body,
            lane: source.lane,
            citationIds: source.citationIds,
            position: position
        )
    }
}

private struct MacSchemeStickyCard: View {
    let card: SchemeCanvasCard

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Text(card.text)
                .font(Typography.bodySmall)
                .foregroundStyle(Color(nsColor: .labelColor))
                .lineLimit(6)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .padding(Spacing.md)

            if card.locked {
                Image(systemName: "lock.fill")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Palette.textSecondary)
                    .padding(Spacing.xs)
            }
        }
        .background(schemeColor(card.color, defaultColor: Color(red: 0.97, green: 0.84, blue: 0.45)))
        .opacity(card.locked ? 0.72 : 1)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(Color.black.opacity(0.12), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .shadow(color: Color.black.opacity(0.08), radius: 8, y: 3)
    }
}

private struct MacSchemeFrameView: View {
    let frame: SchemeCanvasFrame

    var body: some View {
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 8)
                .fill(frame.fill == "transparent" ? Color.clear : schemeColor(frame.fill, defaultColor: Color.clear))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(
                            schemeColor(frame.color, defaultColor: Palette.accent),
                            style: StrokeStyle(lineWidth: 2, dash: [8, 6])
                        )
                )

            Text(frame.title)
                .font(Typography.label)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(1)
                .padding(.horizontal, Spacing.sm)
                .padding(.vertical, Spacing.xs)
                .background(Color(nsColor: .textBackgroundColor).opacity(0.92))
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .padding(Spacing.sm)

            if frame.locked {
                Image(systemName: "lock.fill")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Palette.textSecondary)
                    .padding(Spacing.sm)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
            }
        }
        .opacity(frame.locked ? 0.72 : 1)
    }
}

private struct MacSchemeShapeView: View {
    let shape: SchemeCanvasShape

    var body: some View {
        ZStack(alignment: .topTrailing) {
            shapeBody

            if shape.locked {
                Image(systemName: "lock.fill")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Palette.textSecondary)
                    .padding(Spacing.xs)
            }
        }
        .opacity(shape.locked ? 0.72 : 1)
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private var shapeBody: some View {
        let strokeColor = schemeColor(shape.color, defaultColor: Palette.accent)
        let fillColor = shape.fill == "transparent" ? Color.clear : schemeColor(shape.fill, defaultColor: Color.clear)

        if shape.kind == "ellipse" {
            Ellipse()
                .fill(fillColor)
                .overlay(Ellipse().stroke(strokeColor, lineWidth: 2))
        } else {
            RoundedRectangle(cornerRadius: 8)
                .fill(fillColor)
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(strokeColor, lineWidth: 2))
        }
    }
}

private struct MacSchemeTextBlockView: View {
    let text: SchemeTextBlock

    var body: some View {
        Text(text.text)
            .font(.system(size: text.fontSize, weight: .regular, design: .default))
            .foregroundStyle(schemeColor(text.color, defaultColor: Palette.textPrimary))
            .lineLimit(6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding(Spacing.xs)
            .opacity(text.locked ? 0.72 : 1)
            .overlay(alignment: .topTrailing) {
                if text.locked {
                    Image(systemName: "lock.fill")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Palette.textSecondary)
                }
            }
    }
}

private struct MacSchemeNodeCard: View {
    let node: SchemeNode

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(node.kind.replacingOccurrences(of: "_", with: " "))
                .font(Typography.caption)
                .foregroundStyle(kindColor)
                .lineLimit(1)

            Text(node.title)
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(2)

            if let body = node.body, !body.isEmpty {
                Text(body)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(3)
            }

            Spacer(minLength: 0)
        }
        .padding(Spacing.md)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(.regularMaterial)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(kindColor.opacity(0.35), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .shadow(color: Color.black.opacity(0.08), radius: 8, y: 3)
    }

    private var kindColor: Color {
        switch node.kind {
        case "decision":
            return Palette.accent
        case "risk":
            return Palette.recording
        case "timeline", "milestone":
            return Color(nsColor: .systemBlue)
        case "question":
            return Color(nsColor: .systemPurple)
        default:
            return Palette.textTertiary
        }
    }
}

private func schemeColor(_ value: String, defaultColor: Color) -> Color {
    let hex = value.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
    guard hex.count == 6, let intValue = Int(hex, radix: 16) else {
        return defaultColor
    }
    let red = Double((intValue >> 16) & 0xFF) / 255
    let green = Double((intValue >> 8) & 0xFF) / 255
    let blue = Double(intValue & 0xFF) / 255
    return Color(red: red, green: green, blue: blue)
}
