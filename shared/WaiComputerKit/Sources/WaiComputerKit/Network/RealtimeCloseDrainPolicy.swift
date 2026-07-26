import Foundation

enum RealtimeCloseDrainPolicy {
    static let minimumWait: Duration = .milliseconds(650)
    static let noTranscriptWait: Duration = .milliseconds(2500)
    static let quietWindow: Duration = .milliseconds(900)

    /// Whether the post-`CloseStream` drain window is worth entering.
    ///
    /// The finalization marker is the provider's own signal that the turn is
    /// finalized and its final transcript has been delivered — the collected
    /// segments are already complete. Entering the window in that state cannot
    /// add text: it only waits out `minimumWait`, which the user experiences as
    /// dictation still thinking after it already has the answer. Without the
    /// marker the turn was never finalized upstream, so the window stays and a
    /// straggling final can still land.
    static func shouldDrainAfterCloseStream(finalizationMarkerReceived: Bool) -> Bool {
        !finalizationMarkerReceived
    }

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
