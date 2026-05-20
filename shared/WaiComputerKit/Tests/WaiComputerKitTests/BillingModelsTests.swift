import Foundation
import XCTest
@testable import WaiComputerKit

final class BillingModelsTests: XCTestCase {
    func testSubscriptionDecodesEnforcementEnabled() throws {
        let json = """
        {
          "plan": {
            "code": "free",
            "name": "Free",
            "description": null,
            "usd_amount_monthly": 0,
            "usd_amount_yearly": 0,
            "rub_amount_monthly": 0,
            "rub_amount_yearly": 0,
            "word_cap_per_week": 3000,
            "memory_retention_days": 30,
            "features": {}
          },
          "status": "free",
          "provider": null,
          "billing_period": null,
          "current_period_end": null,
          "cancel_at_period_end": false,
          "trial_end": null,
          "enforcement_enabled": true
        }
        """.data(using: .utf8)!

        let subscription = try JSONDecoder().decode(BillingSubscription.self, from: json)

        XCTAssertTrue(subscription.enforcementEnabled)
    }

    func testPlanFormatsRubPriceForRussianRegion() {
        let plan = BillingPlan(
            code: "pro",
            name: "Pro",
            usdAmountMonthly: 12,
            usdAmountYearly: 96,
            rubAmountMonthly: 999,
            rubAmountYearly: 7999
        )

        let formatted = plan.localizedPrice(
            for: .month,
            region: .ru,
            locale: Locale(identifier: "ru_RU")
        )

        XCTAssertEqual(formatted, "999 ₽")
    }

    func testPlanReturnsNilWhenSelectedRegionHasNoPrice() {
        let plan = BillingPlan(
            code: "pro",
            name: "Pro",
            usdAmountMonthly: 12,
            usdAmountYearly: 96
        )

        XCTAssertNil(plan.localizedPrice(for: .month, region: .ru, locale: Locale(identifier: "ru_RU")))
    }
}
