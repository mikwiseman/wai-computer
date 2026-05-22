import Foundation

extension APIClient {
    /// `GET /api/billing/usage` — current weekly transcribed-words usage.
    public func getBillingUsage() async throws -> BillingUsage {
        try await request(.GET, path: "/api/billing/usage")
    }

    /// `GET /api/billing/subscription` — effective plan + active subscription.
    public func getBillingSubscription() async throws -> BillingSubscription {
        try await request(.GET, path: "/api/billing/subscription")
    }

    /// `GET /api/billing/plans` — marketing-display plan catalogue.
    public func listBillingPlans() async throws -> [BillingPlan] {
        try await request(.GET, path: "/api/billing/plans")
    }

    /// `POST /api/billing/checkout` — start a hosted Stripe/T-Bank session.
    public func createBillingCheckout(
        plan: String, period: String, provider: String? = nil
    ) async throws -> BillingCheckoutResponse {
        let body = BillingCheckoutRequest(plan: plan, period: period, provider: provider)
        return try await request(.POST, path: "/api/billing/checkout", body: body)
    }

    /// `POST /api/billing/promo/claim` — redeem a non-renewing promo grant.
    public func claimBillingPromoCode(_ code: String) async throws -> BillingSubscription {
        let body = BillingPromoClaimRequest(code: code)
        return try await request(.POST, path: "/api/billing/promo/claim", body: body)
    }

    /// `POST /api/billing/cancel` — mark the active subscription as
    /// cancel-at-period-end. The user keeps Pro until the period actually ends.
    public func cancelBillingSubscription() async throws {
        try await requestNoContent(.POST, path: "/api/billing/cancel")
    }
}
