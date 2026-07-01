import SwiftUI
import WaiComputerKit

/// Capture sheet for the second brain: paste a link or any text. A URL is
/// fetched + summarized; free text is saved as a note. Mirrors the macOS
/// add-anything field.
struct AddAnythingSheet: View {
    @Binding var isPresented: Bool
    let isAdding: Bool
    let onSubmit: (String) -> Void

    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var text: String = ""
    @FocusState private var focused: Bool

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        NavigationStack {
            sheetContent
                .navigationTitle(t("Add to brain", "Добавить в мозг"))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button(t("Cancel", "Отмена")) {
                            cancel()
                        }
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        if isAdding {
                            ProgressView()
                        } else {
                            Button(t("Add", "Добавить")) {
                                submit()
                            }
                            .fontWeight(.semibold)
                            .disabled(trimmedText.isEmpty)
                        }
                    }
                }
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .onAppear { focused = true }
        }
    }

    @ViewBuilder
    private var sheetContent: some View {
        if prefersRegularLayout {
            regularSheetLayout
        } else {
            compactSheetLayout
        }
    }

    private var prefersRegularLayout: Bool {
        horizontalSizeClass == .regular || UIDevice.current.userInterfaceIdiom == .pad
    }

    private var regularSheetLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                HStack(alignment: .top, spacing: Spacing.md) {
                    Image(systemName: "doc.text")
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(Palette.accent)
                        .frame(width: 42, height: 42)
                        .background(Palette.accent.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))

                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t("Paste Link or Text", "Вставить ссылку или текст"))
                            .font(Typography.headingLarge)
                            .foregroundStyle(Palette.textPrimary)

                        Text(t("Links are summarized; text is saved as a note.",
                               "Ссылки суммируются, текст сохраняется как заметка."))
                            .font(Typography.bodySmall)
                            .foregroundStyle(Palette.textSecondary)
                    }
                }

                editorCard
            }
            .frame(maxWidth: 760, alignment: .leading)
            .padding(.horizontal, Spacing.xl)
            .padding(.vertical, Spacing.lg)
        }
        .background(Color(uiColor: .secondarySystemBackground))
        .accessibilityIdentifier("add-anything-regular-layout")
    }

    private var compactSheetLayout: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Text(t("Paste a link, or any text to remember.",
                   "Вставьте ссылку или любой текст, чтобы запомнить."))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)

            editorCard

            Spacer()
        }
        .padding(Spacing.lg)
        .accessibilityIdentifier("add-anything-compact-layout")
    }

    private var editorCard: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(t("Material", "Материал"))
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)

            TextEditor(text: $text)
                .font(Typography.body)
                .focused($focused)
                .frame(minHeight: prefersRegularLayout ? 220 : 160)
                .padding(Spacing.xs)
                .background(Color(uiColor: .systemBackground))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Palette.border, lineWidth: 1)
                )
                .accessibilityIdentifier("add-anything-editor")
        }
        .padding(prefersRegularLayout ? Spacing.md : 0)
        .background(
            Group {
                if prefersRegularLayout {
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color(uiColor: .systemBackground))
                        .overlay(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Palette.border.opacity(0.7), lineWidth: 1)
                        )
                }
            }
        )
    }

    private var trimmedText: String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func cancel() {
        isPresented = false
        dismiss()
    }

    private func submit() {
        guard !trimmedText.isEmpty else { return }
        onSubmit(text)
    }
}
