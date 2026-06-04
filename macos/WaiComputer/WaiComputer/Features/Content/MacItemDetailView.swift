import SwiftUI
import WaiComputerKit

/// Detail pane for one Item: title, summary, the key-moments table, key points.
struct MacItemDetailView: View {
    let item: Item
    let onDelete: () -> Void
    let isGeneratingSummaryAudio: Bool
    let isDownloadingSummaryAudio: Bool
    let isPlayingSummaryAudio: Bool
    let onGenerateSummaryAudio: () -> Void
    let onPlaySummaryAudio: () -> Void

    @EnvironmentObject private var languageManager: LanguageManager

    private var keyMoments: [KeyMoment] { item.summary?.keyMoments ?? [] }
    private var keyPoints: [String] { item.summary?.keyPoints ?? [] }
    private var summaryAudio: SummaryAudioState? { item.summaryAudio }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                header

                if item.state == "needs_input", item.summary?.summary == nil {
                    Text(t("Couldn't read this automatically — share the file or paste the text.",
                           "Не удалось прочитать автоматически — поделитесь файлом или вставьте текст."))
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }

                if let summary = item.summary?.summary {
                    summaryAudioControls

                    Text(summary)
                        .font(Typography.body)
                        .foregroundStyle(Palette.textSecondary)
                        .textSelection(.enabled)
                }

                if !keyMoments.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text(t("Key moments", "Ключевые моменты"))
                            .font(Typography.headingSmall)
                        ForEach(keyMoments) { moment in
                            keyMomentRow(moment)
                        }
                    }
                }

                if !keyPoints.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Key points", "Главное"))
                            .font(Typography.headingSmall)
                        ForEach(Array(keyPoints.enumerated()), id: \.offset) { _, point in
                            HStack(alignment: .top, spacing: Spacing.xs) {
                                Text("•").foregroundStyle(Palette.textTertiary)
                                Text(point).font(Typography.bodySmall)
                            }
                        }
                    }
                }
            }
            .padding(Spacing.xl)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
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
            if let url = item.url {
                Link(url, destination: URL(string: url) ?? URL(string: "https://wai.computer")!)
                    .font(Typography.bodySmall)
                    .lineLimit(1)
            }
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
                .foregroundStyle(Palette.accent)
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
