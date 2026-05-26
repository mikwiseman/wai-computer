import AppKit
import SwiftUI
import WaiComputerKit

private enum BillingSectionError: LocalizedError {
    case unsupportedRegion(String)
    case missingProPlan
    case missingPrice(BillingDisplayRegion, BillingDisplayPeriod)
    case invalidCheckoutURL(String)
    case checkoutOpenRejected

    var errorDescription: String? {
        switch self {
        case .unsupportedRegion(let region):
            return String(
                format: String(localized: "billing.error.unsupportedRegion", bundle: .main),
                region
            )
        case .missingProPlan:
            return String(localized: "billing.error.missingProPlan", bundle: .main)
        case .missingPrice(let region, let period):
            return String(
                format: String(localized: "billing.error.priceUnavailable", bundle: .main),
                region.rawValue,
                period.rawValue
            )
        case .invalidCheckoutURL(let url):
            return String(
                format: String(localized: "billing.error.checkoutInvalidURL", bundle: .main),
                url
            )
        case .checkoutOpenRejected:
            return String(localized: "billing.error.checkoutOpenRejected", bundle: .main)
        }
    }
}

/// Subscription + word-usage section embedded in `MacSettingsView`.
enum BillingSectionMode {
    case statusOnly
    case fullManagement
}

