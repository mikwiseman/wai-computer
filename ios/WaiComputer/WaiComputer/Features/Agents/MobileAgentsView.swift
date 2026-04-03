import SwiftUI
import WaiComputerKit

struct MobileAgentsView: View {
    @EnvironmentObject private var appState: AppState

    @State private var agents: [DigitalAgent] = []
    @State private var description = ""
    @State private var isLoading = false
    @State private var isCreating = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                Section("Create Agent") {
                    TextField("Describe what this agent should do…", text: $description, axis: .vertical)
                        .lineLimit(1...3)

                    Button(isCreating ? "Creating…" : "Create Agent") {
                        Task { await createAgent() }
                    }
                    .disabled(description.trimmed().isEmpty || isCreating)
                }

                if agents.isEmpty && !isLoading {
                    Section {
                        ContentUnavailableView(
                            "No Agents",
                            systemImage: "gearshape.2",
                            description: Text("Create an agent to keep working in the background.")
                        )
                    }
                } else {
                    Section("Agents") {
                        ForEach(agents) { agent in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text(agent.name)
                                        .font(.headline)
                                    Spacer()
                                    Text(agent.status.capitalized)
                                        .font(.caption.weight(.medium))
                                        .foregroundStyle(.secondary)
                                }

                                Text(agent.description)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)

                                HStack {
                                    Text(agent.cronExpression ?? agent.scheduleType)
                                    Spacer()
                                    Text("\(agent.runCount) runs")
                                }
                                .font(.caption)
                                .foregroundStyle(.secondary)

                                if let lastResult = agent.lastResult, !lastResult.isEmpty {
                                    Text(lastResult)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(3)
                                }

                                HStack {
                                    Button("Run") {
                                        Task { await runAgent(agent.id) }
                                    }

                                    Button("Delete", role: .destructive) {
                                        Task { await deleteAgent(agent.id) }
                                    }
                                }
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }
            }
            .navigationTitle("Agents")
            .overlay {
                if isLoading && agents.isEmpty {
                    ProgressView("Loading agents…")
                }
            }
            .task { await loadAgents() }
            .refreshable { await loadAgents() }
            .alert("Agent Error", isPresented: Binding(
                get: { error != nil },
                set: { if !$0 { error = nil } }
            )) {
                Button("OK") { error = nil }
            } message: {
                Text(error ?? "Something went wrong.")
            }
        }
    }

    private func loadAgents() async {
        isLoading = true
        defer { isLoading = false }

        do {
            agents = try await appState.getAPIClient().listAgents()
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }

    private func createAgent() async {
        let prompt = description.trimmed()
        guard !prompt.isEmpty else { return }

        isCreating = true
        defer { isCreating = false }

        do {
            _ = try await appState.getAPIClient().createAgent(description: prompt)
            description = ""
            await loadAgents()
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }

    private func runAgent(_ agentId: String) async {
        do {
            _ = try await appState.getAPIClient().runAgent(agentId)
            await loadAgents()
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }

    private func deleteAgent(_ agentId: String) async {
        do {
            try await appState.getAPIClient().deleteAgent(agentId)
            agents.removeAll { $0.id == agentId }
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }
}

private extension String {
    func trimmed() -> String {
        trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
