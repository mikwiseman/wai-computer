"""Tests for config helper methods."""

import pytest

from app.config import Settings


@pytest.fixture
def make_settings():
    """Create settings with overrides."""
    def _make(**overrides):
        defaults = {
            "database_url": "postgresql+asyncpg://localhost/test",
            "jwt_secret": "test-secret",
            "frontend_url": "https://app.example.com",
            "cors_origins": ["http://localhost:3000"],
        }
        defaults.update(overrides)
        return Settings(**defaults)
    return _make


class TestAuthCookieDomainResolved:
    """Tests for Settings.auth_cookie_domain_resolved property."""

    def test_explicit_domain_used_when_set(self, make_settings):
        s = make_settings(auth_cookie_domain="custom.example.com")
        assert s.auth_cookie_domain_resolved == "custom.example.com"

    def test_none_for_empty_hostname(self, make_settings):
        s = make_settings(frontend_url="")
        assert s.auth_cookie_domain_resolved is None

    def test_none_for_ip_address(self, make_settings):
        s = make_settings(frontend_url="http://192.168.1.1:3000")
        assert s.auth_cookie_domain_resolved is None

    def test_none_for_localhost(self, make_settings):
        s = make_settings(frontend_url="http://localhost:3000")
        assert s.auth_cookie_domain_resolved is None

    def test_none_for_single_part(self, make_settings):
        s = make_settings(frontend_url="http://intranet")
        assert s.auth_cookie_domain_resolved is None

    def test_two_part_domain(self, make_settings):
        s = make_settings(frontend_url="https://example.com")
        assert s.auth_cookie_domain_resolved == "example.com"

    def test_three_part_domain_collapses(self, make_settings):
        s = make_settings(frontend_url="https://app.example.com")
        assert s.auth_cookie_domain_resolved == "example.com"

    def test_cc_tld_preserved(self, make_settings):
        s = make_settings(frontend_url="https://app.example.co.uk")
        assert s.auth_cookie_domain_resolved == "example.co.uk"
