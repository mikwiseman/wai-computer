import Foundation
import SwiftUI
import WaiComputerKit

/// Detail pane for one Item: summary first, then the original material/source.
struct MacItemDetailView: View {
    let item: Item
    let onDelete: () -> Void
    let isGeneratingSummaryAudio: Bool
    let isDownloadingSummaryAudio: Bool
    let isPlayingSummaryAudio: Bool
    let onGenerateSummaryAudio: () -> Void
    let onPlaySummaryAudio: () -> Void

    @EnvironmentObject private var languageManager: LanguageManager
    @State private var showDeleteConfirm = false
    @State private var contentCache = MacItemDetailContentCache()

    init(
        item: Item,
        onDelete: @escaping () -> Void,
        isGeneratingSummaryAudio: Bool,
        isDownloadingSummaryAudio: Bool,
        isPlayingSummaryAudio: Bool,
        onGenerateSummaryAudio: @escaping () -> Void,
        onPlaySummaryAudio: @escaping () -> Void
    ) {
        self.item = item
        self.onDelete = onDelete
        self.isGeneratingSummaryAudio = isGeneratingSummaryAudio
        self.isDownloadingSummaryAudio = isDownloadingSummaryAudio
        self.isPlayingSummaryAudio = isPlayingSummaryAudio
        self.onGenerateSummaryAudio = onGenerateSummaryAudio
        self.onPlaySummaryAudio = onPlaySummaryAudio
    }

    private var summaryAudio: SummaryAudioState? { item.summaryAudio }

