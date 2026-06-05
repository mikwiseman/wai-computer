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

    private var summary: ItemSummary? { item.summary }
    private var keyMoments: [KeyMoment] { item.summary?.keyMoments ?? [] }
    private var keyPoints: [String] { item.summary?.keyPoints ?? [] }
    private var summaryAudio: SummaryAudioState? { item.summaryAudio }
    private var topics: [String] { item.summary?.topics ?? [] }

    private var hasUsefulSummary: Bool {
        let text = summary?.summary?.trimmingCharacters(in: .whitespacesAndNewlines)
        return !(text?.isEmpty ?? true) || !keyPoints.isEmpty || !keyMoments.isEmpty || !topics.isEmpty
    }

    private var originalBody: String? {
        let body = item.body?.trimmingCharacters(in: .whitespacesAndNewlines)
        return body?.isEmpty == false ? body : nil
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                header

                if item.state == "needs_input", item.summary?.summary == nil {
                    needsInputBanner
                }

                summarySection

                originalMaterialSection
            }
            .padding(Spacing.xl)
            .frame(maxWidth: 860, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("item-detail-root")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack {
                Text(item.kind.uppercased())
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
                Spacer()
                Button(role: .destructive, action: onDelete) {
                    Image(systemName: "trash")
                }
                .buttonStyle(.borderless)
                .help(t("Delete", "Удалить"))
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
        let pieces = [
            item.source,
            item.status,
            item.occurredAt ?? item.createdAt,
        ]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        return pieces.joined(separator: " / ")
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
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var summarySection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Label(t("Summary", "Сводка"), systemImage: "doc.text.magnifyingglass")
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textPrimary)

            if hasUsefulSummary {
                summaryAudioControls

                if let text = summary?.summary?.trimmingCharacters(in: .whitespacesAndNewlines),
                   !text.isEmpty {
                    Text(text)
                        .font(Typography.reading)
                        .lineSpacing(6)
                        .textSelection(.enabled)
                }

                if !keyPoints.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Key points", "Главное"))
                            .waiSectionHeader()
                        ForEach(Array(keyPoints.enumerated()), id: \.offset) { _, point in
                            HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                                Circle()
                                    .fill(Palette.accent)
                                    .frame(width: 5, height: 5)
                                Text(point)
                                    .font(Typography.bodySmall)
                                    .lineSpacing(4)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                }

                if !keyMoments.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text(t("Key moments", "Ключевые моменты"))
                            .waiSectionHeader()
                        ForEach(keyMoments) { moment in
                            keyMomentRow(moment)
                        }
                    }
                }

                if !topics.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text(t("Topics", "Темы"))
                            .waiSectionHeader()
                        LazyVGrid(
                            columns: [GridItem(.adaptive(minimum: 96), spacing: 6, alignment: .leading)],
                            alignment: .leading,
                            spacing: 6
                        ) {
                            ForEach(topics, id: \.self) { topic in
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
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .accessibilityIdentifier("item-summary-section")
    }

    private var summaryPlaceholder: String {
        switch item.status {
        case "fetching":
            return t("Reading the source material...", "Читаем исходный материал...")
        case "summarizing":
            return t("Building the summary...", "Готовим сводку...")
        default:
            return t("No summary yet.", "Сводки пока нет.")
        }
    }

    private var originalMaterialSection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Label(t("Original Material", "Исходный материал"), systemImage: "doc.text")
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textPrimary)

            sourceMetadata

            if let body = originalBody {
                Text(body)
                    .font(Typography.reading)
                    .lineSpacing(6)
                    .textSelection(.enabled)
                    .padding(.top, Spacing.xs)
            } else {
                Text(t(
                    "Original text is not available in this item yet.",
                    "Исходный текст этого материала пока недоступен."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            }
        }
        .accessibilityIdentifier("item-original-material-section")
    }

    private var sourceMetadata: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            metadataLine(title: t("Source", "Источник"), value: item.source)
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
            metadataLine(title: t("Created", "Создано"), value: item.createdAt)
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

                Text(isDownloadingSummaryAudio ? t("Loading audio...", "Загружаем аудио...") : t("Audio ready", "Аудио готово"))
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
                Text(summaryAudio?.message ?? t("Creating summary audio...", "Создаем аудио сводки..."))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
            }
            .padding(.horizontal, Spacing.md)
            .padding(.vertical, Spacing.sm)
            .background(Palette.recording.opacity(0.10))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .accessibilityIdentifier("item-summary-audio-progress")
        } else if summaryAudio?.isFailed == true {
            Text(summaryAudio?.errorMessage ?? t("Summary audio generation failed.", "Не удалось создать аудио сводки."))
                .font(Typography.caption)
                .foregroundStyle(Palette.recording)
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
