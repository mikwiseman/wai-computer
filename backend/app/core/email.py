"""Email sending via Resend."""

import asyncio
import functools

import resend
import sentry_sdk
from fastapi import HTTPException, status

from app.config import get_settings

# Maps client identifiers to app URL schemes.
# Using an enum-like mapping avoids open redirect vulnerabilities.
APP_CLIENT_URLS = {
    "macos": "waicomputer://auth/verify",
    "ios": "waicomputer://auth/verify",
}


def _send_email_sync(to_email: str, token: str, client: str | None = None) -> None:
    """Synchronous email send — called via run_in_executor."""
    settings = get_settings()
    resend.api_key = settings.resend_api_key

    web_url = f"{settings.frontend_url}/auth/verify?token={token}"

    if client and client in APP_CLIENT_URLS:
        app_url = f"{APP_CLIENT_URLS[client]}?token={token}"
        html = f"""
            <h2>Sign in to WaiComputer</h2>
            <p>Click the link below to sign in. This link expires in 15 minutes.</p>
            <p><a href="{app_url}">Open in WaiComputer App</a></p>
            <p style="color: #666; font-size: 14px;">
                Link not working?
                <a href="{web_url}">Sign in via browser instead</a>
            </p>
            <p>If you didn't request this, you can safely ignore this email.</p>
        """
    else:
        html = f"""
            <h2>Sign in to WaiComputer</h2>
            <p>Click the link below to sign in. This link expires in 15 minutes.</p>
            <p><a href="{web_url}">Sign in to WaiComputer</a></p>
            <p>If you didn't request this, you can safely ignore this email.</p>
        """

    resend.Emails.send(
        {
            "from": settings.email_from,
            "to": [to_email],
            "subject": "Sign in to WaiComputer",
            "html": html,
        }
    )


async def send_magic_link_email(
    to_email: str, token: str, client: str | None = None
) -> None:
    """Send a magic link email to the user without blocking the event loop."""
    sentry_sdk.add_breadcrumb(
        category="email",
        message="Sending magic link email",
        data={"client": client},
        level="info",
    )
    try:
        loop = asyncio.get_running_loop()
        func = functools.partial(_send_email_sync, to_email, token, client)
        await loop.run_in_executor(None, func)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send email",
        ) from e
