"""Provider webhook receivers — verify signatures, normalize, dispatch."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def stripe_webhook(request: Request) -> dict:
    """Receive a Stripe webhook. Phase 2 implements signature verify + event handlers."""
    raise HTTPException(status_code=501, detail="Stripe webhook not yet wired")


@router.post("/tinkoff", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def tinkoff_webhook(request: Request) -> dict:
    """Receive a T-Bank webhook. Phase 3 implements HMAC verify + event handlers."""
    raise HTTPException(status_code=501, detail="T-Bank webhook not yet wired")
