#if canImport(SwiftUI)
import SwiftUI

// Back-compatible `onChange` for a single binary spanning macOS 13 -> 26.
//
// The zero-/two-parameter `onChange(of:initial:_:)` is macOS 14.0 / iOS 17.0 only.
// Below macOS 14 we fall back to the macOS 11 `onChange(of:perform:)`, which fires
// SYNCHRONOUSLY inside the view-update transaction with exact (old, new) semantics —
// unlike a `.task(id:)` emulation, whose async, cancel-on-change behavior can drop a
// rapid change or deliver a stale old value (e.g. on the dictation-finalization path).
//
// `onChange(of:perform:)` is deprecated in macOS 14.0 / iOS 17.0, but:
//   * the legacy path is macOS-only (`#if os(macOS)`) and the package's iOS floor is
//     17, so iOS always takes the native branch and never compiles the legacy call;
//   * the legacy modifiers are marked `@available(macOS, deprecated: 14.0)`, so the
//     deprecated call inside them is in a deprecated context and emits no warning,
//     while instantiating them at the macOS 13 floor (< 14) is warning-free too.
public extension View {
    /// Runs `action` whenever `value` changes (no old/new values needed).
    @ViewBuilder
    func onChangeCompat<V: Equatable>(
        of value: V,
        initial: Bool = false,
        _ action: @escaping () -> Void
    ) -> some View {
        if #available(macOS 14.0, iOS 17.0, *) {
            onChange(of: value, initial: initial) { action() }
        } else {
            #if os(macOS)
            modifier(LegacyOnChangeVoidModifier(value: value, initial: initial, action: action))
            #else
            self
            #endif
        }
    }

    /// Runs `action(oldValue, newValue)` whenever `value` changes.
    @ViewBuilder
    func onChangeCompat<V: Equatable>(
        of value: V,
        initial: Bool = false,
        _ action: @escaping (_ oldValue: V, _ newValue: V) -> Void
    ) -> some View {
        if #available(macOS 14.0, iOS 17.0, *) {
            onChange(of: value, initial: initial) { oldValue, newValue in action(oldValue, newValue) }
        } else {
            #if os(macOS)
            modifier(LegacyOnChangePairModifier(value: value, initial: initial, action: action))
            #else
            self
            #endif
        }
    }
}

#if os(macOS)
@available(macOS, deprecated: 14.0, message: "macOS 13 onChange fallback; delete when the deployment floor reaches macOS 14 and call onChange(of:initial:) directly.")
private struct LegacyOnChangeVoidModifier<V: Equatable>: ViewModifier {
    let value: V
    let initial: Bool
    let action: () -> Void

    func body(content: Content) -> some View {
        content
            .onAppear { if initial { action() } }
            .onChange(of: value) { _ in action() }
    }
}

@available(macOS, deprecated: 14.0, message: "macOS 13 onChange fallback; delete when the deployment floor reaches macOS 14 and call onChange(of:initial:) directly.")
private struct LegacyOnChangePairModifier<V: Equatable>: ViewModifier {
    let value: V
    let initial: Bool
    let action: (V, V) -> Void
    @State private var previous: V?

    func body(content: Content) -> some View {
        content
            .onAppear {
                if previous == nil {
                    previous = value
                    if initial { action(value, value) }
                }
            }
            .onChange(of: value) { newValue in
                // Synchronous: advance the ledger and fire in the same transaction,
                // delivering the true previous value (seeded on first appear).
                let old = previous ?? newValue
                previous = newValue
                action(old, newValue)
            }
    }
}
#endif
#endif
