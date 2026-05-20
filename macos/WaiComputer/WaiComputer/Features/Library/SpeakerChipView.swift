import SwiftUI
import WaiComputerKit

struct SpeakerChipView: View {
    let segment: Segment
    let recordingId: String
    let onAssigned: (RecordingDetail) -> Void

    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var isPopoverPresented = false
    @State private var people: [Person] = []
    @State private var filter: String = ""
    @State private var loadError: String?
    @State private var isWorking = false

    var body: some View {
        Button {
            isPopoverPresented.toggle()
        } label: {
            HStack(spacing: 2) {
                Text(displayLabel)
                    .font(Typography.label)
                    .foregroundStyle(isAssigned ? Palette.accent : Palette.textSecondary)
                if segment.autoAssigned, let conf = confidencePercent {
                    Text("✨\(conf)%")
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
                .frame(width: 320)
        }
        .task(id: isPopoverPresented) {
            if isPopoverPresented && people.isEmpty {
                await loadPeople()
            }
        }
    }

    @ViewBuilder
    private var popoverContent: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            TextField(t("Search or create…", "Найти или создать…"), text: $filter)
                .textFieldStyle(.roundedBorder)
            if let loadError {
                Text(loadError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(filteredPeople) { person in
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
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, Spacing.xs)
                            .frame(height: 32)
                            .foregroundStyle(Palette.accent)
                        }
                        .buttonStyle(.plain)
                        .disabled(isWorking)
                    }
                    if filteredPeople.isEmpty && trimmedFilter.isEmpty {
                        Text(t("No people yet. Type a name above.", "Людей пока нет. Введи имя выше."))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, Spacing.xs)
                    }
                }
            }
            .frame(maxHeight: 220)
        }
    }

    // MARK: - State

    private var rawLabel: String? {
        let candidate = segment.rawLabel ?? segment.speaker
        return (candidate?.isEmpty ?? true) ? nil : candidate
    }

    private var displayLabel: String {
        segment.displayName ?? segment.rawLabel ?? segment.speaker ?? t("Speaker", "Спикер")
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
        return !people.contains { $0.displayName.caseInsensitiveCompare(trimmedFilter) == .orderedSame }
    }

    // MARK: - Actions

    private func loadPeople() async {
        let client = appState.getAPIClient()
        do {
            let rows = try await client.listPeople()
            await MainActor.run {
                self.people = rows
                self.loadError = nil
            }
        } catch {
            await MainActor.run {
                self.loadError = error.localizedDescription
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
                loadError = error.localizedDescription
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
                onAssigned(detail)
            }
        } catch {
            await MainActor.run {
                isWorking = false
                loadError = error.localizedDescription
            }
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
