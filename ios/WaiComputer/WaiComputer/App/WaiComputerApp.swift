import SwiftUI
import UIKit
import WaiComputerKit

#if DEBUG
enum IOSScreenshotScreen: String {
    case record
    case library
    case materials
    case detail
    case settings
    case search
    case comparison
    case history
    case dictionary
}
#endif

enum IOSTestingMode: Equatable {
    case live
    #if DEBUG
    case screenshot(IOSScreenshotScreen)
    #endif

    static var current: IOSTestingMode {
        #if DEBUG
        guard ProcessInfo.processInfo.environment["WAI_ENABLE_SCREENSHOT_MODE"] == "1" else {
            return .live
        }

        if let rawValue = ProcessInfo.processInfo.environment["WAI_SCREENSHOT_SCREEN"],
           let screen = IOSScreenshotScreen(rawValue: rawValue) {
            return .screenshot(screen)
        }

        return .screenshot(.record)
        #else
        return .live
        #endif
    }

    var isScreenshot: Bool {
        #if DEBUG
        if case .screenshot = self {
            return true
        }
        #endif
        return false
    }
}

/// iOS `LexiconChecking` backed by `UITextChecker`. This matches the macOS
/// learning gate: common dictionary words are rejected, while names, brands,
/// and product terms can become dictionary suggestions after repeated edits.
struct IOSLexiconChecker: LexiconChecking {
    func isKnownWord(_ token: String, language: String?) -> Bool {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.contains(where: { $0.isLetter }) else { return true }
        guard let spellLanguage = Self.spellLanguage(for: language) else {
            return true
        }

        let range = NSRange(trimmed.startIndex..<trimmed.endIndex, in: trimmed)
        let misspelledRange = UITextChecker().rangeOfMisspelledWord(
            in: trimmed,
            range: range,
            startingAt: 0,
            wrap: false,
            language: spellLanguage
        )
        return misspelledRange.location == NSNotFound
    }

    private static func spellLanguage(for language: String?) -> String? {
        let available = Set(UITextChecker.availableLanguages)
        if let raw = language?.lowercased(), !raw.isEmpty,
           raw != "multi", raw != "auto", raw != "und" {
            let base = String(raw.prefix(2))
            let candidates = [raw, base]
            if let supported = candidates.first(where: { available.contains($0) }) {
                return supported
            }
            return nil
        }

        for preferred in Locale.preferredLanguages {
            let lowered = preferred.lowercased()
            let base = String(lowered.prefix(2))
            if available.contains(lowered) {
                return lowered
            }
            if available.contains(base) {
                return base
            }
        }
        return available.contains("en") ? "en" : nil
    }
}

#if DEBUG
enum IOSScreenshotFixtures {
    static let createdAt = Date(timeIntervalSince1970: 1_713_158_400)
    static let billingPeriodEnd = Date(timeIntervalSince1970: 1_784_073_600)
    static let productFolderId = "ios-fixture-folder-product"

    static let user = User(
        id: "ios-screenshot-user",
        email: "hello@waiwai.is",
        createdAt: createdAt
    )

    static let identity = UserIdentity(
        firstName: "Mik",
        lastName: "Wiseman",
        hasVoiceprint: true
    )

    static let voiceSharing = VoiceSharingState(
        enabled: true,
        canEnable: true,
        hasFirstName: true,
        hasLastName: true,
        hasVoiceprint: true,
        sharedName: "Mik Wiseman"
    )

    static let telegramStatus = TelegramLinkStatus(
        linked: false,
        botUsername: "waicomputer_bot",
        telegramUserID: nil,
        username: nil,
        firstName: nil,
        lastName: nil,
        linkedAt: nil
    )

    static let billingFreePlan = BillingPlan(
        code: "free",
        name: "Free",
        description: "Weekly transcription allowance for personal capture.",
        wordCapPerWeek: 50_000,
        memoryRetentionDays: 30,
        features: [
            "recording": true,
            "search": true,
            "mcp": true,
        ]
    )

    static let billingProPlan = BillingPlan(
        code: "pro",
        name: "Pro",
        description: "Unlimited memory capture across Mac, iPhone, iPad, and agents.",
        usdAmountMonthly: 20,
        usdAmountYearly: 200,
        rubAmountMonthly: 1_990,
        rubAmountYearly: 19_900,
        wordCapPerWeek: nil,
        memoryRetentionDays: nil,
        features: [
            "recording": true,
            "search": true,
            "mcp": true,
            "billing": true,
        ]
    )

