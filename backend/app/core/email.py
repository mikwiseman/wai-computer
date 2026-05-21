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
    "android": "waicomputer://magic",
    "macos": "waicomputer://auth/verify",
    "ios": "waicomputer://auth/verify",
}

EMAIL_COPY = {
    "en": {
        "magic_subject": "Sign in to WaiComputer",
        "magic_title": "Sign in to WaiComputer",
        "magic_body": "Click the link below to sign in. This link expires in 15 minutes.",
        "magic_cta": "Sign in to WaiComputer",
        "app_cta": "Open WaiComputer App",
        "fallback_prefix": "Link not working?",
        "fallback_cta": "Use browser instead",
        "ignore": "If you didn't request this, you can safely ignore this email.",
        "reset_subject": "Reset your WaiComputer password",
        "reset_title": "Reset your WaiComputer password",
        "reset_body": (
            "Click the link below to set a new password. This link expires in 15 minutes."
        ),
        "reset_cta": "Reset password",
        "reset_ignore": "If you didn't request a password reset, you can safely ignore this email.",
    },
    "ru": {
        "magic_subject": "Вход в WaiComputer",
        "magic_title": "Войти в WaiComputer",
        "magic_body": "Нажми на ссылку ниже, чтобы войти. Ссылка действует 15 минут.",
        "magic_cta": "Войти в WaiComputer",
        "app_cta": "Открыть приложение WaiComputer",
        "fallback_prefix": "Ссылка не открывается?",
        "fallback_cta": "Войти в браузере",
        "ignore": "Если это был не ты, просто проигнорируй это письмо.",
        "reset_subject": "Сброс пароля WaiComputer",
        "reset_title": "Сброс пароля WaiComputer",
        "reset_body": "Нажми на ссылку ниже, чтобы задать новый пароль. Ссылка действует 15 минут.",
        "reset_cta": "Сбросить пароль",
        "reset_ignore": "Если ты не запрашивал сброс пароля, просто проигнорируй это письмо.",
    },
}


def _build_frontend_url(path: str, **query: str) -> str:
    settings = get_settings()
    return f"{settings.frontend_url}{path}?{urlencode(query)}"


def _normalize_locale(locale: str | None) -> str:
    if locale and locale.lower().startswith("ru"):
        return "ru"
    return "en"


def _build_magic_link_html(token: str, client: str | None, locale: str) -> str:
    copy = EMAIL_COPY[locale]
    query = {"token": token}
    if locale != "en":
        query["locale"] = locale
    web_url = _build_frontend_url("/auth/verify", **query)
    web_url_html = escape(web_url, quote=True)

    if client and client in APP_CLIENT_URLS:
        app_query = {"token": token, "client": client}
        if locale != "en":
            app_query["locale"] = locale
        app_url = _build_frontend_url("/auth/app", **app_query)
        app_url_html = escape(app_url, quote=True)
        return f"""
            <h2>{copy["magic_title"]}</h2>
            <p>{copy["magic_body"]}</p>
            <p><a href="{app_url_html}">{copy["app_cta"]}</a></p>
            <p style="color: #666; font-size: 14px;">
                {copy["fallback_prefix"]}
                <a href="{web_url_html}">{copy["fallback_cta"]}</a>
            </p>
            <p>{copy["ignore"]}</p>
        """

    return f"""
        <h2>{copy["magic_title"]}</h2>
        <p>{copy["magic_body"]}</p>
        <p><a href="{web_url_html}">{copy["magic_cta"]}</a></p>
        <p>{copy["ignore"]}</p>
    """


def _build_password_reset_html(token: str, locale: str) -> str:
    copy = EMAIL_COPY[locale]
    query = {"token": token}
    if locale != "en":
        query["locale"] = locale
    reset_url = _build_frontend_url("/auth/reset", **query)
    reset_url_html = escape(reset_url, quote=True)
    return f"""
        <h2>{copy["reset_title"]}</h2>
        <p>{copy["reset_body"]}</p>
        <p><a href="{reset_url_html}">{copy["reset_cta"]}</a></p>
        <p>{copy["reset_ignore"]}</p>
    """


def _send_email_sync(
    to_email: str,
    token: str,
    client: str | None = None,
    locale: str | None = None,
    purpose: str = "magic",
) -> None:
    """Synchronous email send — called via run_in_executor."""
    settings = get_settings()
    resend.api_key = settings.resend_api_key
    normalized_locale = _normalize_locale(locale)
    copy = EMAIL_COPY[normalized_locale]

    if purpose == "reset":
        subject = copy["reset_subject"]
        html = _build_password_reset_html(token, normalized_locale)
    else:
        subject = copy["magic_subject"]
        html = _build_magic_link_html(token, client, normalized_locale)

    resend.Emails.send(
        {
            "from": settings.email_from,
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
    )


async def send_magic_link_email(
    to_email: str,
    token: str,
    client: str | None = None,
    locale: str | None = None,
) -> None:
    """Send a magic link email to the user without blocking the event loop."""
    add_sentry_breadcrumb(
        category="email",
        message="Sending magic link email",
        data={"client": client, "locale": _normalize_locale(locale)},
    )
    try:
        loop = asyncio.get_running_loop()
        func = functools.partial(_send_email_sync, to_email, token, client, locale)
        await loop.run_in_executor(None, func)
    except Exception as e:
        capture_sentry_exception(e, extras={"client": client})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send email",
        ) from e


async def send_password_reset_email(
    to_email: str,
    token: str,
    locale: str | None = None,
) -> None:
    """Send a password reset email to the user without blocking the event loop."""
    add_sentry_breadcrumb(
        category="email",
        message="Sending password reset email",
        data={"locale": _normalize_locale(locale)},
    )
    try:
        loop = asyncio.get_running_loop()
        func = functools.partial(
            _send_email_sync,
            to_email,
            token,
            None,
            locale,
            "reset",
        )
        await loop.run_in_executor(None, func)
    except Exception as e:
        capture_sentry_exception(e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send password reset email",
        ) from e
