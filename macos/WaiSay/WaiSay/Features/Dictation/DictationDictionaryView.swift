import SwiftUI

struct DictationDictionaryView: View {
    @EnvironmentObject private var dictionaryStore: DictationDictionaryStore
    @State private var newWord = ""
    @State private var searchText = ""

    private var filteredWords: [DictionaryWord] {
        if searchText.isEmpty { return dictionaryStore.words }
        return dictionaryStore.words.filter {
            $0.word.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            VStack(alignment: .leading, spacing: Spacing.md) {
                Text("Dictionary")
                    .font(Typography.displaySmall)

                Text("Add personal terms, company jargon, client names, or technical vocabulary. These words improve recognition accuracy during dictation.")
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)

                // Add word field
                HStack(spacing: Spacing.sm) {
                    TextField("Add new word...", text: $newWord)
                        .textFieldStyle(.roundedBorder)
                        .font(Typography.body)
                        .onSubmit { addWord() }

                    Button("Add") { addWord() }
                        .disabled(newWord.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .padding(Spacing.xl)

            Divider()

            // Search
            if !dictionaryStore.words.isEmpty {
                HStack {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(Palette.textTertiary)
                    TextField("Search dictionary...", text: $searchText)
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
                    description: Text("Add words that dictation often misspells — names, acronyms, technical terms.")
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
                        HStack {
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
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func addWord() {
        let trimmed = newWord.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        dictionaryStore.add(word: trimmed)
        newWord = ""
    }
}
