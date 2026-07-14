import SwiftUI
import WaiComputerKit

private enum SpeakerAssignLayout {
    static let chipCornerRadius: CGFloat = 7
    static let rowCornerRadius: CGFloat = 10
    static let errorIconWidth: CGFloat = 16
}

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
                    .font(Typography.label)
                    .foregroundStyle(isAssigned ? Palette.accent : Palette.textSecondary)
                if segment.autoAssigned {
                    Text("✨")
                        .font(.system(size: 10))
                        .foregroundStyle(Palette.textTertiary)
                }
            }
            .padding(.horizontal, Spacing.xs)
            .padding(.vertical, Spacing.xxs)
            .background(isAssigned ? Palette.accentSubtle : Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: SpeakerAssignLayout.chipCornerRadius, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: SpeakerAssignLayout.chipCornerRadius, style: .continuous)
                    .stroke(Palette.border, lineWidth: 1)
            }
        }
        .buttonStyle(.plain)
        .disabled(rawLabel == nil)
        .accessibilityIdentifier("speaker-chip-button")
        .accessibilityHint(Text(helpText))
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

    private var isAssigned: Bool {
        segment.personId != nil
    }

    private var helpText: String {
        if let conf = confidencePercent, segment.autoAssigned {
            return t(
                "Auto-assigned (\(conf)% match). Tap to override.",
                "Назначено автоматически, совпадение \(conf)%. Нажми, чтобы изменить."
            )
        }
        return t("Tap to assign", "Нажми, чтобы назначить")
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
                speakerAssignSearchField

                if let loadError {
                    speakerAssignErrorBanner(loadError)
                }

                List {
                    ForEach(filteredPeople) { person in
                        Button {
                            Task { await assign(personId: person.id) }
                        } label: {
                            speakerPersonRow(person)
                        }
                        .disabled(isWorking)
                        .buttonStyle(.plain)
                        .listRowSeparator(.hidden)
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets(top: Spacing.xs, leading: Spacing.lg, bottom: Spacing.xs, trailing: Spacing.lg))
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
                            speakerCreateRow
                        }
                        .disabled(isWorking)
                        .buttonStyle(.plain)
                        .listRowSeparator(.hidden)
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets(top: Spacing.xs, leading: Spacing.lg, bottom: Spacing.xs, trailing: Spacing.lg))
                    }
                    if people.isEmpty && trimmedFilter.isEmpty {
                        speakerEmptyRow
                            .listRowSeparator(.hidden)
                            .listRowBackground(Color.clear)
                            .listRowInsets(EdgeInsets(top: Spacing.xs, leading: Spacing.lg, bottom: Spacing.xs, trailing: Spacing.lg))
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
            .background(Color(uiColor: .systemBackground))
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

    private var speakerAssignSearchField: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Palette.textTertiary)
            TextField(t("Search or create…", "Найти или создать…"), text: $filter)
                .textFieldStyle(.plain)
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)
                .submitLabel(.done)
                .accessibilityIdentifier("speaker-assign-search-field")
            if !filter.isEmpty {
                Button {
                    filter = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Palette.textTertiary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(t("Clear search", "Очистить поиск"))
            }
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .frame(minHeight: 44)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: SpeakerAssignLayout.rowCornerRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: SpeakerAssignLayout.rowCornerRadius, style: .continuous)
                .stroke(Palette.border, lineWidth: 1)
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.top, Spacing.lg)
        .padding(.bottom, Spacing.sm)
        .accessibilityIdentifier("speaker-assign-search-field")
    }

    private func speakerAssignErrorBanner(_ message: String) -> some View {
        HStack(alignment: .top, spacing: Spacing.xs) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Palette.danger)
                .frame(width: SpeakerAssignLayout.errorIconWidth, alignment: .leading)
            Text(message)
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, Spacing.xs)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.danger.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: SpeakerAssignLayout.rowCornerRadius, style: .continuous))
        .padding(.horizontal, Spacing.lg)
        .padding(.bottom, Spacing.sm)
        .accessibilityIdentifier("speaker-assign-error-banner")
    }

    private func speakerPersonRow(_ person: Person) -> some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: "person.crop.circle")
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(Palette.accent)
            Text(person.displayName)
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(1)
            Spacer(minLength: Spacing.md)
            Image(systemName: "chevron.right")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Palette.textTertiary)
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: SpeakerAssignLayout.rowCornerRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: SpeakerAssignLayout.rowCornerRadius, style: .continuous)
                .stroke(Palette.border, lineWidth: 1)
        }
        .contentShape(RoundedRectangle(cornerRadius: SpeakerAssignLayout.rowCornerRadius, style: .continuous))
        .accessibilityIdentifier("speaker-assign-person-row")
    }

    private var speakerCreateRow: some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: "plus.circle.fill")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(Palette.accent)
            Text(t("Create", "Создать") + " \u{201C}\(trimmedFilter)\u{201D}")
                .font(Typography.body)
                .foregroundStyle(Palette.accent)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: Spacing.md)
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .background(Palette.accentSubtle)
        .clipShape(RoundedRectangle(cornerRadius: SpeakerAssignLayout.rowCornerRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: SpeakerAssignLayout.rowCornerRadius, style: .continuous)
                .stroke(Palette.border, lineWidth: 1)
        }
        .contentShape(RoundedRectangle(cornerRadius: SpeakerAssignLayout.rowCornerRadius, style: .continuous))
        .accessibilityIdentifier("speaker-assign-create-row")
    }

    private var speakerEmptyRow: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: "person.2")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(Palette.textTertiary)
            Text(t("No people yet. Type a name above.", "Людей пока нет. Введи имя выше."))
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: Spacing.md)
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: SpeakerAssignLayout.rowCornerRadius, style: .continuous))
        .accessibilityIdentifier("speaker-assign-empty-row")
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
