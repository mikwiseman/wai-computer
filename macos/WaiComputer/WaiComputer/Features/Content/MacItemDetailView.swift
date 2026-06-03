import SwiftUI
import WaiComputerKit

/// Detail pane for one Item: title, summary, the key-moments table, key points.
struct MacItemDetailView: View {
    let item: Item
    let onDelete: () -> Void

    @EnvironmentObject private var languageManager: LanguageManager

    private var keyMoments: [KeyMoment] { item.summary?.keyMoments ?? [] }
    private var keyPoints: [String] { item.summary?.keyPoints ?? [] }

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
