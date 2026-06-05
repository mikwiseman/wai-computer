import SwiftUI
import WaiComputerKit

/// The "Review" surface — the cherry-pick half of raw→valuable governance.
/// The nightly consolidator auto-saves confident, additive facts and parks
/// destructive corrections / low-confidence guesses here for a one-tap accept
/// or reject. Accepting promotes the fact into canonical memory; rejecting is
/// durable (the fact is never re-proposed).
struct MacReviewView: View {
    let apiClient: APIClient

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacReviewViewModel

    init(apiClient: APIClient) {
        self.apiClient = apiClient
        _model = StateObject(wrappedValue: MacReviewViewModel(apiClient: apiClient))
    }

    var body: some View {
        Group {
            if model.loading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.proposals.isEmpty {
                ContentUnavailableViewCompat(
                    t("All caught up", "Всё разобрано"),
                    systemImage: "checkmark.seal",
                    description: Text(t(
                        "New facts your brain isn't sure about will appear here for you to keep or discard.",
                        "Факты, в которых мозг не уверен, появятся здесь — оставить или отклонить."
                    ))
                )
            } else {
                content
            }
        }
        .task { await model.load() }
    }

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(t("Review", "На проверку"))
                        .font(Typography.displaySmall)
                    Text(t("Decide what's worth remembering.",
                           "Решите, что стоит запомнить."))
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }

                if let error = model.error {
                    Text(errorText(error))
                        .font(Typography.bodySmall)
                        .foregroundStyle(.red)
                }

                VStack(spacing: Spacing.sm) {
                    ForEach(model.proposals) { proposal in
                        proposalCard(proposal)
                    }
                }
            }
            .padding(Spacing.xl)
            .frame(maxWidth: 760, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
    }

    private func proposalCard(_ proposal: MemoryProposal) -> some View {
        let acting = model.actingIds.contains(proposal.id)
        return HStack(alignment: .top, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                HStack(spacing: Spacing.xs) {
                    Text(riskLabel(proposal))
                        .font(Typography.labelSmall)
                        .padding(.horizontal, Spacing.xs)
                        .padding(.vertical, 2)
                        .background(Palette.accentSubtle)
                        .clipShape(Capsule())
                    Text(sectionTitle(proposal.blockLabel))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                    Text("· \(Int((proposal.confidence * 100).rounded()))%")
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                }
                Text(proposal.content)
                    .font(Typography.reading)
                    .foregroundStyle(Palette.textPrimary)
                    .textSelection(.enabled)
                if proposal.operation == "replace_line", let target = proposal.targetLine,
                   !target.isEmpty {
                    Text(t("replaces: ", "заменяет: ") + target)
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                }
            }
            Spacer(minLength: Spacing.sm)
            HStack(spacing: Spacing.sm) {
                Button {
                    Task { await model.reject(proposal.id) }
                } label: {
                    Image(systemName: "xmark")
                        .font(Typography.headingSmall)
                        .foregroundStyle(Palette.textSecondary)
                        .frame(width: 30, height: 30)
                        .background(Palette.surfaceSubtle)
                        .clipShape(Circle())
                }
                .buttonStyle(.plain)
                .help(t("Reject", "Отклонить"))
                .accessibilityLabel(t("Reject", "Отклонить"))
                .disabled(acting)

                Button {
                    Task { await model.accept(proposal.id) }
                } label: {
                    Image(systemName: "checkmark")
                        .font(Typography.headingSmall)
                        .foregroundStyle(.white)
                        .frame(width: 30, height: 30)
                        .background(Palette.accent)
                        .clipShape(Circle())
                }
                .buttonStyle(.plain)
                .help(t("Accept", "Принять"))
                .accessibilityLabel(t("Accept", "Принять"))
                .disabled(acting)
            }
            .opacity(acting ? 0.5 : 1)
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func riskLabel(_ proposal: MemoryProposal) -> String {
        proposal.isHighRisk
            ? t("Correction", "Исправление")
            : t("New fact", "Новый факт")
    }

    private func errorText(_ error: MacReviewViewModel.ReviewError) -> String {
        switch error {
        case .load:
            return t("Couldn't load the review queue. Try again.",
                     "Не удалось загрузить очередь проверки. Попробуйте снова.")
        case .action:
            return t("That action didn't go through. Try again.",
                     "Действие не выполнилось. Попробуйте снова.")
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
final class MacReviewViewModel: ObservableObject {
    /// Semantic error kind — localized in the view via the in-app LanguageManager,
    /// never String(localized:) (which would follow the system locale instead).
    enum ReviewError {
        case load
        case action
    }

    @Published var proposals: [MemoryProposal] = []
    @Published var pendingCount = 0
    @Published var loading = true
    @Published var actingIds: Set<String> = []
    @Published var error: ReviewError?

    private let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        loading = true
        defer { loading = false }
        do {
            let list = try await apiClient.listMemoryProposals(status: "pending")
            proposals = list.proposals
            pendingCount = list.pendingCount
            error = nil
        } catch {
            self.error = .load
        }
    }

    func accept(_ id: String) async {
        await decide(id) { try await self.apiClient.acceptMemoryProposal(id: id) }
    }

    func reject(_ id: String) async {
        await decide(id) { try await self.apiClient.rejectMemoryProposal(id: id) }
    }

    private func decide(_ id: String, _ action: @escaping () async throws -> MemoryProposal) async {
        guard !actingIds.contains(id) else { return }
        actingIds.insert(id)
        defer { actingIds.remove(id) }
        do {
            _ = try await action()
            proposals.removeAll { $0.id == id }
            pendingCount = max(0, pendingCount - 1)
            error = nil
        } catch {
            self.error = .action
        }
    }
}
