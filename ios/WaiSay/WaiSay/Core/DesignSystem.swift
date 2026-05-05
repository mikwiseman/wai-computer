import SwiftUI
import WaiSayKit

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
    static let displayLarge: Font = .system(size: 32, weight: .bold, design: .serif)
    static let displayMedium: Font = .system(size: 26, weight: .semibold, design: .serif)
    static let displaySmall: Font = .system(size: 22, weight: .semibold, design: .serif)

    static let headingLarge: Font = .system(size: 18, weight: .semibold)
    static let headingMedium: Font = .system(size: 15, weight: .semibold)
    static let headingSmall: Font = .system(size: 13, weight: .semibold)

    static let bodyLarge: Font = .system(size: 15)
    static let body: Font = .system(size: 14)
    static let bodySmall: Font = .system(size: 13)
    static let reading: Font = .system(size: 15)

    static let label: Font = .system(size: 12, weight: .medium)
    static let labelSmall: Font = .system(size: 11, weight: .medium)
    static let caption: Font = .system(size: 11)

    static let mono: Font = .system(size: 13, design: .monospaced)
    static let monoLarge: Font = .system(size: 15, weight: .medium, design: .monospaced)
}

// MARK: - Palette

enum Palette {
    /// Warm amber accent — replaces system .blue (darkened for WCAG AA on white).
    /// Mirrors macOS Palette so brand identity stays consistent across platforms.
    static let accent = Color(red: 0.82, green: 0.49, blue: 0.18)
    static let accentSubtle = accent.opacity(0.10)

    static let textPrimary = Color.primary
    static let textSecondary = Color.secondary
    static let textTertiary = Color(uiColor: .tertiaryLabel)

    static let surfaceSubtle = Color.primary.opacity(0.05)
    static let surfaceHover = Color.primary.opacity(0.08)
    static let border = Color.primary.opacity(0.10)

    static let recording = Color.red

    static let priorityHigh = Color(red: 0.85, green: 0.35, blue: 0.30)
    static let priorityMedium = Color(red: 0.80, green: 0.58, blue: 0.30)
    static let priorityLow = Color(uiColor: .tertiaryLabel)

    static let typeReflection = accent
    static func typeColor(_ type: WaiSayKit.RecordingType) -> Color { accent }
}

// MARK: - Buttons

struct WaiPrimaryButtonStyle: ButtonStyle {
    let isDisabled: Bool

    init(isDisabled: Bool = false) {
        self.isDisabled = isDisabled
    }

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

struct WaiGhostButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Typography.headingSmall)
            .foregroundStyle(Palette.accent)
            .opacity(configuration.isPressed ? 0.6 : 1.0)
    }
}

// MARK: - Section Header Modifier

struct WaiSectionHeaderModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .font(Typography.labelSmall)
            .foregroundStyle(Palette.textTertiary)
            .tracking(1.2)
            .textCase(.uppercase)
    }
}

extension View {
    func waiSectionHeader() -> some View {
        modifier(WaiSectionHeaderModifier())
    }
}

// MARK: - Triangle Icon Shape

/// The say.waiwai.is triangle icon (black triangle with computer cutout).
/// Matches macOS WaiTriangleIcon for cross-platform brand consistency.
struct WaiTriangleIcon: View {
    let size: CGFloat

    var body: some View {
        ZStack {
            Triangle()
                .fill(Color.primary)
                .frame(width: size, height: size * 0.87)

            Image(systemName: "desktopcomputer")
                .font(.system(size: size * 0.28, weight: .medium))
                .foregroundStyle(Color(uiColor: .systemBackground))
                .offset(y: size * 0.06)
        }
    }
}

struct Triangle: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.midX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        path.closeSubpath()
        return path
    }
}
