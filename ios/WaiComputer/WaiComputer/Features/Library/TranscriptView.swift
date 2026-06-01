import SwiftUI
import WaiComputerKit

struct TranscriptView: View {
    let segments: [Segment]
    var availability: TranscriptAvailability = .content
    var localRecoveryManifest: RecordingBackupManifest?
    var recordingId: String?
    var onAssigned: ((RecordingDetail) -> Void)?
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var copied = false

    var body: some View {
        if segments.isEmpty {
            emptyState
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    HStack {
                        Spacer()
                        Button {
                            UIPasteboard.general.string = transcriptText
                            copied = true
                            Task {
                                try? await Task.sleep(for: .seconds(1.5))
                                copied = false
                            }
                        } label: {
                            Image(systemName: copied ? "checkmark" : "doc.on.doc")
                                .font(.caption)
                                .foregroundStyle(copied ? .orange : .secondary)
                        }
                        .accessibilityLabel(t("Copy transcript", "Скопировать расшифровку"))
                    }

                    ForEach(segments) { segment in
                        SegmentView(
                            segment: segment,
                            recordingId: recordingId,
                            onAssigned: onAssigned
                        )
                    }
                }
                .padding(24)
            }
        }
    }

    @ViewBuilder
    private var emptyState: some View {
        switch availability {
        case .savedLocally:
            ContentUnavailableView(
                t("Saved locally", "Сохранено локально"),
                systemImage: "externaldrive",
                description: Text(savedLocallyDescription)
            )
            .accessibilityIdentifier("transcript-local-recovery-state")
        case .processing:
            ContentUnavailableView(
                t("Transcript is processing", "Расшифровка готовится"),
                systemImage: "hourglass",
                description: Text(t(
                    "WaiComputer is processing this recording. The transcript will appear here automatically.",
                    "WaiComputer обрабатывает запись. Расшифровка появится здесь автоматически."
                ))
            )
            .accessibilityIdentifier("transcript-processing-state")
        case .content, .empty:
            ContentUnavailableView(
                t("No Transcript", "Нет расшифровки"),
                systemImage: "text.quote",
                description: Text(t(
                    "Transcript will appear here during and after recording",
                    "Расшифровка появится здесь во время и после записи"
                ))
            )
            .accessibilityIdentifier("transcript-empty-state")
        }
    }

    private var savedLocallyDescription: String {
        if localRecoveryManifest?.requiresAuthentication == true {
            return t(
                "Sign in again to sync this recording.",
                "Войди снова, чтобы синхронизировать эту запись."
            )
        }
        if localRecoveryManifest?.isPermanentFailure == true {
            return t(
                "This recording needs attention before it can sync.",
                "Эта запись требует внимания перед синхронизацией."
            )
        }
        if localRecoveryManifest?.isServerProcessing == true {
            return t(
                "Audio is stored on this device while server processing finishes. WaiComputer will keep checking automatically.",
                "Аудио сохранено на этом устройстве, пока сервер завершает обработку. WaiComputer продолжит проверять автоматически."
            )
        }
        return t(
            "This recording is stored on this device. WaiComputer will sync it automatically when the connection is available.",
            "Эта запись сохранена на этом устройстве. WaiComputer синхронизирует ее автоматически, когда соединение будет доступно."
        )
    }

    private var transcriptText: String {
        segments.map { seg in
            let speaker = seg.userFacingSpeakerLabel(languageCode: speakerLanguageCode)
                ?? t("Speaker", "Говорящий")
            let ts = seg.formattedTimestamp
            return "[\(speaker), \(ts)] \(seg.content)"
        }.joined(separator: "\n")
    }

    private var speakerLanguageCode: String {
        switch languageManager.current {
        case .followSystem:
            return languageManager.preferredLocale.identifier
        case .english, .russian:
            return languageManager.current.rawValue
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

struct SegmentView: View {
    let segment: Segment
    let recordingId: String?
    let onAssigned: ((RecordingDetail) -> Void)?
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                if let recordingId, let rawLabel = effectiveRawLabel, !rawLabel.isEmpty {
                    SpeakerChipButton(
                        segment: segment,
                        recordingId: recordingId,
                        onAssigned: { detail in onAssigned?(detail) }
                    )
                } else if let speaker = effectiveDisplay {
                    Text(speaker)
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(.blue)
                }

                Spacer()

                Text(segment.formattedTimestamp)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            Text(segment.content)
                .font(.body)
                .lineLimit(isExpanded ? nil : 3)
                .textSelection(.enabled)
                .onTapGesture {
                    withAnimation {
                        isExpanded.toggle()
                    }
                }
        }
        .padding()
        .background(Color.gray.opacity(0.05))
        .cornerRadius(8)
    }

    private var effectiveRawLabel: String? {
        segment.rawLabel ?? segment.speaker
    }

    private var effectiveDisplay: String? {
        segment.userFacingSpeakerLabel(languageCode: speakerLanguageCode)
    }

    private var speakerLanguageCode: String {
        switch languageManager.current {
        case .followSystem:
            return languageManager.preferredLocale.identifier
        case .english, .russian:
            return languageManager.current.rawValue
        }
    }
}

#Preview {
    TranscriptView(segments: [
        Segment(id: "1", speaker: "Speaker 1", content: "Hello, this is a test segment with some longer content to see how it wraps.", startMs: 0),
        Segment(id: "2", speaker: "Speaker 2", content: "This is another segment.", startMs: 5000),
    ])
    .environmentObject(LanguageManager.shared)
}