    static let billingSubscription = BillingSubscription(
        plan: billingProPlan,
        status: "active",
        provider: BillingDisplayRegion.global.provider,
        billingPeriod: BillingDisplayPeriod.month.rawValue,
        currentPeriodEnd: billingPeriodEnd,
        cancelAtPeriodEnd: false,
        trialEnd: nil,
        enforcementEnabled: true
    )

    static let billingUsage = BillingUsage(
        wordsUsed: 84_320,
        wordsCap: nil,
        resetAt: billingPeriodEnd,
        capExceeded: false
    )

    static let billingPlans = [billingFreePlan, billingProPlan]
    static let billingRegion = BillingDisplayRegion.global

    static let folders: [Folder] = [
        Folder(
            id: productFolderId,
            name: "Product",
            createdAt: createdAt.addingTimeInterval(-900_000),
            itemCount: 3
        ),
    ]

    static let recordings: [Recording] = [
        Recording(
            id: "rec-1",
            title: "Weekly Team Standup",
            type: .meeting,
            status: .ready,
            durationSeconds: 1847,
            createdAt: createdAt
        ),
        Recording(
            id: "rec-2",
            title: "Product Roadmap Sync",
            type: .meeting,
            status: .ready,
            durationSeconds: 2240,
            folderId: productFolderId,
            createdAt: createdAt.addingTimeInterval(-86_400)
        ),
        Recording(
            id: "rec-3",
            title: "Design Review",
            type: .meeting,
            status: .ready,
            durationSeconds: 1640,
            folderId: productFolderId,
            createdAt: createdAt.addingTimeInterval(-172_800)
        ),
        Recording(
            id: "rec-4",
            title: "Customer Interview",
            type: .meeting,
            status: .ready,
            durationSeconds: 1312,
            createdAt: createdAt.addingTimeInterval(-259_200)
        ),
        Recording(
            id: "rec-5",
            title: "Strategy Notes",
            type: .note,
            status: .ready,
            durationSeconds: 905,
            createdAt: createdAt.addingTimeInterval(-345_600)
        ),
        Recording(
            id: "rec-6",
            title: "Morning Reflection",
            type: .reflection,
            status: .ready,
            durationSeconds: 367,
            createdAt: createdAt.addingTimeInterval(-432_000)
        ),
    ]

    static let trashedRecordings: [Recording] = [
        Recording(
            id: "trash-1",
            title: "Old Planning Sync",
            type: .meeting,
            status: .ready,
            durationSeconds: 1420,
            deletedAt: createdAt.addingTimeInterval(-43_200),
            createdAt: createdAt.addingTimeInterval(-604_800)
        ),
    ]

    static let itemListResponse: ItemListResponse = {
        let data = """
        {
            "items": [
                {
                    "id": "item-1",
                    "source": "paste",
                    "url": null,
                    "kind": "note",
                    "title": "Mobile Release Checklist",
                    "state": "ready",
                    "status": "ready",
                    "error": null,
                    "folder_id": "ios-fixture-folder-product",
                    "occurred_at": null,
                    "created_at": "2024-04-15T11:00:00Z",
                    "has_summary": true
                },
                {
                    "id": "item-2",
                    "source": "url",
                    "url": "https://wai.computer",
                    "kind": "article",
                    "title": "Second Brain Launch Notes",
                    "state": "processing",
                    "status": "processing",
                    "error": null,
                    "folder_id": null,
                    "occurred_at": null,
                    "created_at": "2024-04-14T16:30:00Z",
                    "has_summary": false
                }
            ],
            "total": 2
        }
        """.data(using: .utf8)!
        guard let response = try? JSONDecoder().decode(ItemListResponse.self, from: data) else {
            fatalError("itemListResponse fixture JSON is malformed — fix IOSScreenshotFixtures")
        }
        return response
    }()