struct BillingSection: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.locale) private var locale

    let mode: BillingSectionMode

    @State private var subscription: BillingSubscription?
    @State private var usage: BillingUsage?
    @State private var plans: [BillingPlan] = []
    @State private var billingRegion: BillingDisplayRegion?
    @State private var loadError: String?
    @State private var actionError: String?
    @State private var checkoutInFlight = false
    @State private var cancelInFlight = false
    @State private var regionUpdateInFlight = false
    @State private var promoCode = ""
    @State private var promoInFlight = false
    @State private var promoMessage: String?
    @State private var checkoutRefreshTask: Task<Void, Never>?
    @State private var period: BillingDisplayPeriod = .month
    @AppStorage("billingRegionUserSelectedRussian") private var billingRegionUserSelectedRussian = false
    @AppStorage(BillingCheckoutRefreshStore.pendingKey) private var checkoutRefreshPending = false

    init(mode: BillingSectionMode = .fullManagement) {
        self.mode = mode
    }

    private static let checkoutRefreshDelaysNanoseconds: [UInt64] = [
        2_000_000_000,
        3_000_000_000,
        5_000_000_000,
        10_000_000_000,
        20_000_000_000,
        30_000_000_000,
    ]

    private var isRussianUI: Bool {
        languageManager.preferredLocale.language.languageCode?.identifier == "ru"
    }

    var body: some View {
        Section {
            if let subscription, let usage, let billingRegion {
                planLine(subscription: subscription)
                if mode == .fullManagement, isRussianUI {
                    regionPicker(region: billingRegion)
                }
                usageGauge(usage: usage, isPro: subscription.isPro)
                if mode == .fullManagement {
                    if subscription.isPro {
                        proControls(subscription: subscription)
                    } else {
                        freeControls(region: billingRegion)
                    }
                    if let actionError {
                        Text(actionError)
                            .font(Typography.caption)
                            .foregroundStyle(.red)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("settings-billing-action-error")
                    }
                }
            } else if let loadError {
                Text(loadError)
                    .font(Typography.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                ProgressView().controlSize(.small)
            }
        } header: {
            Text("billing.subscription.title", bundle: .main)
                .waiSectionHeader()
                .accessibilityIdentifier("settings-billing-header")
        }
        .task { await loadAll() }
        .onChange(of: languageManager.current) { _, _ in
            Task { await applyRegionForCurrentLanguage() }
        }
        .onDisappear {
            stopCheckoutRefreshPolling()
        }
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

    private func regionPicker(region: BillingDisplayRegion) -> some View {
        Group {
            if isRussianUI {
                Picker(selection: Binding(
                    get: { region },
                    set: { newRegion in
                        Task { await saveBillingRegion(newRegion) }
                    }
                )) {
                    Text("billing.region.global", bundle: .main).tag(BillingDisplayRegion.global)
                    Text("billing.region.ru", bundle: .main).tag(BillingDisplayRegion.ru)
                } label: {
                    Text("billing.region.title", bundle: .main)
                }
                .pickerStyle(.menu)
                .disabled(regionUpdateInFlight || checkoutInFlight || cancelInFlight)
                .accessibilityIdentifier("settings-billing-region-picker")
            }
        }
    }

    @ViewBuilder
    private func statusBadge(for sub: BillingSubscription) -> some View {
        let labelKey: LocalizedStringKey = {
            switch sub.status {
            case "trialing": return "billing.status.trialing"
            case "active": return "billing.status.active"
            case "past_due": return "billing.status.pastDue"
            case "canceled": return "billing.status.canceled"
            default: return LocalizedStringKey(sub.status.capitalized)
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
        Text(labelKey, bundle: .main)
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
                    Text("\(usage.wordsUsed.formatted()) / \(displayCap!.formatted())")
                        .foregroundStyle(usage.capExceeded ? .red : .primary)
                        .monospacedDigit()
                }
                let fraction = min(1.0, max(0.0, Double(usage.wordsUsed) / Double(displayCap!)))
                ProgressView(value: fraction)
                    .tint(usage.capExceeded ? .red : fraction > 0.8 ? .orange : .accentColor)
                Text("billing.usage.resetsSunday", bundle: .main)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    // MARK: - Free user controls

    @ViewBuilder
    private func freeControls(region: BillingDisplayRegion) -> some View {
        Picker(selection: $period) {
            Text("billing.period.month", bundle: .main).tag(BillingDisplayPeriod.month)
            Text("billing.period.year", bundle: .main).tag(BillingDisplayPeriod.year)
        } label: {
            Text("billing.period.month", bundle: .main).hidden()
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .disabled(checkoutInFlight || regionUpdateInFlight || promoInFlight)

        if let pro = currentProPlan() {
            let label = priceLabel(for: pro, region: region)
            HStack {
                if let label {
                    Text(label)
                        .font(Typography.body)
                        .foregroundStyle(.secondary)
                } else {
                    Text(BillingSectionError.missingPrice(region, period).localizedDescription)
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                }
                Spacer()
                Button {
                    Task { await startCheckout(plan: pro, region: region) }
                } label: {
                    if checkoutInFlight {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("billing.upgrade", bundle: .main)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(checkoutInFlight || regionUpdateInFlight || promoInFlight || label == nil)
                .accessibilityIdentifier("settings-billing-upgrade")
            }
        } else {
            Text(BillingSectionError.missingProPlan.localizedDescription)
                .font(Typography.caption)
                .foregroundStyle(.red)
        }

        promoControls
    }

    private var promoControls: some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider()
            LabeledContent {
                HStack(spacing: 8) {
                    TextField("", text: $promoCode)
                        .textFieldStyle(.roundedBorder)
                        .frame(maxWidth: 220)
                        .help(String(localized: "billing.promo.placeholder", bundle: .main))
                        .accessibilityIdentifier("settings-billing-promo-code")
                    Button {
                        Task { await claimPromoCode() }
                    } label: {
                        if promoInFlight {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("billing.promo.apply", bundle: .main)
                        }
                    }
                    .disabled(
                        promoInFlight
                        || checkoutInFlight
                        || regionUpdateInFlight
                        || promoCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    )
                    .accessibilityIdentifier("settings-billing-promo-apply")
                }
            } label: {
                Text("billing.promo.title", bundle: .main)
            }
            if let promoMessage {
                Text(promoMessage)
                    .font(Typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("settings-billing-promo-message")
            }
        }
    }

    private func priceLabel(for pro: BillingPlan, region: BillingDisplayRegion) -> String? {
        guard let amount = pro.localizedPrice(for: period, region: region, locale: locale) else {
            return nil
        }
        let formatString = period == .year
            ? String(localized: "billing.price.perYear", bundle: .main)
            : String(localized: "billing.price.perMonth", bundle: .main)
        return String(format: formatString, amount)
    }

    // MARK: - Pro user controls

    @ViewBuilder
    private func proControls(subscription: BillingSubscription) -> some View {
        if subscription.cancelAtPeriodEnd, let end = subscription.currentPeriodEnd {
            let formatted = formattedPeriodDate(end)
            Text(String(format: String(localized: "billing.subscription.proThrough", bundle: .main), formatted))
                .font(Typography.caption)
                .foregroundStyle(.secondary)
        } else {
            if let end = subscription.currentPeriodEnd {
                Text(String(format: String(localized: "billing.subscription.renewsOn", bundle: .main), formattedPeriodDate(end)))
                    .font(Typography.caption)
                    .foregroundStyle(.secondary)
            }
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
                .disabled(cancelInFlight || regionUpdateInFlight)
            }
        }
    }

    // MARK: - Actions

    private func currentProPlan() -> BillingPlan? {
        if let plan = plans.first(where: { $0.code == "pro" }) {
            return plan
        }
        if subscription?.plan.code == "pro" {
            return subscription?.plan
        }
        return nil
    }

    private func displayRegion(for storedRegion: BillingDisplayRegion) -> BillingDisplayRegion {
        if !isRussianUI {
            return .global
        }
        if storedRegion == .global, !billingRegionUserSelectedRussian {
            return .ru
        }
        return storedRegion
    }

    private func shouldPersistRussianDefault(storedRegion: BillingDisplayRegion) -> Bool {
        isRussianUI && storedRegion == .global && !billingRegionUserSelectedRussian
    }

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
            let displayRegion = displayRegion(for: region)
            await MainActor.run {
                self.subscription = s
                self.usage = u
                self.plans = p
                self.billingRegion = displayRegion
                self.loadError = nil
                self.actionError = nil
                if s.isPro {
                    self.checkoutRefreshPending = false
                }
            }
            if shouldPersistRussianDefault(storedRegion: region) {
                await persistDefaultRussianRegion()
            }
        } catch {
            await MainActor.run {
                self.loadError = error.localizedDescription
            }
        }
    }

    private func applyRegionForCurrentLanguage() async {
        if !isRussianUI {
            await MainActor.run {
                billingRegion = .global
                actionError = nil
            }
            return
        }
        guard billingRegion == .global, !billingRegionUserSelectedRussian else { return }
        await MainActor.run { billingRegion = .ru }
        await persistDefaultRussianRegion()
    }

    private func persistDefaultRussianRegion() async {
        await MainActor.run {
            regionUpdateInFlight = true
            actionError = nil
        }
        do {
            let settings = try await appState.getAPIClient().updateSettings(
                UpdateSettingsRequest(region: BillingDisplayRegion.ru.rawValue)
            )
            guard let confirmed = BillingDisplayRegion(rawValue: settings.region) else {
                throw BillingSectionError.unsupportedRegion(settings.region)
            }
            await MainActor.run {
                billingRegion = displayRegion(for: confirmed)
                regionUpdateInFlight = false
            }
        } catch {
            await MainActor.run {
                regionUpdateInFlight = false
                actionError = error.localizedDescription
            }
        }
    }

    private func saveBillingRegion(_ region: BillingDisplayRegion) async {
        guard isRussianUI else {
            await MainActor.run { billingRegion = .global }
            return
        }
        guard billingRegion != region else { return }
        let previous = billingRegion
        await MainActor.run {
            billingRegion = region
            billingRegionUserSelectedRussian = true
            regionUpdateInFlight = true
            actionError = nil
        }
        do {
            let settings = try await appState.getAPIClient().updateSettings(
                UpdateSettingsRequest(region: region.rawValue)
            )
            guard let confirmed = BillingDisplayRegion(rawValue: settings.region) else {
                throw BillingSectionError.unsupportedRegion(settings.region)
            }
            await MainActor.run {
                billingRegion = confirmed
                regionUpdateInFlight = false
            }
        } catch {
            await MainActor.run {
                billingRegion = previous
                regionUpdateInFlight = false
                actionError = error.localizedDescription
            }
        }
    }

    private func startCheckout(plan: BillingPlan, region: BillingDisplayRegion) async {
        await MainActor.run {
            checkoutInFlight = true
            actionError = nil
        }
        do {
            let resp = try await appState.getAPIClient().createBillingCheckout(
                plan: plan.code,
                period: period.rawValue,
                provider: region.provider
            )
            guard let url = URL(string: resp.checkoutUrl),
                  let scheme = url.scheme?.lowercased(),
                  scheme == "https" || scheme == "http" else {
                throw BillingSectionError.invalidCheckoutURL(resp.checkoutUrl)
            }
            let opened = await MainActor.run {
                NSWorkspace.shared.open(url)
            }
            guard opened else {
                throw BillingSectionError.checkoutOpenRejected
            }
            await MainActor.run {
                checkoutRefreshPending = true
                startCheckoutRefreshPolling()
            }
        } catch {
            await MainActor.run {
                actionError = error.localizedDescription
            }
        }
        await MainActor.run {
            checkoutInFlight = false
        }
    }

    private func claimPromoCode() async {
        let code = promoCode.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty else { return }
        await MainActor.run {
            promoInFlight = true
            actionError = nil
            promoMessage = nil
        }
        do {
            let fresh = try await appState.getAPIClient().claimBillingPromoCode(code)
            await MainActor.run {
                subscription = fresh
                promoCode = ""
                promoMessage = String(localized: "billing.promo.applied", bundle: .main)
                if fresh.isPro {
                    checkoutRefreshPending = false
                }
            }
            await loadAll()
        } catch {
            await MainActor.run {
                actionError = localizedBillingActionError(error)
            }
        }
        await MainActor.run {
            promoInFlight = false
        }
    }

    @MainActor
    private func startCheckoutRefreshPolling() {
        checkoutRefreshTask?.cancel()
        checkoutRefreshTask = Task { @MainActor in
            for delay in Self.checkoutRefreshDelaysNanoseconds {
                do {
                    try await Task.sleep(nanoseconds: delay)
                } catch {
                    return
                }
                guard checkoutRefreshPending else {
                    checkoutRefreshTask = nil
                    return
                }
                await loadAll()
                if subscription?.isPro == true {
                    checkoutRefreshTask = nil
                    return
                }
            }
            checkoutRefreshTask = nil
        }
    }

    @MainActor
    private func stopCheckoutRefreshPolling() {
        checkoutRefreshTask?.cancel()
        checkoutRefreshTask = nil
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
                actionError = error.localizedDescription
            }
        }
        await MainActor.run {
            cancelInFlight = false
        }
    }

    private func formattedPeriodDate(_ date: Date) -> String {
        MacDateFormatting.string(
            from: date,
            dateStyle: .long,
            timeStyle: .none,
            language: languageManager.current
        )
    }

    private func localizedBillingActionError(_ error: Error) -> String {
        let message = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        if message == "Promo code not found" {
            return String(localized: "billing.promo.error.notFound", bundle: .main)
        }
        if message == "Active subscription already exists" {
            return String(localized: "billing.promo.error.activeSubscription", bundle: .main)
        }
        if message == "Promo code expired" {
            return String(localized: "billing.promo.error.expired", bundle: .main)
        }
        if message == "Promo code exhausted" {
            return String(localized: "billing.promo.error.exhausted", bundle: .main)
        }
        if message == "Promo code already redeemed" {
            return String(localized: "billing.promo.error.alreadyRedeemed", bundle: .main)
        }
        return message.isEmpty
            ? String(localized: "billing.error.loadFailed", bundle: .main)
            : message
    }
}