    private func hasUsefulSummary(_ content: MacItemDetailContent) -> Bool {
        let text = content.summary?.summary?.trimmingCharacters(in: .whitespacesAndNewlines)
        return !(text?.isEmpty ?? true)
            || !content.keyPointRows.isEmpty
            || !content.keyMoments.isEmpty
            || !content.topics.isEmpty
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        let content = contentCache.content(for: item)

        // List gives item details the same AppKit-backed row reuse as
        // recordings/search. Large pasted notes are split into rows below so
        // scrolling does not require one huge Text layout pass.
        List {
            header
                .padding(.top, Spacing.xl)
                .padding(.bottom, Spacing.lg)
                .itemDetailListRow()

            if item.state == "needs_input", item.summary?.summary == nil {
                needsInputBanner
                    .padding(.bottom, Spacing.lg)
                    .itemDetailListRow()
            }

            summarySection(content)
                .padding(.bottom, Spacing.lg)
                .itemDetailListRow()

            originalMaterialSection(content)
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .accessibilityIdentifier("item-detail-root")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack {
                Text(ItemKindLabel.text(item.kind, language: languageManager.current) ?? item.kind)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
                Spacer()
                Button(role: .destructive) {
                    showDeleteConfirm = true
                } label: {
                    Image(systemName: "trash")
                }
                .buttonStyle(.borderless)
                .help(t("Delete", "Удалить"))
                .accessibilityLabel(t("Delete", "Удалить"))
                .confirmationDialog(
                    t("Delete this item?", "Удалить материал?"),
                    isPresented: $showDeleteConfirm
                ) {
                    Button(t("Delete", "Удалить"), role: .destructive) {
                        onDelete()
                    }
                    Button(t("Cancel", "Отмена"), role: .cancel) {}
                } message: {
                    Text(t("This action cannot be undone.", "Это действие нельзя отменить."))
                }
            }
            Text(item.title ?? t("Untitled", "Без названия"))
                .font(Typography.displaySmall)
                .textSelection(.enabled)
            Text(itemSubtitle)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2)
        }
    }

    private var itemSubtitle: String {
        var pieces = [sourceLabel(item.source)]
        if let status = statusLabel(item.status) {
            pieces.append(status)
        }
        pieces.append(formattedDate(item.occurredAt ?? item.createdAt))
        return pieces
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " / ")
    }

    private func sourceLabel(_ source: String) -> String {
        if source.hasPrefix("mcp:") {
            return t("Connected source", "Подключённый источник")
        }
        switch source {
        case "url":
            return t("Link", "Ссылка")
        case "paste":
            return t("Pasted text", "Вставленный текст")
        case "upload":
            return t("Upload", "Файл")
        case "telegram":
            return "Telegram"
        default:
            return source
        }
    }

    /// nil for "ready" — a finished item needs no status badge.
    private func statusLabel(_ status: String) -> String? {
        switch status {
        case "ready":
            return nil
        case "fetching":
            return t("Fetching", "Загружается")
        case "summarizing":
            return t("Summarizing", "Обрабатывается")
        case "failed":
            return t("Failed", "Ошибка")
        case "needs_input":
            return t("Needs input", "Нужны данные")
        default:
            return status
        }
    }

    private static let isoWithFractionalSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let isoPlain: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    /// Backend dates are ISO-8601 strings, sometimes with fractional seconds.
    /// Keeps the raw string if parsing fails — never invents a date.
    private func formattedDate(_ iso: String) -> String {
        guard let date = Self.isoWithFractionalSeconds.date(from: iso)
            ?? Self.isoPlain.date(from: iso) else {
            return iso
        }
        return MacDateFormatting.string(
            from: date,
            dateStyle: .medium,
            timeStyle: .short,
            language: languageManager.current
        )
    }

    private var needsInputBanner: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: "doc.badge.ellipsis")
                .foregroundStyle(Palette.accent)
            Text(t(
                "Couldn't read this automatically. Share the file again or paste the text.",
                "Не удалось прочитать автоматически. Поделитесь файлом снова или вставьте текст."
            ))
            .font(Typography.bodySmall)
            .foregroundStyle(Palette.textSecondary)
        }
        .padding(Spacing.md)
        .background(Palette.accentSubtle)
        .clipShape(RoundedRectangle(cornerRadius: Radius.md))
    }

    private func summarySection(_ content: MacItemDetailContent) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Label(t("Summary", "Сводка"), systemImage: "doc.text.magnifyingglass")
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textPrimary)

            if hasUsefulSummary(content) {
                summaryAudioControls

                if let text = content.summary?.summary?.trimmingCharacters(in: .whitespacesAndNewlines),
                   !text.isEmpty {
                    Text(text)
                        .font(Typography.reading)
                        .lineSpacing(6)
                        .textSelection(.enabled)
                }

                if !content.keyPointRows.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Key points", "Главное"))
                            .waiSectionHeader()
                        ForEach(content.keyPointRows) { row in
                            HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                                Circle()
                                    .fill(Palette.accent)
                                    .frame(width: 5, height: 5)
                                Text(row.text)
                                    .font(Typography.bodySmall)
                                    .lineSpacing(4)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                }

                if !content.keyMoments.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text(t("Key moments", "Ключевые моменты"))
                            .waiSectionHeader()
                        ForEach(content.keyMoments) { moment in
                            keyMomentRow(moment)
                        }
                    }
                }

                if !content.topics.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text(t("Topics", "Темы"))
                            .waiSectionHeader()
                        LazyVGrid(
                            columns: [GridItem(.adaptive(minimum: 96), spacing: 6, alignment: .leading)],
                            alignment: .leading,
                            spacing: 6
                        ) {
                            ForEach(content.topics, id: \.self) { topic in
                                Text(topic)
                                    .font(Typography.labelSmall)
                                    .foregroundStyle(Palette.textSecondary)
                                    .padding(.horizontal, Spacing.sm)
                                    .padding(.vertical, 4)
                                    .background(Palette.surfaceSubtle)
                                    .clipShape(Capsule())
                            }
                        }
                    }
                }
            } else if item.status == "failed" {
                failedSummaryBanner
            } else {
                HStack(alignment: .center, spacing: Spacing.sm) {
                    if item.status == "fetching" || item.status == "summarizing" {
                        ProgressView().controlSize(.small)
                    }
                    Text(summaryPlaceholder)
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }
                .padding(Spacing.md)
                .background(Palette.surfaceSubtle)
                .clipShape(RoundedRectangle(cornerRadius: Radius.md))
            }
        }
        .accessibilityIdentifier("item-summary-section")
    }

    private var failedSummaryBanner: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(alignment: .top, spacing: Spacing.sm) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(Palette.danger)
                Text(t("Couldn't summarize this item.", "Не удалось обработать материал."))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textPrimary)
            }
            if let message = item.error?.message, !message.isEmpty {
                Text(message)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .padding(Spacing.md)
        .background(Palette.danger.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: Radius.md))
        .accessibilityIdentifier("item-summary-failed")
    }

    private var summaryPlaceholder: String {
        switch item.status {
        case "fetching":
            return t("Reading the source material…", "Читаем исходный материал…")
        case "summarizing":
            return t("Building the summary…", "Готовим сводку…")
        default:
            return t("No summary yet.", "Сводки пока нет.")
        }
    }

    @ViewBuilder
    private func originalMaterialSection(_ content: MacItemDetailContent) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Label(t("Original Material", "Исходный материал"), systemImage: "doc.text")
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textPrimary)

            sourceMetadata
        }
        .padding(.bottom, content.originalBodyChunks.isEmpty ? Spacing.sm : Spacing.md)
        .itemDetailListRow()
        .accessibilityIdentifier("item-original-material-section")

        if content.originalBodyChunks.isEmpty {
            Text(t(
                "Original text is not available in this item yet.",
                "Исходный текст этого материала пока недоступен."
            ))
            .font(Typography.bodySmall)
            .foregroundStyle(Palette.textSecondary)
            .padding(.bottom, Spacing.xl)
            .itemDetailListRow()
        } else {
            ForEach(content.originalBodyChunks) { chunk in
                Text(chunk.text)
                    .font(Typography.reading)
                    .lineSpacing(6)
                    .textSelection(.enabled)
                    .padding(.vertical, Spacing.xs)
                    .itemDetailListRow()
            }
        }
    }

    private var sourceMetadata: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            metadataLine(title: t("Source", "Источник"), value: sourceLabel(item.source))
            if let sourceRef = item.sourceRef, !sourceRef.isEmpty {
                metadataLine(title: t("Reference", "Ссылка-источник"), value: sourceRef)
            }
            if let url = item.url, let destination = URL(string: url) {
                HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                    Text(t("URL", "URL"))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                        .frame(width: 116, alignment: .leading)
                    Link(url, destination: destination)
                        .font(Typography.bodySmall)
                        .lineLimit(1)
                }
            }
            metadataLine(title: t("Created", "Создано"), value: formattedDate(item.createdAt))
        }
    }

    private func metadataLine(title: String, value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
            Text(title)
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
                .frame(width: 116, alignment: .leading)
            Text(value)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2)
                .textSelection(.enabled)
        }
    }

    @ViewBuilder
    private var summaryAudioControls: some View {
        HStack(alignment: .center, spacing: Spacing.sm) {
            if summaryAudio?.isSucceeded == true {
                Button(action: onPlaySummaryAudio) {
                    Label(
                        summaryAudioPlaybackButtonTitle,
                        systemImage: isPlayingSummaryAudio ? "stop.fill" : "play.fill"
                    )
                }
                .buttonStyle(WaiGhostButtonStyle())
                .disabled(isDownloadingSummaryAudio)
                .accessibilityIdentifier("item-summary-audio-play-button")
                .accessibilityLabel(summaryAudioPlaybackButtonTitle)

                Text(isDownloadingSummaryAudio ? t("Loading audio…", "Загружаем аудио…") : t("Audio ready", "Аудио готово"))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
            } else {
                Button(action: onGenerateSummaryAudio) {
                    Label(
                        summaryAudioButtonTitle,
                        systemImage: summaryAudio?.isFailed == true ? "arrow.clockwise" : "waveform"
                    )
                }
                .buttonStyle(WaiGhostButtonStyle())
                .disabled(isGeneratingSummaryAudio)
                .accessibilityIdentifier("item-summary-audio-create-button")
                .accessibilityLabel(summaryAudioButtonTitle)
            }
        }

        if isGeneratingSummaryAudio || summaryAudio?.isActive == true {
            HStack(alignment: .center, spacing: Spacing.sm) {
                ProgressView()
                    .controlSize(.small)
                Text(summaryAudio?.message ?? t("Creating summary audio…", "Создаем аудио сводки…"))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
            }
            .padding(.horizontal, Spacing.md)
            .padding(.vertical, Spacing.sm)
            .background(Palette.accentSubtle)
            .clipShape(RoundedRectangle(cornerRadius: Radius.md))
            .accessibilityIdentifier("item-summary-audio-progress")
        } else if summaryAudio?.isFailed == true {
            Text(summaryAudio?.errorMessage ?? t("Summary audio generation failed.", "Не удалось создать аудио сводки."))
                .font(Typography.caption)
                .foregroundStyle(Palette.danger)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("item-summary-audio-failure")
        }
    }

    private var summaryAudioButtonTitle: String {
        if isGeneratingSummaryAudio || summaryAudio?.isActive == true {
            return t("Creating Audio", "Создаем аудио")
        }
        if summaryAudio?.isFailed == true {
            return t("Try Audio Again", "Повторить аудио")
        }
        return t("Create Audio", "Создать аудио")
    }

    private var summaryAudioPlaybackButtonTitle: String {
        if isDownloadingSummaryAudio {
            return t("Loading Audio", "Загружаем аудио")
        }
        if isPlayingSummaryAudio {
            return t("Stop Audio", "Остановить аудио")
        }
        return t("Play Audio", "Воспроизвести аудио")
    }

    private func keyMomentRow(_ moment: KeyMoment) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Text(moment.timestamp ?? "—")
                .font(Typography.mono)
                .foregroundStyle(Palette.textSecondary)
                .frame(width: 56, alignment: .leading)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(moment.moment).font(Typography.bodySmall.weight(.medium))
                Text(moment.whyItMatters)
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
        .padding(.vertical, Spacing.xxs)
    }
}

