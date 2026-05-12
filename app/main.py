from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from app.agent.orchestrator import LocalPlannerAgent
from app.domain.models import Coordinates
from app.providers.location_provider import HybridLocationProvider


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"
AGENT = LocalPlannerAgent()
LOCATION_PROVIDER = HybridLocationProvider()


class NearNowHandler(BaseHTTPRequestHandler):
    server_version = "NearNowHTTP/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json({"success": True, "data": {"status": "ok"}, "error": None})
            return
        self._serve_static()

    def do_POST(self) -> None:
        payload = self._read_json()
        if self.path == "/api/agent/plan":
            self._json(AGENT.plan(payload))
            return
        if self.path == "/api/agent/confirm":
            self._json(AGENT.confirm(payload))
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

        address = LOCATION_PROVIDER.reverse_geocode(coordinates)
        return {"success": True, "data": address.to_dict(), "error": None}

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), NearNowHandler)
    print(f"NearNow is running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
