import Foundation

// Turns one (produced → edited) text pair into gated, learnable correction
// pairs. Pure logic; no persistence, no UI. Pipeline:
//   normalize → locate inserted region → align → divergence guard →
//   per-substitution gates (length, noise, phonetic mishearing, OOV/proper-noun).
//
// Only mis-hearings of out-of-vocabulary / proper-noun terms survive — the same
// discipline Wispr Flow uses to keep auto-learning from polluting the dictionary.

public struct CorrectionExtractor: Sendable {

    public struct Config: Sendable {
        /// Bail if the edited text diverges from what we produced by more than
        /// this fraction of tokens (a big rewrite is not a vocabulary fix).
        public var maxDivergenceRatio: Double
        /// Ignore substitutions whose corrected token is shorter than this.
        public var minTokenLength: Int
        /// Require the substitution to be phonetically plausible (a mishearing).
        public var requirePhoneticMatch: Bool
        /// Require the corrected token to be OOV or a proper noun (not a common word).
        public var requireOOVorProperNoun: Bool

        public init(
            maxDivergenceRatio: Double = 0.5,
            minTokenLength: Int = 2,
            requirePhoneticMatch: Bool = true,
            requireOOVorProperNoun: Bool = true
        ) {
            self.maxDivergenceRatio = maxDivergenceRatio
            self.minTokenLength = minTokenLength
            self.requirePhoneticMatch = requirePhoneticMatch
            self.requireOOVorProperNoun = requireOOVorProperNoun
        }

        public static let `default` = Config()
    }

    public let lexicon: LexiconChecking
    public let config: Config

    public init(lexicon: LexiconChecking, config: Config = .default) {
        self.lexicon = lexicon
        self.config = config
    }

    /// Diff `produced` against `edited` and return the substitutions worth
    /// learning. `edited` may be the whole text field the user left after we
    /// pasted into it — the inserted region is located within it first.
    public func extract(produced: String, edited: String, language: String?) -> CorrectionExtractionResult {
        let producedTrimmed = produced.trimmingCharacters(in: .whitespacesAndNewlines)
        let editedTrimmed = edited.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !producedTrimmed.isEmpty, !editedTrimmed.isEmpty else {
            return .empty
        }

        let producedTokens = TokenAlignment.tokenize(producedTrimmed)
        let editedAll = TokenAlignment.tokenize(editedTrimmed)
        guard !producedTokens.isEmpty, !editedAll.isEmpty else {
            return CorrectionExtractionResult(pairs: [], skipped: .emptyInput)
        }

        // Byte-identical token streams ⇒ no edit. Case-only differences are NOT
        // short-circuited here — the capitalization pass below may learn them.
        if producedTokens == editedAll {
            return CorrectionExtractionResult(pairs: [], skipped: .identical)
        }

        // Scope to the region of the edited field that corresponds to what we
        // produced, so unrelated edits elsewhere in the document aren't blamed
        // on dictation.
        let editedTokens: [String]
        if let region = TokenAlignment.locate(producedTokens, in: editedAll) {
            editedTokens = Array(editedAll[region])
        } else if editedAll.count <= producedTokens.count * 2 {
            editedTokens = editedAll
        } else {
            return CorrectionExtractionResult(pairs: [], skipped: .tooDivergent)
        }

        let ops = TokenAlignment.align(producedTokens, editedTokens)

        let changed = ops.reduce(0) { acc, op in
            switch op {
            case .match: return acc
            case .substitute, .insert, .delete: return acc + 1
            }
        }
        let divergence = Double(changed) / Double(max(1, producedTokens.count))
        if divergence > config.maxDivergenceRatio {
            return CorrectionExtractionResult(pairs: [], skipped: .tooDivergent)
        }

        var pairs: [CorrectionPair] = []
        var seen = Set<String>()
        var sawCandidate = false

        func consider(from: String, to: String, casing: Bool) {
            sawCandidate = true
            let ok = casing
                ? isLearnableCasing(to: to, language: language)
                : isLearnable(from: from, to: to, language: language)
            guard ok else { return }
            let key = TokenAlignment.normalize(from) + "→" + TokenAlignment.normalize(to) + (casing ? "|case" : "")
            if seen.insert(key).inserted {
                pairs.append(CorrectionPair(original: from, corrected: to, language: language))
            }
        }

        // Spelling mis-hearings (the recognizer produced a different word).
        for op in ops {
            if case let .substitute(from, to) = op {
                consider(from: from, to: to, casing: false)
            }
        }

        // Pure-capitalization fixes of OOV proper nouns ("figma" → "Figma").
        // Only when tokens line up 1:1, so positions are trustworthy, and only
        // for OOV terms — so sentence-start capitalization of common words
        // ("hello" → "Hello") is never learned.
        if producedTokens.count == editedTokens.count {
            for (p, e) in zip(producedTokens, editedTokens)
            where p != e && p.lowercased() == e.lowercased() && addsCapitalization(from: p, to: e) {
                consider(from: p, to: e, casing: true)
            }
        }

        if pairs.isEmpty {
            return CorrectionExtractionResult(pairs: [], skipped: sawCandidate ? .allGated : .noSubstitutions)
        }
        return CorrectionExtractionResult(pairs: pairs, skipped: nil)
    }

