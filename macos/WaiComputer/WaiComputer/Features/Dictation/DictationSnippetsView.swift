import SwiftUI
import WaiComputerKit

/// Snippet manager: voice-triggered text expansions. Say the trigger while
/// dictating ("my email") and the stored expansion is inserted instead.
struct DictationSnippetsView: View {
    @EnvironmentObject private var snippetsStore: DictationSnippetsStore
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var newTrigger = ""
    @State private var newExpansion = ""
    @State private var searchText = ""
    @State private var editingSnippet: DictationSnippet?
    /// Trigger whose add/save was rejected as a duplicate — inline feedback.
    @State private var duplicateTrigger: String?

    private var visibleSnippets: [DictationSnippet] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return snippetsStore.snippets }
        return snippetsStore.snippets.filter {
            $0.trigger.localizedCaseInsensitiveContains(query)
                || $0.expansion.localizedCaseInsensitiveContains(query)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                Text(t("Snippets", "Сниппеты"))
                    .font(Typography.displaySmall)

                Text(t(
                    "Say a trigger phrase while dictating and WaiComputer types the full expansion — addresses, sign-offs, links.",
                    "Произнеси триггер-фразу во время диктовки — WaiComputer подставит полный текст: адреса, подписи, ссылки."
                ))
                .font(Typography.body)
                .foregroundStyle(Palette.textSecondary)

                addRow
            }
            .padding(Spacing.xl)

            WaiDivider()

            if !snippetsStore.snippets.isEmpty {
                HStack {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(Palette.textTertiary)
                    TextField(t("Search snippets…", "Искать в сниппетах…"), text: $searchText)
                        .textFieldStyle(.plain)
                        .font(Typography.body)
                }
                .padding(.horizontal, Spacing.xl)
                .padding(.vertical, Spacing.md)

                WaiDivider()
            }

            if snippetsStore.snippets.isEmpty {
                Spacer()
                ContentUnavailableViewCompat(
                    t("No Snippets Yet", "Пока нет сниппетов"),
                    systemImage: "text.badge.plus",
                    description: Text(t(
                        "Add a trigger like \u{201C}my email\u{201D} with the text it should expand to.",
                        "Добавь триггер вроде «мой адрес» и текст, в который он разворачивается."
                    ))
                )
                Spacer()
            } else if visibleSnippets.isEmpty {
                Spacer()
                ContentUnavailableViewCompat(
                    t("No Results", "Ничего не найдено"),
                    systemImage: "magnifyingglass",
                    description: Text(t("No snippets match your search.", "Нет сниппетов по запросу."))
                )
                Spacer()
            } else {
                List {
                    ForEach(visibleSnippets) { snippet in
                        DictationSnippetRow(
                            snippet: snippet,
                            onEdit: { editingSnippet = snippet },
                            onDelete: { snippetsStore.delete(snippet) }
                        )
                        .listRowSeparator(.hidden)
                        .listRowBackground(Color.clear)
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .accessibilityIdentifier("dictation-snippets-view")
        .sheet(item: $editingSnippet) { snippet in
            SnippetEditSheet(
                snippet: snippet,
                onSave: { trigger, expansion in
                    let saved = snippetsStore.update(snippet, newTrigger: trigger, newExpansion: expansion)
                    if !saved { duplicateTrigger = trigger }
                    return saved
                }
            )
            .environmentObject(languageManager)
        }
    }

    private var addRow: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(spacing: Spacing.md) {
                TextField(t("Trigger — e.g. my email", "Триггер — например, мой адрес"), text: $newTrigger)
                    .textFieldStyle(.roundedBorder)
                    .font(Typography.body)
                    .frame(maxWidth: 260)
                    .accessibilityIdentifier("snippet-trigger-field")

                TextField(
                    t("Expansion — the text to insert", "Текст, который будет вставлен"),
                    text: $newExpansion
                )
                .textFieldStyle(.roundedBorder)
                .font(Typography.body)
                .accessibilityIdentifier("snippet-expansion-field")

                Button {
                    addSnippet()
                } label: {
                    Label(t("Add", "Добавить"), systemImage: "plus")
                        .font(Typography.headingSmall)
                }
                .buttonStyle(.borderedProminent)
                .disabled(
                    newTrigger.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                    newExpansion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
                .accessibilityIdentifier("snippet-add-button")
            }

            if let duplicateTrigger {
                Text(t(
                    "\u{201C}\(duplicateTrigger)\u{201D} is already a snippet trigger.",
                    "«\(duplicateTrigger)» уже используется как триггер."
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.danger)
            }
        }
    }

    private func addSnippet() {
        duplicateTrigger = nil
        let trigger = newTrigger.trimmingCharacters(in: .whitespacesAndNewlines)
        guard snippetsStore.add(trigger: trigger, expansion: newExpansion) else {
            duplicateTrigger = trigger
            return
        }
        newTrigger = ""
        newExpansion = ""
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

/// One snippet row with the shared hover affordance (surface-tint on
/// pointer-over) used across the app's clickable rows.
private struct DictationSnippetRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let snippet: DictationSnippet
    let onEdit: () -> Void
    let onDelete: () -> Void
    @State private var isHovered = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Spacing.lg) {
            Text(snippet.trigger)
                .font(Typography.headingSmall)
                .frame(width: 200, alignment: .leading)

            Image(systemName: "arrow.right")
                .font(.system(size: 10))
                .foregroundStyle(Palette.textTertiary)

            Text(snippet.expansion)
                .font(Typography.body)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)

            Button(action: onEdit) {
                Image(systemName: "pencil")
            }
            .buttonStyle(.plain)
            .foregroundStyle(Palette.textTertiary)
            .help(t("Edit snippet", "Редактировать сниппет"))

            Button(action: onDelete) {
                Image(systemName: "trash")
            }
            .buttonStyle(.plain)
            .foregroundStyle(Palette.textTertiary)
            .help(t("Delete snippet", "Удалить сниппет"))
        }
        .padding(.vertical, Spacing.sm)
        .padding(.horizontal, Spacing.xl)
        .background(isHovered ? Palette.surfaceHover : Color.clear)
        .contentShape(Rectangle())
        .onHover { isHovered = $0 }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct SnippetEditSheet: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.dismiss) private var dismiss
    let snippet: DictationSnippet
    let onSave: (String, String) -> Bool

    @State private var trigger: String
    @State private var expansion: String
    @State private var showDuplicateWarning = false

    init(snippet: DictationSnippet, onSave: @escaping (String, String) -> Bool) {
        self.snippet = snippet
        self.onSave = onSave
        _trigger = State(initialValue: snippet.trigger)
        _expansion = State(initialValue: snippet.expansion)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.lg) {
            Text(t("Edit Snippet", "Редактировать сниппет"))
                .font(Typography.headingLarge)

            TextField(t("Trigger", "Триггер"), text: $trigger)
                .textFieldStyle(.roundedBorder)

            TextEditor(text: $expansion)
                .font(Typography.body)
                .frame(minHeight: 96)
                .overlay(
                    RoundedRectangle(cornerRadius: Radius.sm)
                        .stroke(Palette.textTertiary.opacity(0.3), lineWidth: 1)
                )

            if showDuplicateWarning {
                Text(t(
                    "That trigger is already used by another snippet.",
                    "Такой триггер уже используется другим сниппетом."
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.danger)
            }

            HStack {
                Spacer()
                Button(t("Cancel", "Отмена")) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button(t("Save", "Сохранить")) {
                    if onSave(trigger, expansion) {
                        dismiss()
                    } else {
                        showDuplicateWarning = true
                    }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(
                    trigger.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                    expansion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
            }
        }
        .padding(Spacing.xl)
        .frame(width: 480)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
