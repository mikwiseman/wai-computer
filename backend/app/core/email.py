"""Email sending via Resend."""

import asyncio
import functools
from html import escape
from urllib.parse import urlencode

import resend
from fastapi import HTTPException, status

from app.config import get_settings
from app.core.observability import add_sentry_breadcrumb, capture_sentry_exception

# Maps client identifiers to app URL schemes.
# Using an enum-like mapping avoids open redirect vulnerabilities.
APP_CLIENT_URLS = {
    "android": "waisay://magic",
    "macos": "waisay://auth/verify",
    "ios": "waisay://auth/verify",
}


def _build_frontend_url(path: str, **query: str) -> str:
    settings = get_settings()
    return f"{settings.frontend_url}{path}?{urlencode(query)}"


def _send_email_sync(to_email: str, token: str, client: str | None = None) -> None:
    """Synchronous email send — called via run_in_executor."""
    settings = get_settings()
    resend.api_key = settings.resend_api_key

    web_url = _build_frontend_url("/auth/verify", token=token)
    web_url_html = escape(web_url, quote=True)

    if client and client in APP_CLIENT_URLS:
        app_url = _build_frontend_url("/auth/app", token=token, client=client)
        app_url_html = escape(app_url, quote=True)
        html = f"""
            <h2>Sign in to WaiSay</h2>
            <p>Click the link below to sign in. This link expires in 15 minutes.</p>
            <p><a href="{app_url_html}">Open WaiSay App</a></p>
            <p style="color: #666; font-size: 14px;">
                Link not working?
                <a href="{web_url_html}">Use browser instead</a>
            </p>
            <p>If you didn't request this, you can safely ignore this email.</p>
        """
    else:
        html = f"""
            <h2>Sign in to WaiSay</h2>
            <p>Click the link below to sign in. This link expires in 15 minutes.</p>
            <p><a href="{web_url_html}">Sign in to WaiSay</a></p>
            <p>If you didn't request this, you can safely ignore this email.</p>
        """

    resend.Emails.send(
        {
            "from": settings.email_from,
            "to": [to_email],
            "subject": "Sign in to WaiSay",
            "html": html,
        }
    )


async def send_magic_link_email(
    to_email: str, token: str, client: str | None = None
) -> None:
    """Send a magic link email to the user without blocking the event loop."""
    add_sentry_breadcrumb(
        category="email",
        message="Sending magic link email",
        data={"client": client},
    )
    try:
        loop = asyncio.get_running_loop()
        func = functools.partial(_send_email_sync, to_email, token, client)
        await loop.run_in_executor(None, func)
    except Exception as e:
        capture_sentry_exception(e, extras={"client": client})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send email",
        ) from e
