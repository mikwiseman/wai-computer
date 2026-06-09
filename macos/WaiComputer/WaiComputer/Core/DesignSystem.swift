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

// MARK: - Theme

enum MacAppearanceMode: String, CaseIterable, Identifiable {
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

enum MacAccentChoice: String, CaseIterable, Identifiable {
    case system
    case amber
    case blue
    case green
    case violet
    case rose
    case graphite

    var id: String { rawValue }

    var tintColor: Color? {
        self == .system ? nil : color
    }

    var previewColor: Color {
        self == .system ? Color(nsColor: .controlAccentColor) : color
    }

    var color: Color {
        switch self {
        case .system:
            return Color(nsColor: .controlAccentColor)
        case .amber:
            return Color(nsColor: .systemOrange)
        case .blue:
            return Color(nsColor: .systemBlue)
        case .green:
            return Color(nsColor: .systemGreen)
        case .violet:
            return Color(nsColor: .systemPurple)
        case .rose:
            return Color(nsColor: .systemPink)
        case .graphite:
            return Color(nsColor: .systemGray)
        }
    }

    /// Foreground for text/icons drawn on top of `color`. Hardcoded white fails
    /// WCAG AA on the lighter accents (amber/green/gray ≈ 2.1–3.3:1), so pick
    /// whichever of black/white has the higher contrast against this accent.
    var onAccentColor: Color {
        guard let ns = NSColor(color).usingColorSpace(.sRGB) else { return .white }
        func lin(_ c: CGFloat) -> CGFloat {
            c <= 0.03928 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }
        let luminance = 0.2126 * lin(ns.redComponent)
            + 0.7152 * lin(ns.greenComponent)
            + 0.0722 * lin(ns.blueComponent)
        let blackContrast = (luminance + 0.05) / 0.05
        let whiteContrast = 1.05 / (luminance + 0.05)
        return blackContrast >= whiteContrast ? .black : .white
    }
}

struct MacThemePreferences {
    static let appearanceKey = "waiAppearanceMode"
    static let accentKey = "waiAccentChoice"
    static let defaultAppearance: MacAppearanceMode = .system
    static let defaultAccent: MacAccentChoice = .amber

    var defaults: UserDefaults = .standard

    var appearance: MacAppearanceMode {
        get {
            guard
                let rawValue = defaults.string(forKey: Self.appearanceKey),
                let appearance = MacAppearanceMode(rawValue: rawValue)
            else {
                return Self.defaultAppearance
            }
            return appearance
        }
        set {
            defaults.set(newValue.rawValue, forKey: Self.appearanceKey)
        }
    }

    var accent: MacAccentChoice {
        get {
            guard
                let rawValue = defaults.string(forKey: Self.accentKey),
                let accent = MacAccentChoice(rawValue: rawValue)
            else {
                return Self.defaultAccent
            }
            return accent
        }
        set {
            defaults.set(newValue.rawValue, forKey: Self.accentKey)
        }
    }

    // Accent/appearance are read on hot paths (every row, every body pass, the
    // NSTableView accent). Reading UserDefaults each time was a measurable scroll
    // cost, so cache the resolved values and refresh only when defaults change.
    private static let cache = MacThemeCache()

    static var currentAppearance: MacAppearanceMode {
        cache.appearance
    }

    static var currentAccent: MacAccentChoice {
        cache.accent
    }
}

/// Main-thread cache for theme preferences. Invalidated on any UserDefaults
/// change (accent/appearance are set through UserDefaults), so it stays correct
/// while avoiding a UserDefaults read on every accent lookup.
private final class MacThemeCache {
    private let prefs = MacThemePreferences()
    private var cachedAccent: MacAccentChoice?
    private var cachedAppearance: MacAppearanceMode?

    init() {
        NotificationCenter.default.addObserver(
            forName: UserDefaults.didChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.cachedAccent = nil
            self?.cachedAppearance = nil
        }
    }

    var accent: MacAccentChoice {
        if let cachedAccent { return cachedAccent }
        let value = prefs.accent
        cachedAccent = value
        return value
    }

