import SwiftUI
import WaiComputerKit

struct SpeakerChipButton: View {
    let segment: Segment
    let recordingId: String
    let onAssigned: (RecordingDetail) -> Void

    @EnvironmentObject var appState: AppState
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
        }
    }

    private var rawLabel: String? {
        let candidate = segment.rawLabel ?? segment.speaker
        return (candidate?.isEmpty ?? true) ? nil : candidate
    }

    private var displayLabel: String {
        segment.displayName ?? segment.rawLabel ?? segment.speaker ?? "Speaker"
    }

    private var confidencePercent: Int? {
        guard let confidence = segment.matchConfidence else { return nil }
        return Int(confidence * 100)
    }
}

private struct SpeakerAssignSheet: View {
    let segment: Segment
    let recordingId: String
    let onAssigned: (RecordingDetail) -> Void
    let onCancel: () -> Void

    @EnvironmentObject var appState: AppState
    @State private var people: [Person] = []
    @State private var filter: String = ""
    @State private var isWorking = false
    @State private var loadError: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                TextField("Search or create…", text: $filter)
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
                    }
                    if shouldShowCreateRow {
                        Button {
                            Task { await assign(newName: trimmedFilter) }
                        } label: {
                            Text("+ Create \u{201C}\(trimmedFilter)\u{201D}")
                                .foregroundStyle(.blue)
                        }
                        .disabled(isWorking)
                    }
                    if people.isEmpty && trimmedFilter.isEmpty {
                        Text("No people yet. Type a name above.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .listStyle(.plain)
            }
            .navigationTitle("Assign Speaker")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") { onCancel() }
                }
            }
            .task {
                await loadPeople()
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
        } catch {
            loadError = error.localizedDescription
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
            loadError = error.localizedDescription
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
            loadError = error.localizedDescription
        }
    }
}
