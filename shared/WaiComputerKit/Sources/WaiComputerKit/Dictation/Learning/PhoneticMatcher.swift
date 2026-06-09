import Foundation

// Phonetic similarity for the learn-from-edits engine: decide whether a
// substitution is a genuine mis-hearing (learnable) or an unrelated rewrite
// (ignore). FROZEN PUBLIC API — implement bodies, keep signatures.
//
// Script-aware: Latin uses a Metaphone-style consonant skeleton; Cyrillic uses
// Russian reduction rules (collapse unstressed vowels О/Ы/Я→А, Ю→У, Е/Ё/Э→И;
// devoice final/pre-consonant Б→П, З→С, Д→Т, В→Ф, Г→К, Ж→Ш; drop ь/ъ and
// doubled letters). Mixed/other scripts fall back to edit-distance similarity.
// Do NOT use Soundex/Metaphone on Cyrillic — they encode English phonetics.

public enum PhoneticMatcher {

    /// True if `a` and `b` plausibly sound alike (a mis-recognition), false if
    /// they read as an unrelated rewrite. Combines phonetic-code equality with
    /// an edit-distance floor; case/whitespace-insensitive.
    public static func areSoundAlike(_ a: String, _ b: String) -> Bool {
        let na = cleaned(a)
        let nb = cleaned(b)
        // Empty inputs carry no signal: never treat as a learnable mis-hearing.
        if na.isEmpty || nb.isEmpty { return false }
        if na == nb { return true }

        let sim = similarity(na, nb)

        // Very short tokens are noisy (a 1-char edit on a 2-char token is a
        // wildly different word); demand near-identity instead of trusting the
        // phonetic skeleton, which collapses too aggressively at this length.
        if na.count <= 2 || nb.count <= 2 {
            return sim >= 0.85
        }

        let ca = code(for: na)
        let cb = code(for: nb)
        if !ca.isEmpty && ca == cb { return true }

        return sim >= 0.72
    }

    /// Normalized similarity in 0...1 (1 = identical), Levenshtein-based on the
    /// case-folded tokens. Exposed for thresholds and tests.
    public static func similarity(_ a: String, _ b: String) -> Double {
        let la = Array(a.lowercased())
        let lb = Array(b.lowercased())
        if la.isEmpty && lb.isEmpty { return 1.0 }
        if la.isEmpty || lb.isEmpty { return 0.0 }
        if la == lb { return 1.0 }
        let distance = levenshtein(la, lb)
        let denominator = Double(max(la.count, lb.count))
        return 1.0 - Double(distance) / denominator
    }

    /// Phonetic code for a single token (script auto-detected). Visible for
    /// tests; two tokens with equal non-empty codes are treated as sound-alike.
    public static func code(for token: String) -> String {
        let folded = cleaned(token)
        guard !folded.isEmpty else { return "" }
        switch dominantScript(folded) {
        case .cyrillic:
            return russianCode(folded)
        case .latin:
            return latinCode(folded)
        case .other:
            // Digits / symbols / mixed scripts carry no reliable phonetic
            // skeleton — fall back to similarity only (empty code never matches).
            return ""
        }
    }

    // MARK: - Script detection

    private enum Script {
        case latin
        case cyrillic
        case other
    }

    /// Majority vote over letters only. A token is Cyrillic if more of its
    /// letters are Cyrillic than Latin, Latin if the reverse, otherwise `other`
    /// (no letters, or a tie).
    private static func dominantScript(_ token: String) -> Script {
        var latin = 0
        var cyrillic = 0
        for scalar in token.unicodeScalars {
            if scalar.value >= 0x0400 && scalar.value <= 0x04FF {
                cyrillic += 1
            } else if (scalar.value >= 0x41 && scalar.value <= 0x5A) ||
                      (scalar.value >= 0x61 && scalar.value <= 0x7A) {
                latin += 1
            }
        }
        if cyrillic == 0 && latin == 0 { return .other }
        if cyrillic > latin { return .cyrillic }
        if latin > cyrillic { return .latin }
        return .other
    }

    // MARK: - Latin phonetic skeleton (Metaphone-style)

