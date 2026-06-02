import SwiftUI
import WaiComputerKit

/// Detail screen for one Item: title, summary, the key-moments table, key points.
/// Loads the full item (with summary) on appear from a lightweight list entry.
struct ItemDetailView: View {
    let itemId: String
    let apiClient: APIClient
    var onDeleted: (() -> Void)?

    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.dismiss) private var dismiss
    @State private var item: Item?
    @State private var isLoading = true
    @State private var errorMessage: String?

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        Group {
            if let item {
                content(item)
            } else if isLoading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ContentUnavailableViewCompat(
                    t("Couldn't load", "Не удалось загрузить"),
                    systemImage: "exclamationmark.triangle",
                    description: Text(errorMessage ?? t("Try again.", "Попробуйте снова."))
                )
            }
        }
        .navigationTitle(item?.kind.capitalized ?? t("Item", "Материал"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if item != nil {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .destructive) {
                        Task { await delete() }
                    } label: {
                        Image(systemName: "trash")
                    }
                }
            }
        }
        .task { await load() }
    }

    private func content(_ item: Item) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                header(item)

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

                let keyMoments = item.summary?.keyMoments ?? []
                if !keyMoments.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text(t("Key moments", "Ключевые моменты")).font(Typography.headingSmall)
                        ForEach(keyMoments) { moment in
                            keyMomentRow(moment)
                        }
                    }
                }

                let keyPoints = item.summary?.keyPoints ?? []
                if !keyPoints.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Key points", "Главное")).font(Typography.headingSmall)
                        ForEach(Array(keyPoints.enumerated()), id: \.offset) { _, point in
                            HStack(alignment: .top, spacing: Spacing.xs) {
                                Text("•").foregroundStyle(Palette.textTertiary)
                                Text(point).font(Typography.bodySmall)
                            }
                        }
                    }
                }
            }
            .padding(Spacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func header(_ item: Item) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(item.kind.uppercased())
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
            Text(item.title ?? t("Untitled", "Без названия"))
                .font(Typography.displaySmall)
                .textSelection(.enabled)
            if let url = item.url, let dest = URL(string: url) {
                Link(url, destination: dest)
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

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            item = try await apiClient.getItem(id: itemId)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func delete() async {
        do {
            try await apiClient.deleteItem(id: itemId)
            onDeleted?()
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
