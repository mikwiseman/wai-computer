"""Email sending via Resend."""

import asyncio

import resend
from fastapi import HTTPException, status

from app.config import get_settings


def _send_email_sync(to_email: str, token: str) -> None:
    """Synchronous email send — called via run_in_executor."""
    settings = get_settings()
    resend.api_key = settings.resend_api_key

    magic_link_url = f"{settings.frontend_url}/auth/verify?token={token}"

    resend.Emails.send(
        {
            "from": settings.email_from,
            "to": [to_email],
            "subject": "Sign in to WaiComputer",
            "html": f"""
                <h2>Sign in to WaiComputer</h2>
                <p>Click the link below to sign in. This link expires in 15 minutes.</p>
                <p><a href="{magic_link_url}">Sign in to WaiComputer</a></p>
                <p>If you didn't request this, you can safely ignore this email.</p>
            """,
        }
    )


async def send_magic_link_email(to_email: str, token: str) -> None:
    """Send a magic link email to the user without blocking the event loop."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send_email_sync, to_email, token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send email",
        ) from e
