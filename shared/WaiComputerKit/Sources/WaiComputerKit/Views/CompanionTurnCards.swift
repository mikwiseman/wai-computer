import SwiftUI

private func companionLocaleIsRussian(_ locale: Locale) -> Bool {
    locale.identifier.lowercased().hasPrefix("ru")
}

/// Friendly label for a hosted-read tool (the MCP brain tools + web_search).
func companionToolLabel(_ tool: String, russian: Bool) -> String {
    switch tool {
    case "search", "search_transcripts":
        return russian ? "Поиск по записям" : "Searched your brain"
    case "web_search":
        return russian ? "Поиск в интернете" : "Searched the web"
    case "fetch", "get_recording_summary":
        return russian ? "Чтение записи" : "Read a recording"
    case "list_recordings":
        return russian ? "Список записей" : "Listed recordings"
    case "list_folders":
        return russian ? "Список папок" : "Listed folders"
    case "list_action_items", "get_action_items":
        return russian ? "Задачи" : "Checked tasks"
    case "get_highlights":
        return russian ? "Ключевые моменты" : "Checked highlights"
    case "search_people":
        return russian ? "Поиск по людям" : "Searched people"
    default:
        return tool
    }
}

func companionToolIcon(_ tool: String) -> String {
    switch tool {
    case "web_search": return "globe"
    case "fetch", "get_recording_summary": return "doc.text"
    case "list_recordings", "list_folders": return "list.bullet"
    case "list_action_items", "get_action_items": return "checklist"
    case "get_highlights": return "sparkles"
    case "search_people": return "person.2"
    default: return "magnifyingglass"
    }
}

/// Renders an assistant turn's folded timeline as an ordered stack of cards.
struct CompanionTimelineView: View {
    let items: [CompanionTurnItem]
    var isLive: Bool
    var accent: Color
    /// (actionId, decision) — nil disables the approve/reject buttons (history).
    var onResolve: ((String, CompanionActionDecision) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(items) { item in
                switch item {
                case .thinking(_, let text):
                    CompanionThinkingCard(text: text, isLive: isLive, accent: accent)
                case .tools(_, let actions):
                    CompanionToolActionsCard(actions: actions, isLive: isLive, accent: accent)
                case .plan(_, let steps):
                    CompanionPlanCard(steps: steps, accent: accent)
                case .text(_, let markdown):
                    CompanionMarkdownText(text: markdown, accent: accent)
                case .action(_, let proposal, let resolution):
                    CompanionActionCard(
                        proposal: proposal,
                        resolution: resolution,
                        accent: accent,
                        onResolve: onResolve
                    )
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Thinking

struct CompanionThinkingCard: View {
    let text: String
    var isLive: Bool
    var accent: Color
    @Environment(\.locale) private var locale
    @State private var expanded: Bool

    init(text: String, isLive: Bool, accent: Color) {
        self.text = text
        self.isLive = isLive
        self.accent = accent
        _expanded = State(initialValue: isLive)
    }

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            Text(text)
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .italic()
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 6)
                .textSelection(.enabled)
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "brain")
                    .font(.system(size: 11))
                    .foregroundStyle(accent.opacity(0.85))
                Text(companionLocaleIsRussian(locale) ? "Размышляю" : "Thinking")
                    .font(.system(size: 13, weight: .medium))
                if isLive {
                    ProgressView().controlSize(.mini)
                }
            }
        }
        .padding(10)
        .background(Color.primary.opacity(0.03))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .accessibilityIdentifier("wai-thinking-card")
    }
}

// MARK: - Tool actions

struct CompanionToolActionsCard: View {
    let actions: [CompanionToolAction]
    var isLive: Bool
    var accent: Color
    @Environment(\.locale) private var locale
    @State private var expanded: Bool

    init(actions: [CompanionToolAction], isLive: Bool, accent: Color) {
        self.actions = actions
        self.isLive = isLive
        self.accent = accent
        _expanded = State(initialValue: isLive)
    }

    private var russian: Bool { companionLocaleIsRussian(locale) }

    private var headerTitle: String {
        let count = actions.count
        if russian { return "Действия · \(count)" }
        return "Tool actions · \(count) \(count == 1 ? "step" : "steps")"
    }

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(actions) { action in
                    HStack(spacing: 8) {
                        statusIcon(action)
                        Image(systemName: companionToolIcon(action.tool))
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .frame(width: 16)
                        Text(companionToolLabel(action.tool, russian: russian))
                            .font(.system(size: 13))
                        if let summary = action.summary, !summary.isEmpty {
                            Text("· \(summary)")
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        Spacer(minLength: 0)
                    }
                }
            }
            .padding(.top, 6)
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "bolt.fill")
                    .font(.system(size: 10))
                    .foregroundStyle(accent)
                Text(headerTitle)
                    .font(.system(size: 13, weight: .medium))
                if isLive && actions.contains(where: { $0.isRunning }) {
                    ProgressView().controlSize(.mini)
                }
            }
        }
        .padding(10)
        .background(Color.primary.opacity(0.04))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .accessibilityIdentifier("wai-tool-actions-card")
    }

    @ViewBuilder
    private func statusIcon(_ action: CompanionToolAction) -> some View {
        if action.isRunning {
            ProgressView().controlSize(.small).frame(width: 14, height: 14)
        } else if action.ok == false {
            Image(systemName: "xmark.circle.fill")
                .font(.system(size: 12))
                .foregroundStyle(.red)
        } else {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 12))
                .foregroundStyle(.green)
        }
    }
}

