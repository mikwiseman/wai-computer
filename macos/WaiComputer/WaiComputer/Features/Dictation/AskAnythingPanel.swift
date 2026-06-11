import Cocoa
import SwiftUI
import WaiComputerKit

final class AskAnythingPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    /// Invoked when the user presses Escape while the panel is key —
    /// keyboard parity with the close button.
    var onEscape: (() -> Void)?

    init() {
        super.init(
            contentRect: NSRect(x: 0, y: 0, width: 820, height: 440),
            styleMask: [.borderless, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        isMovableByWindowBackground = true
        hidesOnDeactivate = false
        isReleasedWhenClosed = false
        setAccessibilityIdentifier("ask-anything-panel")
        animationBehavior = .utilityWindow
        positionAtCenter()
    }

    /// Escape reaches the panel through the responder chain as
    /// `cancelOperation(_:)` — a borderless panel otherwise just beeps.
    override func cancelOperation(_ sender: Any?) {
        onEscape?()
    }

    func setContent(_ view: some View) {
        let hostingView = NSHostingView(rootView: view)
        hostingView.frame = contentRect(forFrameRect: frame)
        contentView = hostingView
    }

    func showAnimated() {
        positionAtCenter()
        alphaValue = 0
        orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.18
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            animator().alphaValue = 1
        }
    }

    func hideAnimated() {
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.14
            context.timingFunction = CAMediaTimingFunction(name: .easeIn)
            animator().alphaValue = 0
        }, completionHandler: { [weak self] in
            self?.orderOut(nil)
        })
    }

    private func positionAtCenter() {
        guard let screen = NSScreen.main else { return }
        let screenFrame = screen.visibleFrame
        let x = screenFrame.midX - frame.width / 2
        let y = screenFrame.midY - frame.height / 2
        setFrameOrigin(NSPoint(x: x, y: y))
    }
}

struct AskAnythingAnswerView: View {
    @ObservedObject var manager: DictationManager
    @ObservedObject private var languageManager = LanguageManager.shared

    var body: some View {
        VStack(spacing: 0) {
            header
            questionRow
            answerPane
        }
        .frame(width: 820, height: 440)
        .background(
            RoundedRectangle(cornerRadius: 24)
                .fill(.regularMaterial)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 24)
                .strokeBorder(.white.opacity(0.26), lineWidth: 0.7)
        )
    }

    private var header: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "sparkles")
                .foregroundStyle(Palette.accent)
            Text("Wai")
                .font(Typography.headingLarge)
                .foregroundStyle(Palette.textPrimary)
            Spacer()
            Button {
                manager.closeAskAnythingAnswer()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Palette.textSecondary)
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("ask-anything-close-button")
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.top, Spacing.lg)
        .padding(.bottom, Spacing.md)
    }

    private var questionRow: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            Image(systemName: "mic")
                .foregroundStyle(Palette.textTertiary)
                .frame(width: 20)
            Text(manager.askAnythingQuestion)
                .font(Typography.headingSmall)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2)
            Spacer(minLength: Spacing.md)
            Button {
                manager.copyAskAnythingQuestion()
            } label: {
                Image(systemName: "doc.on.doc")
                    .foregroundStyle(Palette.textSecondary)
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("ask-anything-copy-question-button")
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.bottom, Spacing.lg)
    }

    private var answerPane: some View {
        VStack(spacing: 0) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "sparkle")
                    .foregroundStyle(Palette.accent)
                Text(t("Answer", "Ответ"))
                    .font(Typography.headingSmall)
                    .foregroundStyle(Palette.textPrimary)
                Spacer()
                Button {
                    manager.copyAskAnythingAnswer()
                } label: {
                    Image(systemName: "doc.on.doc")
                        .foregroundStyle(Palette.textSecondary)
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(.plain)
                .disabled(manager.askAnythingAnswer.isEmpty)
                .accessibilityIdentifier("ask-anything-copy-answer-button")
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.md)

            Divider()

            ScrollView {
                if manager.askAnythingAnswer.isEmpty && manager.isAskAnythingStreaming {
                    ProgressView()
                        .controlSize(.small)
                        .padding(.top, Spacing.xl)
                } else {
                    Text(answerText)
                        .font(.system(size: 22, weight: .regular, design: .default))
                        .lineSpacing(6)
                        .foregroundStyle(Palette.textPrimary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                        .padding(Spacing.lg)
                }
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color(nsColor: .textBackgroundColor).opacity(0.86))
        )
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal, Spacing.xl)
        .padding(.bottom, Spacing.xl)
    }

    private var answerText: String {
        if manager.askAnythingAnswer.isEmpty {
            if manager.isAskAnythingStreaming {
                return t("Thinking...", "Думаю...")
            }
            // Terminal state with nothing produced (cancelled or empty
            // stream) — say so honestly instead of pretending to think.
            return t(
                "No answer. Hold the hotkey to ask again.",
                "Ответа нет. Зажми клавишу и спроси ещё раз."
            )
        }
        return manager.askAnythingAnswer
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
