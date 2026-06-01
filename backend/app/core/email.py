"""Email sending via Resend."""

import asyncio
import functools
from datetime import datetime
from decimal import Decimal
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
        "charge_subject": "Your WaiComputer payment receipt",
        "charge_title": "Payment received",
        "charge_body": "We've charged {amount} for your WaiComputer Pro subscription ({period}).",
        "charge_next": "Your next charge is on {date}.",
        "charge_cancel": "You can cancel auto-renewal at any time:",
        "charge_manage_cta": "Manage subscription",
        "charge_support": "Questions? Reply to this email or contact support.",
        "failed_subject": "WaiComputer payment failed",
        "failed_title": "We couldn't process your payment",
        "failed_body": (
            "Your WaiComputer Pro renewal didn't go through. Update your payment "
            "method to keep your subscription active."
        ),
        "failed_cta": "Manage subscription",
        "reminder_subject": "Your WaiComputer subscription renews soon",
        "reminder_title": "Upcoming renewal",
        "reminder_body": "Your WaiComputer Pro subscription will renew for {amount} on {date}.",
        "reminder_cancel": "If you don't want to renew, you can cancel here:",
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
        "charge_subject": "Оплата подписки WaiComputer",
        "charge_title": "Оплата прошла успешно",
        "charge_body": "Мы списали {amount} за подписку WaiComputer Pro ({period}).",
        "charge_next": "Следующее списание — {date}.",
        "charge_cancel": "Вы можете отменить автопродление в любой момент:",
        "charge_manage_cta": "Управление подпиской",
        "charge_support": "Вопросы? Ответьте на это письмо или напишите в поддержку.",
        "failed_subject": "Не удалось списать оплату WaiComputer",
        "failed_title": "Не получилось провести оплату",
        "failed_body": (
            "Не удалось продлить подписку WaiComputer Pro. Обновите способ оплаты, "
            "чтобы сохранить доступ."
        ),
        "failed_cta": "Управление подпиской",
        "reminder_subject": "Скоро продление подписки WaiComputer",
        "reminder_title": "Предстоящее продление",
        "reminder_body": "Подписка WaiComputer Pro продлится на {amount} — {date}.",
        "reminder_cancel": "Если не хотите продлевать, можно отменить здесь:",
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


# ---------------------------------------------------------------------------
# Billing notifications (T-Bank recurrent compliance)
#
# T-Bank requires the user to be notified of every recurring charge and to be
# able to cancel from that notice. These run inside the payment webhook / Celery
# rebill flow, so — unlike the auth emails above — they must NEVER raise: a
# Resend outage must not roll back a successful charge. They report to Sentry
# and return False instead.
# ---------------------------------------------------------------------------

_PERIOD_LABELS = {
    "en": {"month": "monthly", "year": "yearly"},
    "ru": {"month": "ежемесячно", "year": "ежегодно"},
}


def _billing_manage_url(locale: str) -> str:
    path = "/ru/billing" if locale == "ru" else "/billing"
    return f"{get_settings().frontend_url}{path}"


def _money_str(amount: Decimal, currency: str | None) -> str:
    if (currency or "").upper() == "RUB":
        return f"{int(amount)} ₽"
    return f"${amount:.2f}"


def _charge_date_str(when: datetime | None, locale: str) -> str | None:
    if when is None:
        return None
    return when.strftime("%d.%m.%Y") if locale == "ru" else when.strftime("%b %d, %Y")


def _period_label(period: str | None, locale: str) -> str:
    return _PERIOD_LABELS.get(locale, _PERIOD_LABELS["en"]).get(period or "", period or "")


def _send_html_email_sync(to_email: str, subject: str, html: str) -> None:
    settings = get_settings()
    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {"from": settings.email_from, "to": [to_email], "subject": subject, "html": html}
    )


async def _send_billing_email(to_email: str, subject: str, html: str, *, kind: str) -> bool:
    """Send a transactional billing email, swallowing + reporting any failure.

    Deliberately non-fatal: the charge already succeeded by the time we notify,
    so a mail outage is logged to Sentry rather than rolled back into the
    payment flow.
    """
    add_sentry_breadcrumb(category="email", message="Sending billing email", data={"kind": kind})
    try:
        loop = asyncio.get_running_loop()
        func = functools.partial(_send_html_email_sync, to_email, subject, html)
        await loop.run_in_executor(None, func)
        return True
    except Exception as e:  # noqa: BLE001 — never propagate into the charge flow
        capture_sentry_exception(e, extras={"email_kind": kind})
        return False


def _manage_link_html(locale: str, cta_key: str) -> str:
    copy = EMAIL_COPY[locale]
    url_html = escape(_billing_manage_url(locale), quote=True)
    return f'<p><a href="{url_html}">{copy[cta_key]}</a></p>'


async def send_charge_confirmation_email(
    to_email: str,
    *,
    amount: Decimal,
    currency: str,
    period: str | None,
    next_charge_at: datetime | None,
    locale: str | None = None,
) -> bool:
    """Notify the user of a successful recurring charge, with a cancel link."""
    norm = _normalize_locale(locale)
    copy = EMAIL_COPY[norm]
    amount_str = _money_str(amount, currency)
    next_str = _charge_date_str(next_charge_at, norm)
    next_line = f"<p>{copy['charge_next'].format(date=next_str)}</p>" if next_str else ""
    html = f"""
        <h2>{copy['charge_title']}</h2>
        <p>{copy['charge_body'].format(amount=amount_str, period=_period_label(period, norm))}</p>
        {next_line}
        <p>{copy['charge_cancel']}</p>
        {_manage_link_html(norm, 'charge_manage_cta')}
        <p style="color: #666; font-size: 14px;">{copy['charge_support']}</p>
    """
    return await _send_billing_email(to_email, copy["charge_subject"], html, kind="charge")


async def send_payment_failed_email(to_email: str, *, locale: str | None = None) -> bool:
    """Notify the user a recurring charge failed and how to recover access."""
    norm = _normalize_locale(locale)
    copy = EMAIL_COPY[norm]
    html = f"""
        <h2>{copy['failed_title']}</h2>
        <p>{copy['failed_body']}</p>
        {_manage_link_html(norm, 'failed_cta')}
    """
    return await _send_billing_email(to_email, copy["failed_subject"], html, kind="payment_failed")


async def send_renewal_reminder_email(
    to_email: str,
    *,
    amount: Decimal,
    currency: str,
    next_charge_at: datetime | None,
    locale: str | None = None,
) -> bool:
    """Remind the user of an upcoming recurring charge, with a cancel link."""
    norm = _normalize_locale(locale)
    copy = EMAIL_COPY[norm]
    date_str = _charge_date_str(next_charge_at, norm) or ""
    html = f"""
        <h2>{copy['reminder_title']}</h2>
        <p>{copy['reminder_body'].format(amount=_money_str(amount, currency), date=date_str)}</p>
        <p>{copy['reminder_cancel']}</p>
        {_manage_link_html(norm, 'charge_manage_cta')}
    """
    return await _send_billing_email(
        to_email, copy["reminder_subject"], html, kind="renewal_reminder"
    )