    // MARK: - Gates

    private func isLearnable(from: String, to: String, language: String?) -> Bool {
        let correctedNorm = TokenAlignment.normalize(to)
        let originalNorm = TokenAlignment.normalize(from)
        guard correctedNorm.count >= config.minTokenLength,
              originalNorm.count >= config.minTokenLength else { return false }
        // Real change after normalization (defensive; align shouldn't emit equal).
        guard correctedNorm != originalNorm else { return false }

        if isNoise(corrected: to) { return false }

        if config.requirePhoneticMatch, !PhoneticMatcher.areSoundAlike(from, to) {
            // An unrelated rewrite (e.g. "budget" → "allocate"), not a mishearing.
            return false
        }

        if config.requireOOVorProperNoun, !isVocabularyCandidate(to, language: language) {
            return false
        }
        return true
    }

    /// Only learn capitalization that ADDS case — `to` gains an uppercase letter
    /// that `from` lacked. Rejects down-casing ("Figma"→"figma", "iOS"→"ios"),
    /// which would otherwise teach a regression the post-STT replace then applies.
    private func addsCapitalization(from: String, to: String) -> Bool {
        let fromAllLowercase = !from.contains { $0.isUppercase }
        let toHasUppercase = to.contains { $0.isUppercase }
        return fromAllLowercase && toHasUppercase
    }

    /// Gate for a pure-capitalization correction (same letters, different case).
    /// Skips the phonetic check (a case-only change is trivially a "sound-alike")
    /// and the normalized-inequality guard, but keeps length, noise, and the
    /// OOV gate so only unknown proper nouns are learned.
    private func isLearnableCasing(to: String, language: String?) -> Bool {
        let correctedNorm = TokenAlignment.normalize(to)
        guard correctedNorm.count >= config.minTokenLength else { return false }
        if isNoise(corrected: to) { return false }
        if config.requireOOVorProperNoun, !isVocabularyCandidate(to, language: language) {
            return false
        }
        return true
    }

    /// Reject corrected tokens that are formatting/noise rather than vocabulary:
    /// pure numbers (route to the numeral formatter, not the dictionary) and
    /// character elongations ("yesss").
    private func isNoise(corrected: String) -> Bool {
        let token = corrected
        if token.allSatisfy({ $0.isNumber }) { return true }
        // 3+ of the same letter in a row is an elongation, not a real word.
        var run = 1
        var previous: Character?
        for ch in token.lowercased() {
            if ch == previous { run += 1; if run >= 3 { return true } } else { run = 1 }
            previous = ch
        }
        return false
    }

    /// A corrected token is worth learning only if it is out-of-vocabulary — a
    /// name, brand, or specialized term the recognizer doesn't know. Known
    /// common words are never auto-learned (they would mis-replace ordinary
    /// speech), matching Wispr Flow's "common words aren't added" rule.
    private func isVocabularyCandidate(_ token: String, language: String?) -> Bool {
        !lexicon.isKnownWord(token, language: language)
    }
}
