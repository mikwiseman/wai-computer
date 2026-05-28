import Foundation

public enum BillingDisplayPeriod: String, Codable, CaseIterable, Sendable {
    case month
    case year
}

public enum BillingDisplayRegion: String, Codable, CaseIterable, Sendable {
    case global
    case ru

    public var provider: String {
        switch self {
        case .global: return "stripe"
        case .ru: return "tinkoff"
        }
    }

    public var currencyCode: String {
        switch self {
        case .global: return "USD"
        case .ru: return "RUB"
        }
    }
}

public typealias BillingPeriod = BillingDisplayPeriod
public typealias BillingRegion = BillingDisplayRegion

/// Marketing-display data returned by `/api/billing/plans` and embedded
/// inside `/api/billing/subscription` responses.
public struct BillingPlan: Codable, Equatable, Sendable {
    public let code: String
    public let name: String
    public let description: String?
    public let usdAmountMonthly: Decimal?
    public let usdAmountYearly: Decimal?
    public let rubAmountMonthly: Decimal?
    public let rubAmountYearly: Decimal?
    public let wordCapPerWeek: Int?
    public let memoryRetentionDays: Int?
    public let features: [String: Bool]

    enum CodingKeys: String, CodingKey {
        case code, name, description
        case usdAmountMonthly = "usd_amount_monthly"
        case usdAmountYearly = "usd_amount_yearly"
        case rubAmountMonthly = "rub_amount_monthly"
        case rubAmountYearly = "rub_amount_yearly"
        case wordCapPerWeek = "word_cap_per_week"
        case memoryRetentionDays = "memory_retention_days"
        case features
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.code = try c.decode(String.self, forKey: .code)
        self.name = try c.decode(String.self, forKey: .name)
        self.description = try c.decodeIfPresent(String.self, forKey: .description)
        self.usdAmountMonthly = try c.decodeIfPresent(Decimal.self, forKey: .usdAmountMonthly)
        self.usdAmountYearly = try c.decodeIfPresent(Decimal.self, forKey: .usdAmountYearly)
        self.rubAmountMonthly = try c.decodeIfPresent(Decimal.self, forKey: .rubAmountMonthly)
        self.rubAmountYearly = try c.decodeIfPresent(Decimal.self, forKey: .rubAmountYearly)
        self.wordCapPerWeek = try c.decodeIfPresent(Int.self, forKey: .wordCapPerWeek)
        self.memoryRetentionDays = try c.decodeIfPresent(Int.self, forKey: .memoryRetentionDays)
        let raw = try c.decodeIfPresent([String: Bool].self, forKey: .features) ?? [:]
        self.features = raw
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(code, forKey: .code)
        try c.encode(name, forKey: .name)
        try c.encodeIfPresent(description, forKey: .description)
        try c.encodeIfPresent(usdAmountMonthly, forKey: .usdAmountMonthly)
        try c.encodeIfPresent(usdAmountYearly, forKey: .usdAmountYearly)
        try c.encodeIfPresent(rubAmountMonthly, forKey: .rubAmountMonthly)
        try c.encodeIfPresent(rubAmountYearly, forKey: .rubAmountYearly)
        try c.encodeIfPresent(wordCapPerWeek, forKey: .wordCapPerWeek)
        try c.encodeIfPresent(memoryRetentionDays, forKey: .memoryRetentionDays)
        try c.encode(features, forKey: .features)
    }

    public init(
        code: String,
        name: String,
        description: String? = nil,
        usdAmountMonthly: Decimal? = nil,
        usdAmountYearly: Decimal? = nil,
        rubAmountMonthly: Decimal? = nil,
        rubAmountYearly: Decimal? = nil,
        wordCapPerWeek: Int? = nil,
        memoryRetentionDays: Int? = nil,
        features: [String: Bool] = [:]
    ) {
        self.code = code
        self.name = name
        self.description = description
        self.usdAmountMonthly = usdAmountMonthly
        self.usdAmountYearly = usdAmountYearly
        self.rubAmountMonthly = rubAmountMonthly
        self.rubAmountYearly = rubAmountYearly
        self.wordCapPerWeek = wordCapPerWeek
        self.memoryRetentionDays = memoryRetentionDays
        self.features = features
    }

