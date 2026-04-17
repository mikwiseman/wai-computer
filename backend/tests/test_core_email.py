"""Tests for app/core/email.py - Email sending via Resend."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def _mock_settings():
    mock = MagicMock()
    mock.resend_api_key = "re_test_key_123"
    mock.frontend_url = "https://say.waiwai.is"
    mock.email_from = "WaiSay <noreply@mail.waiwai.is>"
    return mock


class TestSendMagicLinkEmail:
    async def test_successful_send_calls_resend_with_correct_params(self):
        """Successful send calls resend.Emails.send with correct from, to, subject, html."""
        mock_settings = _mock_settings()

        with patch("app.core.email.get_settings", return_value=mock_settings), \
             patch("app.core.email.resend") as mock_resend:
            from app.core.email import send_magic_link_email

            await send_magic_link_email("user@example.com", "abc123token")

            assert mock_resend.api_key == "re_test_key_123"
            mock_resend.Emails.send.assert_called_once()

            call_args = mock_resend.Emails.send.call_args[0][0]
            assert call_args["from"] == "WaiSay <noreply@mail.waiwai.is>"
            assert call_args["to"] == ["user@example.com"]
            assert call_args["subject"] == "Sign in to WaiSay"
            assert "https://say.waiwai.is/auth/verify?token=abc123token" in call_args["html"]

    async def test_resend_failure_raises_http_502(self):
        """When resend.Emails.send raises, an HTTPException with status 502 is raised."""
        mock_settings = _mock_settings()

        with patch("app.core.email.get_settings", return_value=mock_settings), \
             patch("app.core.email.resend") as mock_resend:
            mock_resend.Emails.send.side_effect = Exception("Resend API error")

            from app.core.email import send_magic_link_email

            with pytest.raises(HTTPException) as exc_info:
                await send_magic_link_email("user@example.com", "token123")

            assert exc_info.value.status_code == 502
            assert "Failed to send email" in exc_info.value.detail

    async def test_magic_link_url_format(self):
        """Magic link URL is formatted as {frontend_url}/auth/verify?token={token}."""
        mock_settings = MagicMock()
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.frontend_url = "https://custom.domain.com"
        mock_settings.email_from = "noreply@example.com"

        with patch("app.core.email.get_settings", return_value=mock_settings), \
             patch("app.core.email.resend") as mock_resend:
            from app.core.email import send_magic_link_email

            await send_magic_link_email("user@example.com", "my-special-token")

            call_args = mock_resend.Emails.send.call_args[0][0]
            expected_url = (
                "https://custom.domain.com/auth/verify?token=my-special-token"
            )
            assert expected_url in call_args["html"]

    async def test_client_none_sends_web_link_only(self):
        """When client=None, email contains only the web URL (no app scheme)."""
        mock_settings = _mock_settings()

        with patch("app.core.email.get_settings", return_value=mock_settings), \
             patch("app.core.email.resend") as mock_resend:
            from app.core.email import send_magic_link_email

            await send_magic_link_email("user@example.com", "token123", client=None)

            call_args = mock_resend.Emails.send.call_args[0][0]
            assert "https://say.waiwai.is/auth/verify?token=token123" in call_args["html"]
            assert "waisay://" not in call_args["html"]

    async def test_client_macos_sends_app_link_with_web_fallback(self):
        """When client='macos', email has app URL and web fallback."""
        mock_settings = _mock_settings()

        with patch("app.core.email.get_settings", return_value=mock_settings), \
             patch("app.core.email.resend") as mock_resend:
            from app.core.email import send_magic_link_email

            await send_magic_link_email("user@example.com", "token456", client="macos")

            call_args = mock_resend.Emails.send.call_args[0][0]
            assert "waisay://auth/verify?token=token456" in call_args["html"]
            assert "https://say.waiwai.is/auth/verify?token=token456" in call_args["html"]

    async def test_client_android_sends_app_link_with_web_fallback(self):
        """When client='android', email has app URL and web fallback."""
        mock_settings = _mock_settings()

        with patch("app.core.email.get_settings", return_value=mock_settings), \
             patch("app.core.email.resend") as mock_resend:
            from app.core.email import send_magic_link_email

            await send_magic_link_email("user@example.com", "token789", client="android")

            call_args = mock_resend.Emails.send.call_args[0][0]
            assert "waisay://magic?token=token789" in call_args["html"]
            assert "https://say.waiwai.is/auth/verify?token=token789" in call_args["html"]

    async def test_unknown_client_sends_web_link_only(self):
        """When client is an unknown value, email contains only the web URL."""
        mock_settings = _mock_settings()

        with patch("app.core.email.get_settings", return_value=mock_settings), \
             patch("app.core.email.resend") as mock_resend:
            from app.core.email import send_magic_link_email

            await send_magic_link_email("user@example.com", "token789", client="unknown")

            call_args = mock_resend.Emails.send.call_args[0][0]
            assert "https://say.waiwai.is/auth/verify?token=token789" in call_args["html"]
            assert "waisay://" not in call_args["html"]
