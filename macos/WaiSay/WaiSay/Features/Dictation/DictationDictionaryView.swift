import SwiftUI

struct DictationDictionaryView: View {
    @EnvironmentObject private var dictionaryStore: DictationDictionaryStore
    @State private var newWord = ""
    @State private var newReplacement = ""
    @State private var searchText = ""

    /// SuperWhisper warns that very long vocabulary lists confuse the model
    /// and degrade language detection. ~50 entries on the wire is the
    /// soft-cap; we surface a hint earlier so users course-correct before
    /// recognition quality drops.
    private let warnAboveCount = 30

    private var filteredWords: [DictionaryWord] {
        if searchText.isEmpty { return dictionaryStore.words }
        return dictionaryStore.words.filter {
            $0.word.localizedCaseInsensitiveContains(searchText)
                || ($0.replacement?.localizedCaseInsensitiveContains(searchText) ?? false)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            VStack(alignment: .leading, spacing: Spacing.md) {
                Text("Dictionary")
                    .font(Typography.displaySmall)

                explainerCopy

                if dictionaryStore.words.count >= warnAboveCount {
                    overuseWarning
                }

                addRow
            }
            .padding(Spacing.xl)

            Divider()

            // Search
            if !dictionaryStore.words.isEmpty {
                HStack {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(Palette.textTertiary)
                    TextField("Search dictionary…", text: $searchText)
                        .textFieldStyle(.plain)
                        .font(Typography.body)
                }
                .padding(.horizontal, Spacing.xl)
                .padding(.vertical, Spacing.md)

                Divider()
            }

            // Word list
            if dictionaryStore.words.isEmpty {
                Spacer()
                ContentUnavailableView(
                    "No Words Yet",
                    systemImage: "book",
                    description: Text("Add words dictation often misspells — names, acronyms, technical terms.")
                )
                Spacer()
            } else if filteredWords.isEmpty {
                Spacer()
                ContentUnavailableView(
                    "No Results",
                    systemImage: "magnifyingglass",
                    description: Text("No words match your search.")
                )
                Spacer()
            } else {
                List {
                    ForEach(filteredWords) { word in
                        wordRow(word)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    @ViewBuilder
    private var explainerCopy: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Each entry biases the recognizer toward your spelling. Add an optional replacement to also auto-correct a known misspelling after transcription.")
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            HStack(spacing: 12) {
                badgeLegend(label: "BIAS", color: Palette.accent, hint: "Word boosts recognition")
                badgeLegend(label: "REPLACE", color: .orange, hint: "Auto-corrects to replacement")
            }
        }
    }

    @ViewBuilder
    private var overuseWarning: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.caption)
                .foregroundStyle(.orange)
            Text("\(dictionaryStore.words.count) entries — long vocabulary lists can confuse the recognizer and slow language detection. Keep entries focused on words that genuinely get misheard.")
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.orange.opacity(0.10))
        )
    }

    @ViewBuilder
    private var addRow: some View {
        VStack(spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                TextField("Word or phrase…", text: $newWord)
                    .textFieldStyle(.roundedBorder)
                    .font(Typography.body)
                    .onSubmit { addWord() }

                Image(systemName: "arrow.right")
                    .font(.caption)
                    .foregroundStyle(Palette.textTertiary)

                TextField("Replace with… (optional)", text: $newReplacement)
                    .textFieldStyle(.roundedBorder)
                    .font(Typography.body)
                    .onSubmit { addWord() }

                Button("Add") { addWord() }
                    .disabled(newWord.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            HStack(spacing: 6) {
                Text("Leave the right field empty to add a vocabulary booster only.")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                Spacer()
            }
        }
    }

    @ViewBuilder
    private func wordRow(_ word: DictionaryWord) -> some View {
        HStack(spacing: 8) {
            Text(word.word)
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)

            if let replacement = word.replacement, replacement != word.word {
                Image(systemName: "arrow.right")
                    .font(.caption)
                    .foregroundStyle(Palette.textTertiary)
                Text(replacement)
                    .font(Typography.body)
                    .foregroundStyle(Palette.textSecondary)
                badge(label: "REPLACE", color: .orange)
            } else {
                badge(label: "BIAS", color: Palette.accent)
            }

            Spacer()

            Button {
                dictionaryStore.delete(word)
            } label: {
                Image(systemName: "xmark")
                    .font(.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
            .buttonStyle(.plain)
            .help("Remove word")
        }
        .padding(.vertical, Spacing.xs)
    }

    @ViewBuilder
    private func badge(label: String, color: Color) -> some View {
        Text(label)
            .font(.system(size: 9, weight: .semibold, design: .monospaced))
            .tracking(0.6)
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .fill(color.opacity(0.12))
            )
    }

    @ViewBuilder
    private func badgeLegend(label: String, color: Color, hint: String) -> some View {
        HStack(spacing: 4) {
            badge(label: label, color: color)
            Text(hint)
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
        }
    }

    private func addWord() {
        let trimmed = newWord.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let replacementTrimmed = newReplacement.trimmingCharacters(in: .whitespacesAndNewlines)
        let replacement = replacementTrimmed.isEmpty ? nil : replacementTrimmed
        dictionaryStore.add(word: trimmed, replacement: replacement)
        newWord = ""
        newReplacement = ""
    }
}
