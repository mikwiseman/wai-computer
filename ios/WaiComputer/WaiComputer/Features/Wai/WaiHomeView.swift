import SwiftUI
import WaiComputerKit

/// The "Wai" companion tab. Hosts the shared `CompanionView` and supplies the
/// three host-app inputs macOS provides at `MacContentView.swift:849-854`:
/// a populated `[Recording]` (so citation chips resolve to real titles), the
/// in-app accent colour, and the in-app language locale (so dates/labels in the
/// shared view follow the language picker rather than the system locale).
struct WaiHomeView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager

    let initialChatId: String?

    /// Recordings used purely to resolve citation chip titles inside the shared
    /// `CompanionView`. We fetch our own copy here rather than hoisting the
    /// Library view model into `AppState`; a fresh `.task` load keeps the tab
    /// self-contained at the cost of one extra list request.
    @State private var recordings: [Recording] = []
    @State private var loadError: String?

    init(initialChatId: String? = nil) {
        self.initialChatId = initialChatId
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        CompanionView(
            apiClient: appState.getAPIClient(),
            recordings: recordings,
            initialChatId: initialChatId,
            onTurnCompleted: { completion in
                // Mirror macOS: ping the user when an agent turn finishes while
                // they're away from the app, deep-linking back to the Wai tab.
                IOSWaiTaskNotificationCenter.shared.notifyTaskFinished(
                    title: "Wai",
                    body: completion.preview ?? t("Your task is ready.", "Задача готова."),
                    chatId: completion.chatId
                )
            }
        )
            .environment(\.locale, languageManager.preferredLocale)
            .companionAccentColor(Palette.accent)
            .overlay(alignment: .top) {
                if let loadError {
                    citationLoadBanner(loadError)
                }
            }
            .task {
                IOSWaiTaskNotificationCenter.shared.configure()
                await loadRecordings()
            }
    }

    private func citationLoadBanner(_ message: String) -> some View {
        Text(message)
            .font(.footnote)
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity)
            .background(.ultraThinMaterial)
            .accessibilityIdentifier("wai-citation-load-error")
    }

    private func loadRecordings() async {
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            recordings = IOSScreenshotFixtures.recordings
            return
        }
        #endif

        // Citation chips are an enrichment, not the primary content of this
        // tab, so a failed lookup is surfaced as a quiet banner rather than
        // blocking the chat — but we never silently swallow it.
        do {
            recordings = try await appState.getAPIClient().listRecordings(limit: 100)
            loadError = nil
        } catch is CancellationError {
            // The `.task` was torn down (tab switch / view re-arm); this is not a
            // failure the user needs to see, so leave any existing banner state
            // untouched rather than flashing a misleading error.
            return
        } catch let urlError as URLError where urlError.code == .cancelled {
            return
        } catch {
            loadError = t(
                "Couldn't load recording titles for citations.",
                "Не удалось загрузить названия записей для ссылок."
            )
        }
    }
}
