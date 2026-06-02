import Foundation

/// A swappable text-to-speech sink. The macOS/iOS clients use the offline
/// `AVSpeechTTSProvider`; a server-backed provider can be slotted behind the
/// same protocol for non-Apple surfaces. `speak` completes when the sentence
/// has finished being spoken; `stop` cancels immediately (barge-in).
public protocol TTSProvider: Sendable {
    func speak(_ sentence: String) async
    func stop()
}

/// Buffers streaming text (LLM token deltas) and emits complete sentences so
/// read-aloud can start on the first finished sentence instead of waiting for
/// the whole answer. Pure value logic — no audio — so it is fully unit-tested.
public struct SentenceSegmenter: Sendable {
    private var buffer = ""

    public init() {}

    /// Append a delta and return any sentences that are now complete.
    public mutating func feed(_ delta: String) -> [String] {
        buffer += delta
        var sentences: [String] = []
        while let end = Self.firstSentenceEnd(in: buffer) {
            let sentence = String(buffer[..<end])
                .trimmingCharacters(in: .whitespacesAndNewlines)
            buffer = String(buffer[end...])
            buffer = String(buffer.drop(while: { $0 == " " || $0 == "\n" }))
            if !sentence.isEmpty {
                sentences.append(sentence)
            }
        }
        return sentences
    }

    /// Return whatever remains at end-of-stream (the trailing fragment).
    public mutating func flush() -> String? {
        let remainder = buffer.trimmingCharacters(in: .whitespacesAndNewlines)
        buffer = ""
        return remainder.isEmpty ? nil : remainder
    }

    /// Index just past the first sentence terminator, or nil if none yet.
    /// Strong terminators (! ? … newline and CJK forms) end a sentence
    /// immediately; a period ends one only when followed by whitespace and not
    /// sitting between digits (so "3.14" is not split). A period at the very
    /// end of the buffer waits for more input (it may be "Mr." mid-stream).
    private static func firstSentenceEnd(in text: String) -> String.Index? {
        let strong: Set<Character> = ["!", "?", "…", "\n", "。", "！", "？"]
        let chars = Array(text)
        var i = 0
        while i < chars.count {
            let c = chars[i]
            if strong.contains(c) {
                return text.index(text.startIndex, offsetBy: i + 1)
            }
            if c == "." {
                let prev: Character = i > 0 ? chars[i - 1] : " "
                let hasNext = i + 1 < chars.count
                let next: Character = hasNext ? chars[i + 1] : " "
                let betweenDigits = prev.isNumber && next.isNumber
                if hasNext && !betweenDigits && (next == " " || next == "\n") {
                    return text.index(text.startIndex, offsetBy: i + 1)
                }
            }
            i += 1
        }
        return nil
    }
}

/// Drives a `TTSProvider` from streaming text: segments deltas into sentences
/// and speaks them in order. An actor so feeds/cancels serialize. `cancel`
/// (barge-in) stops the provider and suppresses any further speech for the
/// current read. Feed deltas sequentially (await each) to preserve order.
public actor ReadAloudController {
    private let provider: TTSProvider
    private var segmenter = SentenceSegmenter()
    private var cancelled = false

    public init(provider: TTSProvider) {
        self.provider = provider
    }

    /// Start a fresh read (clears any prior buffer/cancel state).
    public func begin() {
        segmenter = SentenceSegmenter()
        cancelled = false
    }

    /// Feed a streaming text delta; speaks any sentences it completes.
    public func feed(_ delta: String) async {
        if cancelled { return }
        for sentence in segmenter.feed(delta) {
            if cancelled { return }
            await provider.speak(sentence)
        }
    }

    /// End of stream: speak the trailing fragment, if any.
    public func finish() async {
        if cancelled { return }
        if let tail = segmenter.flush() {
            await provider.speak(tail)
        }
    }

    /// Barge-in: stop now and ignore the rest of this read.
    public func cancel() {
        cancelled = true
        provider.stop()
    }
}