    static let items: [Item] = {
        let data = """
        [
            {
                "id": "item-1",
                "source": "paste",
                "source_ref": null,
                "url": null,
                "kind": "note",
                "title": "Mobile Release Checklist",
                "body": "Verify iPad workspace navigation, screenshot fixtures, unified search, and comparison tables before TestFlight.",
                "occurred_at": null,
                "state": "ready",
                "status": "ready",
                "error": null,
                "folder_id": "ios-fixture-folder-product",
                "created_at": "2024-04-15T11:00:00Z",
                "summary": {
                    "summary": "A release checklist for making the iOS app feel aligned with the Mac app before the next TestFlight build.",
                    "key_points": [
                        "Verify iPad workspace navigation",
                        "Capture deterministic screenshots",
                        "Check comparison and search surfaces"
                    ],
                    "topics": ["iPad", "TestFlight", "Parity"],
                    "key_moments": [
                        {
                            "timestamp": null,
                            "moment": "Confirm the iPad split workspace",
                            "why_it_matters": "It proves the mobile UI follows the Mac app's workbench model.",
                            "quote": null,
                            "importance": "high",
                            "start_ms": null,
                            "end_ms": null
                        }
                    ],
                    "sentiment": "focused"
                },
                "summary_audio": null
            },
            {
                "id": "item-2",
                "source": "url",
                "source_ref": null,
                "url": "https://wai.computer",
                "kind": "article",
                "title": "Second Brain Launch Notes",
                "body": null,
                "occurred_at": null,
                "state": "processing",
                "status": "processing",
                "error": null,
                "folder_id": null,
                "created_at": "2024-04-14T16:30:00Z",
                "summary": null,
                "summary_audio": null
            }
        ]
        """.data(using: .utf8)!
        guard let items = try? JSONDecoder().decode([Item].self, from: data) else {
            fatalError("items fixture JSON is malformed — fix IOSScreenshotFixtures")
        }
        return items
    }()

    static let detailRecording = recordings[0]

    static let detail = RecordingDetail(
        id: detailRecording.id,
        title: detailRecording.title,
        type: detailRecording.type,
        status: .ready,
        durationSeconds: detailRecording.durationSeconds,
        language: "en",
        createdAt: detailRecording.createdAt,
        segments: [
            Segment(
                id: "s1",
                speaker: "Alex",
                content: "Quick update. Search is shipping this week and beta feedback is strong.",
                startMs: 0,
                endMs: 4_800,
                confidence: 0.96
            ),
            Segment(
                id: "s2",
                speaker: "Sarah",
                content: "Mobile capture is stable now. We only need to polish library and summaries.",
                startMs: 5_200,
                endMs: 10_600,
                confidence: 0.95
            ),
            Segment(
                id: "s3",
                speaker: "David",
                content: "Let's push the TestFlight build today and share it with the design partners.",
                startMs: 11_000,
                endMs: 16_300,
                confidence: 0.94
            ),
            Segment(
                id: "s4",
                speaker: "Alex",
                content: "Agreed. We'll package the release notes and screenshots right after QA signs off.",
                startMs: 16_700,
                endMs: 22_400,
                confidence: 0.94
            ),
        ],
        summary: Summary(
            summary: "The team confirmed that search is ready to ship, mobile capture is stable, and the next step is pushing a polished TestFlight build with updated screenshots.",
            keyPoints: [
                "Search is ready to ship this week",
                "Mobile capture is stable",
                "Library and summary polish remain",
            ],
            decisions: [
                Decision(
                    decision: "Ship a new TestFlight build today",
                    context: "Share with design partners immediately after QA"
                ),
            ],
            topics: ["Search", "Mobile Capture", "TestFlight"],
            peopleMentioned: ["Alex", "Sarah", "David"],
            sentiment: "positive"
        ),
        actionItems: {
            let json = """
            [
              {
                "id": "a1",
                "recording_id": "rec-1",
                "task": "Upload fresh TestFlight build",
                "owner": "David",
                "due_date": "2026-04-16",
                "priority": "high",
                "status": "pending",
                "source": "ai"
              },
              {
                "id": "a2",
                "recording_id": "rec-1",
                "task": "Refresh App Store screenshots",
                "owner": "Sarah",
                "due_date": "2026-04-16",
                "priority": "high",
                "status": "pending",
                "source": "ai"
              }
            ]
            """.data(using: .utf8)!
            return try! JSONDecoder().decode([ActionItem].self, from: json)
        }()
    )

    private static func detailFixture(for recording: Recording) -> RecordingDetail {
        RecordingDetail(
            id: recording.id,
            title: recording.title,
            type: recording.type,
            status: recording.status,
            durationSeconds: recording.durationSeconds,
            language: "en",
            folderId: recording.folderId,
            deletedAt: recording.deletedAt,
            createdAt: recording.createdAt,
            segments: detail.segments,
            summary: detail.summary,
            summaryGeneration: detail.summaryGeneration,
            summaryAudio: detail.summaryAudio,
            actionItems: detail.actionItems,
            highlights: detail.highlights
        )
    }

