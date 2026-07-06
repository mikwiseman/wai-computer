import AppKit
import SwiftUI
import WaiComputerKit

// Deliberately NOT LocalizedError: descriptions are produced at display time
// by `billingErrorText(_:)` so they resolve against the app's selected
// language (LanguageManager), not the system locale that String(localized:)
// uses (103/135/136). Every throw site in this file is rendered through
// `displayableError(_:)`.
private enum BillingSectionError: Error {
    case unsupportedRegion(String)
    case missingProPlan
    case missingPrice(BillingDisplayRegion, BillingDisplayPeriod)
    case invalidCheckoutURL(String)
    case checkoutOpenRejected
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
    @State private var showingCancelConfirmation = false
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
                            .foregroundStyle(Palette.danger)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("settings-billing-action-error")
                    }
                }
            } else if let loadError {
                Text(loadError)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.danger)
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
        .onChangeCompat(of: languageManager.current) { _, _ in
            Task { await applyRegionForCurrentLanguage() }
        }
        .onDisappear {
            stopCheckoutRefreshPolling()
        }
        .confirmationDialog(
            t("Cancel subscription?", "Отменить подписку?"),
            isPresented: $showingCancelConfirmation,
            titleVisibility: .visible
        ) {
            Button(t("Cancel subscription", "Отменить подписку"), role: .destructive) {
                Task { await cancelSubscription() }
            }
            Button(t("Keep subscription", "Оставить подписку"), role: .cancel) {}
        } message: {
            Text(t(
                "Pro stays active until the end of the current period, then won't renew.",
                "Pro останется активным до конца текущего периода, после чего не продлится."
            ))
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
                    Text(billingErrorText(.missingPrice(region, period)))
                        .font(Typography.caption)
                        .foregroundStyle(Palette.danger)
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
            Text(billingErrorText(.missingProPlan))
                .font(Typography.caption)
                .foregroundStyle(Palette.danger)
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
                        .help(t("Enter promo code", "Введи промокод"))
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
        // t(), not String(localized:) — prices must follow the in-app language
        // (103/135/136).
        return period == .year
            ? t("\(amount) / year", "\(amount) / год")
            : t("\(amount) / month", "\(amount) / мес")
    }

    // MARK: - Pro user controls

    @ViewBuilder
    private func proControls(subscription: BillingSubscription) -> some View {
        if subscription.cancelAtPeriodEnd, let end = subscription.currentPeriodEnd {
            // t(), not String(localized:) — the date is already formatted for
            // the in-app language, so the wrapper must match it (103/135/136).
            let formatted = formattedPeriodDate(end)
            Text(t("Pro through \(formatted)", "Pro до \(formatted)"))
                .font(Typography.caption)
                .foregroundStyle(.secondary)
        } else {
            if let end = subscription.currentPeriodEnd {
                let formatted = formattedPeriodDate(end)
                Text(t("Renews on \(formatted)", "Продление \(formatted)"))
                    .font(Typography.caption)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Spacer()
                Button(role: .destructive) {
                    showingCancelConfirmation = true
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
                self.loadError = displayableError(error)
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
                actionError = displayableError(error)
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
                actionError = displayableError(error)
            }
        }
    }

    private func startCheckout(
        plan: BillingPlan,
        region: BillingDisplayRegion,
        promoCode: String? = nil
    ) async {
        await MainActor.run {
            checkoutInFlight = true
            actionError = nil
        }
        do {
            let resp = try await appState.getAPIClient().createBillingCheckout(
                plan: plan.code,
                period: period.rawValue,
                provider: region.provider,
                promoCode: promoCode
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
                actionError = displayableError(error)
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
                promoMessage = t("Promo code applied.", "Промокод применён.")
                if fresh.isPro {
                    checkoutRefreshPending = false
                }
            }
            await loadAll()
        } catch {
            if isCheckoutPromoCodeError(error) {
                guard let pro = currentProPlan(), let region = billingRegion else {
                    await MainActor.run {
                        actionError = billingErrorText(.missingProPlan)
                        promoInFlight = false
                    }
                    return
                }
                await startCheckout(plan: pro, region: region, promoCode: code)
                await MainActor.run {
                    promoInFlight = false
                }
                return
            }
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
                actionError = displayableError(error)
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

    /// Display-time descriptions for `BillingSectionError`, resolved through
    /// t()/LanguageManager so they follow the in-app language — the same fix
    /// `localizedBillingActionError` applies to promo errors (103/135/136).
    private func billingErrorText(_ error: BillingSectionError) -> String {
        switch error {
        case .unsupportedRegion(let region):
            return t(
                "Unsupported billing region: \(region).",
                "Неподдерживаемый регион оплаты: \(region)."
            )
        case .missingProPlan:
            return t(
                "Pro plan is missing from the billing catalogue.",
                "В каталоге оплаты нет тарифа Pro."
            )
        case .missingPrice(let region, let period):
            return t(
                "No price configured for \(region.rawValue) / \(period.rawValue).",
                "Цена не настроена для \(region.rawValue) / \(period.rawValue)."
            )
        case .invalidCheckoutURL(let url):
            return t(
                "Checkout returned an invalid URL: \(url).",
                "Оплата вернула некорректную ссылку: \(url)."
            )
        case .checkoutOpenRejected:
            return t(
                "macOS rejected the checkout link.",
                "macOS не открыла ссылку оплаты."
            )
        }
    }

    private func displayableError(_ error: Error) -> String {
        if let billingError = error as? BillingSectionError {
            return billingErrorText(billingError)
        }
        return error.localizedDescription
    }

    private func localizedBillingActionError(_ error: Error) -> String {
        let message = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        // Resolve against the app's selected language (LanguageManager), not the
        // system locale that String(localized:) uses — otherwise promo errors leak
        // English when the app UI language and the macOS system language differ
        // (103/135/136).
        switch message {
        case "Promo code not found":
            return t("Promo code not found.", "Промокод не найден.")
        case "Active subscription already exists":
            return t("You already have an active subscription.", "У тебя уже есть активная подписка.")
        case "Promo code expired":
            return t("Promo code expired.", "Срок действия промокода истёк.")
        case "Promo code exhausted":
            return t("Promo code has already been fully used.", "Промокод уже исчерпан.")
        case "Promo code already redeemed":
            return t("You already redeemed this promo code.", "Ты уже использовал этот промокод.")
        case "Promo code does not apply to selected period":
            return t(
                "This promo code does not apply to the selected billing period.",
                "Промокод не применим к выбранному периоду оплаты."
            )
        case "Promo code grants Pro access":
            return t("This promo code grants full Pro access.", "Этот промокод даёт полный доступ Pro.")
        default:
            break
        }
        // Any other promo-code error (incl. server-side 500s) must not leak raw English.
        if message.hasPrefix("Promo code") {
            return t("This promo code can't be applied.", "Этот промокод нельзя применить.")
        }
        return message.isEmpty
            ? t("Something went wrong. Please try again.", "Что-то пошло не так. Попробуй ещё раз.")
            : message
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    private func isCheckoutPromoCodeError(_ error: Error) -> Bool {
        if case APIError.httpError(_, let message) = error {
            return message == "Promo code applies to checkout"
        }
        return false
    }
}
