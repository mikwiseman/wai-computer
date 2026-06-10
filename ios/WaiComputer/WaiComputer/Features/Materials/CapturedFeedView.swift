import SwiftUI
import WaiComputerKit

/// The captured-items feed (links, notes, files) — the Materials tab's main
/// list. Includes the multi-select → Compare flow.
struct CapturedFeedView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @ObservedObject var model: ContentFeedViewModel
    @State private var showAdd = false
    @State private var comparisonRoute: ComparisonRoute?

    private struct ComparisonRoute: Identifiable, Hashable { let id: String }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        List {
            if model.entries.isEmpty {
                Text(t("Tap + to save a link or a note — summarized and searchable forever.",
                       "Нажмите +, чтобы сохранить ссылку или заметку — с конспектом и навсегда в поиске."))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
            } else {
                ForEach(model.entries) { entry in
                    if model.isSelecting {
                        Button { model.toggleCompare(entry.id) } label: {
                            HStack(spacing: Spacing.sm) {
                                Image(systemName: model.compareSelection.contains(entry.id) ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(model.compareSelection.contains(entry.id) ? Palette.accent : Palette.textTertiary)
                                row(entry)
                            }
                        }
                        .buttonStyle(.plain)
                    } else {
                        NavigationLink {
                            ItemDetailView(itemId: entry.id, apiClient: model.apiClient) {
                                Task { await model.load() }
                            }
                        } label: {
                            row(entry)
                        }
                    }
                }
                .onDelete { offsets in
                    let ids = offsets.map { model.entries[$0].id }
                    Task { for id in ids { await model.delete(id) } }
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(t("Materials", "Материалы"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                if !model.entries.isEmpty {
                    Button(model.isSelecting ? t("Done", "Готово") : t("Select", "Выбрать")) {
                        model.toggleSelecting()
                    }
                }
            }
            ToolbarItemGroup(placement: .topBarTrailing) {
                if model.isSelecting {
                    Button {
                        Task {
                            await model.compareSelected()
                            if let id = model.createdComparisonId {
                                comparisonRoute = ComparisonRoute(id: id)
                                model.createdComparisonId = nil
                            }
                        }
                    } label: {
                        Text(model.isComparing
                             ? t("Comparing…", "Сравниваю…")
                             : t("Compare (\(model.compareSelection.count))", "Сравнить (\(model.compareSelection.count))"))
                    }
                    .disabled(!model.canCompare || model.isComparing)
                } else {
                    Button { showAdd = true } label: { Image(systemName: "plus") }
                }
            }
        }
        .navigationDestination(item: $comparisonRoute) { route in
            ComparisonDetailView(apiClient: model.apiClient, comparisonId: route.id)
        }
        .sheet(isPresented: $showAdd) {
            AddAnythingSheet(isPresented: $showAdd, isAdding: model.isAdding) { text in
                Task { if await model.add(text) != nil { showAdd = false } }
            }
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .overlay(alignment: .bottom) {
            if let error = model.errorMessage {
                Text(error)
                    .font(Typography.bodySmall)
                    .foregroundStyle(.white)
                    .padding(Spacing.sm)
                    .background(.red, in: Capsule())
                    .padding(.bottom, Spacing.md)
            }
        }
    }

    private func row(_ entry: ItemListEntry) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(entry.title ?? t("Untitled", "Без названия"))
                .font(Typography.body.weight(.medium))
                .lineLimit(2)
            HStack(spacing: Spacing.xs) {
                Text(entry.kind.uppercased())
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.accent)
                if !entry.hasSummary {
                    Text(t("· summarizing…", "· конспект…"))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                }
            }
        }
        .padding(.vertical, Spacing.xxs)
    }
}