    private static func trashDetailFixture(for recording: Recording) -> RecordingDetail {
        RecordingDetail(
            id: recording.id,
            title: recording.title,
            type: recording.type,
            status: recording.status,
            durationSeconds: recording.durationSeconds,
            language: "en",
            folderId: recording.folderId,
            deletedAt: recording.deletedAt,
            createdAt: recording.createdAt,
            segments: [
                Segment(
                    id: "\(recording.id)-s1",
                    speaker: "Mik",
                    content: "This old planning sync is no longer needed, but keep it visible in Trash until we are sure the migration screenshots are finished.",
                    startMs: 0,
                    endMs: 6_400,
                    confidence: 0.95
                ),
                Segment(
                    id: "\(recording.id)-s2",
                    speaker: "Sarah",
                    content: "Agreed. Restore it only if we need to compare the old launch notes with the current iPad workspace.",
                    startMs: 6_900,
                    endMs: 13_500,
                    confidence: 0.94
                ),
            ],
            summary: Summary(
                summary: "An archived planning sync kept in Trash while the team checks whether old launch notes are still useful for iPad workspace QA.",
                keyPoints: [
                    "The recording is intentionally in Trash",
                    "Restore it only if the old launch notes are needed",
                    "The iPad workspace remains the active QA focus",
                ],
                topics: ["Trash", "iPad Workspace", "Launch Notes"],
                peopleMentioned: ["Mik", "Sarah"],
                sentiment: "neutral"
            )
        )
    }

    static let searchResponse: SearchResponse = {
        let data = """
        {
            "results": [
                {
                    "recording_id": "rec-1",
                    "recording_title": "Weekly Team Standup",
                    "recording_type": "meeting",
                    "segment_id": "search-seg-1",
                    "speaker": "Alex",
                    "content": "Quick update. Search is shipping this week and beta feedback is strong.",
                    "start_ms": 0,
                    "end_ms": 4800,
                    "score": 0.96
                },
                {
                    "recording_id": "rec-2",
                    "recording_title": "Product Roadmap Sync",
                    "recording_type": "meeting",
                    "segment_id": "search-seg-2",
                    "speaker": "Sarah",
                    "content": "We aligned the roadmap around search, capture stability, and the library polish.",
                    "start_ms": 12000,
                    "end_ms": 19200,
                    "score": 0.74
                }
            ],
            "total": 2
        }
        """.data(using: .utf8)!
        guard let response = try? JSONDecoder().decode(SearchResponse.self, from: data) else {
            fatalError("searchResponse fixture JSON is malformed — fix IOSScreenshotFixtures")
        }
        return response
    }()

    static let unifiedSearchResponse: UnifiedSearchResponse = {
        let data = """
        {
            "results": [
                {
                    "source_kind": "recording",
                    "parent_id": "rec-1",
                    "chunk_id": "unified-search-rec-1",
                    "title": "Weekly Team Standup",
                    "kind": "meeting",
                    "snippet": "The recording feature is working well. We need to finish the transcript view and search functionality.",
                    "score": 1.0,
                    "created_at": "2024-04-15T10:00:00Z"
                },
                {
                    "source_kind": "item",
                    "parent_id": "item-1",
                    "chunk_id": "unified-search-item-1",
                    "title": "Mobile Release Checklist",
                    "kind": "note",
                    "snippet": "Verify iPad workspace navigation, screenshot fixtures, and unified search before TestFlight.",
                    "score": 0.86,
                    "created_at": "2024-04-15T11:00:00Z"
                }
            ],
            "total": 2
        }
        """.data(using: .utf8)!
        guard let response = try? JSONDecoder().decode(UnifiedSearchResponse.self, from: data) else {
            fatalError("unifiedSearchResponse fixture JSON is malformed — fix IOSScreenshotFixtures")
        }
        return response
    }()

    static let comparisonListEntries: [ComparisonListEntry] = [
        comparisonListEntry,
    ]

    static let dictationHistoryEntries: [DictationHistoryEntry] = [
        DictationHistoryEntry(
            id: UUID(uuidString: "11111111-1111-1111-1111-111111111111")!,
            timestamp: createdAt.addingTimeInterval(-1_200),
            rawText: "open sigma board and summarize launch notes",
            cleanedText: "Open Figma board and summarize launch notes.",
            durationSeconds: 11,
            wordCount: 7
        ),
        DictationHistoryEntry(
            id: UUID(uuidString: "22222222-2222-2222-2222-222222222222")!,
            timestamp: createdAt.addingTimeInterval(-3_600),
            rawText: "share why computer release checklist",
            cleanedText: "Share WaiComputer release checklist.",
            durationSeconds: 8,
            wordCount: 4
        ),
        DictationHistoryEntry(
            id: UUID(uuidString: "33333333-3333-3333-3333-333333333333")!,
            timestamp: createdAt.addingTimeInterval(-90_000),
            rawText: "ask sarah to review testflight screenshots",
            cleanedText: "Ask Sarah to review TestFlight screenshots.",
            durationSeconds: 9,
            wordCount: 6
        ),
    ]

