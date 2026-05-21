import SwiftUI

/// Reveals billing management controls while paid billing is dogfooded.
///
/// The release UI always shows the current plan and weekly word counter.
/// This debug-only switch reveals upgrade/cancel/region controls so we can
/// dogfood paid billing against the sandbox before announcing it.
struct PaymentModeToggle: View {
    @AppStorage(PaymentModeStore.userDefaultsKey) private var enabled = false

    var body: some View {
        Toggle(isOn: $enabled) {
            VStack(alignment: .leading, spacing: 2) {
                Text("settings.payments.toggle.title", bundle: .main)
                    .font(Typography.body)
                Text("settings.payments.toggle.description", bundle: .main)
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

enum BillingCheckoutRefreshStore {
    static let pendingKey = "billingCheckoutRefreshPending"
}
