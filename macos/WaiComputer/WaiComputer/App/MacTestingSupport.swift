import Foundation
import WaiComputerKit

#if DEBUG
enum MacUITestScenario: String {
    case recordingFlow = "recording_flow"
    case mainView = "main_view"
    case authFlow = "auth_flow"
    case onboardingFlow = "onboarding_flow"
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

    var isMainView: Bool {
        #if DEBUG
        if case .uiTest(.mainView) = self {
            return true
        }
        #endif

        return false
    }

    var isAuthFlow: Bool {
        #if DEBUG
        if case .uiTest(.authFlow) = self {
            return true
        }
        #endif

        return false
    }

    var isOnboardingFlow: Bool {
        #if DEBUG
        if case .uiTest(.onboardingFlow) = self {
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
        email: "screenshots@waiwai.is",
        createdAt: createdAt
    )

    static let recordings: [Recording] = [
        Recording(id: "rec-processing", title: "Processing Recording", type: .meeting, status: .processing, durationSeconds: 121, createdAt: createdAt.addingTimeInterval(3600)),
        Recording(id: "rec-1", title: "Weekly Team Standup", type: .meeting, status: .ready, durationSeconds: 1847, createdAt: createdAt),
        Recording(id: "rec-2", title: "Product Strategy Meeting", type: .meeting, status: .ready, durationSeconds: 3621, createdAt: createdAt.addingTimeInterval(-86400)),
        Recording(id: "rec-3", title: "Design Review: New Dashboard", type: .meeting, status: .ready, durationSeconds: 2456, createdAt: createdAt.addingTimeInterval(-172800)),
        Recording(id: "rec-4", title: "Customer Discovery Call", type: .meeting, status: .ready, durationSeconds: 1923, createdAt: createdAt.addingTimeInterval(-259200)),
        Recording(id: "rec-5", title: "Project kickoff ideas", type: .note, status: .ready, durationSeconds: 845, createdAt: createdAt.addingTimeInterval(-345600)),
        Recording(id: "rec-6", title: "Quarterly Review Notes", type: .note, status: .ready, durationSeconds: 2134, createdAt: createdAt.addingTimeInterval(-432000)),
        Recording(id: "rec-7", title: "Morning Reflection — April", type: .reflection, status: .ready, durationSeconds: 367, createdAt: createdAt.addingTimeInterval(-518400)),
    ]

    static let processingRecording = recordings[0]
    static let readyRecording = recordings[1]
    static let recording = readyRecording

    static let completedRecording = Recording(
        id: "ui-test-completed-recording",
        title: "UI Test Completed Recording",
        type: .note,
        status: .ready,
        durationSeconds: 3,
        createdAt: createdAt.addingTimeInterval(60)
    )

    static let recordingFlowRecordings: [Recording] = [completedRecording] + recordings

    static let recordingDetail = RecordingDetail(
        id: readyRecording.id,
        title: readyRecording.title,
        type: readyRecording.type,
        durationSeconds: readyRecording.durationSeconds,
        language: "en",
        createdAt: readyRecording.createdAt,
        segments: [
            Segment(id: "s1", speaker: "Alex", content: "Good morning everyone. Let us go through our updates for this week.", startMs: 0, endMs: 5200, confidence: 0.95),
            Segment(id: "s2", speaker: "Sarah", content: "Sure. The new dashboard is almost ready. We completed the API integration yesterday and it passed all tests.", startMs: 5500, endMs: 12800, confidence: 0.93),
            Segment(id: "s3", speaker: "Alex", content: "Great progress. What about the mobile app? Are we still on track for the beta release next month?", startMs: 13100, endMs: 22400, confidence: 0.94),
            Segment(id: "s4", speaker: "David", content: "Yes, we are on schedule. The recording feature is working well. We need to finish the transcript view and search functionality.", startMs: 22800, endMs: 35600, confidence: 0.92),
            Segment(id: "s5", speaker: "Sarah", content: "The AI summarization is performing really well in testing. We are seeing 95 percent accuracy on meeting notes now.", startMs: 36000, endMs: 48200, confidence: 0.96),
            Segment(id: "s6", speaker: "Alex", content: "One more thing. The customer feedback has been very positive. They love the real-time transcription feature.", startMs: 48500, endMs: 62100, confidence: 0.91),
            Segment(id: "s7", speaker: "David", content: "Let us schedule a demo for the stakeholders next Friday. I will prepare the presentation slides.", startMs: 62500, endMs: 75000, confidence: 0.94),
            Segment(id: "s8", speaker: "Alex", content: "Sounds good. Any blockers? No? Great. Let us keep the momentum going. See everyone tomorrow.", startMs: 75300, endMs: 88000, confidence: 0.93),
        ],
        summary: Summary(
            summary: "Team standup covered dashboard API integration (completed), mobile app beta timeline (on track), AI summarization accuracy (95%), and positive customer feedback on real-time transcription. Demo scheduled for stakeholders next Friday.",
            keyPoints: [
                "Dashboard API integration completed and passed all tests",
                "Mobile app on track for beta release next month",
                "AI summarization achieving 95% accuracy on meeting notes",
                "Customer feedback very positive on real-time transcription",
            ],
            decisions: [
                Decision(decision: "Schedule stakeholder demo for next Friday", context: "David will prepare the presentation"),
                Decision(decision: "Continue mobile app development on current timeline", context: "On track for beta release"),
            ],
            topics: ["Dashboard", "Mobile App", "AI Summarization", "Customer Feedback"],
            peopleMentioned: ["Alex", "Sarah", "David"],
            sentiment: "positive"
        ),
        actionItems: {
            let json = """
            [
                {"id":"a1","recording_id":"rec-1","task":"Prepare stakeholder demo presentation","owner":"David","due_date":"2026-04-18","priority":"high","status":"pending","source":"ai"},
                {"id":"a2","recording_id":"rec-1","task":"Finish transcript view and search","owner":"David","due_date":"2026-04-25","priority":"medium","status":"pending","source":"ai"},
                {"id":"a3","recording_id":"rec-1","task":"Review customer feedback report","owner":"Alex","due_date":"2026-04-15","priority":"medium","status":"pending","source":"ai"}
            ]
            """.data(using: .utf8)!
            return try! JSONDecoder().decode([ActionItem].self, from: json)
        }()
    )

    static let processingRecordingDetail = RecordingDetail(
        id: processingRecording.id,
        title: processingRecording.title,
        type: processingRecording.type,
        status: processingRecording.status,
        durationSeconds: processingRecording.durationSeconds,
        language: "en",
        createdAt: processingRecording.createdAt,
        segments: []
    )

    static let completedRecordingDetail = RecordingDetail(
        id: completedRecording.id,
        title: completedRecording.title,
        type: completedRecording.type,
        status: completedRecording.status,
        durationSeconds: completedRecording.durationSeconds,
        language: "en",
        createdAt: completedRecording.createdAt,
        segments: [
            Segment(
                id: "ui-test-final-segment",
                speaker: nil,
                content: "UI test finalized transcript.",
                startMs: 0,
                endMs: 3000,
                confidence: 1
            ),
        ]
    )
}
#endif

#if DEBUG
struct MacPermissionTestingSnapshot {
    let hasMicrophonePermission: Bool
    let accessibilityStatus: MacInputPermission.Status
    let systemAudioStatus: MacInputPermission.Status
}

enum MacPermissionTesting {
    private static var permissionMock: String? {
        ProcessInfo.processInfo.environment["WAI_MOCK_DICTATION_PERMISSIONS"]
    }

    static var dictationPermissionSnapshot: MacPermissionTestingSnapshot? {
        switch permissionMock {
        case "missing":
            return MacPermissionTestingSnapshot(
                hasMicrophonePermission: false,
                accessibilityStatus: .denied,
                systemAudioStatus: .denied
            )
        case "needs_restart_accessibility", "needs_restart_paste", "needs_restart_input":
            // Legacy aliases (the latter two referred to TCC services that
            // the app no longer requires individually). All map to the
            // single Accessibility-stale state under the unified model.
            return MacPermissionTestingSnapshot(
                hasMicrophonePermission: true,
                accessibilityStatus: .staleNeedsRestart,
                systemAudioStatus: .granted
            )
        case "all_granted":
            return MacPermissionTestingSnapshot(
                hasMicrophonePermission: true,
                accessibilityStatus: .granted,
                systemAudioStatus: .granted
            )
        default:
            return nil
        }
    }

    static var forcesMissingDictationPermissions: Bool {
        dictationPermissionSnapshot != nil
    }
}
#endif