    var appearance: MacAppearanceMode {
        if let cachedAppearance { return cachedAppearance }
        let value = prefs.appearance
        cachedAppearance = value
        return value
    }
}

enum MacDateFormatting {
    private static let formatterCacheLock = NSLock()
    private static var formatterCache: [String: DateFormatter] = [:]

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

    static func string(
        from date: Date,
        dateStyle: DateFormatter.Style,
        timeStyle: DateFormatter.Style,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        let locale = locale(for: language)
        let cacheKey = "\(locale.identifier)|\(dateStyle.rawValue)|\(timeStyle.rawValue)"
        formatterCacheLock.lock()
        defer { formatterCacheLock.unlock() }
        let formatter: DateFormatter
        if let cached = formatterCache[cacheKey] {
            formatter = cached
        } else {
            let created = DateFormatter()
            created.locale = locale
            created.dateStyle = dateStyle
            created.timeStyle = timeStyle
            formatterCache[cacheKey] = created
            formatter = created
        }
        return formatter.string(from: date)
    }
}

// MARK: - Palette

enum Palette {
    /// App-wide accent. The concrete color is selected in Settings and sourced
    /// from AppKit system colors so light, dark, and increased contrast stay adaptive.
    static var accent: Color { MacThemePreferences.currentAccent.color }
    /// WCAG-safe foreground for content drawn on top of `accent`.
    static var onAccent: Color { MacThemePreferences.currentAccent.onAccentColor }
    /// Accent at 10% opacity — subtle backgrounds
    static var accentSubtle: Color { accent.opacity(0.10) }

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
    static var typeReflection: Color { accent }
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
            .foregroundStyle(Palette.onAccent)
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

enum MacMainLayoutMetrics {
    static let sidebarMinWidth: CGFloat = 236
    static let sidebarIdealWidth: CGFloat = 264
    static let sidebarMaxWidth: CGFloat = 320
    static let listMinWidth: CGFloat = 360
    static let listIdealWidth: CGFloat = 420
    static let listMaxWidth: CGFloat = 560
    static let recordingRowMinHeight: CGFloat = 48
    static let recordingRowFailureMinHeight: CGFloat = 68
    static let toolbarIconFrame: CGFloat = 28
    static let folderNameSheetWidth: CGFloat = 720
    static let folderNameSheetActionWidth: CGFloat = 200
    static let recordingTitleEditMinWidth: CGFloat = 440
    static let speakerAssignmentPopoverWidth: CGFloat = 360
    static let sidebarRowMinHeight: CGFloat = 30
    static let sidebarRowHorizontalPadding: CGFloat = 8
    static let sidebarFooterHorizontalPadding: CGFloat = 18
    static let searchContentMaxWidth: CGFloat = 880
    static let minimumReadableDetailWidth: CGFloat = 520
    static let allColumnsReadableWidth: CGFloat = sidebarIdealWidth + listMinWidth + minimumReadableDetailWidth

    static func preferredColumnVisibility(
        hasListColumn: Bool,
        containerWidth: CGFloat
    ) -> NavigationSplitViewVisibility {
        guard hasListColumn else { return .all }
        return containerWidth < allColumnsReadableWidth ? .doubleColumn : .all
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
    /// Runs `action` when the Escape key is pressed. Uses `onKeyPress(.escape)` on
    /// macOS 14+, falling back to `onExitCommand` (macOS 12+) below that floor.
    @ViewBuilder
    func onEscapeKeyCompat(_ action: @escaping () -> Void) -> some View {
        if #available(macOS 14.0, *) {
            self.onKeyPress(.escape) {
                action()
                return .handled
            }
        } else {
            self.onExitCommand(perform: action)
        }
    }

    /// `.scrollBounceBehavior(.basedOnSize)` on macOS 13.3+; no-op below (cosmetic).
    @ViewBuilder
    func scrollBounceBasedOnSizeCompat() -> some View {
        if #available(macOS 13.3, *) {
            self.scrollBounceBehavior(.basedOnSize)
        } else {
            self
        }
    }

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
