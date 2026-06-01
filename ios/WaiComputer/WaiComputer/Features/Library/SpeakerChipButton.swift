import SwiftUI
import WaiComputerKit

struct SpeakerChipButton: View {
    let segment: Segment
    let recordingId: String
    let onAssigned: (RecordingDetail) -> Void

    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var isSheetPresented = false

    var body: some View {
        Button {
            isSheetPresented = true
        } label: {
            HStack(spacing: 2) {
                Text(displayLabel)
                    .font(.caption)
                    .fontWeight(.semibold)
                    .foregroundStyle(segment.personId != nil ? .blue : .secondary)
                if segment.autoAssigned, let conf = confidencePercent {
                    Text("✨\(conf)%")
                        .font(.system(size: 9))
                        .foregroundStyle(.secondary)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(rawLabel == nil)
        .sheet(isPresented: $isSheetPresented) {
            SpeakerAssignSheet(
                segment: segment,
                recordingId: recordingId,
                onAssigned: { detail in
                    onAssigned(detail)
                    isSheetPresented = false
                },
                onCancel: { isSheetPresented = false }
            )
            .environmentObject(appState)
            .environmentObject(languageManager)
        }
    }

    private var rawLabel: String? {
        let candidate = segment.rawLabel ?? segment.speaker
        return (candidate?.isEmpty ?? true) ? nil : candidate
    }

    private var displayLabel: String {
        segment.userFacingSpeakerLabel(languageCode: speakerLanguageCode)
            ?? t("Speaker", "Говорящий")
    }

    private var speakerLanguageCode: String {
        switch languageManager.current {
        case .followSystem:
            return languageManager.preferredLocale.identifier
        case .english, .russian:
            return languageManager.current.rawValue
        }
    }

    private var confidencePercent: Int? {
        guard let confidence = segment.matchConfidence else { return nil }
        return Int(confidence * 100)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct SpeakerAssignSheet: View {
    let segment: Segment
    let recordingId: String
    let onAssigned: (RecordingDetail) -> Void
    let onCancel: () -> Void

    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var people: [Person] = []
    @State private var filter: String = ""
    @State private var isWorking = false
    @State private var loadError: String?
    // Manage the global speaker directory from the picker (127).
    @State private var renameTarget: Person?
    @State private var renameDraft: String = ""
    @State private var deleteTarget: Person?
    @State private var mergeSource: Person?
    @State private var mergeInto: Person?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                TextField(t("Search or create…", "Найти или создать…"), text: $filter)
                    .textFieldStyle(.roundedBorder)
                    .padding()

                if let loadError {
                    Text(loadError)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding(.horizontal)
                }

                List {
                    ForEach(filteredPeople) { person in
                        Button {
                            Task { await assign(personId: person.id) }
                        } label: {
                            Text(person.displayName)
                        }
                        .disabled(isWorking)
                        .contextMenu {
                            Button(t("Rename…", "Переименовать…")) {
                                renameDraft = person.displayName
                                renameTarget = person
                            }
                            Button(t("Delete", "Удалить"), role: .destructive) {
                                deleteTarget = person
                            }
                        }
                    }
                    if shouldShowCreateRow {
                        Button {
                            Task { await assign(newName: trimmedFilter) }
                        } label: {
                            Text("+ " + t("Create", "Создать") + " \u{201C}\(trimmedFilter)\u{201D}")
                                .foregroundStyle(.blue)
                        }
                        .disabled(isWorking)
                    }
                    if people.isEmpty && trimmedFilter.isEmpty {
                        Text(t("No people yet. Type a name above.", "Людей пока нет. Введи имя выше."))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .listStyle(.plain)
            }
            .navigationTitle(t("Assign Speaker", "Назначить говорящего"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button(t("Cancel", "Отмена")) { onCancel() }
                }
            }
            .task {
                await loadPeople()
            }
            .alert(
                t("Rename speaker", "Переименовать говорящего"),
                isPresented: Binding(
                    get: { renameTarget != nil },
                    set: { if !$0 { renameTarget = nil } }
                )
            ) {
                TextField(t("Name", "Имя"), text: $renameDraft)
                Button(t("Save", "Сохранить")) { Task { await performRename() } }
                Button(t("Cancel", "Отмена"), role: .cancel) { renameTarget = nil }
            }
            .confirmationDialog(
                deleteTarget.map {
                    String(format: t("Delete \u{201C}%@\u{201D}?", "Удалить \u{00AB}%@\u{00BB}?"), $0.displayName)
                } ?? "",
                isPresented: Binding(
                    get: { deleteTarget != nil },
                    set: { if !$0 { deleteTarget = nil } }
                ),
                titleVisibility: .visible
            ) {
                Button(t("Delete", "Удалить"), role: .destructive) {
                    Task { await performDelete() }
                }
                Button(t("Cancel", "Отмена"), role: .cancel) { deleteTarget = nil }
            }
            .alert(
                t("Merge speakers?", "Объединить говорящих?"),
                isPresented: Binding(
                    get: { mergeSource != nil && mergeInto != nil },
                    set: { if !$0 { mergeSource = nil; mergeInto = nil } }
                )
            ) {
                Button(t("Merge", "Объединить")) { Task { await performMerge() } }
                Button(t("Cancel", "Отмена"), role: .cancel) {
                    mergeSource = nil
                    mergeInto = nil
                }
            } message: {
                if let into = mergeInto {
                    Text(String(
                        format: t(
                            "A speaker named \u{201C}%@\u{201D} already exists. Merge into it? All recordings using the renamed speaker move to it.",
                            "Говорящий \u{00AB}%@\u{00BB} уже существует. Объединить с ним? Все записи с переименованным говорящим перейдут к нему."
                        ),
                        into.displayName
                    ))
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private var trimmedFilter: String {
        filter.trimmingCharacters(in: .whitespaces)
    }

    private var filteredPeople: [Person] {
        guard !trimmedFilter.isEmpty else { return people }
        return people.filter {
            $0.displayName.localizedCaseInsensitiveContains(trimmedFilter)
        }
    }

    private var shouldShowCreateRow: Bool {
        guard !trimmedFilter.isEmpty else { return false }
        return !people.contains {
            $0.displayName.caseInsensitiveCompare(trimmedFilter) == .orderedSame
        }
    }

    private var rawLabel: String? {
        let candidate = segment.rawLabel ?? segment.speaker
        return (candidate?.isEmpty ?? true) ? nil : candidate
    }

    private func loadPeople() async {
        do {
            people = try await appState.getAPIClient().listPeople()
            loadError = nil
        } catch {
            loadError = error.userFacingMessage(context: .library)
        }
    }

    private func assign(personId: String) async {
        guard let rawLabel else { return }
        isWorking = true
        defer { isWorking = false }
        do {
            let detail = try await appState.getAPIClient().assignSpeaker(
                recordingId: recordingId,
                rawLabel: rawLabel,
                personId: personId,
                newDisplayName: nil
            )
            onAssigned(detail)
        } catch {
            loadError = error.userFacingMessage(context: .library)
        }
    }

    private func assign(newName: String) async {
        guard let rawLabel else { return }
        isWorking = true
        defer { isWorking = false }
        do {
            let detail = try await appState.getAPIClient().assignSpeaker(
                recordingId: recordingId,
                rawLabel: rawLabel,
                personId: nil,
                newDisplayName: newName
            )
            onAssigned(detail)
        } catch {
            loadError = error.userFacingMessage(context: .library)
        }
    }

    private func performRename() async {
        guard let target = renameTarget else { return }
        renameTarget = nil
        let newName = renameDraft.trimmingCharacters(in: .whitespaces)
        guard !newName.isEmpty,
              newName.caseInsensitiveCompare(target.displayName) != .orderedSame else { return }
        // Renaming onto an existing name is a merge, not a duplicate (127): offer to
        // consolidate so recordings already using that name aren't split.
        if let existing = people.first(where: {
            $0.id != target.id && $0.displayName.caseInsensitiveCompare(newName) == .orderedSame
        }) {
            mergeSource = target
            mergeInto = existing
            return
        }
        isWorking = true
        defer { isWorking = false }
        do {
            _ = try await appState.getAPIClient().updatePerson(id: target.id, displayName: newName)
            await loadPeople()
        } catch {
            loadError = error.userFacingMessage(context: .library)
        }
    }

    private func performDelete() async {
        guard let target = deleteTarget else { return }
        deleteTarget = nil
        isWorking = true
        defer { isWorking = false }
        do {
            try await appState.getAPIClient().deletePerson(id: target.id)
            await loadPeople()
        } catch {
            loadError = error.userFacingMessage(context: .library)
        }
    }

    private func performMerge() async {
        guard let source = mergeSource, let into = mergeInto else { return }
        mergeSource = nil
        mergeInto = nil
        isWorking = true
        defer { isWorking = false }
        do {
            _ = try await appState.getAPIClient().mergePeople(sourceId: source.id, intoPersonId: into.id)
            await loadPeople()
        } catch {
            loadError = error.userFacingMessage(context: .library)
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
