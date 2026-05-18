"""Provider webhook receivers — verify signatures, normalize, dispatch."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import Database
from app.billing.providers.base import ProviderUnavailableError
from app.billing.providers.stripe_provider import StripeProvider
from app.billing.service import apply_stripe_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, db: Database) -> dict:
    """Receive a Stripe webhook, verify signature, dispatch to subscription state."""
    raw = await request.body()
    provider = StripeProvider()
    try:
        event = await provider.parse_webhook(raw_body=raw, headers=dict(request.headers))
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    logger.info("Stripe webhook received type=%s", event.type)
    await apply_stripe_event(db, event)
    return {"received": True, "type": event.type}


@router.post("/tinkoff", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def tinkoff_webhook(request: Request) -> dict:
    """Receive a T-Bank webhook. Phase 3 implements HMAC verify + event handlers."""
    raise HTTPException(status_code=501, detail="T-Bank webhook not yet wired")
