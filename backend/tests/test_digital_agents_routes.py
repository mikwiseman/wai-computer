"""Tests for digital agents CRUD routes."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestCreateAgent:
    @patch("app.services.agent.digital_agents.anthropic.AsyncAnthropic")
    async def test_create_agent(self, mock_anthropic, client: AsyncClient, auth_headers: dict):
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = AsyncMock(
            content=[
                AsyncMock(
                    text='{"name": "HN Monitor", "cron": "0 9 * * *", '
                    '"tools": "search_web", "system_prompt": "Check HN for AI news"}'
                )
            ]
        )

        response = await client.post(
            "/api/agents",
            json={"description": "Check HackerNews for AI news every morning"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "HN Monitor"
        assert data["schedule_type"] == "cron"
        assert data["cron_expression"] == "0 9 * * *"
        assert data["status"] == "active"
        assert data["delivery_channel"] == "api"

    async def test_create_agent_requires_auth(self, client: AsyncClient):
        response = await client.post(
            "/api/agents",
            json={"description": "test agent"},
        )
        assert response.status_code == 401

    async def test_create_agent_validates_description(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.post(
            "/api/agents",
            json={"description": "ab"},  # too short
            headers=auth_headers,
        )
        assert response.status_code == 422


class TestListAgents:
    async def test_list_empty(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/agents", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    @patch("app.services.agent.digital_agents.anthropic.AsyncAnthropic")
    async def test_list_with_agents(self, mock_anthropic, client: AsyncClient, auth_headers: dict):
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = AsyncMock(
            content=[
                AsyncMock(
                    text='{"name": "Agent 1", "cron": "manual", '
                    '"tools": "", "system_prompt": "test"}'
                )
            ]
        )
        await client.post(
            "/api/agents",
            json={"description": "a test agent for monitoring things"},
            headers=auth_headers,
        )
        response = await client.get("/api/agents", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()) == 1


class TestDeleteAgent:
    @patch("app.services.agent.digital_agents.anthropic.AsyncAnthropic")
    async def test_delete_agent(self, mock_anthropic, client: AsyncClient, auth_headers: dict):
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = AsyncMock(
            content=[
                AsyncMock(
                    text='{"name": "Temp", "cron": "manual", "tools": "", "system_prompt": "x"}'
                )
            ]
        )
        create_resp = await client.post(
            "/api/agents",
            json={"description": "temporary agent for testing deletion"},
            headers=auth_headers,
        )
        agent_id = create_resp.json()["id"]

        response = await client.delete(f"/api/agents/{agent_id}", headers=auth_headers)
        assert response.status_code == 204

        list_resp = await client.get("/api/agents", headers=auth_headers)
        agents = list_resp.json()
        # Should be empty or status=deleted (not shown in list)
        active = [a for a in agents if a["status"] != "deleted"]
        assert len(active) == 0

    async def test_delete_nonexistent(self, client: AsyncClient, auth_headers: dict):
        response = await client.delete(
            "/api/agents/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404
