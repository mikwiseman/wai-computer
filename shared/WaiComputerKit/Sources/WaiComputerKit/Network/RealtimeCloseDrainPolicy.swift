import Foundation

enum RealtimeCloseDrainPolicy {
    static let minimumWait: Duration = .milliseconds(650)
    static let noTranscriptWait: Duration = .milliseconds(2500)
    static let quietWindow: Duration = .milliseconds(900)

    static func shouldKeepWaiting(
        now: ContinuousClock.Instant,
        deadline: ContinuousClock.Instant,
        startedAt: ContinuousClock.Instant,
        lastTranscriptEventAt: ContinuousClock.Instant?,
        finalizationMarkerReceived: Bool
    ) -> Bool {
        guard now < deadline else { return false }

        let minimumWaitUntil = startedAt + minimumWait
        if finalizationMarkerReceived, now >= minimumWaitUntil {
            return false
        }

        if let lastTranscriptEventAt {
            return !(now >= minimumWaitUntil && now - lastTranscriptEventAt >= quietWindow)
        }

        return now < startedAt + noTranscriptWait
    }
}
