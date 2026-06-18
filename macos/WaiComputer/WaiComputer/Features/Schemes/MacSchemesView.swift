import AppKit
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
    case lasso
    case draw
    case highlighter
    case eraser
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
        case .lasso:
            return OnboardingL10n.text("Lasso", "Лассо", language: language)
        case .draw:
            return OnboardingL10n.text("Pen", "Перо", language: language)
        case .highlighter:
            return OnboardingL10n.text("Highlight", "Маркер", language: language)
        case .eraser:
            return OnboardingL10n.text("Erase", "Ластик", language: language)
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
        case .lasso: return "lasso"
        case .draw: return "pencil.tip"
        case .highlighter: return "highlighter"
        case .eraser: return "eraser"
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

    private struct MultiItemDragState {
        let id: String
        let origin: SchemeCanvasLayout
        let itemIds: [String]
    }

    private struct ResizeDragState {
        let id: String
        let kind: ResizableItemKind
        let handle: ResizeHandle
        let origin: SchemeCanvasLayout
    }

    private struct BoardHandle: Equatable {
        let id: String
    }

    private struct ProjectionSourceSummary: Equatable {
        let id: String
        let sourceKind: String
        let sourceId: String
        let title: String
        let kind: String?
        let createdAt: String?
    }

    private enum LayerAction {
        case front
        case forward
        case backward
        case back
    }

    private enum ResizeHandle: String, CaseIterable, Identifiable {
        case nw
        case ne
        case sw
        case se

        var id: String { rawValue }
        var isWest: Bool { self == .nw || self == .sw }
        var isNorth: Bool { self == .nw || self == .ne }
    }

    private enum ResizableItemKind {
        case card
        case shape
        case frame
        case text
        case source
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
    @State private var sourceDrag: ItemDragState?
    @State private var resizeDrag: ResizeDragState?
    @State private var draftStrokeId: String?
    @State private var eraserDidPushUndo = false
    @State private var selectedItemId: String?
    @State private var selectedItemIds: [String] = []
    @State private var pendingConnector: BoardHandle?
    @State private var multiDrag: MultiItemDragState?
    @State private var marqueeStart: SchemePosition?
    @State private var marqueeCurrent: SchemePosition?
    @State private var lassoPoints: [SchemePosition] = []
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
    private let sourceWidth: Double = 320
    private let sourceHeight: Double = 170
    private let maxPinnedSourceBlocks = 12
    private let penColor = "#111827"
    private let penWidth = 3.0
    private let highlighterColor = "#facc15"
    private let highlighterWidth = 14.0
    private let highlighterOpacity = 0.35
    private let eraserRadius = 14.0
    private let defaultGridSize = 40.0
    private let minGridSize = 8.0
    private let maxGridSize = 240.0

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
                            .overlay(resizeHandleOverlay(id: frame.id, kind: .frame))
                            .position(screenPoint(for: frameCenter(frame), in: proxy.size))
                            .zIndex(layerZIndex(frame.zIndex))
                            .highPriorityGesture(frameGesture(for: frame))
                            .accessibilityIdentifier("scheme-frame-\(frame.id)")
                    }

                    ForEach(layout.texts) { text in
                        MacSchemeTextBlockView(text: text)
                            .frame(width: CGFloat(text.width), height: CGFloat(text.height))
                            .overlay(selectionOverlay(id: text.id))
                            .overlay(resizeHandleOverlay(id: text.id, kind: .text))
                            .position(screenPoint(for: textCenter(text), in: proxy.size))
                            .zIndex(layerZIndex(text.zIndex))
                            .highPriorityGesture(textGesture(for: text))
                            .accessibilityIdentifier("scheme-text-\(text.id)")
                    }

                    ForEach(layout.sources) { source in
                        MacSchemeSourceBlockView(source: source)
                            .frame(width: CGFloat(source.width), height: CGFloat(source.height))
                            .overlay(selectionOverlay(id: source.id))
                            .overlay(resizeHandleOverlay(id: source.id, kind: .source))
                            .position(screenPoint(for: sourceCenter(source), in: proxy.size))
                            .zIndex(layerZIndex(source.zIndex))
                            .highPriorityGesture(sourceGesture(for: source))
                            .accessibilityIdentifier("scheme-source-\(source.id)")
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
                            .overlay(resizeHandleOverlay(id: card.id, kind: .card))
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
                            .overlay(resizeHandleOverlay(id: shape.id, kind: .shape))
                            .position(screenPoint(for: shapeCenter(shape), in: proxy.size))
                            .zIndex(layerZIndex(shape.zIndex))
                            .highPriorityGesture(shapeGesture(for: shape))
                            .accessibilityIdentifier("scheme-shape-\(shape.id)")
                    }

                    if let marqueeRect = marqueeRect(in: proxy.size) {
                        Rectangle()
                            .fill(Palette.accent.opacity(0.14))
                            .overlay(Rectangle().stroke(Palette.accent, lineWidth: 1))
                            .frame(width: marqueeRect.width, height: marqueeRect.height)
                            .position(x: marqueeRect.midX, y: marqueeRect.midY)
                            .zIndex(1_000_001)
                            .allowsHitTesting(false)
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
                pinProjectionSources()
            } label: {
                Image(systemName: "pin")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .disabled(unpinnedProjectionSources.isEmpty)
            .help(t("Pin Sources", "Закрепить источники"))

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
                layout.snapToGrid.toggle()
                layout.gridSize = normalisedGridSize(layout.gridSize)
                onCommit(layout)
            } label: {
                Image(systemName: layout.snapToGrid ? "grid.circle.fill" : "grid.circle")
            }
            .buttonStyle(WaiGhostButtonStyle())
            .help(t("Snap to Grid", "Привязка к сетке"))

            Stepper(value: $layout.gridSize, in: minGridSize...maxGridSize, step: 4) {
                Text("\(Int(normalisedGridSize(layout.gridSize)))")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .frame(width: 34, alignment: .trailing)
            }
            .frame(width: 92)
            .help(t("Grid Size", "Размер сетки"))
            .onChangeCompat(of: layout.gridSize) {
                layout.gridSize = normalisedGridSize(layout.gridSize)
                onCommit(layout)
            }

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

    private var isSnapBypassed: Bool {
        NSEvent.modifierFlags.contains(.command) || NSEvent.modifierFlags.contains(.control)
    }

    private func normalisedGridSize(_ value: Double) -> Double {
        min(maxGridSize, max(minGridSize, value.isFinite ? value : defaultGridSize))
    }

    private func snapValue(_ value: Double) -> Double {
        let gridSize = normalisedGridSize(layout.gridSize)
        return (value / gridSize).rounded() * gridSize
    }

    private func snapPosition(_ position: SchemePosition, isBypassed: Bool = false) -> SchemePosition {
        guard layout.snapToGrid, !isBypassed else { return position }
        return SchemePosition(x: snapValue(position.x), y: snapValue(position.y), pressure: position.pressure)
    }

    private func snapRect(_ rect: (x: Double, y: Double, width: Double, height: Double), handle: ResizeHandle?) -> (x: Double, y: Double, width: Double, height: Double) {
        guard layout.snapToGrid, !isSnapBypassed else { return rect }
        guard let handle else {
            return (x: snapValue(rect.x), y: snapValue(rect.y), width: rect.width, height: rect.height)
        }

        let right = rect.x + rect.width
        let bottom = rect.y + rect.height
        let snappedX = handle.isWest ? snapValue(rect.x) : rect.x
        let snappedY = handle.isNorth ? snapValue(rect.y) : rect.y
        let snappedRight = handle.isWest ? right : snapValue(right)
        let snappedBottom = handle.isNorth ? bottom : snapValue(bottom)
        return (
            x: snappedX,
            y: snappedY,
            width: max(1, snappedRight - snappedX),
            height: max(1, snappedBottom - snappedY)
        )
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

    private var projectionSourceSummaries: [ProjectionSourceSummary] {
        guard let projection else { return [] }
        return projection.citations.prefix(maxPinnedSourceBlocks).compactMap { citation in
            guard let id = citation["id"]?.stringValue,
                  let sourceKind = citation["source_kind"]?.stringValue,
                  ["item", "recording", "chat"].contains(sourceKind),
                  let sourceId = citation["source_id"]?.stringValue,
                  let title = citation["title"]?.stringValue,
                  !id.isEmpty,
                  !sourceId.isEmpty,
                  !title.isEmpty
            else { return nil }

            return ProjectionSourceSummary(
                id: id,
                sourceKind: sourceKind,
                sourceId: sourceId,
                title: title,
                kind: citation["kind"]?.stringValue,
                createdAt: citation["created_at"]?.stringValue
            )
        }
    }

    private var unpinnedProjectionSources: [ProjectionSourceSummary] {
        let pinned = Set(layout.sources.map(\.citationId))
        return projectionSourceSummaries.filter { !pinned.contains($0.id) }
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
        !selectedItemIds.isEmpty
            && selectedItemIds.allSatisfy { canLockItem($0) && !isItemLocked($0) }
    }

    private var canDuplicateSelected: Bool {
        !selectedItemIds.isEmpty && selectedItemIds.allSatisfy(canDuplicateItem)
    }

    private var canLockSelected: Bool {
        !selectedItemIds.isEmpty && selectedItemIds.allSatisfy(canLockItem)
    }

    private var isSelectedLocked: Bool {
        canLockSelected && selectedItemIds.allSatisfy(isItemLocked)
    }

    private var canArrangeSelected: Bool {
        canLockSelected && selectedItemIds.allSatisfy { !isItemLocked($0) }
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
        clearSelection()
        pendingConnector = nil
        editingItemId = nil
        draftStrokeId = nil
        panStart = nil
        nodeDrag = nil
        cardDrag = nil
        shapeDrag = nil
        frameDrag = nil
        textDrag = nil
        sourceDrag = nil
        resizeDrag = nil
        multiDrag = nil
        marqueeStart = nil
        marqueeCurrent = nil
        lassoPoints.removeAll()
        layout = nextLayout
        onCommit(layout)
    }

    private func selectSingle(_ id: String?) {
        selectedItemId = id
        selectedItemIds = id.map { [$0] } ?? []
    }

    private func setSelection(_ ids: [String]) {
        var seen: Set<String> = []
        selectedItemIds = ids.filter { seen.insert($0).inserted }
        selectedItemId = selectedItemIds.last
    }

    private func clearSelection() {
        selectedItemId = nil
        selectedItemIds = []
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
            || layout.sources.contains { $0.id == id && $0.locked }
            || layout.strokes.contains { $0.id == id && $0.locked }
            || layout.connectors.contains { $0.id == id && $0.locked }
    }

    private func canLockItem(_ id: String) -> Bool {
        layout.cards.contains { $0.id == id }
            || layout.shapes.contains { $0.id == id }
            || layout.frames.contains { $0.id == id }
            || layout.texts.contains { $0.id == id }
            || layout.sources.contains { $0.id == id }
            || layout.strokes.contains { $0.id == id }
            || layout.connectors.contains { $0.id == id }
    }

    private func canDuplicateItem(_ id: String) -> Bool {
        guard !isItemLocked(id) else { return false }
        return layout.cards.contains { $0.id == id }
            || layout.shapes.contains { $0.id == id }
            || layout.frames.contains { $0.id == id }
            || layout.texts.contains { $0.id == id }
            || layout.sources.contains { $0.id == id }
            || layout.strokes.contains { $0.id == id }
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
            + layout.sources.map { ($0.id, $0.zIndex) }
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
        for source in layout.sources.indices where layout.sources[source].zIndex == 0 {
            layout.sources[source].zIndex = nextIndex
            nextIndex += 1
        }
        for card in layout.cards.indices where layout.cards[card].zIndex == 0 {
            layout.cards[card].zIndex = nextIndex
            nextIndex += 1
        }
    }

    private func itemBounds() -> [(id: String, rect: CGRect)] {
        var bounds: [(id: String, rect: CGRect)] = positionedNodes.map { node in
            (
                id: node.id,
                rect: CGRect(
                    x: node.position.x,
                    y: node.position.y,
                    width: Double(nodeWidth),
                    height: Double(nodeHeight)
                )
            )
        }
        bounds += layout.cards.map { card in
            (id: card.id, rect: CGRect(x: card.x, y: card.y, width: card.width, height: card.height))
        }
        bounds += layout.shapes.map { shape in
            (id: shape.id, rect: CGRect(x: shape.x, y: shape.y, width: shape.width, height: shape.height))
        }
        bounds += layout.frames.map { frame in
            (id: frame.id, rect: CGRect(x: frame.x, y: frame.y, width: frame.width, height: frame.height))
        }
        bounds += layout.texts.map { text in
            (id: text.id, rect: CGRect(x: text.x, y: text.y, width: text.width, height: text.height))
        }
        bounds += layout.sources.map { source in
            (id: source.id, rect: CGRect(x: source.x, y: source.y, width: source.width, height: source.height))
        }
        bounds += layout.strokes.compactMap { stroke in
            pointsBounds(id: stroke.id, points: stroke.points)
        }
        bounds += layout.connectors.compactMap { connector in
            pointsBounds(id: connector.id, points: connectorPoints(connector))
        }
        return bounds
    }

    private func pointsBounds(id: String, points: [SchemePosition]) -> (id: String, rect: CGRect)? {
        guard let first = points.first else { return nil }
        var minX = first.x
        var maxX = first.x
        var minY = first.y
        var maxY = first.y
        for point in points.dropFirst() {
            minX = min(minX, point.x)
            maxX = max(maxX, point.x)
            minY = min(minY, point.y)
            maxY = max(maxY, point.y)
        }
        return (id: id, rect: CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY))
    }

    private func itemRect(in candidate: SchemeCanvasLayout, id: String) -> CGRect? {
        if let node = projection?.nodes.first(where: { $0.id == id }) {
            let position = candidate.nodePositions[id] ?? node.position
            return CGRect(x: position.x, y: position.y, width: Double(nodeWidth), height: Double(nodeHeight))
        }
        if let card = candidate.cards.first(where: { $0.id == id }) {
            return CGRect(x: card.x, y: card.y, width: card.width, height: card.height)
        }
        if let shape = candidate.shapes.first(where: { $0.id == id }) {
            return CGRect(x: shape.x, y: shape.y, width: shape.width, height: shape.height)
        }
        if let frame = candidate.frames.first(where: { $0.id == id }) {
            return CGRect(x: frame.x, y: frame.y, width: frame.width, height: frame.height)
        }
        if let text = candidate.texts.first(where: { $0.id == id }) {
            return CGRect(x: text.x, y: text.y, width: text.width, height: text.height)
        }
        if let source = candidate.sources.first(where: { $0.id == id }) {
            return CGRect(x: source.x, y: source.y, width: source.width, height: source.height)
        }
        if let stroke = candidate.strokes.first(where: { $0.id == id }) {
            return pointsBounds(id: stroke.id, points: stroke.points)?.rect
        }
        if let connector = candidate.connectors.first(where: { $0.id == id }) {
            return pointsBounds(id: connector.id, points: connector.points)?.rect
        }
        return nil
    }

    private func normalisedSelectionRect(from start: SchemePosition, to end: SchemePosition) -> CGRect {
        let minX = min(start.x, end.x)
        let minY = min(start.y, end.y)
        return CGRect(x: minX, y: minY, width: abs(start.x - end.x), height: abs(start.y - end.y))
    }

    private func selectionIds(in rect: CGRect) -> [String] {
        itemBounds()
            .filter { $0.rect.intersects(rect) }
            .map(\.id)
    }

    private func selectionIds(inLasso points: [SchemePosition]) -> [String] {
        guard points.count >= 3 else { return [] }
        return itemBounds()
            .filter { boundsMostlyInsideLasso($0.rect, polygon: points) }
            .map(\.id)
    }

    private func boundsMostlyInsideLasso(_ rect: CGRect, polygon: [SchemePosition]) -> Bool {
        let samples = sampledPoints(in: rect)
        let insideCount = samples.filter { pointInPolygon($0, polygon: polygon) }.count
        return Double(insideCount) / Double(samples.count) >= 0.9
    }

    private func sampledPoints(in rect: CGRect) -> [SchemePosition] {
        let widthSteps = rect.width <= 1 ? 1 : 4
        let heightSteps = rect.height <= 1 ? 1 : 4
        var points: [SchemePosition] = []
        for xIndex in 0...widthSteps {
            for yIndex in 0...heightSteps {
                points.append(SchemePosition(
                    x: Double(rect.minX + (rect.width * CGFloat(xIndex)) / CGFloat(widthSteps)),
                    y: Double(rect.minY + (rect.height * CGFloat(yIndex)) / CGFloat(heightSteps))
                ))
            }
        }
        return points
    }

    private func pointInPolygon(_ point: SchemePosition, polygon: [SchemePosition]) -> Bool {
        guard polygon.count >= 3 else { return false }
        var inside = false
        var previous = polygon.count - 1
        for index in polygon.indices {
            let currentPoint = polygon[index]
            let previousPoint = polygon[previous]
            let crosses = (currentPoint.y > point.y) != (previousPoint.y > point.y)
                && point.x < ((previousPoint.x - currentPoint.x) * (point.y - currentPoint.y))
                    / (previousPoint.y - currentPoint.y)
                    + currentPoint.x
            if crosses {
                inside.toggle()
            }
            previous = index
        }
        return inside
    }

    private func pointDistance(_ first: SchemePosition, _ second: SchemePosition) -> Double {
        hypot(first.x - second.x, first.y - second.y)
    }

    private func marqueeRect(in size: CGSize) -> CGRect? {
        guard let marqueeStart, let marqueeCurrent else { return nil }
        let worldRect = normalisedSelectionRect(from: marqueeStart, to: marqueeCurrent)
        let origin = screenPoint(for: SchemePosition(x: worldRect.minX, y: worldRect.minY), in: size)
        return CGRect(
            x: origin.x,
            y: origin.y,
            width: worldRect.width * layout.viewport.zoom,
            height: worldRect.height * layout.viewport.zoom
        )
    }

    private func layoutWithCurrentNodePositions() -> SchemeCanvasLayout {
        var origin = layout
        for node in positionedNodes where selectedItemIds.contains(node.id) {
            origin.nodePositions[node.id] = node.position
        }
        return origin
    }

    private func translatedLayout(
        from origin: SchemeCanvasLayout,
        itemIds: [String],
        translation: CGSize
    ) -> SchemeCanvasLayout {
        let selected = Set(itemIds)
        let baseDx = Double(translation.width / CGFloat(origin.viewport.zoom))
        let baseDy = Double(translation.height / CGFloat(origin.viewport.zoom))
        var dx = baseDx
        var dy = baseDy
        var next = origin

        if origin.snapToGrid, !isSnapBypassed,
           let anchor = itemIds.compactMap({ itemRect(in: origin, id: $0) }).first {
            let targetX = Double(anchor.minX) + baseDx
            let targetY = Double(anchor.minY) + baseDy
            dx += snapValue(targetX) - targetX
            dy += snapValue(targetY) - targetY
        }

        for itemId in selected {
            if let position = next.nodePositions[itemId] {
                next.nodePositions[itemId] = SchemePosition(x: position.x + dx, y: position.y + dy)
            }
        }
        for index in next.cards.indices where selected.contains(next.cards[index].id) {
            next.cards[index].x += dx
            next.cards[index].y += dy
        }
        for index in next.shapes.indices where selected.contains(next.shapes[index].id) {
            next.shapes[index].x += dx
            next.shapes[index].y += dy
        }
        for index in next.frames.indices where selected.contains(next.frames[index].id) {
            next.frames[index].x += dx
            next.frames[index].y += dy
        }
        for index in next.texts.indices where selected.contains(next.texts[index].id) {
            next.texts[index].x += dx
            next.texts[index].y += dy
        }
        for index in next.sources.indices where selected.contains(next.sources[index].id) {
            next.sources[index].x += dx
            next.sources[index].y += dy
        }
        for index in next.strokes.indices where selected.contains(next.strokes[index].id) {
            next.strokes[index].points = next.strokes[index].points.map {
                SchemePosition(x: $0.x + dx, y: $0.y + dy, pressure: $0.pressure)
            }
        }
        for index in next.connectors.indices where selected.contains(next.connectors[index].id) {
            next.connectors[index].points = next.connectors[index].points.map {
                SchemePosition(x: $0.x + dx, y: $0.y + dy)
            }
        }

        return next
    }

    private func draggedPosition(from origin: SchemePosition, translation: CGSize) -> SchemePosition {
        let position = SchemePosition(
            x: origin.x + Double(translation.width / CGFloat(layout.viewport.zoom)),
            y: origin.y + Double(translation.height / CGFloat(layout.viewport.zoom))
        )
        return snapPosition(position, isBypassed: isSnapBypassed)
    }

    private func beginMultiDragIfNeeded(id: String, translation: CGSize) -> Bool {
        guard tool == .select, selectedItemIds.contains(id), selectedItemIds.count > 1 else { return false }
        guard selectedItemIds.allSatisfy({ !isItemLocked($0) }) else { return true }
        if multiDrag?.id != id {
            pushUndoSnapshot()
            multiDrag = MultiItemDragState(id: id, origin: layoutWithCurrentNodePositions(), itemIds: selectedItemIds)
        }
        if let multiDrag {
            layout = translatedLayout(from: multiDrag.origin, itemIds: multiDrag.itemIds, translation: translation)
        }
        return true
    }

    private func endMultiDragIfNeeded(id: String, translation: CGSize) -> Bool {
        guard let multiDrag, multiDrag.id == id else { return false }
        layout = translatedLayout(from: multiDrag.origin, itemIds: multiDrag.itemIds, translation: translation)
        self.multiDrag = nil
        onCommit(layout)
        return true
    }

    private func selectionOverlay(id: String) -> some View {
        RoundedRectangle(cornerRadius: 8)
            .stroke(selectedItemIds.contains(id) ? Palette.accent : Color.clear, lineWidth: 2)
            .padding(-3)
    }

    private func resizeHandleOverlay(id: String, kind: ResizableItemKind) -> some View {
        GeometryReader { proxy in
            ZStack {
                if selectedItemIds.count == 1, selectedItemIds.contains(id), !isItemLocked(id) {
                    ForEach(ResizeHandle.allCases) { handle in
                        RoundedRectangle(cornerRadius: 3)
                            .fill(Color(nsColor: .textBackgroundColor))
                            .overlay(
                                RoundedRectangle(cornerRadius: 3)
                                    .stroke(Palette.accent, lineWidth: 1)
                            )
                            .frame(width: 10, height: 10)
                            .position(resizeHandlePosition(handle, in: proxy.size))
                            .highPriorityGesture(resizeGesture(id: id, kind: kind, handle: handle))
                    }
                }
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
        .allowsHitTesting(selectedItemIds.count == 1 && selectedItemIds.contains(id) && !isItemLocked(id))
    }

    private func resizeHandlePosition(_ handle: ResizeHandle, in size: CGSize) -> CGPoint {
        CGPoint(
            x: handle.isWest ? 0 : size.width,
            y: handle.isNorth ? 0 : size.height
        )
    }

    private func resizeGesture(id: String, kind: ResizableItemKind, handle: ResizeHandle) -> some Gesture {
        DragGesture(minimumDistance: 1)
            .onChanged { value in
                guard tool == .select, !isItemLocked(id) else { return }
                if resizeDrag?.id != id || resizeDrag?.kind != kind || resizeDrag?.handle != handle {
                    pushUndoSnapshot()
                    resizeDrag = ResizeDragState(id: id, kind: kind, handle: handle, origin: layout)
                    selectSingle(id)
                }
                guard let resizeDrag else { return }
                layout = resizedLayout(
                    from: resizeDrag.origin,
                    id: id,
                    kind: kind,
                    handle: handle,
                    translation: value.translation
                )
            }
            .onEnded { value in
                guard tool == .select,
                      let resizeDrag,
                      resizeDrag.id == id,
                      resizeDrag.kind == kind,
                      resizeDrag.handle == handle
                else { return }
                layout = resizedLayout(
                    from: resizeDrag.origin,
                    id: id,
                    kind: kind,
                    handle: handle,
                    translation: value.translation
                )
                self.resizeDrag = nil
                selectSingle(id)
                onCommit(layout)
            }
    }

    private func resizedLayout(from origin: SchemeCanvasLayout, id: String, kind: ResizableItemKind, handle: ResizeHandle, translation: CGSize) -> SchemeCanvasLayout {
        var next = origin
        let dx = Double(translation.width / CGFloat(origin.viewport.zoom))
        let dy = Double(translation.height / CGFloat(origin.viewport.zoom))

        switch kind {
        case .card:
            guard let index = next.cards.firstIndex(where: { $0.id == id }) else { return next }
            let resized = resizedRect(
                x: next.cards[index].x,
                y: next.cards[index].y,
                width: next.cards[index].width,
                height: next.cards[index].height,
                kind: kind,
                handle: handle,
                dx: dx,
                dy: dy
            )
            next.cards[index].x = resized.x
            next.cards[index].y = resized.y
            next.cards[index].width = resized.width
            next.cards[index].height = resized.height
        case .shape:
            guard let index = next.shapes.firstIndex(where: { $0.id == id }) else { return next }
            let resized = resizedRect(
                x: next.shapes[index].x,
                y: next.shapes[index].y,
                width: next.shapes[index].width,
                height: next.shapes[index].height,
                kind: kind,
                handle: handle,
                dx: dx,
                dy: dy
            )
            next.shapes[index].x = resized.x
            next.shapes[index].y = resized.y
            next.shapes[index].width = resized.width
            next.shapes[index].height = resized.height
        case .frame:
            guard let index = next.frames.firstIndex(where: { $0.id == id }) else { return next }
            let resized = resizedRect(
                x: next.frames[index].x,
                y: next.frames[index].y,
                width: next.frames[index].width,
                height: next.frames[index].height,
                kind: kind,
                handle: handle,
                dx: dx,
                dy: dy
            )
            next.frames[index].x = resized.x
            next.frames[index].y = resized.y
            next.frames[index].width = resized.width
            next.frames[index].height = resized.height
        case .text:
            guard let index = next.texts.firstIndex(where: { $0.id == id }) else { return next }
            let resized = resizedRect(
                x: next.texts[index].x,
                y: next.texts[index].y,
                width: next.texts[index].width,
                height: next.texts[index].height,
                kind: kind,
                handle: handle,
                dx: dx,
                dy: dy
            )
            next.texts[index].x = resized.x
            next.texts[index].y = resized.y
            next.texts[index].width = resized.width
            next.texts[index].height = resized.height
        case .source:
            guard let index = next.sources.firstIndex(where: { $0.id == id }) else { return next }
            let resized = resizedRect(
                x: next.sources[index].x,
                y: next.sources[index].y,
                width: next.sources[index].width,
                height: next.sources[index].height,
                kind: kind,
                handle: handle,
                dx: dx,
                dy: dy
            )
            next.sources[index].x = resized.x
            next.sources[index].y = resized.y
            next.sources[index].width = resized.width
            next.sources[index].height = resized.height
        }

        return next
    }

    private func resizedRect(
        x: Double,
        y: Double,
        width: Double,
        height: Double,
        kind: ResizableItemKind,
        handle: ResizeHandle,
        dx: Double,
        dy: Double
    ) -> (x: Double, y: Double, width: Double, height: Double) {
        let limits = resizeLimits(for: kind)
        let nextWidth = min(limits.maxWidth, max(limits.minWidth, handle.isWest ? width - dx : width + dx))
        let nextHeight = min(limits.maxHeight, max(limits.minHeight, handle.isNorth ? height - dy : height + dy))
        let snapped = snapRect((
            x: handle.isWest ? x + width - nextWidth : x,
            y: handle.isNorth ? y + height - nextHeight : y,
            width: nextWidth,
            height: nextHeight
        ), handle: handle)
        let clampedWidth = min(limits.maxWidth, max(limits.minWidth, snapped.width))
        let clampedHeight = min(limits.maxHeight, max(limits.minHeight, snapped.height))
        return (
            x: handle.isWest ? x + width - clampedWidth : snapped.x,
            y: handle.isNorth ? y + height - clampedHeight : snapped.y,
            width: clampedWidth,
            height: clampedHeight
        )
    }

    private func resizeLimits(for kind: ResizableItemKind) -> (minWidth: Double, minHeight: Double, maxWidth: Double, maxHeight: Double) {
        switch kind {
        case .card:
            return (24, 24, 1200, 1200)
        case .shape:
            return (16, 16, 2000, 2000)
        case .frame:
            return (88, 88, 4000, 4000)
        case .text:
            return (24, 24, 1600, 1600)
        case .source:
            return (88, 68, 1600, 1600)
        }
    }

    private func boardGesture(size: CGSize) -> some Gesture {
        DragGesture(minimumDistance: (tool == .draw || tool == .highlighter || tool == .eraser) ? 1 : 0)
            .onChanged { value in
                let world = worldPoint(for: value.location, in: size)
                switch tool {
                case .draw, .highlighter:
                    if let draftStrokeId {
                        appendPoint(world, toStroke: draftStrokeId)
                    } else {
                        pushUndoSnapshot()
                        let isHighlighter = tool == .highlighter
                        let stroke = SchemeStroke(
                            id: "stroke:\(UUID().uuidString)",
                            points: [
                                SchemePosition(x: world.x, y: world.y, pressure: 1),
                                SchemePosition(x: world.x, y: world.y, pressure: 1),
                            ],
                            kind: isHighlighter ? "highlighter" : "pen",
                            color: isHighlighter ? highlighterColor : penColor,
                            width: isHighlighter ? highlighterWidth : penWidth,
                            opacity: isHighlighter ? highlighterOpacity : 1,
                            zIndex: nextLayerIndex()
                        )
                        layout.strokes.append(stroke)
                        draftStrokeId = stroke.id
                        selectSingle(stroke.id)
                    }
                case .eraser:
                    if !eraserDidPushUndo {
                        pushUndoSnapshot()
                        eraserDidPushUndo = true
                    }
                    eraseStrokes(at: world)
                case .pan:
                    if panStart == nil {
                        panStart = layout.viewport
                    }
                    let origin = panStart ?? layout.viewport
                    layout.viewport = SchemeViewport(
                        x: origin.x + Double(value.translation.width),
                        y: origin.y + Double(value.translation.height),
                        zoom: origin.zoom
                    )
                case .select:
                    if marqueeStart == nil {
                        marqueeStart = world
                    }
                    marqueeCurrent = world
                    if let marqueeStart {
                        setSelection(selectionIds(in: normalisedSelectionRect(from: marqueeStart, to: world)))
                    }
                case .lasso:
                    if let last = lassoPoints.last {
                        if pointDistance(world, last) >= 2 {
                            lassoPoints.append(world)
                        }
                    } else {
                        lassoPoints = [world]
                    }
                    setSelection(selectionIds(inLasso: lassoPoints))
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
                case .draw, .highlighter:
                    draftStrokeId = nil
                    onCommit(layout)
                case .eraser:
                    if eraserDidPushUndo {
                        eraseStrokes(at: world)
                        onCommit(layout)
                    }
                    eraserDidPushUndo = false
                case .pan:
                    panStart = nil
                    onCommit(layout)
                case .select:
                    if let marqueeStart, let marqueeCurrent {
                        let rect = normalisedSelectionRect(from: marqueeStart, to: marqueeCurrent)
                        if rect.width < 3 && rect.height < 3 {
                            clearSelection()
                        }
                    }
                    marqueeStart = nil
                    marqueeCurrent = nil
                case .lasso:
                    if lassoPoints.count < 3 {
                        clearSelection()
                    }
                    lassoPoints.removeAll()
                case .connector:
                    pendingConnector = nil
                }
            }
    }

    private func nodeGesture(for node: SchemeNode) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                if beginMultiDragIfNeeded(id: node.id, translation: value.translation) { return }
                if nodeDrag?.id != node.id {
                    pushUndoSnapshot()
                    nodeDrag = ItemDragState(id: node.id, origin: node.position)
                    selectSingle(node.id)
                }
                let origin = nodeDrag?.origin ?? node.position
                layout.nodePositions[node.id] = draggedPosition(from: origin, translation: value.translation)
            }
            .onEnded { value in
                if tool == .connector {
                    handleConnectorTap(id: node.id)
                    return
                }
                guard tool == .select else { return }
                if endMultiDragIfNeeded(id: node.id, translation: value.translation) { return }
                let origin = nodeDrag?.origin ?? node.position
                layout.nodePositions[node.id] = draggedPosition(from: origin, translation: value.translation)
                selectSingle(node.id)
                nodeDrag = nil
                onCommit(layout)
            }
    }

    private func cardGesture(for card: SchemeCanvasCard) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                guard !card.locked else {
                    selectSingle(card.id)
                    return
                }
                if beginMultiDragIfNeeded(id: card.id, translation: value.translation) { return }
                if cardDrag?.id != card.id {
                    pushUndoSnapshot()
                    cardDrag = ItemDragState(id: card.id, origin: SchemePosition(x: card.x, y: card.y))
                    selectSingle(card.id)
                }
                let origin = cardDrag?.origin ?? SchemePosition(x: card.x, y: card.y)
                let position = draggedPosition(from: origin, translation: value.translation)
                updateCard(card.id) {
                    $0.x = position.x
                    $0.y = position.y
                }
            }
            .onEnded { value in
                guard !card.locked else {
                    selectSingle(card.id)
                    cardDrag = nil
                    return
                }
                if tool == .connector {
                    handleConnectorTap(id: card.id)
                    return
                }
                guard tool == .select else { return }
                if endMultiDragIfNeeded(id: card.id, translation: value.translation) { return }
                let origin = cardDrag?.origin ?? SchemePosition(x: card.x, y: card.y)
                let position = draggedPosition(from: origin, translation: value.translation)
                updateCard(card.id) {
                    $0.x = position.x
                    $0.y = position.y
                }
                selectSingle(card.id)
                cardDrag = nil
                onCommit(layout)
            }
    }

    private func shapeGesture(for shape: SchemeCanvasShape) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                guard !shape.locked else {
                    selectSingle(shape.id)
                    return
                }
                if beginMultiDragIfNeeded(id: shape.id, translation: value.translation) { return }
                if shapeDrag?.id != shape.id {
                    pushUndoSnapshot()
                    shapeDrag = ItemDragState(id: shape.id, origin: SchemePosition(x: shape.x, y: shape.y))
                    selectSingle(shape.id)
                }
                let origin = shapeDrag?.origin ?? SchemePosition(x: shape.x, y: shape.y)
                let position = draggedPosition(from: origin, translation: value.translation)
                updateShape(shape.id) {
                    $0.x = position.x
                    $0.y = position.y
                }
            }
            .onEnded { value in
                guard !shape.locked else {
                    selectSingle(shape.id)
                    shapeDrag = nil
                    return
                }
                if tool == .connector {
                    handleConnectorTap(id: shape.id)
                    return
                }
                guard tool == .select else { return }
                if endMultiDragIfNeeded(id: shape.id, translation: value.translation) { return }
                let origin = shapeDrag?.origin ?? SchemePosition(x: shape.x, y: shape.y)
                let position = draggedPosition(from: origin, translation: value.translation)
                updateShape(shape.id) {
                    $0.x = position.x
                    $0.y = position.y
                }
                selectSingle(shape.id)
                shapeDrag = nil
                onCommit(layout)
            }
    }

    private func frameGesture(for frame: SchemeCanvasFrame) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                guard !frame.locked else {
                    selectSingle(frame.id)
                    return
                }
                if beginMultiDragIfNeeded(id: frame.id, translation: value.translation) { return }
                if frameDrag?.id != frame.id {
                    pushUndoSnapshot()
                    frameDrag = ItemDragState(id: frame.id, origin: SchemePosition(x: frame.x, y: frame.y))
                    selectSingle(frame.id)
                }
                let origin = frameDrag?.origin ?? SchemePosition(x: frame.x, y: frame.y)
                let position = draggedPosition(from: origin, translation: value.translation)
                updateFrame(frame.id) {
                    $0.x = position.x
                    $0.y = position.y
                }
            }
            .onEnded { value in
                guard !frame.locked else {
                    selectSingle(frame.id)
                    frameDrag = nil
                    return
                }
                if tool == .connector {
                    handleConnectorTap(id: frame.id)
                    return
                }
                guard tool == .select else { return }
                if endMultiDragIfNeeded(id: frame.id, translation: value.translation) { return }
                let origin = frameDrag?.origin ?? SchemePosition(x: frame.x, y: frame.y)
                let position = draggedPosition(from: origin, translation: value.translation)
                updateFrame(frame.id) {
                    $0.x = position.x
                    $0.y = position.y
                }
                selectSingle(frame.id)
                frameDrag = nil
                onCommit(layout)
            }
    }

    private func textGesture(for text: SchemeTextBlock) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                guard !text.locked else {
                    selectSingle(text.id)
                    return
                }
                if beginMultiDragIfNeeded(id: text.id, translation: value.translation) { return }
                if textDrag?.id != text.id {
                    pushUndoSnapshot()
                    textDrag = ItemDragState(id: text.id, origin: SchemePosition(x: text.x, y: text.y))
                    selectSingle(text.id)
                }
                let origin = textDrag?.origin ?? SchemePosition(x: text.x, y: text.y)
                let position = draggedPosition(from: origin, translation: value.translation)
                updateText(text.id) {
                    $0.x = position.x
                    $0.y = position.y
                }
            }
            .onEnded { value in
                guard !text.locked else {
                    selectSingle(text.id)
                    textDrag = nil
                    return
                }
                if tool == .connector {
                    handleConnectorTap(id: text.id)
                    return
                }
                guard tool == .select else { return }
                if endMultiDragIfNeeded(id: text.id, translation: value.translation) { return }
                let origin = textDrag?.origin ?? SchemePosition(x: text.x, y: text.y)
                let position = draggedPosition(from: origin, translation: value.translation)
                updateText(text.id) {
                    $0.x = position.x
                    $0.y = position.y
                }
                selectSingle(text.id)
                textDrag = nil
                onCommit(layout)
            }
    }

    private func sourceGesture(for source: SchemeCanvasSourceBlock) -> some Gesture {
        DragGesture(minimumDistance: tool == .connector ? 0 : 1)
            .onChanged { value in
                guard tool == .select else { return }
                guard !source.locked else {
                    selectSingle(source.id)
                    return
                }
                if beginMultiDragIfNeeded(id: source.id, translation: value.translation) { return }
                if sourceDrag?.id != source.id {
                    pushUndoSnapshot()
                    sourceDrag = ItemDragState(id: source.id, origin: SchemePosition(x: source.x, y: source.y))
                    selectSingle(source.id)
                }
                let origin = sourceDrag?.origin ?? SchemePosition(x: source.x, y: source.y)
                let position = draggedPosition(from: origin, translation: value.translation)
                updateSource(source.id) {
                    $0.x = position.x
                    $0.y = position.y
                }
            }
            .onEnded { value in
                guard !source.locked else {
                    selectSingle(source.id)
                    sourceDrag = nil
                    return
                }
                if tool == .connector {
                    handleConnectorTap(id: source.id)
                    return
                }
                guard tool == .select else { return }
                if endMultiDragIfNeeded(id: source.id, translation: value.translation) { return }
                let origin = sourceDrag?.origin ?? SchemePosition(x: source.x, y: source.y)
                let position = draggedPosition(from: origin, translation: value.translation)
                updateSource(source.id) {
                    $0.x = position.x
                    $0.y = position.y
                }
                selectSingle(source.id)
                sourceDrag = nil
                onCommit(layout)
            }
    }

    private func drawBoard(context: GraphicsContext, size: CGSize) {
        drawGrid(context: context, size: size)
        drawProjectionEdges(context: context, size: size)
        drawConnectors(context: context, size: size)
        drawStrokes(context: context, size: size)
        drawLasso(context: context, size: size)
    }

    private func drawGrid(context: GraphicsContext, size: CGSize) {
        let spacing = CGFloat(normalisedGridSize(layout.gridSize) * layout.viewport.zoom)
        guard spacing >= 4 else { return }

        let originX = size.width / 2 + CGFloat(layout.viewport.x)
        let originY = size.height / 2 + CGFloat(layout.viewport.y)
        var path = Path()

        var x = originX.truncatingRemainder(dividingBy: spacing)
        if x < 0 { x += spacing }
        while x <= size.width {
            path.move(to: CGPoint(x: x, y: 0))
            path.addLine(to: CGPoint(x: x, y: size.height))
            x += spacing
        }

        var y = originY.truncatingRemainder(dividingBy: spacing)
        if y < 0 { y += spacing }
        while y <= size.height {
            path.move(to: CGPoint(x: 0, y: y))
            path.addLine(to: CGPoint(x: size.width, y: y))
            y += spacing
        }

        context.stroke(path, with: .color(Palette.textSecondary.opacity(0.08)), lineWidth: 1)
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
                with: .color(
                    schemeColor(stroke.color, defaultColor: Palette.textPrimary)
                        .opacity(stroke.locked ? min(stroke.opacity, 0.45) : stroke.opacity)
                ),
                style: StrokeStyle(lineWidth: CGFloat(stroke.width) * CGFloat(layout.viewport.zoom), lineCap: .round, lineJoin: .round)
            )
        }
    }

    private func drawLasso(context: GraphicsContext, size: CGSize) {
        guard lassoPoints.count > 1 else { return }
        var path = Path()
        path.move(to: screenPoint(for: lassoPoints[0], in: size))
        for point in lassoPoints.dropFirst() {
            path.addLine(to: screenPoint(for: point, in: size))
        }
        if lassoPoints.count > 2 {
            path.closeSubpath()
            context.fill(path, with: .color(Palette.accent.opacity(0.12)))
        }
        context.stroke(
            path,
            with: .color(Palette.accent),
            style: StrokeStyle(lineWidth: 1.5, dash: [7, 5])
        )
    }

    private func addCard(at point: SchemePosition) {
        pushUndoSnapshot()
        let rect = snapRect(
            (x: point.x - stickyWidth / 2, y: point.y - stickyHeight / 2, width: stickyWidth, height: stickyHeight),
            handle: nil
        )
        let card = SchemeCanvasCard(
            id: "card:\(UUID().uuidString)",
            x: rect.x,
            y: rect.y,
            width: stickyWidth,
            height: stickyHeight,
            text: t("Note", "Заметка"),
            zIndex: nextLayerIndex()
        )
        layout.cards.append(card)
        selectSingle(card.id)
        onCommit(layout)
    }

    private func addShape(kind: String, at point: SchemePosition) {
        pushUndoSnapshot()
        let rect = snapRect(
            (x: point.x - shapeWidth / 2, y: point.y - shapeHeight / 2, width: shapeWidth, height: shapeHeight),
            handle: nil
        )
        let shape = SchemeCanvasShape(
            id: "shape:\(UUID().uuidString)",
            kind: kind,
            x: rect.x,
            y: rect.y,
            width: shapeWidth,
            height: shapeHeight,
            color: kind == "ellipse" ? "#7c3aed" : "#2563eb",
            zIndex: nextLayerIndex()
        )
        layout.shapes.append(shape)
        selectSingle(shape.id)
        onCommit(layout)
    }

    private func addFrame(at point: SchemePosition) {
        pushUndoSnapshot()
        let rect = snapRect(
            (x: point.x - frameWidth / 2, y: point.y - frameHeight / 2, width: frameWidth, height: frameHeight),
            handle: nil
        )
        let frame = SchemeCanvasFrame(
            id: "frame:\(UUID().uuidString)",
            x: rect.x,
            y: rect.y,
            width: frameWidth,
            height: frameHeight,
            title: t("Frame", "Фрейм"),
            zIndex: nextLayerIndex()
        )
        layout.frames.append(frame)
        selectSingle(frame.id)
        onCommit(layout)
    }

    private func addText(at point: SchemePosition) {
        pushUndoSnapshot()
        let rect = snapRect(
            (x: point.x - textWidth / 2, y: point.y - textHeight / 2, width: textWidth, height: textHeight),
            handle: nil
        )
        let text = SchemeTextBlock(
            id: "text:\(UUID().uuidString)",
            x: rect.x,
            y: rect.y,
            width: textWidth,
            height: textHeight,
            text: t("Text", "Текст"),
            fontSize: 22,
            zIndex: nextLayerIndex()
        )
        layout.texts.append(text)
        selectSingle(text.id)
        onCommit(layout)
    }

    private func pinProjectionSources() {
        let sources = unpinnedProjectionSources
        guard !sources.isEmpty else { return }

        pushUndoSnapshot()
        var nextZIndex = nextLayerIndex()
        let sourceOffset = layout.sources.count
        let blocks = sources.enumerated().map { index, source in
            let block = sourceBlock(from: source, index: sourceOffset + index, zIndex: nextZIndex)
            nextZIndex += 1
            return block
        }

        layout.sources.append(contentsOf: blocks)
        setSelection(blocks.map(\.id))
        onCommit(layout)
    }

    private func sourceBlock(from source: ProjectionSourceSummary, index: Int, zIndex: Int) -> SchemeCanvasSourceBlock {
        SchemeCanvasSourceBlock(
            id: "source-block:\(source.sourceKind):\(source.sourceId)",
            sourceKind: source.sourceKind,
            sourceId: source.sourceId,
            citationId: source.id,
            x: -760,
            y: -240 + Double(index) * (sourceHeight + 28),
            width: sourceWidth,
            height: sourceHeight,
            title: source.title,
            subtitle: sourceSubtitle(source),
            excerpt: sourceExcerpt(source),
            color: sourceKindColor(source.sourceKind),
            zIndex: zIndex
        )
    }

    private func sourceSubtitle(_ source: ProjectionSourceSummary) -> String? {
        let parts = [
            source.kind,
            source.createdAt.map { String($0.prefix(10)) },
        ].compactMap { value -> String? in
            guard let value, !value.isEmpty else { return nil }
            return value
        }
        return parts.isEmpty ? source.sourceKind : parts.joined(separator: " / ")
    }

    private func sourceExcerpt(_ source: ProjectionSourceSummary) -> String? {
        projection?.nodes.first {
            $0.kind == "source"
                && $0.sourceKind == source.sourceKind
                && $0.sourceId == source.sourceId
        }?.body
    }

    private func sourceKindColor(_ sourceKind: String) -> String {
        switch sourceKind {
        case "recording":
            return "#ecfeff"
        case "chat":
            return "#f5f3ff"
        default:
            return "#eef2ff"
        }
    }

    private func appendPoint(_ point: SchemePosition, toStroke strokeId: String) {
        guard let index = layout.strokes.firstIndex(where: { $0.id == strokeId }) else { return }
        layout.strokes[index].points.append(SchemePosition(x: point.x, y: point.y, pressure: 1))
    }

    private func eraseStrokes(at point: SchemePosition) {
        layout.strokes.removeAll { stroke in
            !stroke.locked && strokeContains(stroke, point: point)
        }
    }

    private func strokeContains(_ stroke: SchemeStroke, point: SchemePosition) -> Bool {
        guard stroke.points.count >= 2 else { return false }
        let threshold = max(eraserRadius, stroke.width / 2 + 6)
        for index in 1..<stroke.points.count {
            if distance(point, toSegmentFrom: stroke.points[index - 1], to: stroke.points[index]) <= threshold {
                return true
            }
        }
        return false
    }

    private func distance(_ point: SchemePosition, toSegmentFrom start: SchemePosition, to end: SchemePosition) -> Double {
        let dx = end.x - start.x
        let dy = end.y - start.y
        guard dx != 0 || dy != 0 else {
            return hypot(point.x - start.x, point.y - start.y)
        }
        let rawRatio = ((point.x - start.x) * dx + (point.y - start.y) * dy) / (dx * dx + dy * dy)
        let ratio = min(1, max(0, rawRatio))
        let projected = SchemePosition(x: start.x + ratio * dx, y: start.y + ratio * dy)
        return hypot(point.x - projected.x, point.y - projected.y)
    }

    private func handleConnectorTap(id: String) {
        selectSingle(id)
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
            selectSingle(connector.id)
            onCommit(layout)
        } else {
            pendingConnector = handle
        }
    }

    private func deleteSelected() {
        guard canDeleteSelected else { return }
        pushUndoSnapshot()
        let selected = Set(selectedItemIds)
        layout.cards.removeAll { selected.contains($0.id) }
        layout.shapes.removeAll { selected.contains($0.id) }
        layout.frames.removeAll { selected.contains($0.id) }
        layout.texts.removeAll { selected.contains($0.id) }
        layout.sources.removeAll { selected.contains($0.id) }
        layout.strokes.removeAll { selected.contains($0.id) }
        layout.connectors.removeAll {
            selected.contains($0.id)
                || $0.sourceId.map { selected.contains($0) } == true
                || $0.targetId.map { selected.contains($0) } == true
        }
        clearSelection()
        onCommit(layout)
    }

    private func toggleSelectedLock() {
        guard canLockSelected else { return }
        pushUndoSnapshot()
        let selected = Set(selectedItemIds)
        let locked = !isSelectedLocked

        for id in selected {
            updateCard(id) { $0.locked = locked }
            updateShape(id) { $0.locked = locked }
            updateFrame(id) { $0.locked = locked }
            updateText(id) { $0.locked = locked }
            updateSource(id) { $0.locked = locked }
            updateStroke(id) { $0.locked = locked }
            updateConnector(id) { $0.locked = locked }
        }

        onCommit(layout)
    }

    private func arrangeSelected(_ action: LayerAction) {
        guard canArrangeSelected else { return }
        pushUndoSnapshot()
        normaliseLayerIndexes()

        let selected = Set(selectedItemIds)
        let items = layoutLayerItems().sorted { $0.zIndex < $1.zIndex }
        guard items.contains(where: { selected.contains($0.id) }) else { return }

        switch action {
        case .front:
            var nextIndex = (items.last?.zIndex ?? 0) + 1
            for item in items where selected.contains(item.id) {
                setItemZIndex(item.id, zIndex: nextIndex)
                nextIndex += 1
            }
        case .back:
            var nextIndex = (items.first?.zIndex ?? 0) - selectedItemIds.count
            for item in items where selected.contains(item.id) {
                setItemZIndex(item.id, zIndex: nextIndex)
                nextIndex += 1
            }
        case .forward:
            var ordered = items
            if ordered.count > 1 {
                for index in stride(from: ordered.count - 2, through: 0, by: -1) {
                    if selected.contains(ordered[index].id), !selected.contains(ordered[index + 1].id) {
                        ordered.swapAt(index, index + 1)
                    }
                }
                for (index, item) in ordered.enumerated() {
                    setItemZIndex(item.id, zIndex: index + 1)
                }
            }
        case .backward:
            var ordered = items
            if ordered.count > 1 {
                for index in 1..<ordered.count {
                    if selected.contains(ordered[index].id), !selected.contains(ordered[index - 1].id) {
                        ordered.swapAt(index - 1, index)
                    }
                }
                for (index, item) in ordered.enumerated() {
                    setItemZIndex(item.id, zIndex: index + 1)
                }
            }
        }

        onCommit(layout)
    }

    private func duplicateSelected() {
        guard canDuplicateSelected else { return }
        pushUndoSnapshot()
        let offset = 32.0
        var nextSelection: [String] = []

        for selectedItemId in selectedItemIds {
            if var card = layout.cards.first(where: { $0.id == selectedItemId }) {
                card.id = "card:\(UUID().uuidString)"
                card.x += offset
                card.y += offset
                card.zIndex = nextLayerIndex()
                layout.cards.append(card)
                nextSelection.append(card.id)
                continue
            }

            if var shape = layout.shapes.first(where: { $0.id == selectedItemId }) {
                shape.id = "shape:\(UUID().uuidString)"
                shape.x += offset
                shape.y += offset
                shape.zIndex = nextLayerIndex()
                layout.shapes.append(shape)
                nextSelection.append(shape.id)
                continue
            }

            if var frame = layout.frames.first(where: { $0.id == selectedItemId }) {
                frame.id = "frame:\(UUID().uuidString)"
                frame.x += offset
                frame.y += offset
                frame.zIndex = nextLayerIndex()
                layout.frames.append(frame)
                nextSelection.append(frame.id)
                continue
            }

            if var text = layout.texts.first(where: { $0.id == selectedItemId }) {
                text.id = "text:\(UUID().uuidString)"
                text.x += offset
                text.y += offset
                text.zIndex = nextLayerIndex()
                layout.texts.append(text)
                nextSelection.append(text.id)
                continue
            }

            if var source = layout.sources.first(where: { $0.id == selectedItemId }) {
                source.id = "source:\(UUID().uuidString)"
                source.x += offset
                source.y += offset
                source.zIndex = nextLayerIndex()
                layout.sources.append(source)
                nextSelection.append(source.id)
                continue
            }

            if var stroke = layout.strokes.first(where: { $0.id == selectedItemId }) {
                stroke.id = "stroke:\(UUID().uuidString)"
                stroke.points = stroke.points.map { point in
                    SchemePosition(x: point.x + offset, y: point.y + offset, pressure: point.pressure)
                }
                stroke.zIndex = nextLayerIndex()
                layout.strokes.append(stroke)
                nextSelection.append(stroke.id)
            }
        }

        setSelection(nextSelection)
        onCommit(layout)
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

    private func updateSource(_ id: String, mutate: (inout SchemeCanvasSourceBlock) -> Void) {
        guard let index = layout.sources.firstIndex(where: { $0.id == id }) else { return }
        mutate(&layout.sources[index])
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
        updateSource(id) { $0.zIndex = zIndex }
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

    private func sourceCenter(_ source: SchemeCanvasSourceBlock) -> SchemePosition {
        SchemePosition(x: source.x + source.width / 2, y: source.y + source.height / 2)
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
        if let source = layout.sources.first(where: { $0.id == id }) {
            return sourceCenter(source)
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
            sourceKind: source.sourceKind,
            sourceId: source.sourceId,
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

private struct MacSchemeSourceBlockView: View {
    let source: SchemeCanvasSourceBlock

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(source.sourceKind)
                .font(Typography.caption)
                .foregroundStyle(sourceAccent)
                .lineLimit(1)
                .padding(.horizontal, Spacing.xs)
                .padding(.vertical, 2)
                .background(sourceAccent.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 4))

            Text(source.title)
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(2)

            if let subtitle = source.subtitle, !subtitle.isEmpty {
                Text(subtitle)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }

            if let excerpt = source.excerpt, !excerpt.isEmpty {
                Text(excerpt)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(4)
            }

            Spacer(minLength: 0)
        }
        .padding(Spacing.md)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(schemeColor(source.color, defaultColor: Color(red: 0.93, green: 0.95, blue: 1)))
        .opacity(source.locked ? 0.72 : 1)
        .overlay(alignment: .topTrailing) {
            if source.locked {
                Image(systemName: "lock.fill")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Palette.textSecondary)
                    .padding(Spacing.xs)
            }
        }
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(sourceAccent.opacity(0.35), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .shadow(color: Color.black.opacity(0.08), radius: 8, y: 3)
    }

    private var sourceAccent: Color {
        switch source.sourceKind {
        case "recording":
            return Color(nsColor: .systemTeal)
        case "chat":
            return Color(nsColor: .systemPurple)
        default:
            return Palette.accent
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
