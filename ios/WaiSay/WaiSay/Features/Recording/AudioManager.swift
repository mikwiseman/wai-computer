import Foundation
import AVFoundation
import WaiSayKit

/// Manages audio session and permissions for the app
@MainActor
class AudioManager: ObservableObject {
    static let shared = AudioManager()

    @Published var hasPermission = false
    @Published var isConfigured = false

    private init() {
        Task {
            await checkPermission()
        }
    }

    func checkPermission() async {
        hasPermission = AVAudioApplication.shared.recordPermission == .granted
    }

    func requestPermission() async -> Bool {
        let granted = await AVAudioApplication.requestRecordPermission()
        hasPermission = granted
        return granted
    }

    func configureAudioSession() throws {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()

        try session.setCategory(
            .playAndRecord,
            mode: .default,
            options: [.defaultToSpeaker, .allowBluetooth]
        )

        try session.setActive(true)
        isConfigured = true
        #endif
    }

    func deactivateAudioSession() {
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false)
        isConfigured = false
        #endif
    }
}
