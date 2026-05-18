import SwiftUI
import WaiComputerKit

struct WaiHomeView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        // Citation chips fall back to "Recording" until we wire in a shared
        // recordings list — passing [] here is intentional, not a fallback.
        CompanionView(apiClient: appState.getAPIClient(), recordings: [])
    }
}
