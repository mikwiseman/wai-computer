import SwiftUI
import WaiComputerKit

private enum SpeakerAssignmentPopoverLayout {
    static let listMaxHeight: CGFloat = 220
    static let errorIconWidth: CGFloat = 16
}

struct SpeakerChipView: View {
    let segment: Segment
    let recordingId: String
    let onAssigned: (RecordingDetail) -> Void

    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var isPopoverPresented = false
    @State private var people: [Person] = []
    @State private var visiblePeople: [Person] = []
    @State private var filter: String = ""
    @State private var loadError: String?
    @State private var isWorking = false
    // Manage the global speaker directory from the picker (127).
    @State private var renameTarget: Person?
    @State private var renameDraft: String = ""
    @State private var deleteTarget: Person?
    @State private var mergeSource: Person?
    @State private var mergeInto: Person?

    var body: some View {
        Button {
            isPopoverPresented.toggle()
        } label: {
            HStack(spacing: 2) {
                Text(displayLabel)
                    .font(Typography.label)
                    .foregroundStyle(isAssigned ? Palette.accent : Palette.textSecondary)
                if segment.autoAssigned {
                    // Sparkle marks an auto-assigned speaker; the raw match
                    // percentage was unclear to users so it's dropped from the
                    // chip — the .help() tooltip still explains it (128).
                    Text("✨")
                        .font(.system(size: 10))
                        .foregroundStyle(Palette.textTertiary)
                }
            }
        }
        .buttonStyle(.plain)
        .help(helpText)
        .disabled(rawLabel == nil)
        .popover(isPresented: $isPopoverPresented, arrowEdge: .bottom) {
            popoverContent
                .padding(Spacing.md)
                .frame(width: MacMainLayoutMetrics.speakerAssignmentPopoverWidth, alignment: .leading)
        }
        .task(id: isPopoverPresented) {
            if isPopoverPresented && people.isEmpty {
                await loadPeople()
            }
        }
        .onChangeCompat(of: filter) { _, _ in
            refreshVisiblePeople()
        }
    }

