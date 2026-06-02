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

                if let processingText = processingText {
                    HStack(alignment: .top, spacing: Spacing.sm) {
                        if item.status == "fetching" || item.status == "summarizing" {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundStyle(.red)
                        }
                        Text(processingText)
                            .font(Typography.bodySmall)
                            .foregroundStyle(item.status == "failed" ? .red : Palette.textSecondary)
                            .textSelection(.enabled)
                    }
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
                Text(kindLabel(item.kind))
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
                if let label = statusLabel(item.status) {
                    Text(label)
                        .font(Typography.labelSmall)
                        .foregroundStyle(statusColor(item.status))
                }
                Spacer()
                Button(role: .destructive, action: onDelete) {
                    Image(systemName: "trash")
                }
                .buttonStyle(.borderless)
                .help(t("Delete", "Удалить"))
            }
            Text(displayTitle)
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

    private var displayTitle: String {
        let trimmed = (item.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !isPlaceholderTitle(trimmed) {
            return trimmed
        }
        return item.url ?? t("Untitled", "Без названия")
    }

    private func isPlaceholderTitle(_ value: String) -> Bool {
        let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return normalized.isEmpty
            || normalized == "untitled"
            || normalized == "[untitled]"
            || normalized == "без названия"
            || normalized == "[без названия]"
    }

    private var processingText: String? {
        if item.status == "fetching" {
            return t("Fetching the source text…", "Получаем текст источника…")
        }
        if item.status == "summarizing", item.summary?.summary == nil {
            return t(
                "Extracted text is being summarized. This material will update automatically.",
                "Текст извлечён, идёт краткое содержание. Материал обновится автоматически."
            )
        }
        if item.status == "needs_input" {
            return item.error?.message ?? t(
                "Couldn't read this automatically — share the file or paste the text.",
                "Не удалось прочитать автоматически — поделитесь файлом или вставьте текст."
            )
        }
        if item.status == "failed" {
            return item.error?.message ?? t(
                "Couldn't process this material.",
                "Не удалось обработать этот материал."
            )
        }
        return nil
    }

    private func kindLabel(_ kind: String) -> String {
        switch kind {
        case "pdf": return "PDF"
        case "doc", "docx", "document": return t("DOC", "ДОК")
        case "presentation": return t("SLIDES", "СЛАЙДЫ")
        case "spreadsheet": return t("SHEET", "ТАБЛИЦА")
        default: return kind.uppercased()
        }
    }

    private func statusLabel(_ status: String) -> String? {
        switch status {
        case "fetching": return t("fetching…", "загрузка…")
        case "summarizing": return t("summarizing…", "обработка…")
        case "needs_input": return t("needs input", "нужен текст")
        case "failed": return t("failed", "ошибка")
        default: return nil
        }
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "needs_input", "failed": return .red
        default: return Palette.accent
        }
    }
}
