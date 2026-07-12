"""Stepik REST API client (OAuth2 client_credentials)."""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import httpx

from mcp_stepik.settings import STEPIK_API_HOST, STEPIK_CLIENT_ID, STEPIK_CLIENT_SECRET


class StepikError(RuntimeError):
    """HTTP / auth failure talking to Stepik."""


class StepikClient:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_host: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.client_id = client_id or STEPIK_CLIENT_ID
        self.client_secret = client_secret or STEPIK_CLIENT_SECRET
        self.api_host = (api_host or STEPIK_API_HOST).rstrip("/")
        self._timeout = timeout
        self._token: str | None = None
        self._expires: float = 0.0
        self._http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def _get_token(self) -> str:
        if self._token and time.time() < self._expires:
            return self._token
        if not self.client_id or not self.client_secret:
            raise StepikError("STEPIK_CLIENT_ID and STEPIK_CLIENT_SECRET are required")
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = self._http.post(
            f"{self.api_host}/oauth2/token/",
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if resp.status_code >= 400:
            raise StepikError(f"auth failed HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise StepikError(f"auth failed: {data}")
        self._token = token
        self._expires = time.time() + int(data.get("expires_in", 3600)) - 60
        return token

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        token = self._get_token()
        url = f"{self.api_host}/api/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token}"}
        if files is None and json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self._http.request(
            method,
            url,
            json=json_body if files is None else None,
            params=params,
            files=files,
            data=data if files is not None else (None if json_body is not None else data),
            headers=headers,
        )
        if resp.status_code >= 400:
            raise StepikError(f"HTTP {resp.status_code} {method} {url}: {resp.text}")
        if not resp.content:
            return {}
        return resp.json()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    # --- courses ---
    def list_my_courses(self, page: int = 1) -> Any:
        return self.get("courses", params={"is_my_own": "true", "page": page})

    def get_course(self, course_id: int) -> dict[str, Any]:
        rows = self.get(f"courses/{course_id}").get("courses") or []
        if not rows:
            raise StepikError(f"course {course_id} not found")
        return rows[0]

    def create_course(self, title: str, **fields: Any) -> dict[str, Any]:
        body = {"course": {"title": title, "is_enabled": False, **fields}}
        return self.post("courses", json_body=body)["courses"][0]

    def update_course(self, course_id: int, **fields: Any) -> dict[str, Any]:
        # Stepik PUT requires title; merge with current course when omitted.
        if "title" not in fields:
            current = self.get_course(course_id)
            fields = {"title": current["title"], **fields}
        return self.put(f"courses/{course_id}", json_body={"course": fields})["courses"][0]

    def publish_course(self, course_id: int) -> dict[str, Any]:
        return self.update_course(course_id, is_enabled=True)

    def delete_course(self, course_id: int) -> None:
        self.delete(f"courses/{course_id}")

    # --- sections ---
    def list_sections(self, course_id: int) -> list[dict[str, Any]]:
        # Filter ?course= often returns [] for drafts; use course.sections + ids[].
        course = self.get_course(course_id)
        ids = course.get("sections") or []
        if not ids:
            return []
        params: list[tuple[str, Any]] = [("ids[]", i) for i in ids]
        # httpx supports list of tuples
        token = self._get_token()
        url = f"{self.api_host}/api/sections"
        resp = self._http.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code >= 400:
            raise StepikError(f"HTTP {resp.status_code} GET {url}: {resp.text}")
        return resp.json().get("sections") or []

    def create_section(self, course_id: int, title: str, position: int = 1) -> dict[str, Any]:
        body = {"section": {"course": course_id, "title": title, "position": position}}
        return self.post("sections", json_body=body)["sections"][0]

    def update_section(self, section_id: int, **fields: Any) -> dict[str, Any]:
        return self.put(f"sections/{section_id}", json_body={"section": fields})["sections"][0]

    def delete_section(self, section_id: int) -> None:
        self.delete(f"sections/{section_id}")

    # --- lessons / units ---
    def get_lesson(self, lesson_id: int) -> dict[str, Any]:
        rows = self.get(f"lessons/{lesson_id}").get("lessons") or []
        if not rows:
            raise StepikError(f"lesson {lesson_id} not found")
        return rows[0]

    def create_lesson(self, title: str, is_public: bool = False) -> dict[str, Any]:
        title = title[:64]
        body = {"lesson": {"title": title, "is_public": is_public}}
        return self.post("lessons", json_body=body)["lessons"][0]

    def update_lesson(self, lesson_id: int, **fields: Any) -> dict[str, Any]:
        if "title" in fields and isinstance(fields["title"], str):
            fields["title"] = fields["title"][:64]
        return self.put(f"lessons/{lesson_id}", json_body={"lesson": fields})["lessons"][0]

    def delete_lesson(self, lesson_id: int) -> None:
        self.delete(f"lessons/{lesson_id}")

    def create_unit(self, section_id: int, lesson_id: int, position: int = 1) -> dict[str, Any]:
        body = {"unit": {"section": section_id, "lesson": lesson_id, "position": position}}
        return self.post("units", json_body=body)["units"][0]

    def list_units(self, section_id: int) -> list[dict[str, Any]]:
        # GET /units?section=… often 500; prefer section.units + ids[].
        rows = self.get(f"sections/{section_id}").get("sections") or []
        if not rows:
            return []
        ids = rows[0].get("units") or []
        if not ids:
            return []
        token = self._get_token()
        url = f"{self.api_host}/api/units"
        params: list[tuple[str, Any]] = [("ids[]", i) for i in ids]
        resp = self._http.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code >= 400:
            raise StepikError(f"HTTP {resp.status_code} GET {url}: {resp.text}")
        return resp.json().get("units") or []

    def delete_unit(self, unit_id: int) -> None:
        self.delete(f"units/{unit_id}")

    # --- steps ---
    def list_steps(self, lesson_id: int) -> list[dict[str, Any]]:
        return self.get("steps", params={"lesson": lesson_id}).get("steps") or []

    def create_step_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post("step-sources", json_body={"step-source": payload})["step-sources"][0]

    def update_step_source(self, step_source_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.put(
            f"step-sources/{step_source_id}",
            json_body={"step-source": payload},
        )["step-sources"][0]

    def delete_step(self, step_id: int) -> None:
        # DELETE /api/steps/{id} → 405; use step-sources.
        self.delete(f"step-sources/{step_id}")

    # --- videos ---
    def upload_video(
        self,
        file_path: Path,
        *,
        lesson_id: int | None = None,
        course_id: int | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if lesson_id is not None:
            data["lesson"] = str(lesson_id)
        if course_id is not None:
            data["course"] = str(course_id)
        with file_path.open("rb") as fh:
            files = {"source": (file_path.name, fh, "application/octet-stream")}
            result = self.request("POST", "videos", files=files, data=data or None)
        rows = result.get("videos") or []
        if not rows:
            raise StepikError(f"upload returned no video: {result}")
        return rows[0]

    def get_video(self, video_id: int) -> dict[str, Any]:
        rows = self.get(f"videos/{video_id}").get("videos") or []
        if not rows:
            raise StepikError(f"video {video_id} not found")
        return rows[0]

    def health(self) -> dict[str, Any]:
        token = self._get_token()
        return {"ok": True, "token_prefix": token[:8], "api_host": self.api_host}


_client: StepikClient | None = None


def get_client() -> StepikClient:
    global _client
    if _client is None:
        _client = StepikClient()
    return _client
