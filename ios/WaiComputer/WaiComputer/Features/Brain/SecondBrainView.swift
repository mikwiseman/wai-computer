import SwiftUI
import WaiComputerKit

/// The "Brain" tab: the second-brain home. A universal feed of captured items
/// (links, notes, files, MCP-ingested rows) with add-anything capture, plus
/// entries to the compiled-wiki Memory, the Review queue, and Comparisons.
struct SecondBrainView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: ContentFeedViewModel
    @State private var showAdd = false

    init(apiClient: APIClient) {
        _model = StateObject(wrappedValue: ContentFeedViewModel(apiClient: apiClient))
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    NavigationLink {
                        MemoryView(apiClient: model.apiClient)
                    } label: {
                        entryRow(icon: "brain", title: t("Memory", "Память"), badge: nil)
                    }
                    NavigationLink {
                        ReviewView(apiClient: model.apiClient)
                    } label: {
                        entryRow(icon: "tray.full", title: t("Review", "На проверку"),
                                 badge: model.pendingReviewCount)
                    }
                }

                Section(header: Text(t("Captured", "Сохранённое"))) {
                    if model.entries.isEmpty {
                        Text(t("Tap + to save a link or a note — summarized and searchable forever.",
                               "Нажмите +, чтобы сохранить ссылку или заметку — с конспектом и навсегда в поиске."))
                            .font(Typography.bodySmall)
                            .foregroundStyle(Palette.textSecondary)
                    } else {
                        ForEach(model.entries) { entry in
                            NavigationLink {
                                ItemDetailView(itemId: entry.id, apiClient: model.apiClient) {
                                    Task { await model.load() }
                                }
                            } label: {
                                row(entry)
                            }
                        }
                        .onDelete { offsets in
                            let ids = offsets.map { model.entries[$0].id }
                            Task { for id in ids { await model.delete(id) } }
                        }
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle(t("Brain", "Мозг"))
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showAdd = true } label: { Image(systemName: "plus") }
                        .accessibilityIdentifier("brain-add-button")
                }
            }
            .sheet(isPresented: $showAdd) {
                AddAnythingSheet(isPresented: $showAdd, isAdding: model.isAdding) { text in
                    Task {
                        if await model.add(text) != nil { showAdd = false }
                    }
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
    }

    private func entryRow(icon: String, title: String, badge: Int?) -> some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: icon)
                .font(.system(size: 15))
                .foregroundStyle(Palette.accent)
                .frame(width: 24)
            Text(title).font(Typography.body)
            Spacer()
            if let badge, badge > 0 {
                Text("\(badge)")
                    .font(Typography.labelSmall.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 2)
                    .background(Palette.accent, in: Capsule())
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
