import AppKit
import SwiftUI
import WaiComputerKit

/// Subscription + word-usage section embedded in `MacSettingsView`.
///
/// Free users see a weekly gauge ("Words: 8,230 / 10,000 this week"),
/// an Upgrade button that opens hosted Stripe / T-Bank checkout in the
/// default browser, and the plan summary. Pro users see "Unlimited"
/// plus a Cancel button that flips ``cancel_at_period_end`` on the
/// active subscription. Both rails are fed by the same backend
/// endpoints — the section doesn't care which provider is in play.
struct BillingSection: View {
    @EnvironmentObject var appState: MacAppState

    @State private var subscription: BillingSubscription?
    @State private var usage: BillingUsage?
    @State private var loadError: String?
    @State private var checkoutInFlight = false
    @State private var cancelInFlight = false
    @State private var period: String = "month"
    @State private var providerOverride: String?

    var body: some View {
        Section {
            if let subscription, let usage {
                planLine(subscription: subscription)
                usageGauge(usage: usage, isPro: subscription.isPro)
                if subscription.isPro {
                    proControls(subscription: subscription)
                } else {
                    freeControls()
                }
            } else if let loadError {
                Text(loadError)
                    .font(Typography.caption)
                    .foregroundStyle(.red)
            } else {
                ProgressView().controlSize(.small)
            }
        } header: {
            Text("billing.subscription.title", bundle: .main)
                .waiSectionHeader()
                .accessibilityIdentifier("settings-billing-header")
        }
        .task { await loadAll() }
    }

    // MARK: - Plan + Usage

    private func planLine(subscription: BillingSubscription) -> some View {
        HStack {
            Text(subscription.plan.name)
                .font(Typography.body.weight(.semibold))
            Spacer()
            statusBadge(for: subscription)
        }
    }

    @ViewBuilder
    private func statusBadge(for sub: BillingSubscription) -> some View {
        let label: String = {
            switch sub.status {
            case "trialing": return "Trial"
            case "active": return "Active"
            case "past_due": return "Past due"
            case "canceled": return "Canceled"
            default: return sub.status.capitalized
            }
        }()
        let color: Color = {
            switch sub.status {
            case "active", "trialing": return .green
            case "past_due": return .orange
            case "canceled", "expired": return .gray
            default: return .secondary
            }
        }()
        Text(label)
            .font(Typography.caption)
            .padding(.horizontal, 8).padding(.vertical, 2)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }

    @ViewBuilder
    private func usageGauge(usage: BillingUsage, isPro: Bool) -> some View {
        if isPro || usage.wordsCap == nil {
            LabeledContent {
                Text("billing.usage.unlimited", bundle: .main)
                    .foregroundStyle(.secondary)
            } label: {
                Text("billing.usage.title", bundle: .main)
            }
        } else {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("billing.usage.title", bundle: .main)
                    Spacer()
                    Text("\(usage.wordsUsed.formatted()) / \(usage.wordsCap!.formatted())")
                        .foregroundStyle(usage.capExceeded ? .red : .primary)
                        .monospacedDigit()
                }
                ProgressView(value: usage.fractionUsed)
                    .tint(usage.capExceeded ? .red : usage.fractionUsed > 0.8 ? .orange : .accentColor)
                Text("billing.usage.resetsSunday", bundle: .main)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    // MARK: - Free user controls

    @ViewBuilder
    private func freeControls() -> some View {
        Picker(selection: $period) {
            Text("billing.period.month", bundle: .main).tag("month")
            Text("billing.period.year", bundle: .main).tag("year")
        } label: {
            Text("billing.period.month", bundle: .main).hidden()
        }
        .pickerStyle(.segmented)
        .labelsHidden()

        if let pro = currentProPlan() {
            HStack {
                Text(priceLabel(for: pro))
                    .font(Typography.body)
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    Task { await startCheckout(plan: pro) }
                } label: {
                    if checkoutInFlight {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("billing.upgrade", bundle: .main)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(checkoutInFlight)
                .accessibilityIdentifier("settings-billing-upgrade")
            }
        }
    }

    /// Region detection for displayed currency. We don't have a server-supplied
    /// region on the User model yet (it's stored backend-side); fall back to
    /// the build-time WAIDownloadRegion stamp so RU DMG installs show RUB.
    private func userRegion() -> String {
        if let stamp = Bundle.main.object(forInfoDictionaryKey: "WAIDownloadRegion") as? String {
            return stamp.lowercased()
        }
        return "global"
    }

    private func priceLabel(for pro: BillingPlan) -> String {
        if userRegion() == "ru",
           let monthly = pro.rubAmountMonthly, let yearly = pro.rubAmountYearly {
            return period == "year" ? "₽\(yearly) / year" : "₽\(monthly) / month"
        }
        if let monthly = pro.usdAmountMonthly, let yearly = pro.usdAmountYearly {
            return period == "year" ? "$\(yearly) / year" : "$\(monthly) / month"
        }
        return ""
    }

    // MARK: - Pro user controls

    @ViewBuilder
    private func proControls(subscription: BillingSubscription) -> some View {
        if subscription.cancelAtPeriodEnd, let end = subscription.currentPeriodEnd {
            Text("Pro through \(end.formatted(date: .abbreviated, time: .omitted))")
                .font(Typography.caption)
                .foregroundStyle(.secondary)
        } else {
            HStack {
                Spacer()
                Button(role: .destructive) {
                    Task { await cancelSubscription() }
                } label: {
                    if cancelInFlight {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("billing.subscription.cancel", bundle: .main)
                    }
                }
                .disabled(cancelInFlight)
            }
        }
    }

    // MARK: - Actions

    private func currentProPlan() -> BillingPlan? {
        // For v1.0 we only model two plans; if the current subscription is
        // pro, return its plan; otherwise synthesise a quick lookup.
        if subscription?.plan.code == "pro" {
            return subscription?.plan
        }
        return BillingPlan(
            code: "pro",
            name: "Pro",
            usdAmountMonthly: 12,
            usdAmountYearly: 96,
            rubAmountMonthly: 999,
            rubAmountYearly: 7999,
            features: ["agents": true, "mcp": true, "advanced_search": true]
        )
    }

    private func loadAll() async {
        do {
            async let sub = appState.getAPIClient().getBillingSubscription()
            async let use = appState.getAPIClient().getBillingUsage()
            let (s, u) = try await (sub, use)
            await MainActor.run {
                self.subscription = s
                self.usage = u
                self.loadError = nil
            }
        } catch {
            await MainActor.run {
                self.loadError = "Couldn't load billing: \(error)"
            }
        }
    }

    private func startCheckout(plan: BillingPlan) async {
        await MainActor.run { checkoutInFlight = true }
        defer { Task { await MainActor.run { checkoutInFlight = false } } }
        do {
            let resp = try await appState.getAPIClient().createBillingCheckout(
                plan: plan.code, period: period, provider: providerOverride
            )
            if let url = URL(string: resp.checkoutUrl) {
                await MainActor.run { NSWorkspace.shared.open(url) }
            }
        } catch {
            await MainActor.run { loadError = "Checkout failed: \(error)" }
        }
    }

    private func cancelSubscription() async {
        await MainActor.run { cancelInFlight = true }
        defer { Task { await MainActor.run { cancelInFlight = false } } }
        do {
            try await appState.getAPIClient().cancelBillingSubscription()
            await loadAll()
        } catch {
            await MainActor.run { loadError = "Cancel failed: \(error)" }
        }
    }
}
