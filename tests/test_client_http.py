"""HTTP-mocked StepikClient tests."""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_stepik.client import StepikClient, StepikError


@pytest.fixture
def client() -> StepikClient:
    return StepikClient(
        client_id="id",
        client_secret="secret",
        api_host="https://stepik.test",
    )


@respx.mock
def test_create_course(client: StepikClient) -> None:
    respx.post("https://stepik.test/oauth2/token/").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    )
    respx.post("https://stepik.test/api/courses").mock(
        return_value=httpx.Response(
            200, json={"courses": [{"id": 7, "title": "Hello", "is_enabled": False}]}
        )
    )
    c = client.create_course("Hello")
    assert c["id"] == 7


@respx.mock
def test_auth_error(client: StepikClient) -> None:
    respx.post("https://stepik.test/oauth2/token/").mock(
        return_value=httpx.Response(401, text="nope")
    )
    with pytest.raises(StepikError):
        client.create_course("X")
