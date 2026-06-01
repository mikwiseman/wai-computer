import SwiftUI
import WaiComputerKit

private enum BillingSectionError: LocalizedError {
    case unsupportedRegion(String)

    var errorDescription: String? {
        switch self {
        case .unsupportedRegion(let region):
            return "Unsupported billing region: \(region)"
        }
    }
}

/// Read-only subscription + word-usage section embedded in `SettingsView`.
///
/// PRODUCT DECISION: iOS billing is read-only. The macOS web-checkout path
/// (Stripe/Tinkoff via an external browser) cannot ship for digital goods on
/// the App Store, so this surface shows status/usage and offers cancel only —
/// there is NO in-app upgrade/purchase button. Users upgrade on web or macOS.
///
/// Ports the read paths from macOS `BillingSection`: plan line + status badge,
/// usage gauge, renewal / Pro-through date, an informational region row
/// (RU UI only), cancel-subscription, and localized errors.
///
/// Renders `Section`s directly so it composes into the parent `List`.
struct BillingStatusSection: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager

    @State private var subscription: BillingSubscription?
    @State private var usage: BillingUsage?
    @State private var plans: [BillingPlan] = []
    @State private var billingRegion: BillingDisplayRegion?
    @State private var loadError: String?
    @State private var actionError: String?
    @State private var cancelInFlight = false

    private var isRussianUI: Bool {
        languageManager.preferredLocale.language.languageCode?.identifier == "ru"
    }

    var body: some View {
        Section {
            if let subscription, let usage {
                planLine(subscription: subscription)
                if isRussianUI, let billingRegion {
                    regionRow(region: billingRegion)
                }
                usageGauge(usage: usage, isPro: subscription.isPro)
                if subscription.isPro {
                    proControls(subscription: subscription)
                }
                if let actionError {
                    Text(actionError)
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("settings-billing-action-error")
                }
            } else if let loadError {
                Text(loadError)
                    .font(Typography.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                ProgressView()
            }
        } header: {
            Text(t("Subscription", "Подписка"))
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

    /// Informational region/currency display (RU UI only). Read-only — region
    /// is set server-side from the post-login `WAIDownloadRegion` sync; it is
    /// shown here only so RU users understand which currency a future upgrade
    /// would use. No picker (the web-checkout flow it would feed can't ship on
    /// iOS per Guideline 3.1.1).
    private func regionRow(region: BillingDisplayRegion) -> some View {
        LabeledContent {
            Text(regionName(region))
                .foregroundStyle(.secondary)
        } label: {
            Text(t("Region", "Регион"))
        }
        .accessibilityIdentifier("settings-billing-region-row")
    }

    private func regionName(_ region: BillingDisplayRegion) -> String {
        switch region {
        case .global:
            return t("Global (USD)", "Глобальный (USD)")
        case .ru:
            return t("Russia (RUB)", "Россия (RUB)")
        }
    }

    @ViewBuilder
    private func statusBadge(for sub: BillingSubscription) -> some View {
        let label: String = {
            switch sub.status {
            case "trialing": return t("Trial", "Пробный")
            case "active": return t("Active", "Активна")
            case "past_due": return t("Past due", "Просрочена")
            case "canceled": return t("Canceled", "Отменена")
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
        let displayCap = displayWordsCap(usage: usage)
        if displayCap == nil {
            LabeledContent {
                Text(t("Unlimited", "Без ограничений"))
                    .foregroundStyle(.secondary)
            } label: {
                Text(t("Words this week", "Слов за неделю"))
            }
        } else {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(t("Words this week", "Слов за неделю"))
                    Spacer()
                    Text("\(usage.wordsUsed.formatted()) / \(displayCap!.formatted())")
                        .foregroundStyle(usage.capExceeded ? .red : .primary)
                        .monospacedDigit()
                }
                let fraction = min(1.0, max(0.0, Double(usage.wordsUsed) / Double(displayCap!)))
                ProgressView(value: fraction)
                    .tint(usage.capExceeded ? .red : fraction > 0.8 ? .orange : Palette.accent)
                Text(t("Resets every Sunday", "Сбрасывается каждое воскресенье"))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    // MARK: - Pro user controls

    @ViewBuilder
    private func proControls(subscription: BillingSubscription) -> some View {
        if subscription.cancelAtPeriodEnd, let end = subscription.currentPeriodEnd {
            Text(t(
                "Pro access through \(formattedPeriodDate(end))",
                "Доступ Pro до \(formattedPeriodDate(end))"
            ))
            .font(Typography.caption)
            .foregroundStyle(.secondary)
        } else {
            if let end = subscription.currentPeriodEnd {
                Text(t(
                    "Renews on \(formattedPeriodDate(end))",
                    "Продлевается \(formattedPeriodDate(end))"
                ))
                .font(Typography.caption)
                .foregroundStyle(.secondary)
            }
            Button(role: .destructive) {
                Task { await cancelSubscription() }
            } label: {
                HStack {
                    Text(t("Cancel subscription", "Отменить подписку"))
                    if cancelInFlight {
                        Spacer()
                        ProgressView()
                    }
                }
            }
            .disabled(cancelInFlight)
            .accessibilityIdentifier("settings-billing-cancel")
        }
    }

    // MARK: - Data

    private func displayWordsCap(usage: BillingUsage) -> Int? {
        if subscription?.isPro == true {
            return nil
        }
        if let cap = usage.wordsCap {
            return cap
        }
        if let cap = subscription?.plan.wordCapPerWeek {
            return cap
        }
        return plans.first(where: { $0.code == "free" })?.wordCapPerWeek
    }

    private func loadAll() async {
        do {
            let client = appState.getAPIClient()
            async let sub = client.getBillingSubscription()
            async let use = client.getBillingUsage()
            async let planRows = client.listBillingPlans()
            async let userSettings = client.getSettings()
            let (s, u, p, settings) = try await (sub, use, planRows, userSettings)
            guard let region = BillingDisplayRegion(rawValue: settings.region) else {
                throw BillingSectionError.unsupportedRegion(settings.region)
            }
            await MainActor.run {
                self.subscription = s
                self.usage = u
                self.plans = p
                self.billingRegion = region
                self.loadError = nil
                self.actionError = nil
            }
        } catch {
            await MainActor.run {
                self.loadError = localizedLoadError(error)
            }
        }
    }

    private func cancelSubscription() async {
        await MainActor.run {
            cancelInFlight = true
            actionError = nil
        }
        do {
            try await appState.getAPIClient().cancelBillingSubscription()
            await loadAll()
        } catch {
            await MainActor.run {
                actionError = localizedLoadError(error)
            }
        }
        await MainActor.run {
            cancelInFlight = false
        }
    }

    private func formattedPeriodDate(_ date: Date) -> String {
        IOSDateFormatting.string(
            from: date,
            dateStyle: .long,
            timeStyle: .none,
            language: languageManager.current
        )
    }

    /// Resolve a billing error against the in-app language. Falls back to the
    /// raw localized description for unknown messages rather than masking it.
    private func localizedLoadError(_ error: Error) -> String {
        let message = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        return message.isEmpty
            ? t("Something went wrong. Please try again.", "Что-то пошло не так. Попробуй ещё раз.")
            : message
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