    @ViewBuilder
    private var popoverContent: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            TextField(t("Search or create…", "Найти или создать…"), text: $filter)
                .textFieldStyle(.plain)
                .waiTextField(isActive: true)
                .frame(maxWidth: .infinity)
            if let loadError {
                HStack(alignment: .top, spacing: Spacing.xs) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Palette.recording)
                        .frame(width: SpeakerAssignmentPopoverLayout.errorIconWidth, alignment: .leading)
                    Text(loadError)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, Spacing.sm)
                .padding(.vertical, Spacing.xs)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Palette.recording.opacity(0.10))
                .clipShape(RoundedRectangle(cornerRadius: Radius.md))
            }
            List {
                ForEach(visiblePeople) { person in
                    Button {
                        Task { await assign(personId: person.id) }
                    } label: {
                        Text(person.displayName)
                            .lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, Spacing.xs)
                            .frame(height: 32)
                    }
                    .buttonStyle(.plain)
                    .contentShape(Rectangle())
                    .disabled(isWorking)
                    .speakerPickerListRow()
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
                        HStack(spacing: Spacing.xs) {
                            Image(systemName: "plus")
                                .font(.system(size: 12, weight: .semibold))
                            Text(t("Create", "Создать") + " “\(trimmedFilter)”")
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, Spacing.xs)
                        .frame(height: 32)
                        .foregroundStyle(Palette.accent)
                    }
                    .buttonStyle(.plain)
                    .disabled(isWorking)
                    .speakerPickerListRow()
                }
                if visiblePeople.isEmpty && trimmedFilter.isEmpty {
                    Text(t("No people yet. Type a name above.", "Людей пока нет. Введи имя выше."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, Spacing.xs)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .frame(height: 32)
                        .speakerPickerListRow()
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .frame(maxHeight: SpeakerAssignmentPopoverLayout.listMaxHeight)
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
                String(format: t("Delete “%@”?", "Удалить «%@»?"), $0.displayName)
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
        } message: {
            if let target = deleteTarget {
                Text(String(
                    format: t(
                        "This removes “%@” from your people directory and unassigns them in all recordings.",
                        "Это удалит «%@» из справочника людей и снимет назначение во всех записях."
                    ),
                    target.displayName
                ))
            }
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
                        "A speaker named “%@” already exists. Merge into it? All recordings using the renamed speaker move to it.",
                        "Говорящий «%@» уже существует. Объединить с ним? Все записи с переименованным говорящим перейдут к нему."
                    ),
                    into.displayName
                ))
            }
        }
    }

    // MARK: - State

    private var rawLabel: String? {
        let candidate = segment.rawLabel ?? segment.speaker
        return (candidate?.isEmpty ?? true) ? nil : candidate
    }

    private var displayLabel: String {
        segment.userFacingSpeakerLabel(languageCode: speakerLanguageCode) ?? t("Speaker", "Говорящий")
    }

    private var isAssigned: Bool {
        segment.personId != nil
    }

    private var confidencePercent: Int? {
        guard let confidence = segment.matchConfidence else { return nil }
        return Int(confidence * 100)
    }

    private var helpText: String {
        if let conf = confidencePercent, segment.autoAssigned {
            return t(
                "Auto-assigned (\(conf)% match). Click to override.",
                "Назначено автоматически, совпадение \(conf)%. Нажми, чтобы изменить."
            )
        }
        return t("Click to assign", "Нажми, чтобы назначить")
    }

    private var speakerLanguageCode: String {
        switch languageManager.current {
        case .followSystem:
            return languageManager.preferredLocale.identifier
        case .english, .russian:
            return languageManager.current.rawValue
        }
    }

    private var trimmedFilter: String {
        filter.trimmingCharacters(in: .whitespaces)
    }

    private var shouldShowCreateRow: Bool {
        guard !trimmedFilter.isEmpty else { return false }
        return !people.contains { $0.displayName.caseInsensitiveCompare(trimmedFilter) == .orderedSame }
    }

    private func refreshVisiblePeople() {
        refreshVisiblePeople(people: people, filter: filter)
    }

    private func refreshVisiblePeople(people: [Person], filter: String) {
        let trimmedFilter = filter.trimmingCharacters(in: .whitespaces)
        guard !trimmedFilter.isEmpty else {
            visiblePeople = people
            return
        }
        visiblePeople = people.filter {
            $0.displayName.localizedCaseInsensitiveContains(trimmedFilter)
        }
    }

    // MARK: - Actions

    private func loadPeople() async {
        let client = appState.getAPIClient()
        do {
            let rows = try await client.listPeople()
            await MainActor.run {
                self.people = rows
                self.refreshVisiblePeople(people: rows, filter: self.filter)
                self.loadError = nil
            }
        } catch {
            await MainActor.run {
                self.loadError = error.userFacingMessage(context: .library)
            }
        }
    }

    private func assign(personId: String) async {
        guard let rawLabel else { return }
        await MainActor.run { isWorking = true }
        let client = appState.getAPIClient()
        do {
            let detail = try await client.assignSpeaker(
                recordingId: recordingId,
                rawLabel: rawLabel,
                personId: personId,
                newDisplayName: nil
            )
            await MainActor.run {
                isWorking = false
                isPopoverPresented = false
                filter = ""
                onAssigned(detail)
            }
        } catch {
            await MainActor.run {
                isWorking = false
                loadError = error.userFacingMessage(context: .library)
            }
        }
    }

    private func assign(newName: String) async {
        guard let rawLabel else { return }
        await MainActor.run { isWorking = true }
        let client = appState.getAPIClient()
        do {
            let detail = try await client.assignSpeaker(
                recordingId: recordingId,
                rawLabel: rawLabel,
                personId: nil,
                newDisplayName: newName
            )
            await MainActor.run {
                isWorking = false
                isPopoverPresented = false
                filter = ""
                people = []
                visiblePeople = []
                onAssigned(detail)
            }
        } catch {
            await MainActor.run {
                isWorking = false
                loadError = error.userFacingMessage(context: .library)
            }
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
        await MainActor.run { isWorking = true }
        do {
            _ = try await appState.getAPIClient().updatePerson(id: target.id, displayName: newName)
            await loadPeople()
        } catch {
            await MainActor.run { loadError = error.userFacingMessage(context: .library) }
        }
        await MainActor.run { isWorking = false }
    }

    private func performDelete() async {
        guard let target = deleteTarget else { return }
        deleteTarget = nil
        await MainActor.run { isWorking = true }
        do {
            try await appState.getAPIClient().deletePerson(id: target.id)
            await loadPeople()
        } catch {
            await MainActor.run { loadError = error.userFacingMessage(context: .library) }
        }
        await MainActor.run { isWorking = false }
    }

    private func performMerge() async {
        guard let source = mergeSource, let into = mergeInto else { return }
        mergeSource = nil
        mergeInto = nil
        await MainActor.run { isWorking = true }
        do {
            _ = try await appState.getAPIClient().mergePeople(sourceId: source.id, intoPersonId: into.id)
            await loadPeople()
        } catch {
            await MainActor.run { loadError = error.userFacingMessage(context: .library) }
        }
        await MainActor.run { isWorking = false }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private extension View {
    func speakerPickerListRow() -> some View {
        listRowInsets(EdgeInsets())
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
    }
}