    static let dictionaryWords: [DictionaryWord] = [
        DictionaryWord(
            id: UUID(uuidString: "44444444-4444-4444-4444-444444444444")!,
            word: "Figma",
            replacement: nil,
            origin: "learned",
            createdAt: createdAt.addingTimeInterval(-7_200)
        ),
        DictionaryWord(
            id: UUID(uuidString: "55555555-5555-5555-5555-555555555555")!,
            word: "why computer",
            replacement: "WaiComputer",
            origin: "learned",
            createdAt: createdAt.addingTimeInterval(-6_800)
        ),
        DictionaryWord(
            id: UUID(uuidString: "66666666-6666-6666-6666-666666666666")!,
            word: "TestFlight",
            replacement: nil,
            origin: "manual",
            createdAt: createdAt.addingTimeInterval(-4_800)
        ),
    ]

    static let comparisonSet: ComparisonSet = {
        let data = """
        {
          "id": "comparison-1",
          "title": "Mobile launch material comparison",
          "item_ids": ["item-1", "item-2"],
          "columns": [
            { "name": "Purpose", "type": "text" },
            { "name": "Current state", "type": "text" },
            { "name": "Next action", "type": "text" }
          ],
          "rows": [
            {
              "item_id": "item-1",
              "title": "Mobile Release Checklist",
              "values": {
                "Purpose": "Operational checklist for the TestFlight pass and App Store screenshot review.",
                "Current state": "Ready to use for QA. The remaining work is visual confirmation on iPad and iPhone.",
                "Next action": "Run the screenshot script, inspect the iPad workspace, and attach the final images to the release note."
              }
            },
            {
              "item_id": "item-2",
              "title": "Second Brain Launch Notes",
              "values": {
                "Purpose": "External positioning for capture, recall, and cross-device memory workflows.",
                "Current state": "Processing. Needs a final summary before it should be used in customer-facing copy.",
                "Next action": "Wait for item processing, then compare the summary against the release checklist."
              }
            }
          ],
          "schema_rationale": "The table compares each material by purpose, readiness, and the next launch action so mobile QA can decide what to use immediately.",
          "status": "ready",
          "created_at": "2024-04-15T12:00:00Z"
        }
        """.data(using: .utf8)!
        guard let set = try? JSONDecoder().decode(ComparisonSet.self, from: data) else {
            fatalError("comparisonSet fixture JSON is malformed — fix IOSScreenshotFixtures")
        }
        return set
    }()

    private static let comparisonListEntry: ComparisonListEntry = {
        let data = """
        {
          "id": "comparison-1",
          "title": "Mobile launch material comparison",
          "item_count": 2,
          "status": "ready",
          "created_at": "2024-04-15T12:00:00Z"
        }
        """.data(using: .utf8)!
        guard let entry = try? JSONDecoder().decode(ComparisonListEntry.self, from: data) else {
            fatalError("comparisonListEntry fixture JSON is malformed — fix IOSScreenshotFixtures")
        }
        return entry
    }()

    static func recording(id: String) -> Recording {
        recordings.first(where: { $0.id == id }) ?? detailRecording
    }

    static func recordingDetail(id: String) -> RecordingDetail {
        if let recording = trashedRecordings.first(where: { $0.id == id }) {
            return trashDetailFixture(for: recording)
        }
        if let recording = recordings.first(where: { $0.id == id }) {
            return recording.id == detail.id ? detail : detailFixture(for: recording)
        }
        return detail
    }

    static func item(id: String) -> Item {
        guard let item = items.first(where: { $0.id == id }) else {
            fatalError("No iOS screenshot item fixture for id \(id)")
        }
        return item
    }

    static func comparison(id: String) -> ComparisonSet {
        guard comparisonSet.id == id else {
            fatalError("No iOS screenshot comparison fixture for id \(id)")
        }
        return comparisonSet
    }
}
#endif

