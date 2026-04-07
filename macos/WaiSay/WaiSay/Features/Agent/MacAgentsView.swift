import SwiftUI
import WaiSayKit

struct MacAgentsView: View {
    let apiClient: APIClient

    @State private var agents: [DigitalAgent] = []
    @State private var isLoading = false
    @State private var error: String?
    @State private var newAgentDescription = ""
    @State private var isCreating = false

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text("Digital Agents")
                    .font(Typography.displaySmall)
                Spacer()
                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                }
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.md)

            WaiDivider()

            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.xl) {
                    // Create agent section
                    createAgentSection

                    // Agent list
                    if agents.isEmpty && !isLoading {
                        emptyState
                    } else {
                        ForEach(agents) { agent in
                            AgentCard(
                                agent: agent,
                                onRun: { runAgent(agent) },
                                onDelete: { deleteAgent(agent) }
                            )
                        }
                    }
                }
                .padding(Spacing.lg)
            }
        }
        .task {
            await loadAgents()
        }
        .alert("Agent Error", isPresented: Binding(
            get: { error != nil },
            set: { if !$0 { error = nil } }
        )) {
            Button("OK") { error = nil }
        } message: {
            Text(error ?? "Something went wrong.")
        }
    }

    // MARK: - Create Agent

    private var createAgentSection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Text("CREATE AGENT")
                .waiSectionHeader()

            HStack(spacing: Spacing.md) {
                TextField("Describe what this agent should do...", text: $newAgentDescription, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(Typography.bodyLarge)
                    .lineLimit(1...3)
                    .padding(Spacing.md)
                    .background(Palette.surfaceSubtle)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .accessibilityIdentifier("agent-create-input")

                Button {
                    createAgent()
                } label: {
                    if isCreating {
                        ProgressView()
                            .controlSize(.small)
                            .frame(width: 28, height: 28)
                    } else {
                        Image(systemName: "plus")
                            .font(Typography.headingSmall)
                            .foregroundStyle(.white)
                            .frame(width: 28, height: 28)
                            .background(
                                newAgentDescription.trimmingCharacters(in: .whitespaces).isEmpty
                                    ? Palette.textTertiary
                                    : Palette.accent
                            )
                            .clipShape(Circle())
                    }
                }
                .buttonStyle(.plain)
                .disabled(newAgentDescription.trimmingCharacters(in: .whitespaces).isEmpty || isCreating)
                .accessibilityIdentifier("agent-create-button")
            }
        }
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: Spacing.md) {
            Spacer().frame(height: Spacing.xxxl)

            ContentUnavailableView(
                "No Agents",
                systemImage: "gearshape.2",
                description: Text("Create an agent to automate tasks like daily summaries or reminders.")
            )
        }
    }

    // MARK: - Actions

    private func loadAgents() async {
        isLoading = true
        do {
            agents = try await apiClient.listAgents()
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
        isLoading = false
    }

    private func createAgent() {
        let description = newAgentDescription.trimmingCharacters(in: .whitespaces)
        guard !description.isEmpty else { return }
        isCreating = true

        Task {
            do {
                let agent = try await apiClient.createAgent(description: description)
                agents.insert(agent, at: 0)
                newAgentDescription = ""
            } catch {
                self.error = error.userFacingMessage(context: .generic)
            }
            isCreating = false
        }
    }

    private func runAgent(_ agent: DigitalAgent) {
        Task {
            do {
                _ = try await apiClient.runAgent(agent.id)
                // Reload to get updated status
                await loadAgents()
            } catch {
                self.error = error.userFacingMessage(context: .generic)
            }
        }
    }

    private func deleteAgent(_ agent: DigitalAgent) {
        Task {
            do {
                try await apiClient.deleteAgent(agent.id)
                agents.removeAll { $0.id == agent.id }
            } catch {
                self.error = error.userFacingMessage(context: .generic)
            }
        }
    }
}

// MARK: - Agent Card

private struct AgentCard: View {
    let agent: DigitalAgent
    let onRun: () -> Void
    let onDelete: () -> Void

    @State private var showResult = false

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            // Header row: status icon + name + actions
            HStack(alignment: .top, spacing: Spacing.md) {
                Text(statusIcon)
                    .font(.system(size: 14))

                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(agent.name)
                        .font(Typography.headingMedium)

                    Text(agent.description)
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(2)
                }

                Spacer()

                HStack(spacing: Spacing.sm) {
                    Button {
                        onRun()
                    } label: {
                        Text("Run")
                            .font(Typography.headingSmall)
                            .foregroundStyle(Palette.accent)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("agent-run-\(agent.id)")

                    Button {
                        onDelete()
                    } label: {
                        Image(systemName: "trash")
                            .font(Typography.bodySmall)
                            .foregroundStyle(Palette.textTertiary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("agent-delete-\(agent.id)")
                }
            }

            // Metadata row
            HStack(spacing: Spacing.lg) {
                if let schedule = agent.cronExpression {
                    metadataItem(icon: "clock", text: schedule)
                } else {
                    metadataItem(icon: "clock", text: agent.scheduleType)
                }

                metadataItem(icon: "arrow.clockwise", text: "\(agent.runCount) runs")

                if let lastRun = agent.lastRunAt {
                    metadataItem(icon: "calendar", text: formatDate(lastRun))
                }
            }

            // Expandable last result
            if let result = agent.lastResult, !result.isEmpty {
                DisclosureGroup(isExpanded: $showResult) {
                    Text(result)
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                        .textSelection(.enabled)
                        .padding(.top, Spacing.xs)
                } label: {
                    Text("Last result")
                        .font(Typography.label)
                        .foregroundStyle(Palette.accent)
                }
            }

            // Error display
            if let lastError = agent.lastError, !lastError.isEmpty {
                HStack(spacing: Spacing.xs) {
                    Image(systemName: "exclamationmark.triangle")
                        .font(Typography.caption)
                    Text(lastError)
                        .font(Typography.caption)
                        .lineLimit(2)
                }
                .foregroundStyle(Palette.recording)
            }
        }
        .waiCard()
    }

    private var statusIcon: String {
        switch agent.status.lowercased() {
        case "active":
            return "\u{1F7E2}" // green circle
        case "paused":
            return "\u{23F8}\u{FE0F}" // pause
        case "failed", "error":
            return "\u{274C}" // red X
        default:
            return "\u{26AA}" // white circle
        }
    }

    private func metadataItem(icon: String, text: String) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: icon)
                .font(Typography.caption)
            Text(text)
                .font(Typography.caption)
        }
        .foregroundStyle(Palette.textTertiary)
    }

    private func formatDate(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}
