import SwiftUI
import WaiComputerKit

// MARK: - Spacing (8pt grid)

enum Spacing {
    static let xxs: CGFloat = 2
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    static let xl: CGFloat = 24
    static let xxl: CGFloat = 32
    static let xxxl: CGFloat = 48
    static let huge: CGFloat = 64
}

// MARK: - Typography

enum Typography {
    /// 32pt bold serif — Recording title in detail
    static let displayLarge: Font = .system(size: 32, weight: .bold, design: .serif)
    /// 26pt semibold serif — Page headings
    static let displayMedium: Font = .system(size: 26, weight: .semibold, design: .serif)
    /// 22pt semibold serif — Section headings
    static let displaySmall: Font = .system(size: 22, weight: .semibold, design: .serif)

    /// 18pt semibold sans — Section headers
    static let headingLarge: Font = .system(size: 18, weight: .semibold)
    /// 15pt semibold sans — List row titles, search input
    static let headingMedium: Font = .system(size: 15, weight: .semibold)
    /// 13pt semibold sans — Small headers, buttons
    static let headingSmall: Font = .system(size: 13, weight: .semibold)

    /// 15pt regular sans — Input field text
    static let bodyLarge: Font = .system(size: 15)
    /// 14pt regular sans — Default body
    static let body: Font = .system(size: 14)
    /// 13pt regular sans — Secondary body
    static let bodySmall: Font = .system(size: 13)
    /// 15pt regular sans — Transcript/summary (use with lineSpacing(6))
    static let reading: Font = .system(size: 15)

    /// 12pt medium sans — Metadata, dates
    static let label: Font = .system(size: 12, weight: .medium)
    /// 11pt medium sans — Section headers (uppercase + tracked)
    static let labelSmall: Font = .system(size: 11, weight: .medium)
    /// 11pt regular sans — Smallest text
    static let caption: Font = .system(size: 11)

    /// 13pt regular mono — Durations, timestamps
    static let mono: Font = .system(size: 13, design: .monospaced)
    /// 15pt medium mono — Recording timer
    static let monoLarge: Font = .system(size: 15, weight: .medium, design: .monospaced)
}

// MARK: - Palette

enum Palette {
    /// Warm amber accent — replaces system .blue (darkened for WCAG AA on white)
    static let accent = Color(red: 0.82, green: 0.49, blue: 0.18)
    /// Accent at 10% opacity — subtle backgrounds
    static let accentSubtle = accent.opacity(0.10)

    /// Primary text
    static let textPrimary = Color.primary
    /// Secondary text
    static let textSecondary = Color.secondary
    /// Tertiary text
    static let textTertiary = Color(nsColor: .tertiaryLabelColor)

    /// Subtle surface — 5% opacity (visible in both light and dark mode)
    static let surfaceSubtle = Color.primary.opacity(0.05)
    /// Hover state surface — 8% opacity
    static let surfaceHover = Color.primary.opacity(0.08)
    /// Border — 10% opacity
    static let border = Color.primary.opacity(0.10)

    /// Recording indicator
    static let recording = Color.red

    /// Priority colors
    static let priorityHigh = Color(red: 0.85, green: 0.35, blue: 0.30)
    static let priorityMedium = Color(red: 0.80, green: 0.58, blue: 0.30)
    static let priorityLow = Color(nsColor: .tertiaryLabelColor)

    /// Accent color for recordings (type-neutral)
    static let typeReflection = accent
    static func typeColor(_ type: WaiComputerKit.RecordingType) -> Color { accent }
}

// MARK: - View Modifiers

/// Large text field with subtle border + accent glow on focus
struct WaiTextFieldModifier: ViewModifier {
    let isActive: Bool

    func body(content: Content) -> some View {
        content
            .font(Typography.bodyLarge)
            .padding(Spacing.md)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .strokeBorder(isActive ? Palette.accent : Palette.border, lineWidth: isActive ? 1.5 : 1)
            )
    }
}

/// Hero-sized input for search/chat
struct WaiLargeInputModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .font(Typography.headingMedium)
            .padding(Spacing.md)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

/// Barely-visible grouping background
struct WaiCardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(Spacing.md)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

/// Accent-filled primary button
struct WaiPrimaryButtonStyle: ButtonStyle {
    let isDisabled: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Typography.headingSmall)
            .foregroundStyle(.white)
            .padding(.horizontal, Spacing.xl)
            .padding(.vertical, Spacing.md)
            .background(isDisabled ? Palette.accent.opacity(0.4) : Palette.accent)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .opacity(configuration.isPressed ? 0.8 : 1.0)
    }
}

/// Text-only accent button
struct WaiGhostButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Typography.headingSmall)
            .foregroundStyle(Palette.accent)
            .opacity(configuration.isPressed ? 0.6 : 1.0)
    }
}

/// Uppercase, tracked, tertiary section header
struct WaiSectionHeaderModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .font(Typography.labelSmall)
            .foregroundStyle(Palette.textTertiary)
            .tracking(1.2)
            .textCase(.uppercase)
    }
}

// MARK: - View Extensions

extension View {
    func waiTextField(isActive: Bool = false) -> some View {
        modifier(WaiTextFieldModifier(isActive: isActive))
    }

    func waiLargeInput() -> some View {
        modifier(WaiLargeInputModifier())
    }

    func waiCard() -> some View {
        modifier(WaiCardModifier())
    }

    func waiSectionHeader() -> some View {
        modifier(WaiSectionHeaderModifier())
    }
}

// MARK: - Tab Bar Component

/// Text-based tab bar with accent underline animation
struct WaiTabBar<T: Hashable>: View {
    let tabs: [(label: String, value: T)]
    @Binding var selection: T

    var body: some View {
        HStack(spacing: Spacing.xl) {
            ForEach(tabs, id: \.value) { tab in
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        selection = tab.value
                    }
                } label: {
                    VStack(spacing: Spacing.xs) {
                        Text(tab.label)
                            .font(Typography.headingSmall)
                            .foregroundStyle(selection == tab.value ? Palette.accent : Palette.textSecondary)

                        Capsule()
                            .fill(selection == tab.value ? Palette.accent : Color.clear)
                            .frame(height: 2)
                    }
                    .fixedSize(horizontal: true, vertical: false)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("tab-\(tab.label.lowercased().replacingOccurrences(of: " ", with: "-"))")
            }
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm)
    }
}


// MARK: - Thin Divider Replacement

/// Use instead of Divider() — 1px line using Palette.border
struct WaiDivider: View {
    var body: some View {
        Palette.border
            .frame(height: 1)
    }
}
