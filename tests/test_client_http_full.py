"""Broader StepikClient coverage via respx."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from mcp_stepik.client import StepikClient, StepikError


@pytest.fixture
def client() -> StepikClient:
    c = StepikClient(client_id="id", client_secret="secret", api_host="https://stepik.test")
    yield c
    c.close()


def _auth(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("https://stepik.test/oauth2/token/").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    )


@respx.mock
def test_crud_surface(client: StepikClient) -> None:
    _auth(respx)
    respx.get("https://stepik.test/api/courses").mock(
        return_value=httpx.Response(200, json={"courses": [{"id": 1, "title": "A"}], "meta": {}})
    )
    respx.get("https://stepik.test/api/courses/1").mock(
        return_value=httpx.Response(200, json={"courses": [{"id": 1, "title": "A"}]})
    )
    respx.put("https://stepik.test/api/courses/1").mock(
        return_value=httpx.Response(
            200, json={"courses": [{"id": 1, "title": "B", "is_enabled": True}]}
        )
    )
    respx.get("https://stepik.test/api/sections").mock(
        return_value=httpx.Response(200, json={"sections": [{"id": 2, "title": "S"}]})
    )
    respx.post("https://stepik.test/api/sections").mock(
        return_value=httpx.Response(200, json={"sections": [{"id": 2, "title": "S"}]})
    )
    respx.put("https://stepik.test/api/sections/2").mock(
        return_value=httpx.Response(200, json={"sections": [{"id": 2, "title": "S2"}]})
    )
    respx.delete("https://stepik.test/api/sections/2").mock(return_value=httpx.Response(204))
    respx.get("https://stepik.test/api/lessons/3").mock(
        return_value=httpx.Response(200, json={"lessons": [{"id": 3, "title": "L"}]})
    )
    respx.post("https://stepik.test/api/lessons").mock(
        return_value=httpx.Response(200, json={"lessons": [{"id": 3, "title": "L"}]})
    )
    respx.put("https://stepik.test/api/lessons/3").mock(
        return_value=httpx.Response(200, json={"lessons": [{"id": 3, "title": "L2"}]})
    )
    respx.delete("https://stepik.test/api/lessons/3").mock(return_value=httpx.Response(204))
    respx.post("https://stepik.test/api/units").mock(
        return_value=httpx.Response(
            200, json={"units": [{"id": 4, "section": 2, "lesson": 3}]}
        )
    )
    respx.get("https://stepik.test/api/sections/2").mock(
        return_value=httpx.Response(200, json={"sections": [{"id": 2, "units": [4]}]})
    )
    respx.get("https://stepik.test/api/units").mock(
        return_value=httpx.Response(200, json={"units": [{"id": 4, "lesson": 3}]})
    )
    respx.delete("https://stepik.test/api/units/4").mock(return_value=httpx.Response(204))
    respx.get("https://stepik.test/api/steps").mock(
        return_value=httpx.Response(
            200, json={"steps": [{"id": 5, "block": {"name": "text"}}]}
        )
    )
    respx.post("https://stepik.test/api/step-sources").mock(
        return_value=httpx.Response(200, json={"step-sources": [{"id": 5}]})
    )
    respx.put("https://stepik.test/api/step-sources/5").mock(
        return_value=httpx.Response(200, json={"step-sources": [{"id": 5}]})
    )
    respx.delete("https://stepik.test/api/step-sources/5").mock(return_value=httpx.Response(204))
    respx.get("https://stepik.test/api/videos/9").mock(
        return_value=httpx.Response(
            200, json={"videos": [{"id": 9, "status": "ready"}]}
        )
    )

    assert client.list_my_courses()["courses"][0]["id"] == 1
    assert client.get_course(1)["id"] == 1
    assert client.update_course(1, title="B")["title"] == "B"
    assert client.publish_course(1)["is_enabled"] is True
    # list_sections uses course.sections + ids[]; stub course already returned sections=[]
    assert client.list_sections(1) == []
    assert client.create_section(1, "S")["id"] == 2
    assert client.update_section(2, title="S2")["title"] == "S2"
    client.delete_section(2)
    assert client.get_lesson(3)["id"] == 3
    assert client.create_lesson("L")["id"] == 3
    assert client.update_lesson(3, title="L2")["title"] == "L2"
    client.delete_lesson(3)
    assert client.create_unit(2, 3)["id"] == 4
    assert client.list_units(2)
    client.delete_unit(4)
    assert client.list_steps(3)
    assert client.create_step_source({"lesson": 3, "position": 1, "block": {"name": "text"}})["id"] == 5
    assert client.update_step_source(5, {"block": {"name": "text", "text": "x"}})["id"] == 5
    client.delete_step(5)
    assert client.get_video(9)["status"] == "ready"
    assert client.health()["ok"] is True


@respx.mock
def test_upload_video(client: StepikClient, tmp_path: Path) -> None:
    _auth(respx)
    respx.post("https://stepik.test/api/videos").mock(
        return_value=httpx.Response(
            200, json={"videos": [{"id": 11, "status": "ready"}]}
        )
    )
    f = tmp_path / "a.mp4"
    f.write_bytes(b"00")
    v = client.upload_video(f, lesson_id=1, course_id=2)
    assert v["id"] == 11


@respx.mock
def test_missing_objects(client: StepikClient) -> None:
    _auth(respx)
    respx.get("https://stepik.test/api/courses/404").mock(
        return_value=httpx.Response(200, json={"courses": []})
    )
    with pytest.raises(StepikError):
        client.get_course(404)