    /// A deterministic consonant skeleton: keep the leading sound, drop later
    /// vowels, and fold a handful of English spelling equivalences so that
    /// "figma"/"figmah" and "kubernetes"/"kubernetis" share a code while
    /// unrelated words do not. Not full Double Metaphone — just enough signal.
    private static func latinCode(_ token: String) -> String {
        // Uppercase, strip anything that is not an A–Z letter.
        let letters = Array(token.uppercased().unicodeScalars.filter {
            $0.value >= 0x41 && $0.value <= 0x5A
        }.map { Character($0) })
        guard !letters.isEmpty else { return "" }

        let vowels: Set<Character> = ["A", "E", "I", "O", "U"]
        var out: [Character] = []
        let n = letters.count
        var i = 0

        while i < n {
            let c = letters[i]
            let next: Character? = (i + 1 < n) ? letters[i + 1] : nil
            let prev: Character? = out.last

            // Collapse runs of the same source letter (double letters: TT→T).
            if i + 1 < n && letters[i + 1] == c {
                i += 1
                continue
            }

            switch c {
            case "A", "E", "I", "O", "U":
                // Keep a vowel only if it leads the code (preserves the initial
                // sound, e.g. "apple" → "APL"); drop interior/trailing vowels.
                if out.isEmpty {
                    out.append(c)
                }
            case "Y":
                // Y is a vowel except when it leads the word (yes → consonant).
                if out.isEmpty {
                    out.append("Y")
                }
            case "P":
                if next == "H" {
                    // PH → F
                    out.append("F")
                    i += 2
                    continue
                }
                out.append("P")
            case "C":
                if next == "K" {
                    // CK → K (single)
                    out.append("K")
                    i += 2
                    continue
                }
                if next == "H" {
                    // CH → X (a distinct sound; keeps "tech"≠"tek")
                    out.append("X")
                    i += 2
                    continue
                }
                // Soft C before E/I/Y sounds like S; hard C elsewhere like K.
                if let nx = next, nx == "E" || nx == "I" || nx == "Y" {
                    appendUnlessDup(&out, "S")
                } else {
                    appendUnlessDup(&out, "K")
                }
            case "Q":
                // Q(u) → K
                appendUnlessDup(&out, "K")
                if next == "U" { i += 1 }
            case "K":
                appendUnlessDup(&out, "K")
            case "S":
                if next == "H" {
                    out.append("X")
                    i += 2
                    continue
                }
                out.append("S")
            case "T":
                if next == "H" {
                    out.append("0") // TH as its own sound
                    i += 2
                    continue
                }
                out.append("T")
            case "G":
                if next == "H" {
                    // Silent GH (e.g. "night") — drop entirely.
                    i += 2
                    continue
                }
                out.append("G")
            case "Z":
                appendUnlessDup(&out, "S")
            case "X":
                // X → KS
                out.append("K")
                out.append("S")
            case "W":
                // Keep W only when it starts a syllable sound (before a vowel);
                // silent after a vowel (e.g. trailing "ow").
                if let nx = next, vowels.contains(nx) {
                    out.append("W")
                } else if out.isEmpty {
                    out.append("W")
                }
            case "H":
                // Keep H only if it leads a sound (before a vowel) and is not
                // already swallowed by a digraph above; silent after a vowel
                // (so "figmah" == "figma").
                if let nx = next, vowels.contains(nx) {
                    if prev == nil || vowels.contains(prev!) {
                        out.append("H")
                    }
                }
            default:
                appendUnlessDup(&out, c)
            }
            i += 1
        }

        // Drop a common silent trailing E that survived as the lead vowel only
        // when something follows it — already handled (interior vowels dropped).
        return String(out)
    }

    private static func appendUnlessDup(_ out: inout [Character], _ c: Character) {
        if out.last != c {
            out.append(c)
        }
    }

    // MARK: - Russian phonetic reduction

    /// Russian-specific reduction. Do NOT run Latin Metaphone here. Collapses
    /// unstressed-vowel mergers and final/pre-voiceless devoicing so that
    /// homophones the recognizer confuses ("компания"/"кампания") share a code.
    private static func russianCode(_ token: String) -> String {
        // Uppercase Cyrillic, drop non-Cyrillic-letter characters.
        let letters = Array(token.uppercased().unicodeScalars.filter {
            $0.value >= 0x0400 && $0.value <= 0x04FF
        }.map { Character($0) })
        guard !letters.isEmpty else { return "" }

        // Voiceless consonants that trigger regressive devoicing of a preceding
        // voiced obstruent.
        let voiceless: Set<Character> = ["П", "Ф", "К", "Т", "Ш", "С", "Х", "Ц", "Ч", "Щ"]
        let devoice: [Character: Character] = [
            "Б": "П", "З": "С", "Д": "Т", "В": "Ф", "Г": "К", "Ж": "Ш"
        ]

        var stage: [Character] = []
        let n = letters.count

        for i in 0..<n {
            var c = letters[i]

            // Drop soft/hard signs entirely.
            if c == "Ь" || c == "Ъ" { continue }

            // Vowel reduction (merge unstressed-confusable vowels).
            switch c {
            case "О", "Ы", "Я": c = "А"
            case "Ю": c = "У"
            case "Е", "Ё", "Э": c = "И"
            default: break
            }

            // Consonant devoicing: a voiced obstruent is devoiced word-finally
            // or before a voiceless consonant. Look ahead at the ORIGINAL stream
            // for the trigger, skipping ь/ъ (which are not sounds themselves).
            if let voicelessForm = devoice[c] {
                var trigger: Character? = nil
                var k = i + 1
                while k < n {
                    let nxt = letters[k]
                    if nxt == "Ь" || nxt == "Ъ" { k += 1; continue }
                    trigger = nxt
                    break
                }
                let isFinal = (trigger == nil)            // nothing voiced/voiceless after
                let beforeVoiceless = trigger.map { voiceless.contains($0) } ?? false
                if isFinal || beforeVoiceless {
                    c = voicelessForm
                }
            }

            stage.append(c)
        }

        // Collapse doubled letters (after reduction so "нн"→"н", and merges
        // created by reduction also collapse).
        var out: [Character] = []
        for c in stage {
            if out.last != c {
                out.append(c)
            }
        }
        return String(out)
    }

    // MARK: - Shared helpers

    /// Lower-case and strip surrounding whitespace; the comparison unit.
    private static func cleaned(_ s: String) -> String {
        s.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    /// Classic iterative Levenshtein (two-row), unit cost.
    private static func levenshtein(_ a: [Character], _ b: [Character]) -> Int {
        if a.isEmpty { return b.count }
        if b.isEmpty { return a.count }
        var previous = Array(0...b.count)
        var current = Array(repeating: 0, count: b.count + 1)
        for i in 1...a.count {
            current[0] = i
            for j in 1...b.count {
                let cost = a[i - 1] == b[j - 1] ? 0 : 1
                current[j] = min(
                    previous[j] + 1,        // deletion
                    current[j - 1] + 1,     // insertion
                    previous[j - 1] + cost  // substitution
                )
            }
            swap(&previous, &current)
        }
        return previous[b.count]
    }
}
