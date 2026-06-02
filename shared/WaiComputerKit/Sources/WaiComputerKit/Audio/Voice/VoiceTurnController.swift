import Foundation

/// The lifecycle of one push-to-talk voice turn, surfaced to the speaking
/// overlay.
public enum VoiceTurnState: Sendable, Equatable {
    case idle
    case listening  // capturing the user's speech
    case thinking  // transcript submitted, awaiting the brain's response
    case speaking  // reading the response aloud
}

/// Coordinates a push-to-talk voice turn over a ``ReadAloudController``,
/// enforcing the two interruption guards from the design: a monotonic turn id
/// so late callbacks from a superseded turn are dropped (staleness), and
/// cancel-on-interrupt so a new press during thinking/speaking barges in and
/// silences the previous read. The mic, STT, and brain stream live in the app
/// and call into this; the controller owns no I/O, so it is fully testable.
///
/// Threading: an actor, so every transition is serialized — a barge-in is
/// processed only between delta feeds, never interleaved with one.
public actor VoiceTurnController {
    private let readAloud: ReadAloudController
    private let onState: @Sendable (VoiceTurnState) -> Void

    public private(set) var state: VoiceTurnState = .idle
    private var currentTurn: UInt64 = 0

    public init(
        readAloud: ReadAloudController,
        onState: @escaping @Sendable (VoiceTurnState) -> Void = { _ in }
    ) {
        self.readAloud = readAloud
        self.onState = onState
    }

    /// User pressed push-to-talk. Starts a new turn and returns its id, which
    /// the caller threads through the transcript/delta/finish callbacks. If a
    /// previous turn is still thinking or speaking, this is a barge-in: its read
    /// is cancelled first and its remaining callbacks become stale.
    @discardableResult
    public func beginListening() async -> UInt64 {
        if state == .thinking || state == .speaking {
            await readAloud.cancel()
        }
        currentTurn &+= 1
        transition(.listening)
        return currentTurn
    }

    /// The transcript for `turn` is final. Ignored if `turn` is stale or the
    /// turn is no longer listening. On success moves to `thinking`; the caller
    /// then starts streaming the brain's response.
    @discardableResult
    public func transcriptReady(turn: UInt64) -> Bool {
        guard turn == currentTurn, state == .listening else { return false }
        transition(.thinking)
        return true
    }

    /// A streaming response delta for `turn`. Ignored if stale. The first delta
    /// flips `thinking` to `speaking` and begins the read-aloud.
    public func appendResponse(_ delta: String, turn: UInt64) async {
        guard turn == currentTurn else { return }
        if state == .thinking {
            await readAloud.begin()
            transition(.speaking)
        }
        guard state == .speaking else { return }
        await readAloud.feed(delta)
    }

    /// The response stream for `turn` finished. Ignored if stale. Speaks any
    /// trailing fragment and returns to idle.
    public func completeResponse(turn: UInt64) async {
        guard turn == currentTurn else { return }
        if state == .speaking {
            await readAloud.finish()
        }
        transition(.idle)
    }

    /// Abort `turn` (user cancel, or the brain errored). Ignored if stale.
    public func abort(turn: UInt64) async {
        guard turn == currentTurn else { return }
        await readAloud.cancel()
        transition(.idle)
    }

    private func transition(_ next: VoiceTurnState) {
        guard next != state else { return }
        state = next
        onState(next)
    }
}