@main
struct WaiComputerApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var appState = AppState()
    @StateObject private var languageManager = LanguageManager.shared
    @StateObject private var dictationLanguageStore = DictationLanguageStore()
    @StateObject private var historyStore = DictationHistoryStore()
    @StateObject private var dictionaryStore = DictationDictionaryStore()
    @StateObject private var learningEngine = DictionaryLearningEngine(lexicon: IOSLexiconChecker())
    @State private var didPrepareScreenshotFixtures = false
    @AppStorage(IOSThemePreferences.appearanceKey) private var appearanceModeRawValue = IOSThemePreferences.defaultAppearance.rawValue
    @AppStorage(IOSThemePreferences.accentKey) private var accentChoiceRawValue = IOSThemePreferences.defaultAccent.rawValue

    private var appearanceMode: IOSAppearanceMode {
        IOSAppearanceMode(rawValue: appearanceModeRawValue) ?? IOSThemePreferences.defaultAppearance
    }

    private var accentChoice: IOSAccentChoice {
        IOSAccentChoice(rawValue: accentChoiceRawValue) ?? IOSThemePreferences.defaultAccent
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(\.locale, languageManager.preferredLocale)
                .environmentObject(languageManager)
                .environmentObject(appState)
                .environmentObject(dictationLanguageStore)
                .environmentObject(historyStore)
                .environmentObject(dictionaryStore)
                .environmentObject(learningEngine)
                .preferredColorScheme(appearanceMode.preferredColorScheme)
                .tint(accentChoice.tintColor)
                .onAppear {
                    prepareScreenshotFixturesIfNeeded()
                }
                .task(id: appState.isAuthenticated) {
                    await syncDictationStoresForAuthState()
                }
                .onOpenURL { url in
                    Task { await appState.handleIncomingURL(url) }
                }
                .onChange(of: appState.isCheckingAuth) { _, _ in
                    Task { await syncDictationStoresForAuthState() }
                }
                .onChange(of: scenePhase) { _, newPhase in
                    guard newPhase == .active else { return }
                    Task {
                        await appState.resumePendingRecordingSyncIfNeeded()
                        await syncDictationStoresForAuthState()
                    }
                }
        }
    }

    @MainActor
    private func prepareScreenshotFixturesIfNeeded() {
        #if DEBUG
        guard IOSTestingMode.current.isScreenshot, !didPrepareScreenshotFixtures else { return }
        didPrepareScreenshotFixtures = true
        historyStore.loadScreenshotFixtures()
        dictionaryStore.loadScreenshotFixtures()
        learningEngine.clearAll()
        learningEngine.observeEdit(
            produced: "open sigma board and summarize launch notes",
            edited: "open Figma board and summarize launch notes",
            language: "en"
        )
        learningEngine.observeEdit(
            produced: "open sigma board and summarize launch notes",
            edited: "open Figma board and summarize launch notes",
            language: "en"
        )
        #endif
    }

    @MainActor
    private func syncDictationStoresForAuthState() async {
        guard !appState.isCheckingAuth else { return }

        if appState.isAuthenticated {
            #if DEBUG
            guard !IOSTestingMode.current.isScreenshot else { return }
            #endif

            let client = appState.getAPIClient()
            historyStore.attach(apiClient: client)
            dictionaryStore.attach(apiClient: client)
            await historyStore.hydrate()
            await dictionaryStore.hydrate()
        } else {
            historyStore.clearLocalCache()
            dictionaryStore.clearLocalCache()
        }
    }
}

/// Global app state
@MainActor
class AppState: ObservableObject {
    @Published var isAuthenticated = false
    @Published var isCheckingAuth = true
    @Published var currentUser: User?
    @Published var isLoading = false
    @Published var error: String?
    @Published var hasCompletedOnboarding: Bool = false
    @Published var magicLinkSent = false
    @Published var passwordResetSent = false

    static let onboardingCompletedKey = "nativeOnboardingV2Completed"

    let apiClient: APIClient
    private var hasAttemptedStoredSessionRestore = false

    init() {
        #if !DEBUG
        SentryHelper.start(dsn: "https://b677540a781e0058c8568b614d517530@o4508963132145664.ingest.us.sentry.io/4511116052070400")
        #endif

        // Configure API client
        let baseURL = URL(string: "https://wai.computer")!
        apiClient = APIClient(baseURL: baseURL)

        // Resolve onboarding flag honoring env-var overrides used by tests/dev.
        let env = ProcessInfo.processInfo.environment
        if env["WAI_FORCE_ONBOARDING"] == "1" {
            UserDefaults.standard.set(false, forKey: AppState.onboardingCompletedKey)
            hasCompletedOnboarding = false
        } else if env["WAI_SKIP_ONBOARDING"] == "1" {
            UserDefaults.standard.set(true, forKey: AppState.onboardingCompletedKey)
            hasCompletedOnboarding = true
        } else {
            hasCompletedOnboarding = UserDefaults.standard.bool(forKey: AppState.onboardingCompletedKey)
        }

        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            currentUser = IOSScreenshotFixtures.user
            isAuthenticated = true
            isCheckingAuth = false
            hasCompletedOnboarding = true
            return
        }
        #endif

