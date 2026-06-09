"""Integration tests for the FastAPI endpoints (mocks the ADK runner)."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_health():
    from letting_copilot.app import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_properties():
    from letting_copilot.app import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/properties")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 5
    assert data[0]["id"] == "prop_001"
