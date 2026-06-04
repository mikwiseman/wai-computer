import SwiftUI
import WaiComputerKit

@MainActor
final class MacAgentsViewModel: ObservableObject {
    @Published var agents: [AgentDefinition] = []
    @Published var runs: [AgentRun] = []
    @Published var actions: [AgentAction] = []
    @Published var reminders: [Reminder] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var statusMessage: String?

    private let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            agents = try await apiClient.listAgents().agents
            runs = try await apiClient.listAllAgentRuns().runs
            actions = try await apiClient.listAgentActions().actions
            reminders = try await apiClient.listReminders().reminders
            errorMessage = nil
        } catch {
            errorMessage = error.userFacingMessage(context: .generic)
        }
    }

    func createAgent(name: String, note: String) async {
        await perform(status: "Agent created.") {
            _ = try await apiClient.createAgent(
                AgentCreateRequest(
                    name: name,
                    kind: "mac",
                    triggerType: .manual,
                    config: [
                        "steps": .array([
                            .object([
                                "tool": .string("note"),
                                "args": .object(["text": .string(note)])
                            ])
                        ])
                    ],
                    autonomy: "propose",
                    enabled: true
                )
            )
        }
    }

    func startRun(agent: AgentDefinition, objective: String) async {
        await perform(status: "Agent run started.") {
            _ = try await apiClient.startAgentRun(
                agentId: agent.id,
                StartAgentRunRequest(
                    triggerKind: .manual,
                    triggerPayload: ["objective": .string(objective)],
                    idempotencyKey: "mac:\(UUID().uuidString)",
                    runInline: false
                )
            )
        }
    }

    func resolve(action: AgentAction, decision: String) async {
        await perform(status: "Action resolved.") {
            guard let agentId = action.agentId, let runId = action.runId else {
                throw MacAgentsError.missingActionScope
            }
            _ = try await apiClient.resolveAgentAction(
                agentId: agentId,
                runId: runId,
                actionId: action.id,
                ResolveAgentActionRequest(decision: decision)
            )
        }
    }

    func createReminder(text: String, dueAt: Date) async {
        await perform(status: "Reminder created.") {
            _ = try await apiClient.createReminder(
                ReminderCreateRequest(
                    text: text,
                    dueAt: dueAt,
                    source: "mac",
                    metadata: ["origin": .string("mac_agents")]
                )
            )
        }
    }

    func cancel(reminder: Reminder) async {
        await perform(status: "Reminder cancelled.") {
            _ = try await apiClient.cancelReminder(reminderId: reminder.id)
        }
    }

    private func perform(
        status: String,
        operation: () async throws -> Void
    ) async {
        do {
            try await operation()
            statusMessage = status
            errorMessage = nil
            await load()
        } catch {
            errorMessage = error.userFacingMessage(context: .generic)
        }
    }
}

struct MacAgentsView: View {
    @StateObject private var model: MacAgentsViewModel
    @State private var agentName = ""
    @State private var agentNote = ""
    @State private var reminderText = ""
    @State private var runObjective = ""

    init(apiClient: APIClient) {
        _model = StateObject(wrappedValue: MacAgentsViewModel(apiClient: apiClient))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            if let error = model.errorMessage {
                Text(error).foregroundStyle(.red)
            }
            if let status = model.statusMessage {
                Text(status).foregroundStyle(.secondary)
            }
            forms
            List {
                Section("Agents") {
                    ForEach(model.agents) { agent in
                        HStack {
                            Text(agent.name)
                            Spacer()
                            Button("Run") {
                                Task { await model.startRun(agent: agent, objective: runObjective) }
                            }
                            .disabled(runObjective.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }
                }
                Section("Approvals") {
                    ForEach(model.actions) { action in
                        HStack {
                            Text(action.preview)
                            Spacer()
                            Button("Once") {
                                Task { await model.resolve(action: action, decision: "once") }
                            }
                        }
                    }
                }
                Section("Reminders") {
                    ForEach(model.reminders) { reminder in
                        HStack {
                            Text(reminder.text)
                            Spacer()
                            Button("Cancel") {
                                Task { await model.cancel(reminder: reminder) }
                            }
                        }
                    }
                }
            }
        }
        .padding()
        .task { await model.load() }
    }

    private var header: some View {
        HStack {
            Text("Agents").font(.title2).fontWeight(.semibold)
            Spacer()
            Button("Refresh") {
                Task { await model.load() }
            }
            .disabled(model.isLoading)
        }
    }

    private var forms: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Agent name", text: $agentName)
            TextField("Agent note", text: $agentNote)
            Button("Create Agent") {
                Task { await model.createAgent(name: agentName, note: agentNote) }
            }
            .disabled(agentName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

            TextField("Run objective", text: $runObjective)
            TextField("Reminder", text: $reminderText)
            Button("Create Reminder") {
                Task {
                    await model.createReminder(
                        text: reminderText,
                        dueAt: Date().addingTimeInterval(3_600)
                    )
                }
            }
            .disabled(reminderText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
    }
}

private enum MacAgentsError: LocalizedError {
    case missingActionScope

    var errorDescription: String? {
        switch self {
        case .missingActionScope:
            return "Agent action is missing its agent or run scope."
        }
    }
}
