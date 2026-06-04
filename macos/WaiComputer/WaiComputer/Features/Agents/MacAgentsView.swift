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

    func resolve(action: AgentAction, decision: AgentActionDecision) async {
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
    @EnvironmentObject private var languageManager: LanguageManager
    private let apiClient: APIClient
    private let recordings: [Recording]
    @StateObject private var model: MacAgentsViewModel
    @AppStorage("desktopComputerUseEnabled") private var computerUseEnabled = false
    @State private var controlsExpanded = false
    @State private var agentName = ""
    @State private var agentNote = ""
    @State private var reminderText = ""
    @State private var runObjective = ""
    @State private var reminderDueAt = Date().addingTimeInterval(3_600)

    init(apiClient: APIClient, recordings: [Recording]) {
        self.apiClient = apiClient
        self.recordings = recordings
        _model = StateObject(wrappedValue: MacAgentsViewModel(apiClient: apiClient))
    }

    var body: some View {
        VStack(spacing: 0) {
            CompanionView(
                apiClient: apiClient,
                recordings: recordings,
                showsConversationSwitcher: true
            )
            .environment(\.locale, MacDateFormatting.locale(for: languageManager.current))
            .companionAccentColor(Palette.accent)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            controlsDrawer
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task { await model.load() }
    }

    private var controlsDrawer: some View {
        VStack(spacing: 0) {
            WaiDivider()

            DisclosureGroup(isExpanded: $controlsExpanded) {
                ScrollView {
                    VStack(alignment: .leading, spacing: Spacing.lg) {
                        banners
                        edgeControl
                        forms
                        agentsSection
                        approvalsSection
                        remindersSection
                    }
                    .frame(maxWidth: 920, alignment: .topLeading)
                    .padding(.top, Spacing.md)
                    .padding(.bottom, Spacing.lg)
                }
                .frame(maxHeight: 360)
            } label: {
                HStack(spacing: Spacing.md) {
                    Label(t("Agent controls", "Управление агентами"), systemImage: "slider.horizontal.3")
                        .font(Typography.headingMedium)
                        .foregroundStyle(Palette.textPrimary)

                    Text(macActionStatusText)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textSecondary)

                    Spacer()

                    Button(t("Refresh", "Обновить")) {
                        Task { await model.load() }
                    }
                    .help(t("Refresh agent controls", "Обновить управление агентами"))
                    .disabled(model.isLoading)
                }
            }
            .accessibilityIdentifier("mac-agents-controls")
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.md)
        }
        .background(Palette.surfaceSubtle)
    }

    private var macActionStatusText: String {
        computerUseEnabled
            ? t("Mac actions on", "Действия Mac включены")
            : t("Mac actions off", "Действия Mac выключены")
    }

    @ViewBuilder
    private var banners: some View {
        if let error = model.errorMessage {
            InlineAgentBanner(message: error, systemImage: "exclamationmark.triangle", tint: Palette.recording)
        }
        if let status = model.statusMessage {
            InlineAgentBanner(message: status, systemImage: "checkmark.circle", tint: Palette.accent)
        }
    }

    private var edgeControl: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Toggle(isOn: $computerUseEnabled) {
                Label(t("Mac edge agent", "Mac edge-агент"), systemImage: "desktopcomputer")
                    .font(Typography.headingMedium)
            }
            .toggleStyle(.switch)
            .accessibilityIdentifier("mac-agents-edge-toggle")

            Text(t(
                "When enabled, this Mac can execute approved desktop actions while Inbox or Agents is open.",
                "Когда включено, этот Mac выполняет подтвержденные desktop-действия, пока открыт Инбокс или Агенты."
            ))
            .font(Typography.bodySmall)
            .foregroundStyle(Palette.textSecondary)
        }
        .padding(Spacing.lg)
        .background(Palette.accentSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var forms: some View {
        HStack(alignment: .top, spacing: Spacing.lg) {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                sectionTitle(t("Create agent", "Создать агента"), "plus.circle")
                TextField(t("Agent name", "Название агента"), text: $agentName)
                    .textFieldStyle(.roundedBorder)
                TextField(t("First note or instruction", "Первая заметка или инструкция"), text: $agentNote)
                    .textFieldStyle(.roundedBorder)
                Button {
                    Task { await model.createAgent(name: trimmedAgentName, note: trimmedAgentNote) }
                } label: {
                    Label(t("Create", "Создать"), systemImage: "plus")
                }
                .disabled(trimmedAgentName.isEmpty || trimmedAgentNote.isEmpty || model.isLoading)
                .accessibilityIdentifier("mac-agents-create-button")
            }
            .padding(Spacing.lg)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))

            VStack(alignment: .leading, spacing: Spacing.sm) {
                sectionTitle(t("New reminder", "Новое напоминание"), "bell")
                TextField(t("Reminder text", "Текст напоминания"), text: $reminderText)
                    .textFieldStyle(.roundedBorder)
                DatePicker(t("Due", "Когда"), selection: $reminderDueAt, displayedComponents: [.date, .hourAndMinute])
                Button {
                    Task { await model.createReminder(text: trimmedReminderText, dueAt: reminderDueAt) }
                } label: {
                    Label(t("Create Reminder", "Создать напоминание"), systemImage: "bell.badge")
                }
                .disabled(trimmedReminderText.isEmpty || model.isLoading)
                .accessibilityIdentifier("mac-agents-create-reminder-button")
            }
            .padding(Spacing.lg)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
    }

    private var agentsSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            sectionTitle(t("Agents", "Агенты"), "sparkles")

            TextField(t("Objective for a manual run", "Цель ручного запуска"), text: $runObjective)
                .textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("mac-agents-run-objective")

            if model.agents.isEmpty {
                emptyState(t("No agents yet.", "Агентов пока нет."))
            } else {
                ForEach(model.agents) { agent in
                    HStack(spacing: Spacing.md) {
                        VStack(alignment: .leading, spacing: Spacing.xs) {
                            Text(agent.name)
                                .font(Typography.headingMedium)
                            Text("\(agent.kind) · \(agent.autonomy)")
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textSecondary)
                        }
                        Spacer()
                        Button {
                            Task { await model.startRun(agent: agent, objective: trimmedRunObjective) }
                        } label: {
                            Label(t("Run", "Запустить"), systemImage: "play.fill")
                        }
                        .disabled(trimmedRunObjective.isEmpty || model.isLoading)
                    }
                    .padding(.vertical, Spacing.sm)
                    WaiDivider()
                }
            }
        }
        .padding(Spacing.lg)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var approvalsSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            sectionTitle(t("Approvals", "Подтверждения"), "checkmark.shield")

            if model.actions.isEmpty {
                emptyState(t("No pending actions.", "Нет действий на подтверждение."))
            } else {
                ForEach(model.actions) { action in
                    HStack(alignment: .top, spacing: Spacing.md) {
                        VStack(alignment: .leading, spacing: Spacing.xs) {
                            Text(action.preview)
                                .font(Typography.headingMedium)
                            Text(action.tool)
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textSecondary)
                        }
                        Spacer()
                        Button(t("Approve", "Подтвердить")) {
                            Task { await model.resolve(action: action, decision: .once) }
                        }
                        .disabled(model.isLoading)

                        Button(t("Reject", "Отклонить"), role: .destructive) {
                            Task { await model.resolve(action: action, decision: .reject) }
                        }
                        .disabled(model.isLoading)
                    }
                    .padding(.vertical, Spacing.sm)
                    WaiDivider()
                }
            }
        }
        .padding(Spacing.lg)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var remindersSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            sectionTitle(t("Reminders", "Напоминания"), "bell")

            if model.reminders.isEmpty {
                emptyState(t("No pending reminders.", "Нет ожидающих напоминаний."))
            } else {
                ForEach(model.reminders) { reminder in
                    HStack(alignment: .top, spacing: Spacing.md) {
                        VStack(alignment: .leading, spacing: Spacing.xs) {
                            Text(reminder.text)
                                .font(Typography.headingMedium)
                            Text(reminderDueText(reminder))
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textSecondary)
                        }
                        Spacer()
                        Button(t("Cancel", "Отменить"), role: .destructive) {
                            Task { await model.cancel(reminder: reminder) }
                        }
                        .disabled(model.isLoading)
                    }
                    .padding(.vertical, Spacing.sm)
                    WaiDivider()
                }
            }
        }
        .padding(Spacing.lg)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func sectionTitle(_ title: String, _ systemImage: String) -> some View {
        Label(title, systemImage: systemImage)
            .font(Typography.headingMedium)
            .foregroundStyle(Palette.textPrimary)
    }

    private func emptyState(_ text: String) -> some View {
        Text(text)
            .font(Typography.bodySmall)
            .foregroundStyle(Palette.textSecondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, Spacing.sm)
    }

    private func reminderDueText(_ reminder: Reminder) -> String {
        MacDateFormatting.string(
            from: reminder.dueAt,
            dateStyle: .medium,
            timeStyle: .short,
            language: languageManager.current
        )
    }

    private var trimmedAgentName: String {
        agentName.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var trimmedAgentNote: String {
        agentNote.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var trimmedReminderText: String {
        reminderText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var trimmedRunObjective: String {
        runObjective.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct InlineAgentBanner: View {
    let message: String
    let systemImage: String
    let tint: Color

    var body: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: systemImage)
                .foregroundStyle(tint)
            Text(message)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textPrimary)
            Spacer()
        }
        .padding(Spacing.md)
        .background(tint.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 8))
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