private final class MacItemDetailContentCache {
    private var lastKey: MacItemDetailContentKey?
    private var cachedContent: MacItemDetailContent?

    func content(for item: Item) -> MacItemDetailContent {
        let key = MacItemDetailContentKey(item: item)
        if key == lastKey, let cachedContent {
            return cachedContent
        }

        let content = MacItemDetailContent(item: item)
        lastKey = key
        cachedContent = content
        return content
    }
}

private struct MacItemDetailContentKey: Equatable {
    let id: String
    let source: String
    let sourceRef: String?
    let url: String?
    let kind: String
    let title: String?
    let body: String?
    let occurredAt: String?
    let state: String
    let status: String
    let errorCode: String?
    let errorMessage: String?
    let folderId: String?
    let createdAt: String
    let summaryText: String?
    let keyPoints: [String]
    let topics: [String]
    let keyMoments: [MacItemKeyMomentSignature]
    let sentiment: String?

    init(item: Item) {
        id = item.id
        source = item.source
        sourceRef = item.sourceRef
        url = item.url
        kind = item.kind
        title = item.title
        body = item.body
        occurredAt = item.occurredAt
        state = item.state
        status = item.status
        errorCode = item.error?.code
        errorMessage = item.error?.message
        folderId = item.folderId
        createdAt = item.createdAt
        summaryText = item.summary?.summary
        keyPoints = item.summary?.keyPoints ?? []
        topics = item.summary?.topics ?? []
        keyMoments = (item.summary?.keyMoments ?? []).map(MacItemKeyMomentSignature.init)
        sentiment = item.summary?.sentiment
    }
}

