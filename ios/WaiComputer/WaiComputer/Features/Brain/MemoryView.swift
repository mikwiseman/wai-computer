import SwiftUI
import WaiComputerKit

/// The compiled-wiki view of what WaiComputer durably knows — long-term memory
/// sections + the entity knowledge graph. Read-only. Ported from macOS MacBrainView;
/// titled "Memory" since the iOS tab is already "Brain".
struct MemoryView: View {
    let apiClient: APIClient

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MemoryViewModel

    init(apiClient: APIClient) {
        self.apiClient = apiClient
        _model = StateObject(wrappedValue: MemoryViewModel(apiClient: apiClient))
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        Group {
            if model.loading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let brain = model.brain, hasContent(brain) {
                content(brain)
            } else {
                ContentUnavailableViewCompat(
                    t("Nothing learned yet", "Пока ничего не известно"),
                    systemImage: "brain",
                    description: Text(t(
                        "As you record and add content, durable facts and people appear here.",
                        "По мере записей и добавления материалов здесь появятся факты и люди."
                    ))
                )
            }
        }
        .navigationTitle(t("Memory", "Память"))
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load() }
    }

    private func hasContent(_ brain: BrainProjection) -> Bool {
        brain.entityCount > 0 || brain.memorySections.contains { !$0.body.isEmpty }
    }

    private func content(_ brain: BrainProjection) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                ForEach(brain.memorySections) { section in
                    if !section.body.isEmpty {
                        VStack(alignment: .leading, spacing: Spacing.xs) {
                            Text(sectionTitle(section.label))
                                .font(Typography.headingSmall)
                            Text(section.body)
                                .font(Typography.reading)
                                .lineSpacing(5)
                                .foregroundStyle(Palette.textSecondary)
                                .textSelection(.enabled)
                        }
                    }
                }

                if !brain.entityPages.isEmpty {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text(t("People & topics", "Люди и темы") + " (\(brain.entityCount))")
                            .font(Typography.headingSmall)
                        ForEach(brain.entityPages) { page in
                            entityCard(page)
                        }
                    }
                }
            }
            .padding(Spacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func entityCard(_ page: BrainEntityPage) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: entityIcon(page.type))
                    .font(.system(size: 11))
                    .foregroundStyle(Palette.accent)
                Text(page.name).font(Typography.bodySmall.weight(.medium))
                Text(page.type.uppercased())
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
            ForEach(Array(page.relations.enumerated()), id: \.offset) { _, rel in
                Text("→ \(rel.relationType ?? "related to") \(rel.targetName)")
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
                    .padding(.leading, Spacing.md)
            }
        }
        .padding(Spacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func entityIcon(_ type: String) -> String {
        switch type {
        case "person": return "person"
        case "project": return "folder"
        case "organization": return "building.2"
        default: return "tag"
        }
    }

    private func sectionTitle(_ label: String) -> String {
        switch label {
        case "human": return t("About you", "О вас")
        case "topics": return t("Recurring topics", "Повторяющиеся темы")
        case "preferences": return t("Preferences", "Предпочтения")
        default: return label.capitalized
        }
    }
}

@MainActor
final class MemoryViewModel: ObservableObject {
    @Published var brain: BrainProjection?
    @Published var loading = true

    private let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        loading = true
        defer { loading = false }
        brain = try? await apiClient.getBrain()
    }
}
