import SwiftUI
import WaiComputerKit

/// The compiled-wiki "Brain" view: a read-only browse of what WaiComputer
/// durably knows — long-term memory sections + the entity knowledge graph.
struct MacBrainView: View {
    let apiClient: APIClient

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacBrainViewModel

    init(apiClient: APIClient) {
        self.apiClient = apiClient
        _model = StateObject(wrappedValue: MacBrainViewModel(apiClient: apiClient))
    }

    var body: some View {
        Group {
            if model.loading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let message = model.errorMessage {
                VStack(spacing: Spacing.md) {
                    ContentUnavailableViewCompat(
                        t("Couldn't load your brain", "Не удалось загрузить мозг"),
                        systemImage: "exclamationmark.triangle",
                        description: Text(message)
                    )
                    Button(t("Retry", "Повторить")) {
                        Task { await model.load() }
                    }
                    .buttonStyle(.borderedProminent)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let brain = model.brain {
                content(brain)
            } else {
                ContentUnavailableViewCompat(
                    t("Your brain is empty", "Ваш мозг пуст"),
                    systemImage: "brain",
                    description: Text(t(
                        "As you record and add content, durable facts and people appear here.",
                        "По мере записей и добавления материалов здесь появятся факты и люди."
                    ))
                )
            }
        }
        .task { await model.load() }
    }

    private func content(_ brain: BrainProjection) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(t("Brain", "Мозг"))
                        .font(Typography.displaySmall)
                    Text(t("What WaiComputer durably knows about you.",
                           "Что WaiComputer надёжно знает о вас."))
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }

                // Memory sections (human / topics / preferences …)
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

                // Entity pages (knowledge graph)
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
            .padding(Spacing.xl)
            .frame(maxWidth: 760, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .topLeading)
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

@MainActor
final class MacBrainViewModel: ObservableObject {
    @Published var brain: BrainProjection?
    @Published var loading = true
    @Published var errorMessage: String?

    private let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        loading = true
        errorMessage = nil
        defer { loading = false }
        do {
            // No-fallback: a transient backend failure must NOT masquerade as
            // "your brain is empty" — surface it with a Retry.
            brain = try await apiClient.getBrain()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
