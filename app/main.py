from __future__ import annotations

import json
import mimetypes
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from app.auth import AuthError, AuthService
from app.agent.orchestrator import LocalPlannerAgent
from app.domain.models import Coordinates
from app.providers.location_provider import OpenStreetMapLocationProvider
from app.storage.repository import StorageError, create_repository


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web" / "dist"
REPOSITORY = create_repository()
AUTH = AuthService(REPOSITORY)
AGENT = LocalPlannerAgent()
LOCATION_PROVIDER = OpenStreetMapLocationProvider()
SESSION_COOKIE = "nearnow_session"


class NearNowHandler(BaseHTTPRequestHandler):
    server_version = "NearNowHTTP/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json({"success": True, "data": {"status": "ok"}, "error": None})
            return
        if self.path == "/api/auth/me":
            user = self._current_user()
            self._json({"success": True, "data": {"authenticated": bool(user), "user": user}, "error": None})
            return
        if self.path == "/api/companions":
            user = self._current_user()
            if not user:
                self._json(self._auth_required(), 401)
                return
            self._json({"success": True, "data": REPOSITORY.list_companions(user["user_id"]), "error": None})
            return
        self._serve_static()

    def do_POST(self) -> None:
        payload = self._read_json()
        if self.path == "/api/auth/login":
            self._json_login(payload)
            return
        if self.path == "/api/auth/logout":
            token = self._session_token()
            AUTH.logout(token)
            self._json(
                {"success": True, "data": {"logged_out": True}, "error": None},
                headers=[self._expired_cookie_header()],
            )
            return
        if self.path == "/api/agent/plan":
            user = self._current_user()
            if not user:
                self._json(self._auth_required(), 401)
                return
            response = AGENT.plan(payload)
            if response.get("success"):
                storage_error = self._persist_plan(user, payload, response["data"])
                if storage_error:
                    self._json(storage_error, 500)
                    return
            self._json(response)
            return
        if self.path == "/api/agent/confirm":
            user = self._current_user()
            if not user:
                self._json(self._auth_required(), 401)
                return
            response = AGENT.confirm(payload)
            if response.get("success"):
                self._mark_notifications_ready(user, payload, response["data"])
            self._json(response)
            return
        if self.path == "/api/location/reverse-geocode":
            self._json(self._reverse_geocode(payload))
            return
        self._json({"success": False, "data": None, "error": {"code": "NOT_FOUND", "message": "接口不存在"}}, 404)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[NearNow] {self.address_string()} - {format % args}")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _serve_static(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path in {"/", ""}:
            target = WEB_ROOT / "index.html"
        else:
            target = (WEB_ROOT / path.lstrip("/")).resolve()
        if not str(target).startswith(str(WEB_ROOT.resolve())) or not target.exists() or not target.is_file():
            self.send_error(404, "Not found")
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reverse_geocode(self, payload: dict) -> dict:
        coordinates_payload = payload.get("coordinates") or {}
        try:
            coordinates = Coordinates(
                lat=float(coordinates_payload["lat"]),
                lng=float(coordinates_payload["lng"]),
            )
        except (KeyError, TypeError, ValueError):
            return {
                "success": False,
                "data": None,
                "error": {
                    "code": "INVALID_COORDINATES",
                    "message": "缺少可用于地址反查的经纬度。",
                    "recoverable": True,
                },
            }

        try:
            address = LOCATION_PROVIDER.reverse_geocode(coordinates)
        except RuntimeError:
            return {
                "success": False,
                "data": None,
                "error": {
                    "code": "REVERSE_GEOCODE_FAILED",
                    "message": "真实地址反查失败，请手动输入城市、区县和商圈/地标。",
                    "recoverable": True,
                },
            }
        return {"success": True, "data": address.to_dict(), "error": None}

    def _json_login(self, payload: dict) -> None:
        try:
            result = AUTH.login_or_register(
                str(payload.get("username", "")),
                str(payload.get("password", "")),
                str(payload.get("display_name", "") or ""),
            )
        except AuthError as exc:
            self._json(
                {
                    "success": False,
                    "data": None,
                    "error": {"code": "AUTH_FAILED", "message": str(exc), "recoverable": True},
                },
                401,
            )
            return
        except StorageError as exc:
            self._json(self._storage_error(exc), 500)
            return

        self._json(
            {"success": True, "data": {"user": result["user"]}, "error": None},
            headers=[self._session_cookie_header(result["token"])],
        )

    def _persist_plan(self, user: dict, payload: dict, plan: dict) -> dict | None:
        try:
            user_id = user["user_id"]
            user_context = payload.get("user_context") or {}
            companions = REPOSITORY.save_companions(user_id=user_id, companions=payload.get("companions") or [])
            REPOSITORY.save_user_location(user_id=user_id, location=user_context)
            REPOSITORY.save_plan(
                user_id=user_id,
                plan_id=plan["plan_id"],
                mode=str(payload.get("mode") or "real"),
                message=str(payload.get("message") or ""),
                user_context=user_context,
                plan=plan,
            )
            REPOSITORY.save_plan_notification_targets(
                user_id=user_id,
                plan_id=plan["plan_id"],
                companions=companions,
                message=plan.get("final_message") or plan.get("summary") or "",
            )
        except StorageError as exc:
            return self._storage_error(exc)
        return None

    def _mark_notifications_ready(self, user: dict, payload: dict, result: dict) -> None:
        try:
            REPOSITORY.mark_plan_notifications_sent(
                user_id=user["user_id"],
                plan_id=str(payload.get("plan_id") or result.get("plan_id") or ""),
                message=str(result.get("final_message") or ""),
            )
        except StorageError:
            return

    def _current_user(self) -> dict | None:
        try:
            return AUTH.authenticate(self._session_token())
        except StorageError:
            return None

    def _session_token(self) -> str | None:
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        cookie = SimpleCookie()
        cookie.load(raw_cookie)
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _session_cookie_header(self, token: str) -> tuple[str, str]:
        return (
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={7 * 24 * 60 * 60}",
        )

    def _expired_cookie_header(self) -> tuple[str, str]:
        return ("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")

    def _auth_required(self) -> dict:
        return {
            "success": False,
            "data": None,
            "error": {"code": "AUTH_REQUIRED", "message": "请先登录后再生成方案。", "recoverable": True},
        }

    def _storage_error(self, error: Exception) -> dict:
        return {
            "success": False,
            "data": None,
            "error": {"code": "STORAGE_ERROR", "message": str(error), "recoverable": True},
        }

    def _json(self, payload: dict, status: int = 200, headers: list[tuple[str, str]] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for key, value in headers or []:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        except BrokenPipeError:
            return


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), NearNowHandler)
    print(f"NearNow is running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
