import Foundation

/// Platform-neutral foundation for every WaiComputer surface.
///
/// Color, typography, and material remain platform adapters because SwiftUI
/// resolves them differently on iOS and macOS. Geometry and motion live here
/// so native screens and shared views cannot silently drift apart.
public enum WaiDesignTokens {
    public enum Spacing {
        public static let xxs: CGFloat = 2
        public static let xs: CGFloat = 4
        public static let sm: CGFloat = 8
        public static let md: CGFloat = 12
        public static let lg: CGFloat = 16
        public static let xl: CGFloat = 24
        public static let xxl: CGFloat = 32
        public static let xxxl: CGFloat = 48
        public static let huge: CGFloat = 64
    }

    /// Concentric corner hierarchy: small controls sit inside cards, and cards
    /// sit inside floating panels without competing radii.
    public enum Radius {
        public static let sm: CGFloat = 8
        public static let md: CGFloat = 12
        public static let lg: CGFloat = 16
        public static let xl: CGFloat = 22
        public static let xxl: CGFloat = 28
    }

    public enum Control {
        /// Compact desktop-only affordances.
        public static let compactHeight: CGFloat = 32
        /// The minimum comfortable iOS tap target and standard large control.
        public static let regularHeight: CGFloat = 44
        /// Hero actions and recording controls.
        public static let largeHeight: CGFloat = 52
    }

    public enum Motion {
        public static let quick: TimeInterval = 0.16
        public static let standard: TimeInterval = 0.25
        public static let emphasized: TimeInterval = 0.35
    }
}