// MARK: - Plan

struct CompanionPlanCard: View {
    let steps: [CompanionPlanStep]
    var accent: Color
    @Environment(\.locale) private var locale

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "checklist")
                    .font(.system(size: 12))
                    .foregroundStyle(accent)
                Text(companionLocaleIsRussian(locale) ? "План" : "Plan")
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
            }
            VStack(alignment: .leading, spacing: 7) {
                ForEach(Array(steps.enumerated()), id: \.offset) { _, step in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        stepIcon(step.status)
                        Text(step.title)
                            .font(.system(size: 14))
                            .strikethrough(step.status == "done", color: .secondary)
                            .foregroundStyle(step.status == "done" ? .secondary : .primary)
                        Spacer(minLength: 0)
                    }
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(accent.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(accent.opacity(0.18), lineWidth: 1)
        )
        .accessibilityIdentifier("wai-plan-card")
    }

    @ViewBuilder
    private func stepIcon(_ status: String) -> some View {
        Group {
            switch status {
            case "done":
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
            case "in_progress":
                Image(systemName: "circle.lefthalf.filled").foregroundStyle(accent)
            default:
                Image(systemName: "circle").foregroundStyle(.secondary)
            }
        }
        .font(.system(size: 13))
    }
}

// MARK: - Action approval

struct CompanionActionCard: View {
    let proposal: CompanionActionProposal
    let resolution: CompanionActionResolution?
    var accent: Color
    var onResolve: ((String, CompanionActionDecision) -> Void)?
    @Environment(\.locale) private var locale
    @State private var pending: CompanionActionDecision?

    private var russian: Bool { companionLocaleIsRussian(locale) }

    private var actionIcon: String {
        proposal.tool.hasPrefix("desktop_") ? "macwindow" : "paperplane.fill"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: actionIcon)
                    .foregroundStyle(accent)
                    .font(.system(size: 13, weight: .semibold))
                Text(russian ? "Нужно подтверждение" : "Approval needed")
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
            }
            Text(proposal.preview)
                .font(.system(size: 14))
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if let recipient = proposal.recipient, !recipient.isEmpty {
                Text((russian ? "Кому: " : "To: ") + recipient)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }
            controls
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(accent.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(accent.opacity(0.25), lineWidth: 1)
        )
        .accessibilityIdentifier("wai-action-card")
    }

    @ViewBuilder
    private var controls: some View {
        if let resolution {
            switch resolution {
            case .executing:
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small)
                    Text(russian ? "Выполняю…" : "Working…")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
            case .resolved(let status, _):
                HStack(spacing: 6) {
                    Image(systemName: resolvedIcon(status))
                        .foregroundStyle(resolvedColor(status))
                    Text(resolvedLabel(status))
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                }
            }
        } else if let onResolve {
            HStack(spacing: 8) {
                Button(role: .cancel) {
                    trigger(.reject, onResolve)
                } label: {
                    Text(russian ? "Отклонить" : "Reject")
                }
                .buttonStyle(.bordered)
                .disabled(pending != nil)
                .accessibilityIdentifier("wai-action-reject")

                Spacer(minLength: 0)

                Button {
                    trigger(.always, onResolve)
                } label: {
                    Text(russian ? "Всегда" : "Always")
                }
                .buttonStyle(.bordered)
                .disabled(pending != nil)

                Button {
                    trigger(.once, onResolve)
                } label: {
                    if pending == .once {
                        ProgressView().controlSize(.small)
                    } else {
                        Text(russian ? "Подтвердить" : "Approve")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(pending != nil)
                .accessibilityIdentifier("wai-action-approve")
            }
        }
    }

    private func trigger(
        _ decision: CompanionActionDecision,
        _ onResolve: (String, CompanionActionDecision) -> Void
    ) {
        pending = decision
        onResolve(proposal.actionId, decision)
    }

    private func resolvedIcon(_ status: String) -> String {
        switch status {
        case "executed", "dispatched": return "checkmark.circle.fill"
        case "rejected": return "xmark.circle.fill"
        default: return "exclamationmark.triangle.fill"
        }
    }

    private func resolvedColor(_ status: String) -> Color {
        switch status {
        case "executed", "dispatched": return .green
        case "rejected": return .secondary
        default: return .orange
        }
    }

    private func resolvedLabel(_ status: String) -> String {
        switch status {
        case "executed": return russian ? "Готово" : "Done"
        case "dispatched": return russian ? "Отправлено на Mac" : "Sent to your Mac"
        case "rejected": return russian ? "Отклонено" : "Rejected"
        case "failed": return russian ? "Не удалось" : "Failed"
        default: return status
        }
    }
}

// MARK: - Markdown

