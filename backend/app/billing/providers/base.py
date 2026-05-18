"""Abstract payment provider interface.

Both Stripe and T-Bank implementations conform to this so the routing layer
can stay provider-agnostic and the subscription state machine has exactly
one shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class ProviderUnavailableError(Exception):
    """Raised when a provider is selected but its credentials are not configured."""


@dataclass(frozen=True)
class CheckoutResult:
    """Result of starting a hosted checkout session."""

    checkout_url: str
    provider: str
    provider_session_id: str | None = None


@dataclass(frozen=True)
class ProviderEvent:
    """Normalized event distilled from a provider webhook."""

    type: str
    subscription_id_provider: str | None
    customer_id_provider: str | None
    status: str | None  # e.g. "active", "past_due", "canceled" (provider-normalized)
    raw: dict[str, Any]


class PaymentProvider(ABC):
    """Stripe / T-Bank interface."""

    name: str

    @abstractmethod
    async def create_checkout(
        self,
        *,
        plan_code: str,
        period: str,  # "month" | "year"
        user_email: str,
        user_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int | None = None,
    ) -> CheckoutResult:
        """Create a hosted checkout session and return its URL."""

    @abstractmethod
    async def cancel_subscription(self, provider_subscription_id: str) -> None:
        """Mark the provider subscription as canceled at period end."""

    @abstractmethod
    async def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> ProviderEvent:
        """Verify the webhook signature and return a normalized event.

        Raises ``ProviderUnavailableError`` if credentials are missing,
        ``ValueError`` if the signature is invalid.
        """
