import SwiftUI
import WaiComputerKit

/// Capture sheet for the second brain: paste a link or any text. A URL is
/// fetched + summarized; free text is saved as a note. Mirrors the macOS
/// add-anything field.
struct AddAnythingSheet: View {
    @Binding var isPresented: Bool
    let isAdding: Bool
    let onSubmit: (String) -> Void

    @EnvironmentObject private var languageManager: LanguageManager
    @State private var text: String = ""
    @FocusState private var focused: Bool

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: Spacing.md) {
                Text(t("Paste a link, or any text to remember.",
                       "Вставьте ссылку или любой текст, чтобы запомнить."))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)

                TextEditor(text: $text)
                    .font(Typography.body)
                    .focused($focused)
                    .frame(minHeight: 160)
                    .padding(Spacing.xs)
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Palette.border, lineWidth: 1)
                    )

                Spacer()
            }
            .padding(Spacing.lg)
            .navigationTitle(t("Add to brain", "Добавить в мозг"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(t("Cancel", "Отмена")) { isPresented = false }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if isAdding {
                        ProgressView()
                    } else {
                        Button(t("Add", "Добавить")) {
                            onSubmit(text)
                        }
                        .fontWeight(.semibold)
                        .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
            }
            .onAppear { focused = true }
        }
    }
}
