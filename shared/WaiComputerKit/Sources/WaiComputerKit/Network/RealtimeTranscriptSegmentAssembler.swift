import Foundation

enum RealtimeTranscriptSegmentAssembler {
    static func deepgramSegments(
        from words: [[String: Any]],
        fallbackTranscript: String,
        fallbackConfidence: Double?,
        fallbackStartMs: Int
    ) -> [LiveTranscriptSegment] {
        var segments: [LiveTranscriptSegment] = []
        var currentWords: [[String: Any]] = []
        var currentSpeaker: String?

        func flush() {
            guard !currentWords.isEmpty else { return }
            let text = joinedDeepgramWords(currentWords)
            guard !text.isEmpty else {
                currentWords = []
                return
            }
            let startMs = secondsMs(currentWords.first?["start"])
                ?? segments.last?.endMs
                ?? fallbackStartMs
            segments.append(LiveTranscriptSegment(
                text: text,
                speaker: currentSpeaker,
                isFinal: true,
                startMs: startMs,
                endMs: secondsMs(currentWords.last?["end"]) ?? startMs,
                confidence: averageConfidence(currentWords) ?? fallbackConfidence ?? 0
            ))
            currentWords = []
        }

        for word in words {
            guard deepgramWordText(word) != nil else { continue }
            let speaker = speakerLabel(word["speaker"])
            if !currentWords.isEmpty, speaker != currentSpeaker {
                flush()
            }
            currentSpeaker = speaker
            currentWords.append(word)
        }
        flush()

        if segments.isEmpty {
            let startMs = secondsMs(words.first?["start"]) ?? fallbackStartMs
            return [
                LiveTranscriptSegment(
                    text: fallbackTranscript,
                    speaker: speakerLabel(words.first?["speaker"]),
                    isFinal: true,
                    startMs: startMs,
                    endMs: secondsMs(words.last?["end"]) ?? startMs,
                    confidence: fallbackConfidence ?? averageConfidence(words) ?? 0
                )
            ]
        }
        return segments
    }

    static func sonioxSegments(
        from tokens: [[String: Any]],
        isFinal: Bool,
        fallbackStartMs: Int
    ) -> [LiveTranscriptSegment] {
        let speechTokens = tokens.filter {
            ($0["translation_status"] as? String) != "translation"
                && (($0["text"] as? String)?.hasPrefix("<") != true)
        }
        guard !speechTokens.isEmpty else { return [] }

        var segments: [LiveTranscriptSegment] = []
        var currentTokens: [[String: Any]] = []
        var currentSpeaker: String?

        func flush() {
            guard !currentTokens.isEmpty else { return }
            let text = currentTokens.compactMap { $0["text"] as? String }
                .joined()
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else {
                currentTokens = []
                return
            }
            let startMs = integerMs(currentTokens.first?["start_ms"])
                ?? segments.last?.endMs
                ?? fallbackStartMs
            segments.append(LiveTranscriptSegment(
                text: text,
                speaker: currentSpeaker,
                isFinal: isFinal,
                startMs: startMs,
                endMs: integerMs(currentTokens.last?["end_ms"]) ?? startMs,
                confidence: averageConfidence(currentTokens) ?? 0
            ))
            currentTokens = []
        }

        for token in speechTokens {
            let speaker = speakerLabel(token["speaker"])
            if !currentTokens.isEmpty, speaker != currentSpeaker {
                flush()
            }
            currentSpeaker = speaker
            currentTokens.append(token)
        }
        flush()
        return segments
    }

    private static func speakerLabel(_ value: Any?) -> String? {
        guard let value else { return nil }
        if let string = value as? String {
            if string.lowercased().hasPrefix("speaker") {
                return string
            }
            return "Speaker \(string)"
        }
        if let int = value as? Int {
            return "Speaker \(int)"
        }
        if let number = value as? NSNumber {
            return "Speaker \(number.intValue)"
        }
        return nil
    }

    private static func deepgramWordText(_ word: [String: Any]) -> String? {
        let text = (word["punctuated_word"] as? String) ?? (word["word"] as? String)
        let trimmed = text?.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed?.isEmpty == false ? trimmed : nil
    }

    private static func joinedDeepgramWords(_ words: [[String: Any]]) -> String {
        words.compactMap(deepgramWordText)
            .reduce(into: "") { result, word in
                if result.isEmpty {
                    result = word
                } else if word.unicodeScalars.first.map({ CharacterSet(charactersIn: ".,?!;:%)]}").contains($0) }) == true {
                    result += word
                } else {
                    result += " " + word
                }
            }
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func secondsMs(_ value: Any?) -> Int? {
        guard let value else { return nil }
        if let double = value as? Double {
            return Int(double * 1000)
        }
        if let int = value as? Int {
            return int * 1000
        }
        if let number = value as? NSNumber {
            return Int(number.doubleValue * 1000)
        }
        if let string = value as? String, let double = Double(string) {
            return Int(double * 1000)
        }
        return nil
    }

    private static func integerMs(_ value: Any?) -> Int? {
        if let int = value as? Int {
            return int
        }
        if let double = value as? Double {
            return Int(double)
        }
        if let number = value as? NSNumber {
            return number.intValue
        }
        if let string = value as? String, let int = Int(string) {
            return int
        }
        return nil
    }

    private static func averageConfidence(_ items: [[String: Any]]) -> Double? {
        let confidences = items.compactMap { item -> Double? in
            if let double = item["confidence"] as? Double {
                return double
            }
            if let number = item["confidence"] as? NSNumber {
                return number.doubleValue
            }
            return nil
        }
        guard !confidences.isEmpty else { return nil }
        return confidences.reduce(0, +) / Double(confidences.count)
    }
}
