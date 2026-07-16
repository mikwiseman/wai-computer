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

// MARK: - Radius (concentric hierarchy)

enum Radius {
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    static let xl: CGFloat = 22
    static let xxl: CGFloat = 28
}

// MARK: - Elevation

enum Elevation {
    case raised
    case floating

    var color: Color {
        switch self {
        case .raised: return Color.black.opacity(0.08)
        case .floating: return Color.black.opacity(0.18)
        }
    }

    var radius: CGFloat {
        switch self {
        case .raised: return 12
        case .floating: return 28
        }
    }

    var y: CGFloat {
        switch self {
        case .raised: return 4
        case .floating: return 12
        }
    }
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

// MARK: - Theme

/// Light/Dark/System preference. Mirrors `MacAppearanceMode` (the
/// `preferredColorScheme` logic is pure SwiftUI and identical cross-platform).
enum IOSAppearanceMode: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    var id: String { rawValue }

    var preferredColorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }
}

/// Accent color preference. Mirrors `MacAccentChoice` but builds colors from
/// `Color(uiColor:)` system colors (the AppKit `NSColor` constructors have no
/// iOS counterpart). `.system` keeps the brand amber so the default app tint is
/// unchanged from before the picker existed.
enum IOSAccentChoice: String, CaseIterable, Identifiable {
    case system
    case amber
    case blue
    case green
    case violet
    case rose
    case graphite

    var id: String { rawValue }

    /// The tint applied to the scene. `.system` resolves to the brand amber so
    /// the default tint matches the pre-picker behavior (iOS has no per-app
    /// "system accent" the way macOS exposes `controlAccentColor`).
    var tintColor: Color { color }

    var previewColor: Color { color }

    var color: Color {
        switch self {
        case .system, .amber:
            // Brand warm amber (matches Palette.accent default).
            return Color(red: 0.82, green: 0.49, blue: 0.18)
        case .blue:
            return Color(uiColor: .systemBlue)
        case .green:
            return Color(uiColor: .systemGreen)
        case .violet:
            return Color(uiColor: .systemPurple)
        case .rose:
            return Color(uiColor: .systemPink)
        case .graphite:
            return Color(uiColor: .systemGray)
        }
    }

    /// Foreground for content placed directly on the accent fill. Every current
    /// iOS system accent is bright enough that black has the stronger WCAG
    /// contrast in both light and dark appearances.
    var onAccentColor: Color {
        switch self {
        case .system, .amber, .blue, .green, .violet, .rose, .graphite:
            return .black
        }
    }
}

/// AppStorage keys + defaults for the appearance preferences. Mirrors
/// `MacThemePreferences` (same UserDefaults keys so a future shared sync stays
/// consistent, though the values are read independently per platform).
enum IOSThemePreferences {
    static let appearanceKey = "waiAppearanceMode"
    static let accentKey = "waiAccentChoice"
    static let defaultAppearance: IOSAppearanceMode = .system
    static let defaultAccent: IOSAccentChoice = .amber

    static var currentAppearance: IOSAppearanceMode {
        let rawValue = UserDefaults.standard.string(forKey: appearanceKey)
        return rawValue.flatMap(IOSAppearanceMode.init(rawValue:)) ?? defaultAppearance
    }

    static var currentAccent: IOSAccentChoice {
        let rawValue = UserDefaults.standard.string(forKey: accentKey)
        return rawValue.flatMap(IOSAccentChoice.init(rawValue:)) ?? defaultAccent
    }
}

/// Locale-aware date formatting keyed to the in-app language. Mirrors
/// `MacDateFormatting`.
enum IOSDateFormatting {
    static func locale(for language: LanguageManager.SupportedLanguage) -> Locale {
        switch language {
        case .followSystem:
            return .current
        case .english:
            return Locale(identifier: "en")
        case .russian:
            return Locale(identifier: "ru")
        }
    }

    /// Cache of configured `DateFormatter`s keyed by (language, dateStyle,
    /// timeStyle). `DateFormatter` creation is expensive, and `string(from:)` is
    /// called once per row in large lists — allocating a fresh formatter each
    /// time caused measurable scroll jank. Guarded by a lock because formatters
    /// are not `Sendable` and callers may not all be on the main actor.
    private static let cacheLock = NSLock()
    nonisolated(unsafe) private static var formatterCache: [String: DateFormatter] = [:]

    static func string(
        from date: Date,
        dateStyle: DateFormatter.Style,
        timeStyle: DateFormatter.Style,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        let key = "\(language.rawValue)-\(dateStyle.rawValue)-\(timeStyle.rawValue)"
        cacheLock.lock()
        defer { cacheLock.unlock() }
        let formatter: DateFormatter
        if let cached = formatterCache[key] {
            formatter = cached
        } else {
            formatter = DateFormatter()
            formatter.locale = locale(for: language)
            formatter.dateStyle = dateStyle
            formatter.timeStyle = timeStyle
            formatterCache[key] = formatter
        }
        return formatter.string(from: date)
    }