    public func amount(for period: BillingDisplayPeriod, region: BillingDisplayRegion) -> Decimal? {
        switch (period, region) {
        case (.month, .global):
            return usdAmountMonthly
        case (.year, .global):
            return usdAmountYearly
        case (.month, .ru):
            return rubAmountMonthly
        case (.year, .ru):
            return rubAmountYearly
        }
    }

    public func localizedPrice(
        for period: BillingDisplayPeriod,
        region: BillingDisplayRegion,
        locale: Locale = .current
    ) -> String? {
        guard let amount = amount(for: period, region: region) else { return nil }
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = region.currencyCode
        formatter.locale = locale
        formatter.minimumFractionDigits = 0
        formatter.maximumFractionDigits = 2
        return formatter.string(from: NSDecimalNumber(decimal: amount))
    }
}

public struct BillingSubscription: Codable, Equatable, Sendable {
    public let plan: BillingPlan
    public let status: String  // "free", "trialing", "active", "past_due", "canceled", ...
    public let provider: String?  // "stripe" | "tinkoff" | nil for free
    public let billingPeriod: String?  // "month" | "year" | nil
    public let currentPeriodEnd: Date?
    public let cancelAtPeriodEnd: Bool
    public let trialEnd: Date?
    public let enforcementEnabled: Bool

    enum CodingKeys: String, CodingKey {
        case plan, status, provider
        case billingPeriod = "billing_period"
        case currentPeriodEnd = "current_period_end"
        case cancelAtPeriodEnd = "cancel_at_period_end"
        case trialEnd = "trial_end"
        case enforcementEnabled = "enforcement_enabled"
    }

    public var isPro: Bool { plan.code == "pro" && status != "canceled" && status != "expired" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        plan = try c.decode(BillingPlan.self, forKey: .plan)
        status = try c.decode(String.self, forKey: .status)
        provider = try c.decodeIfPresent(String.self, forKey: .provider)
        billingPeriod = try c.decodeIfPresent(String.self, forKey: .billingPeriod)
        currentPeriodEnd = try c.decodeIfPresent(Date.self, forKey: .currentPeriodEnd)
        cancelAtPeriodEnd = try c.decode(Bool.self, forKey: .cancelAtPeriodEnd)
        trialEnd = try c.decodeIfPresent(Date.self, forKey: .trialEnd)
        enforcementEnabled = try c.decodeIfPresent(Bool.self, forKey: .enforcementEnabled) ?? false
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(plan, forKey: .plan)
        try c.encode(status, forKey: .status)
        try c.encodeIfPresent(provider, forKey: .provider)
        try c.encodeIfPresent(billingPeriod, forKey: .billingPeriod)
        try c.encodeIfPresent(currentPeriodEnd, forKey: .currentPeriodEnd)
        try c.encode(cancelAtPeriodEnd, forKey: .cancelAtPeriodEnd)
        try c.encodeIfPresent(trialEnd, forKey: .trialEnd)
        try c.encode(enforcementEnabled, forKey: .enforcementEnabled)
    }
}

public struct BillingUsage: Codable, Equatable, Sendable {
    public let wordsUsed: Int
    public let wordsCap: Int?  // nil means the server is not enforcing a weekly cap for this request.
    public let resetAt: Date
    public let capExceeded: Bool

    enum CodingKeys: String, CodingKey {
        case wordsUsed = "words_used"
        case wordsCap = "words_cap"
        case resetAt = "reset_at"
        case capExceeded = "cap_exceeded"
    }

    public var fractionUsed: Double {
        guard let cap = wordsCap, cap > 0 else { return 0 }
        return min(1.0, max(0.0, Double(wordsUsed) / Double(cap)))
    }
}

public struct BillingCheckoutRequest: Encodable, Sendable {
    public let plan: String
    public let period: String  // "month" | "year"
    public let provider: String?  // optional override
    public let promoCode: String?

    enum CodingKeys: String, CodingKey {
        case plan, period, provider
        case promoCode = "promo_code"
    }

    public init(plan: String, period: String, provider: String? = nil, promoCode: String? = nil) {
        self.plan = plan
        self.period = period
        self.provider = provider
        self.promoCode = promoCode
    }
}

public struct BillingPromoClaimRequest: Encodable, Sendable {
    public let code: String

    public init(code: String) {
        self.code = code
    }
}

public struct BillingCheckoutResponse: Codable, Sendable {
    public let provider: String
    public let checkoutUrl: String

    enum CodingKeys: String, CodingKey {
        case provider
        case checkoutUrl = "checkout_url"
    }
}