        // Set up token refresh callbacks
        Task {
            await apiClient.setOnTokenRefreshed { accessToken, refreshToken in
                KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: accessToken)
                KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: refreshToken)
                Task {
                    await PendingRecordingSyncCoordinator.shared.scheduleSync(using: self.apiClient)
                }
            }
            await apiClient.setOnAuthenticationFailed { [weak self] in
                Task { @MainActor in
                    self?.handleAuthenticationFailed()
                }
            }
        }

        // Start network monitoring — triggers sync on connectivity recovery
        NetworkMonitor.shared.start { [weak self] in
            guard let self else { return }
            Task { @MainActor in
                await self.resumePendingRecordingSyncIfNeeded()
            }
        }

        if hasCompletedOnboarding {
            beginStoredSessionRestoreIfNeeded()
        } else {
            isCheckingAuth = false
        }
    }

    /// Mark the welcome tour as seen. The flag persists across logout and
    /// account deletion — onboarding is a product introduction, not part of
    /// the auth lifecycle.
    func completeOnboarding() {
        UserDefaults.standard.set(true, forKey: AppState.onboardingCompletedKey)
        hasCompletedOnboarding = true
        beginStoredSessionRestoreIfNeeded()
    }

    private func beginStoredSessionRestoreIfNeeded() {
        guard !hasAttemptedStoredSessionRestore else {
            isCheckingAuth = false
            return
        }

        hasAttemptedStoredSessionRestore = true
        isCheckingAuth = true

        // Restore tokens only after onboarding. This avoids a first-launch
        // Keychain prompt and prevents old installs from silently skipping the tour.
        let accessToken: String? = {
            if let arg = ProcessInfo.processInfo.environment["WAICOMPUTER_ACCESS_TOKEN"] {
                KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: arg)
                return arg
            }
            return KeychainHelper.load(key: KeychainHelper.accessTokenKey)
        }()
        let refreshOverride = ProcessInfo.processInfo.environment["WAICOMPUTER_REFRESH_TOKEN"]
        if let refreshOverride {
            KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: refreshOverride)
        }

        guard let accessToken else {
            isCheckingAuth = false
            return
        }

        Task {
            await apiClient.setAccessToken(accessToken)
            let rt = refreshOverride ?? KeychainHelper.load(key: KeychainHelper.refreshTokenKey)
            if let rt {
                await apiClient.setRefreshToken(rt)
            }
            await loadCurrentUser()
            isCheckingAuth = false
        }
    }

    func login(email: String, password: String) async {
        isLoading = true
        error = nil

        do {
            let response = try await apiClient.login(email: email, password: password)
            await apiClient.setAccessToken(response.accessToken)
            KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: response.accessToken)
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
                KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: rt)
            }
            await loadCurrentUser()
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.userFacingMessage(context: .authentication)
        }

        isLoading = false
    }

    func register(email: String, password: String, acceptedLegalTerms: Bool) async {
        isLoading = true
        error = nil

        do {
            let response = try await apiClient.register(
                email: email,
                password: password,
                acceptedLegalTerms: acceptedLegalTerms
            )
            await apiClient.setAccessToken(response.accessToken)
            KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: response.accessToken)
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
                KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: rt)
            }
            await loadCurrentUser()
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.userFacingMessage(context: .authentication)
        }

        isLoading = false
    }

    /// In-app language → backend locale tag ("ru" or "en"). Mirrors macOS.
    private var authLocale: String {
        LanguageManager.shared.preferredLocale.language.languageCode?.identifier == "ru" ? "ru" : "en"
    }

    /// Request a passwordless sign-in link. Mirrors macOS `requestMagicLink`.
    func requestMagicLink(email: String, acceptedLegalTerms: Bool = false) async {
        isLoading = true
        error = nil
        do {
            _ = try await apiClient.requestMagicLink(
                email: email,
                client: "ios",
                locale: authLocale,
                acceptedLegalTerms: acceptedLegalTerms
            )
            magicLinkSent = true
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.userFacingMessage(context: .authentication)
        }
        isLoading = false
    }

    /// Request a password-reset email. Mirrors macOS `requestPasswordReset`.
    func requestPasswordReset(email: String, locale: String?) async {
        isLoading = true
        error = nil
        do {
            _ = try await apiClient.requestPasswordReset(email: email, locale: locale)
            passwordResetSent = true
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.userFacingMessage(context: .authentication)
        }
        isLoading = false
    }

    /// Handle the magic-link deep link `waicomputer://auth/verify?token=…`.
    func handleIncomingURL(_ url: URL) async {
        guard url.scheme == "waicomputer",
              url.host == "auth",
              url.path == "/verify" || url.path == "verify",
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let token = components.queryItems?.first(where: { $0.name == "token" })?.value
        else { return }

        isLoading = true
        error = nil
        do {
            let response = try await apiClient.verifyMagicLink(token: token)
            await apiClient.setAccessToken(response.accessToken)
            KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: response.accessToken)
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
                KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: rt)
            }
            magicLinkSent = false
            // A user arriving via magic link has effectively finished onboarding.
            if !hasCompletedOnboarding {
                UserDefaults.standard.set(true, forKey: AppState.onboardingCompletedKey)
                hasCompletedOnboarding = true
            }
            await loadCurrentUser()
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.userFacingMessage(context: .authentication)
        }
        isLoading = false
    }

    func logout() async {
        let rt = await apiClient.getRefreshToken()
        do {
            _ = try await apiClient.logout(refreshToken: rt)
        } catch {
            // Best-effort server logout
        }

        await clearLocalSession()
    }

    /// Permanently delete the current account. Returns an error message on
    /// failure; on success tokens are cleared and the app is routed back to
    /// the auth screen.
    func deleteAccount() async -> String? {
        guard isAuthenticated else { return nil }
        isLoading = true
        error = nil
        defer { isLoading = false }

        do {
            _ = try await apiClient.deleteAccount()
        } catch {
            SentryHelper.captureError(error, extras: ["action": "deleteAccount"])
            let message = error.userFacingMessage(context: .authentication)
            self.error = message
            return message
        }

        await clearLocalSession()
        return nil
    }

    /// Clear in-memory auth state, API client tokens, Keychain entries, and
    /// Sentry user context. Used by both `logout` and `deleteAccount`.
    private func clearLocalSession() async {
        await apiClient.setAccessToken(nil)
        await apiClient.setRefreshToken(nil)
        KeychainHelper.delete(key: KeychainHelper.accessTokenKey)
        KeychainHelper.delete(key: KeychainHelper.refreshTokenKey)
        SentryHelper.clearUser()
        currentUser = nil
        isAuthenticated = false
    }

    /// Called when auto-refresh fails — transition to login screen
    private func handleAuthenticationFailed() {
        KeychainHelper.delete(key: KeychainHelper.accessTokenKey)
        KeychainHelper.delete(key: KeychainHelper.refreshTokenKey)
        Task {
            await apiClient.setAccessToken(nil)
            await apiClient.setRefreshToken(nil)
        }
        currentUser = nil
        isAuthenticated = false
    }

    func loadCurrentUser() async {
        do {
            let user = try await apiClient.getCurrentUser()
            currentUser = user
            isAuthenticated = true
            SentryHelper.setUser(id: user.id)
            await PendingRecordingSyncCoordinator.shared.scheduleSync(
                using: apiClient,
                recoverAbandonedLocalRecordings: true
            )
        } catch {
            isAuthenticated = false
            currentUser = nil
            SentryHelper.clearUser()
        }
    }

    func resumePendingRecordingSyncIfNeeded() async {
        guard isAuthenticated else { return }
        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: apiClient)
    }

    private func handleAPIError(_ error: APIError) {
        switch error {
        case .unauthorized:
            self.error = "Invalid credentials"
        case .httpError, .networkError:
            self.error = error.userFacingMessage(context: .authentication)
        default:
            self.error = error.userFacingMessage(context: .authentication)
        }
    }

    func getAPIClient() -> APIClient {
        return apiClient
    }

    /// Deterministic search results for DEBUG screenshot / UI-test runs so the
    /// search surface can be captured without a live backend. Mirrors
    /// `MacAppState.uiTestSearchResponse(query:)`.
    func uiTestSearchResponse(query: String) -> SearchResponse? {
        #if DEBUG
        guard IOSTestingMode.current.isScreenshot,
              !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return IOSScreenshotFixtures.searchResponse
        #else
        return nil
        #endif
    }

    /// Deterministic unified-search results for DEBUG screenshot / UI-test
    /// runs. Mirrors the macOS `uiTestUnifiedSearchResponse` hook.
    func uiTestUnifiedSearchResponse(query: String) -> UnifiedSearchResponse? {
        #if DEBUG
        guard IOSTestingMode.current.isScreenshot,
              !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return IOSScreenshotFixtures.unifiedSearchResponse
        #else
        return nil
        #endif
    }
}