private struct MacItemKeyMomentSignature: Equatable {
    let timestamp: String?
    let moment: String
    let whyItMatters: String
    let quote: String?
    let importance: String
    let startMs: Int?
    let endMs: Int?

    init(_ keyMoment: KeyMoment) {
        timestamp = keyMoment.timestamp
        moment = keyMoment.moment
        whyItMatters = keyMoment.whyItMatters
        quote = keyMoment.quote
        importance = keyMoment.importance
        startMs = keyMoment.startMs
        endMs = keyMoment.endMs
    }
}

private struct MacItemDetailContent {
    let summary: ItemSummary?
    let keyMoments: [KeyMoment]
    let keyPointRows: [ItemKeyPointRow]
    let topics: [String]
    let originalBodyChunks: [OriginalMaterialChunk]

    init(item: Item) {
        summary = item.summary
        keyMoments = item.summary?.keyMoments ?? []
        keyPointRows = (item.summary?.keyPoints ?? []).enumerated().map { index, text in
            ItemKeyPointRow(id: index, text: text)
        }
        topics = item.summary?.topics ?? []
        originalBodyChunks = Self.originalMaterialChunks(from: item.body)
    }

    private static let originalBodyChunkLimit = 1_800

    private static func originalMaterialChunks(from body: String?) -> [OriginalMaterialChunk] {
        guard let normalized = body?.trimmingCharacters(in: .whitespacesAndNewlines),
              !normalized.isEmpty else {
            return []
        }

        var chunks: [OriginalMaterialChunk] = []
        var chunkId = 0
        var start = normalized.startIndex

        while start < normalized.endIndex {
            let hardEnd = normalized.index(
                start,
                offsetBy: originalBodyChunkLimit,
                limitedBy: normalized.endIndex
            ) ?? normalized.endIndex
            var end = hardEnd

            if hardEnd < normalized.endIndex,
               let newline = normalized[start..<hardEnd].lastIndex(of: "\n"),
               normalized.distance(from: start, to: newline) > originalBodyChunkLimit / 2 {
                end = normalized.index(after: newline)
            }

            let text = String(normalized[start..<end])
                .trimmingCharacters(in: .newlines)
            if !text.isEmpty {
                chunks.append(OriginalMaterialChunk(id: chunkId, text: text))
                chunkId += 1
            }

            start = end
        }

        return chunks
    }
}

private struct ItemKeyPointRow: Identifiable, Equatable {
    let id: Int
    let text: String
}

private struct OriginalMaterialChunk: Identifiable, Equatable {
    let id: Int
    let text: String
}

private extension View {
    func itemDetailListRow() -> some View {
        self
            .frame(maxWidth: MacMainLayoutMetrics.readingMeasure, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .listRowInsets(EdgeInsets(
                top: 0,
                leading: Spacing.xl,
                bottom: 0,
                trailing: Spacing.xl
            ))
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
    }
}
