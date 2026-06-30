import SwiftUI
import WaiComputerKit

struct MacSelectionCommandContext {
    let canSelectAll: Bool
    let canClearSelection: Bool
    let canDelete: Bool
    let canMoveToTrash: Bool
    let canRestore: Bool
    let canDeletePermanently: Bool
    let selectAll: () -> Void
    let clearSelection: () -> Void
    let delete: () -> Void
    let moveToTrash: () -> Void
    let restore: () -> Void
    let deletePermanently: () -> Void
}

private struct MacSelectionCommandContextKey: FocusedValueKey {
    typealias Value = MacSelectionCommandContext
}

extension FocusedValues {
    var macSelectionCommands: MacSelectionCommandContext? {
        get { self[MacSelectionCommandContextKey.self] }
        set { self[MacSelectionCommandContextKey.self] = newValue }
    }
}

struct MacSelectionCommands: Commands {
    @FocusedValue(\.macSelectionCommands) private var context

    var body: some Commands {
        CommandGroup(after: .pasteboard) {
            Divider()

            Button(t("Select All Rows", "Выделить все строки")) {
                context?.selectAll()
            }
            .keyboardShortcut("a", modifiers: .command)
            .disabled(context?.canSelectAll != true)

            Button(t("Clear Selection", "Снять выделение")) {
                context?.clearSelection()
            }
            .keyboardShortcut(.escape, modifiers: [])
            .disabled(context?.canClearSelection != true)

            Button(t("Delete Selected", "Удалить выбранное")) {
                context?.delete()
            }
            .keyboardShortcut(.delete, modifiers: [])
            .disabled(context?.canDelete != true)

            Button(t("Move Selected to Trash", "Переместить выбранное в корзину")) {
                context?.moveToTrash()
            }
            .keyboardShortcut(.delete, modifiers: .command)
            .disabled(context?.canMoveToTrash != true)

            Button(t("Restore Selected", "Восстановить выбранное")) {
                context?.restore()
            }
            .keyboardShortcut("r", modifiers: [.command, .option])
            .disabled(context?.canRestore != true)

            Button(t("Delete Selected Permanently", "Удалить выбранное навсегда")) {
                context?.deletePermanently()
            }
            .keyboardShortcut(.delete, modifiers: [.command, .shift])
            .disabled(context?.canDeletePermanently != true)
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: LanguageManager.shared.current)
    }
}
