import Foundation
import WaiComputerKit

#if DEBUG
enum MacUITestScenario: String {
    case recordingFlow = "recording_flow"
}
#endif

enum MacTestingMode: Equatable {
    case live
    #if DEBUG
    case uiTest(MacUITestScenario)
    #endif

    static var current: MacTestingMode {
        #if DEBUG
        guard ProcessInfo.processInfo.environment["WAI_ENABLE_UI_TEST_MODE"] == "1" else {
            return .live
        }

        if let rawValue = ProcessInfo.processInfo.environment["UITEST_SCENARIO"],
           let scenario = MacUITestScenario(rawValue: rawValue) {
            return .uiTest(scenario)
        }
        #endif

        return .live
    }

    var isRecordingFlow: Bool {
        #if DEBUG
        if case .uiTest(.recordingFlow) = self {
            return true
        }
        #endif

        return false
    }
}

struct CompletedRecordingContext: Equatable {
    let recordingId: String
    let transcript: String
    let duration: TimeInterval
    let recordingType: RecordingType
}

#if DEBUG
enum MacUITestFixtures {
    static let createdAt = Date(timeIntervalSince1970: 1_709_292_000)

    static let user = User(
        id: "ui-test-user",
        email: "ui-test@wai.computer",
        createdAt: createdAt
    )

    static let recording = Recording(
        id: "ui-test-recording",
        title: "UI Test Recording",
        type: .note,
        durationSeconds: 3,
        language: "en",
        createdAt: createdAt
    )

    static let recordingDetail = RecordingDetail(
        id: recording.id,
        title: recording.title,
        type: recording.type,
        durationSeconds: recording.durationSeconds,
        language: recording.language,
        createdAt: recording.createdAt,
        segments: [
            Segment(
                id: "ui-test-segment",
                speaker: "Speaker 0",
                content: "UI test finalized transcript.",
                startMs: 0,
                endMs: 3000,
                confidence: 0.99
            ),
        ],
        summary: nil,
        actionItems: []
    )
}
#endif
