from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent.orchestrator import LocalPlannerAgent
from app.auth import AuthError, AuthService
from app.domain.models import Coordinates
from app.providers.amap_provider import AmapLocationProvider
from app.storage.repository import AppRepository, StorageError, create_repository


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web" / "dist"
SESSION_COOKIE = "nearnow_session"

REPOSITORY = create_repository()
AUTH = AuthService(REPOSITORY)
AGENT = LocalPlannerAgent()
LOCATION_PROVIDER = AmapLocationProvider()

logger = logging.getLogger("nearnow.api")


class CoordinatesPayload(BaseModel):
    lat: float = Field(..., description="纬度")
    lng: float = Field(..., description="经度")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, description="账号")
    password: str = Field(..., min_length=6, description="密码")
    display_name: str | None = Field(default=None, description="展示名称，首次登录注册时使用")


class PlanRequest(BaseModel):
    message: str = Field(default="", description="自然语言活动目标")
    mode: str = Field(default="real", description="规划模式：real / mock")
    user_context: dict[str, Any] = Field(default_factory=dict, description="出发位置、城市、定位精度等上下文")
    participants: list[dict[str, Any]] = Field(default_factory=list, description="直接参与 Planning 的人物画像")
    companions: list[dict[str, Any]] = Field(default_factory=list, description="同行者画像与联系方式")


class ConfirmRequest(BaseModel):
    plan_id: str = Field(..., description="方案 ID")
    confirmed_action_ids: list[str] = Field(default_factory=list, description="用户确认执行的动作 ID")
    selected_route_mode: str | None = Field(default=None, description="用户选择的交通方式")


class ReverseGeocodeRequest(BaseModel):
    coordinates: CoordinatesPayload
    precision: str | None = Field(default=None, description="定位精度：approximate / precise")


class APIError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        recoverable: bool = True,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.recoverable = recoverable


def success_response(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data, "error": None}


def error_response(code: str, message: str, recoverable: bool = True) -> dict[str, Any]:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "recoverable": recoverable},
    }


def json_error(
    status_code: int,
    code: str,
    message: str,
    recoverable: bool = True,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_response(code, message, recoverable),
    )


def configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=os.getenv("NEARNOW_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def cors_origins() -> list[str]:
    raw = os.getenv("NEARNOW_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["http://localhost:3000"]


def cookie_secure() -> bool:
    return os.getenv("NEARNOW_COOKIE_SECURE", "false").lower() == "true"


def create_app() -> FastAPI:
    configure_logging()
    api = FastAPI(
        title="NearNow 邻刻计划 API",
        description="本地短时活动规划与执行 Agent 后端服务。",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    api.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_middleware(api)
    register_exception_handlers(api)
    register_routes(api)
    return api


def register_middleware(api: FastAPI) -> None:
    @api.middleware("http")
    async def access_log_middleware(request: Request, call_next):
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started_at) * 1000
            logger.exception("%s %s failed %.1fms", request.method, request.url.path, duration_ms)
            raise
        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "%s %s %s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


def register_exception_handlers(api: FastAPI) -> None:
    @api.exception_handler(APIError)
    async def api_error_handler(_request: Request, exc: APIError) -> JSONResponse:
        return json_error(exc.status_code, exc.code, exc.message, exc.recoverable)

    @api.exception_handler(AuthError)
    async def auth_error_handler(_request: Request, exc: AuthError) -> JSONResponse:
        return json_error(401, "AUTH_FAILED", str(exc), True)

    @api.exception_handler(StorageError)
    async def storage_error_handler(_request: Request, exc: StorageError) -> JSONResponse:
        logger.exception("storage error")
        return json_error(500, "STORAGE_ERROR", str(exc), True)

    @api.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return json_error(422, "INVALID_REQUEST", f"请求参数不合法：{exc.errors()}", True)

    @api.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        message = "接口不存在" if exc.status_code == 404 else str(exc.detail)
        return json_error(exc.status_code, code, message, True)

    @api.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return json_error(500, "INTERNAL_ERROR", "服务异常，请稍后重试。", True)


def register_routes(api: FastAPI) -> None:
    @api.get("/health", tags=["system"], summary="健康检查")
    def health() -> dict[str, Any]:
        return success_response({"status": "ok"})

    @api.get("/api/auth/me", tags=["auth"], summary="读取当前登录用户")
    def current_user(user: dict[str, Any] | None = Depends(optional_user)) -> dict[str, Any]:
        return success_response({"authenticated": bool(user), "user": user})

    @api.post("/api/auth/login", tags=["auth"], summary="登录或首次注册")
    def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
        result = AUTH.login_or_register(payload.username, payload.password, payload.display_name or "")
        response.set_cookie(
            key=SESSION_COOKIE,
            value=result["token"],
            httponly=True,
            samesite="lax",
            secure=cookie_secure(),
            path="/",
            max_age=7 * 24 * 60 * 60,
        )
        return success_response({"user": result["user"]})

    @api.post("/api/auth/logout", tags=["auth"], summary="退出登录")
    def logout(
        response: Response,
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> dict[str, Any]:
        AUTH.logout(token)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return success_response({"logged_out": True})

    @api.get("/api/companions", tags=["companions"], summary="读取历史同行者")
    def companions(user: dict[str, Any] = Depends(required_user)) -> dict[str, Any]:
        return success_response(REPOSITORY.list_companions(user["user_id"]))

    @api.post("/api/agent/plan", tags=["agent"], summary="生成活动规划")
    def plan(payload: PlanRequest, user: dict[str, Any] = Depends(required_user)) -> dict[str, Any]:
        request_payload = model_dump(payload)
        response = AGENT.plan(request_payload)
        log_business_failure("POST", "/api/agent/plan", response)
        if response.get("success"):
            persist_plan(REPOSITORY, user, request_payload, response["data"])
        return response

    @api.post("/api/agent/confirm", tags=["agent"], summary="确认并执行方案")
    def confirm(payload: ConfirmRequest, user: dict[str, Any] = Depends(required_user)) -> dict[str, Any]:
        request_payload = model_dump(payload)
        response = AGENT.confirm(request_payload)
        log_business_failure("POST", "/api/agent/confirm", response)
        if response.get("success"):
            mark_notifications_ready(REPOSITORY, user, request_payload, response["data"])
        return response

    @api.post("/api/location/reverse-geocode", tags=["location"], summary="逆地理编码")
    def reverse_geocode(payload: ReverseGeocodeRequest) -> dict[str, Any]:
        coordinates = Coordinates(lat=payload.coordinates.lat, lng=payload.coordinates.lng)
        try:
            address = LOCATION_PROVIDER.reverse_geocode(coordinates)
        except RuntimeError:
            raise APIError(
                status_code=502,
                code="REVERSE_GEOCODE_FAILED",
                message="真实地址反查失败，请手动输入城市、区县和商圈/地标。",
                recoverable=True,
            )
        return success_response(address.to_dict())

    @api.api_route("/api/{_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(_path: str) -> JSONResponse:
        return json_error(404, "NOT_FOUND", "接口不存在", True)

    @api.get("/{full_path:path}", include_in_schema=False, response_model=None)
    def serve_frontend(full_path: str):
        return static_response(full_path)


def optional_user(token: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict[str, Any] | None:
    return AUTH.authenticate(token)


def required_user(user: dict[str, Any] | None = Depends(optional_user)) -> dict[str, Any]:
    if not user:
        raise APIError(status_code=401, code="AUTH_REQUIRED", message="请先登录后再生成方案。", recoverable=True)
    return user


def persist_plan(repository: AppRepository, user: dict[str, Any], payload: dict[str, Any], plan: dict[str, Any]) -> None:
    user_id = user["user_id"]
    user_context = payload.get("user_context") or {}
    companions = repository.save_companions(user_id=user_id, companions=payload.get("companions") or [])
    repository.save_user_location(user_id=user_id, location=user_context)
    repository.save_plan(
        user_id=user_id,
        plan_id=plan["plan_id"],
        mode=str(payload.get("mode") or "real"),
        message=str(payload.get("message") or ""),
        user_context=user_context,
        plan=plan,
    )
    repository.save_plan_notification_targets(
        user_id=user_id,
        plan_id=plan["plan_id"],
        companions=companions,
        message=plan.get("final_message") or plan.get("summary") or "",
    )


def mark_notifications_ready(
    repository: AppRepository,
    user: dict[str, Any],
    payload: dict[str, Any],
    result: dict[str, Any],
) -> None:
    repository.mark_plan_notifications_sent(
        user_id=user["user_id"],
        plan_id=str(payload.get("plan_id") or result.get("plan_id") or ""),
        message=str(result.get("final_message") or ""),
    )


def log_business_failure(method: str, path: str, response: dict[str, Any]) -> None:
    if response.get("success") is not False:
        return
    error = response.get("error") if isinstance(response.get("error"), dict) else {}
    logger.warning(
        "%s %s business_failed code=%s recoverable=%s message=%s",
        method,
        path,
        error.get("code") or "UNKNOWN",
        error.get("recoverable"),
        error.get("message") or "",
    )


def static_response(full_path: str) -> FileResponse | JSONResponse:
    if not WEB_ROOT.exists():
        return json_error(404, "STATIC_NOT_BUILT", "前端构建产物不存在，请先运行 npm run build。", True)

    requested = "index.html" if full_path in {"", "/"} else full_path
    target = (WEB_ROOT / requested).resolve()
    web_root = WEB_ROOT.resolve()
    if not str(target).startswith(str(web_root)):
        return json_error(403, "FORBIDDEN", "非法静态资源路径。", False)
    if target.is_dir():
        target = target / "index.html"
    if target.exists() and target.is_file():
        return FileResponse(target)

    index = WEB_ROOT / "index.html"
    if index.exists():
        return FileResponse(index)
    return json_error(404, "NOT_FOUND", "静态资源不存在。", True)


def model_dump(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


app = create_app()


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    print(f"NearNow FastAPI is running at http://{host}:{port}")
    print(f"OpenAPI docs: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