    /// Compact timestamp for list rows: "Сегодня, 10:25" / "Вчера, 18:19",
    /// "8 июля, 10:25" within the current year, "8 июля 2025, 10:25" otherwise.
    /// Mirrors `MacDateFormatting.listTimestamp`.
    static func listTimestamp(
        from date: Date,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        let calendar = Calendar.current
        let time = string(from: date, dateStyle: .none, timeStyle: .short, language: language)
        if calendar.isDateInToday(date) {
            return "\(OnboardingL10n.text("Today", "Сегодня", language: language)), \(time)"
        }
        if calendar.isDateInYesterday(date) {
            return "\(OnboardingL10n.text("Yesterday", "Вчера", language: language)), \(time)"
        }
        let sameYear = calendar.component(.year, from: date) == calendar.component(.year, from: Date())
        let day = templatedString(from: date, template: sameYear ? "MMMMd" : "yMMMMd", language: language)
        return "\(day), \(time)"
    }

    /// Duration as "0:53", "28:40", or hours-aware "3:28:40" — never "208:40".
    /// Mirrors `MacDateFormatting.duration`.
    static func duration(seconds: Int) -> String {
        ClockDuration.string(seconds: seconds)
    }

    private static func templatedString(
        from date: Date,
        template: String,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        let locale = locale(for: language)
        let key = "tpl-\(locale.identifier)-\(template)"
        cacheLock.lock()
        defer { cacheLock.unlock() }
        let formatter: DateFormatter
        if let cached = formatterCache[key] {
            formatter = cached
        } else {
            formatter = DateFormatter()
            formatter.locale = locale
            if template == "yMMMMd", locale.identifier.hasPrefix("ru") {
                // The locale template appends "г." ("8 июля 2025 г.") — noise in list rows.
                formatter.dateFormat = "d MMMM yyyy"
            } else {
                formatter.setLocalizedDateFormatFromTemplate(template)
            }
            formatterCache[key] = formatter
        }
        return formatter.string(from: date)
    }
}

// MARK: - Palette

enum Palette {
    /// App-wide accent selected in Appearance settings.
    static var accent: Color { IOSThemePreferences.currentAccent.color }
    static var onAccent: Color { IOSThemePreferences.currentAccent.onAccentColor }
    static var accentSubtle: Color { accent.opacity(0.12) }

    static let textPrimary = Color.primary
    static let textSecondary = Color.secondary
    static let textTertiary = Color(uiColor: .tertiaryLabel)

    /// Spatial Studio canvas and content surfaces. These are intentionally
    /// opaque: Liquid Glass is reserved for navigation and floating controls.
    static let canvas = Color(uiColor: .systemGroupedBackground)
    static let panel = Color(uiColor: .systemBackground)
    static let panelRaised = Color(uiColor: .secondarySystemGroupedBackground)
    static let surfaceSubtle = Color.primary.opacity(0.05)
    static let surfaceHover = Color.primary.opacity(0.08)
    static let border = Color.primary.opacity(0.10)

    /// Live-recording indicator only (pulsing dot, record/stop tint). For error
    /// and failure states use `danger` — mirrors macOS `Palette`.
    static let recording = Color.red

    /// Semantic status colors. Mirror the macOS `Palette` so error/success/
    /// warning states read consistently across platforms.
    static let danger = Color(uiColor: .systemRed)
    static let success = Color(uiColor: .systemGreen)
    static let warning = Color(uiColor: .systemOrange)

    static let priorityHigh = Color(red: 0.85, green: 0.35, blue: 0.30)
    static let priorityMedium = Color(red: 0.80, green: 0.58, blue: 0.30)
    static let priorityLow = Color(uiColor: .tertiaryLabel)

    static let typeReflection = accent
    static func typeColor(_ type: WaiComputerKit.RecordingType) -> Color { accent }
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
            .foregroundStyle(Palette.onAccent)
            .padding(.horizontal, Spacing.xl)
            .padding(.vertical, Spacing.md)
            .frame(minHeight: 44)
            .background(isDisabled ? Palette.accent.opacity(0.4) : Palette.accent)
            .clipShape(Capsule())
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

struct WaiQuietButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Typography.headingSmall)
            .foregroundStyle(Palette.textSecondary)
            .padding(.horizontal, Spacing.md)
            .padding(.vertical, Spacing.sm)
            .frame(minHeight: 44)
            .background(configuration.isPressed ? Palette.surfaceHover : Color.clear)
            .clipShape(Capsule())
    }
}

// MARK: - Surfaces

private struct WaiCardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(Spacing.lg)
            .background(Palette.panel, in: RoundedRectangle(cornerRadius: Radius.lg, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .strokeBorder(Palette.border, lineWidth: 1)
            )
    }
}

private struct WaiShadowModifier: ViewModifier {
    let elevation: Elevation

    func body(content: Content) -> some View {
        content.shadow(color: elevation.color, radius: elevation.radius, y: elevation.y)
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
    func waiCard() -> some View {
        modifier(WaiCardModifier())
    }

    func waiShadow(_ elevation: Elevation) -> some View {
        modifier(WaiShadowModifier(elevation: elevation))
    }

    /// Liquid Glass for floating navigation and interactive chrome only.
    /// Content cards stay opaque for hierarchy and legibility.
    @ViewBuilder
    func waiGlassChrome(cornerRadius: CGFloat, interactive: Bool = false) -> some View {
        if #available(iOS 26.0, *) {
            if interactive {
                self.glassEffect(.regular.interactive(), in: .rect(cornerRadius: cornerRadius))
            } else {
                self.glassEffect(.regular, in: .rect(cornerRadius: cornerRadius))
            }
        } else {
            self
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
        }
    }

    func waiSectionHeader() -> some View {
        modifier(WaiSectionHeaderModifier())
    }
}

// MARK: - Triangle Icon Shape

/// The wai.computer triangle icon (black triangle with computer cutout).
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
