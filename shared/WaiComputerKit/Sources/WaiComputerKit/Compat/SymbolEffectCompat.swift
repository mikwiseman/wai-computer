#if canImport(SwiftUI)
import SwiftUI

public extension View {
    /// Applies `.symbolEffect(.variableColor.iterative)` on macOS 14+ / iOS 17+.
    /// The effect is macOS 14.0 only and purely cosmetic, so below the floor the
    /// symbol simply renders without the animation.
    @ViewBuilder
    func variableColorIterativeEffectCompat() -> some View {
        if #available(macOS 14.0, iOS 17.0, *) {
            self.symbolEffect(.variableColor.iterative)
        } else {
            self
        }
    }
}
#endif
