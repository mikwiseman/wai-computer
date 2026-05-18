import SwiftUI

/// Hides the billing surface entirely until the user opts in.
///
/// v1.0 ships Payment mode **off** so every install is effectively free
/// and unlimited. Flipping it on reveals the Subscription section, the
/// weekly word gauge, the Upgrade button, and the cap-exceeded sheet —
/// purely so we can dogfood the paid flow against the sandbox before
/// announcing it. The server-side ``billing_enforcement_enabled`` env
/// flag controls whether the backend actually returns 402s; the two
/// switches are independent on purpose.
struct PaymentModeToggle: View {
    @AppStorage(PaymentModeStore.userDefaultsKey) private var enabled = false

    var body: some View {
        Toggle(isOn: $enabled) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Payment mode")
                    .font(Typography.body)
                Text("Show the Subscription tab and weekly word counter. Off by default — leave it off and everything stays free and unlimited.")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .toggleStyle(.switch)
        .accessibilityIdentifier("settings-payment-mode-toggle")
    }
}

/// Single source of truth for the Payment-mode flag so non-SwiftUI code
/// (e.g. ``BillingSection`` conditionals) can read the same key.
enum PaymentModeStore {
    static let userDefaultsKey = "paymentModeEnabled"

    static var isEnabled: Bool {
        UserDefaults.standard.bool(forKey: userDefaultsKey)
    }
}
