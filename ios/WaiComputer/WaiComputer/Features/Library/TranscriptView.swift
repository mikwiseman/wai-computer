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
    /// Memoizes `mergeTurns` so state changes (copy feedback, language, tab
    /// switches) don't re-sort and re-merge long transcripts on every body pass.
    @State private var displayCache = TranscriptDisplayCache()

    var body: some View {
        if segments.isEmpty {
            emptyState
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .center, spacing: Spacing.md) {
                        Text(t("Transcript", "Расшифровка"))
                            .waiSectionHeader()
                        Spacer()
                        copyTranscriptButton
                    }

                    ForEach(displayCache.turns(for: segments, languageCode: speakerLanguageCode)) { turn in
                        SegmentView(
                            segment: turn.displaySegment,
                            recordingId: recordingId,
                            onAssigned: onAssigned
                        )
                    }
                }
                .padding(24)
            }
            .accessibilityIdentifier("transcript-content")
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

    private var copyTranscriptButton: some View {
        // Single tap copies clean prose (the common case); the menu exposes the
        // timestamped variant without making it default.
        Menu {
            Button {
                copyTranscript(style: .plain)
            } label: {
                Label(t("Copy text", "Скопировать текст"), systemImage: "doc.on.doc")
            }
            .accessibilityIdentifier("transcript-copy-plain")

            Button {
                copyTranscript(style: .timestamped)
            } label: {
                Label(t("Copy with timestamps", "Скопировать с тайм-кодами"), systemImage: "clock")
            }
            .accessibilityIdentifier("transcript-copy-timestamped")
        } label: {
            Label(copied ? t("Copied", "Скопировано") : t("Copy Transcript", "Скопировать расшифровку"), systemImage: copied ? "checkmark" : "doc.on.doc")
        } primaryAction: {
            copyTranscript(style: .plain)
        }
        .buttonStyle(.bordered)
        .tint(Palette.accent)
        .fixedSize()
        .accessibilityIdentifier("transcript-copy-menu")
        .accessibilityLabel(t("Copy transcript", "Скопировать расшифровку"))
    }

    private func copyTranscript(style: TranscriptStyle) {
        UIPasteboard.general.string = TranscriptRendering.transcriptText(
            segments, style: style, languageCode: speakerLanguageCode
        )
        copied = true
        Task {
            try? await Task.sleep(for: .seconds(1.5))
            copied = false
        }
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

/// Caches merged transcript turns keyed by cheap segment-array identity checks
/// (mirrors `MacTranscriptDisplayCache`), so body passes reuse the previous
/// merge instead of recomputing it for identical inputs.
private final class TranscriptDisplayCache {
    private var lastKey: TranscriptSegmentsCacheKey?
    private var lastLanguageCode: String?
    private var cachedTurns: [TranscriptTurn] = []

    func turns(for segments: [Segment], languageCode: String) -> [TranscriptTurn] {
        let key = TranscriptSegmentsCacheKey(segments: segments)
        if key == lastKey, languageCode == lastLanguageCode {
            return cachedTurns
        }

        cachedTurns = TranscriptRendering.mergeTurns(segments, languageCode: languageCode)
        lastKey = key
        lastLanguageCode = languageCode
        return cachedTurns
    }
}

private struct TranscriptSegmentsCacheKey: Equatable {
    let storageAddress: UInt?
    let count: Int
    let firstId: String?
    let firstContentCount: Int?
    let lastId: String?
    let lastContentCount: Int?

    init(segments: [Segment]) {
        storageAddress = segments.withUnsafeBufferPointer { buffer in
            buffer.baseAddress.map { UInt(bitPattern: $0) }
        }
        count = segments.count
        firstId = segments.first?.id
        firstContentCount = segments.first?.content.count
        lastId = segments.last?.id
        lastContentCount = segments.last?.content.count
    }
}

struct SegmentView: View {
    let segment: Segment
    let recordingId: String?
    let onAssigned: ((RecordingDetail) -> Void)?
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                if let recordingId, let rawLabel = effectiveRawLabel, !rawLabel.isEmpty {
                    SpeakerChipButton(
                        segment: segment,
                        recordingId: recordingId,
                        onAssigned: { detail in onAssigned?(detail) }
                    )
                } else if let speaker = effectiveDisplay {
                    Text(speaker)
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                }

                Text(segment.formattedTimestamp)
                    .font(Typography.mono)
                    .foregroundStyle(Palette.textTertiary)
            }

            Text(segment.content)
                .font(Typography.reading)
                .lineSpacing(6)
                .foregroundStyle(Palette.textPrimary)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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