/// Lightweight block-aware markdown renderer for assistant answers: paragraphs,
/// ATX headings, unordered/ordered lists, fenced code blocks, plus inline
/// emphasis/code/links via AttributedString — without a markdown dependency.
struct CompanionMarkdownText: View {
    let text: String
    var accent: Color = .accentColor

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(CompanionMarkdownBlock.parse(text).enumerated()), id: \.offset) { _, block in
                block.view(accent: accent)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private enum CompanionMarkdownBlock {
    case heading(level: Int, text: String)
    case paragraph(String)
    case bullets([String])
    case ordered([String])
    case code(String)

    @ViewBuilder
    func view(accent: Color) -> some View {
        switch self {
        case .heading(let level, let text):
            Text(companionInlineMarkdown(text))
                .font(.system(size: level <= 1 ? 19 : (level == 2 ? 16 : 15), weight: .semibold))
                .frame(maxWidth: .infinity, alignment: .leading)
        case .paragraph(let text):
            Text(companionInlineMarkdown(text))
                .font(.system(size: 15))
                .lineSpacing(4)
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
        case .bullets(let items):
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("•").foregroundStyle(accent)
                        Text(companionInlineMarkdown(item)).font(.system(size: 15)).lineSpacing(4)
                        Spacer(minLength: 0)
                    }
                }
            }
        case .ordered(let items):
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(items.enumerated()), id: \.offset) { idx, item in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("\(idx + 1).").foregroundStyle(accent).monospacedDigit()
                        Text(companionInlineMarkdown(item)).font(.system(size: 15)).lineSpacing(4)
                        Spacer(minLength: 0)
                    }
                }
            }
        case .code(let code):
            Text(code)
                .font(.system(size: 13, design: .monospaced))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(Color.primary.opacity(0.06))
                .clipShape(RoundedRectangle(cornerRadius: 8))
        }
    }

    static func parse(_ text: String) -> [CompanionMarkdownBlock] {
        var blocks: [CompanionMarkdownBlock] = []
        let lines = text.components(separatedBy: "\n")
        var index = 0
        var paragraph: [String] = []

        func flushParagraph() {
            if !paragraph.isEmpty {
                let joined = paragraph.joined(separator: " ").trimmingCharacters(in: .whitespaces)
                if !joined.isEmpty { blocks.append(.paragraph(joined)) }
                paragraph = []
            }
        }

        while index < lines.count {
            let raw = lines[index]
            let trimmed = raw.trimmingCharacters(in: .whitespaces)

            if trimmed.hasPrefix("```") {
                flushParagraph()
                var code: [String] = []
                index += 1
                while index < lines.count,
                    !lines[index].trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                    code.append(lines[index])
                    index += 1
                }
                index += 1  // closing fence
                blocks.append(.code(code.joined(separator: "\n")))
                continue
            }
            if trimmed.isEmpty {
                flushParagraph()
                index += 1
                continue
            }
            if trimmed.hasPrefix("#") {
                flushParagraph()
                let hashes = trimmed.prefix(while: { $0 == "#" }).count
                let headingText = String(trimmed.dropFirst(hashes)).trimmingCharacters(in: .whitespaces)
                blocks.append(.heading(level: min(hashes, 3), text: headingText))
                index += 1
                continue
            }
            if isBullet(trimmed) {
                flushParagraph()
                var items: [String] = []
                while index < lines.count, isBullet(lines[index].trimmingCharacters(in: .whitespaces)) {
                    items.append(stripBullet(lines[index].trimmingCharacters(in: .whitespaces)))
                    index += 1
                }
                blocks.append(.bullets(items))
                continue
            }
            if isOrdered(trimmed) {
                flushParagraph()
                var items: [String] = []
                while index < lines.count, isOrdered(lines[index].trimmingCharacters(in: .whitespaces)) {
                    items.append(stripOrdered(lines[index].trimmingCharacters(in: .whitespaces)))
                    index += 1
                }
                blocks.append(.ordered(items))
                continue
            }
            paragraph.append(trimmed)
            index += 1
        }
        flushParagraph()
        return blocks
    }

    private static func isBullet(_ s: String) -> Bool {
        s.hasPrefix("- ") || s.hasPrefix("* ") || s.hasPrefix("• ")
    }
    private static func stripBullet(_ s: String) -> String {
        String(s.dropFirst(2)).trimmingCharacters(in: .whitespaces)
    }
    private static func isOrdered(_ s: String) -> Bool {
        guard let dot = s.firstIndex(of: ".") else { return false }
        let prefix = s[s.startIndex..<dot]
        return !prefix.isEmpty && prefix.allSatisfy(\.isNumber) && s[dot...].hasPrefix(". ")
    }
    private static func stripOrdered(_ s: String) -> String {
        guard let dot = s.firstIndex(of: ".") else { return s }
        return String(s[s.index(after: dot)...]).trimmingCharacters(in: .whitespaces)
    }
}

private func companionInlineMarkdown(_ string: String) -> AttributedString {
    (try? AttributedString(
        markdown: string,
        options: AttributedString.MarkdownParsingOptions(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        )
    )) ?? AttributedString(string)
}
