import logging
import os
import json
import contextvars
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.security import APIKeyHeader, HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.exception_handlers import http_exception_handler as _default_http_exc_handler
from starlette.requests import Request as StarletteRequest
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from starlette.middleware.base import BaseHTTPMiddleware
import uuid
import time

from domain.models import SimulationInput


_log_level = os.getenv("SIM_LOG_LEVEL", "INFO").upper()
_log_to_file = os.getenv("SIM_LOG_TO_FILE", "0") == "1"
_log_json = os.getenv("SIM_LOG_JSON", "0") == "1"


# request_id を文脈に保持し、ログへ注入する
REQUEST_ID_VAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        rid = REQUEST_ID_VAR.get()
        # 既に extra で与えられていない場合のみ設定
        if not hasattr(record, "request_id"):
            record.request_id = rid
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        payload = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        # 代表的な拡張属性（存在すれば追加）
        for k in ("request_id", "run_id", "event", "path", "method", "status"):
            v = getattr(record, k, None)
            if v is not None:
                payload[k] = v
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, _log_level, logging.INFO))
    # 既存のハンドラをクリア（uvicorn などの設定と重複しないように）
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = JsonFormatter() if _log_json else logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(message)s [request_id=%(request_id)s]",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    stream_h = logging.StreamHandler()
    stream_h.setFormatter(fmt)
    stream_h.addFilter(RequestIdFilter())
    root.addHandler(stream_h)
    if _log_to_file:
        file_h = logging.FileHandler("simulation.log")
        file_h.setFormatter(fmt)
        file_h.addFilter(RequestIdFilter())
        root.addHandler(file_h)


_configure_logging()

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parents[1]
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Cache last summary for GET /summary
_LAST_SUMMARY = None


def set_last_summary(summary):
    global _LAST_SUMMARY
    _LAST_SUMMARY = summary


def reset_last_summary():
    global _LAST_SUMMARY
    _LAST_SUMMARY = None


def validate_input(input_data: SimulationInput) -> None:
    # Node name uniqueness
    names = [n.name for n in input_data.nodes]
    if len(names) != len(set(names)):
        dup = [x for x in names if names.count(x) > 1]
        raise HTTPException(
            status_code=422, detail=f"Duplicate node names: {sorted(set(dup))}"
        )
    name_set = set(names)
    # Network links referential integrity and duplicate detection
    seen = set()
    for l in input_data.network:
        if l.from_node not in name_set or l.to_node not in name_set:
            raise HTTPException(
                status_code=422,
                detail=f"Network link refers unknown node: {l.from_node}->{l.to_node}",
            )
        key = (l.from_node, l.to_node)
        if key in seen:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate network link: {l.from_node}->{l.to_node}",
            )
        seen.add(key)


# 認証トグル（AUTH_MODE=none|apikey|basic）
_AUTH_MODE = os.getenv("AUTH_MODE", "none").lower()
_APIKEY_NAME = os.getenv("API_KEY_HEADER", "X-API-Key")
_APIKEY_VALUE = os.getenv("API_KEY_VALUE", "")
_BASIC_USER = os.getenv("BASIC_USER", "")
_BASIC_PASS = os.getenv("BASIC_PASS", "")
_api_key_header = APIKeyHeader(name=_APIKEY_NAME, auto_error=False)
_basic = HTTPBasic(auto_error=False)


async def _require_auth(api_key: str | None = Depends(_api_key_header), creds: HTTPBasicCredentials | None = Depends(_basic)):
    if _AUTH_MODE in ("", "none"):
        return
    # bypass for health/static
    # 判定はルータ側で行うのが正確だが簡易に全体適用
    if _AUTH_MODE == "apikey":
        if _APIKEY_VALUE and api_key == _APIKEY_VALUE:
            return
        raise HTTPException(status_code=401, detail="invalid api key")
    if _AUTH_MODE == "basic":
        if creds and _BASIC_USER and _BASIC_PASS and creds.username == _BASIC_USER and creds.password == _BASIC_PASS:
            return
        raise HTTPException(status_code=401, detail="invalid basic auth")
    raise HTTPException(status_code=401, detail="unauthorized")


from app.metrics import observe_http
from app.jobs import JOB_MANAGER
import base64


class _RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = rid
        token = REQUEST_ID_VAR.set(rid)
        started = time.monotonic()
        # リクエスト開始ログ
        logging.info(
            "http_request_start",
            extra={
                "event": "http_request_start",
                "method": request.method,
                "path": request.url.path,
                "request_id": rid,
            },
        )
        try:
            response = await call_next(request)
        except Exception as e:  # ここに来るのは未ハンドル例外
            logging.error(
                "http_exception",
                extra={
                    "event": "http_exception",
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                    "request_id": rid,
                },
            )
            try:
                observe_http(request, 500, started)
            finally:
                REQUEST_ID_VAR.reset(token)
            return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
        response.headers["X-Request-ID"] = rid
        # リクエスト完了ログ
        logging.info(
            "http_request",
            extra={
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "request_id": rid,
            },
        )
        try:
            observe_http(request, response.status_code, started)
        finally:
            REQUEST_ID_VAR.reset(token)
        return response


@app.exception_handler(HTTPException)
async def _http_exc_logger(request: StarletteRequest, exc: HTTPException):
    rid = getattr(getattr(request, "state", object()), "request_id", REQUEST_ID_VAR.get())
    logging.warning(
        "http_error",
        extra={
            "event": "http_error",
            "method": request.method,
            "path": request.url.path,
            "status": exc.status_code,
            "request_id": rid,
        },
    )
    return await _default_http_exc_handler(request, exc)


app.add_middleware(_RequestIDMiddleware)
 
# 簡易認証ミドルウェア
class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _AUTH_MODE in ("", "none"):
            return await call_next(request)
        # Allow static and health endpoints without auth
        path = request.url.path or ""
        if (
            path.startswith("/static/")
            or path.startswith("/ui/")
            or path in ("/healthz", "/", "/index.html", "/__debug/index", "/openapi.json")
            or path.startswith("/docs")
        ):
            return await call_next(request)
        try:
            if _AUTH_MODE == "apikey":
                key = request.headers.get(_APIKEY_NAME)
                if _APIKEY_VALUE and key == _APIKEY_VALUE:
                    return await call_next(request)
                return JSONResponse(status_code=401, content={"detail": "invalid api key"})
            if _AUTH_MODE == "basic":
                auth = request.headers.get("Authorization", "")
                if auth.lower().startswith("basic "):
                    try:
                        raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
                        user, pwd = raw.split(":", 1)
                        if user == _BASIC_USER and pwd == _BASIC_PASS and user and pwd:
                            return await call_next(request)
                    except Exception:
                        pass
                return JSONResponse(status_code=401, content={"detail": "invalid basic auth"})
        except Exception:
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})


app.add_middleware(_AuthMiddleware)

# OpenTelemetry (任意) 簡易計装
_OTEL_ENABLED = os.getenv("OTEL_ENABLED", "0") == "1"
if _OTEL_ENABLED:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        resource = Resource(attributes={SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "scpln")})
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")  # e.g., http://localhost:4318
        exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        FastAPIInstrumentor().instrument_app(app)
    except Exception:
        pass


@app.get("/", response_class=HTMLResponse)
async def read_index():
    idx = BASE_DIR / "index.html"
    try:
        logging.info("index_resolve", extra={"event": "index_resolve", "path": str(idx), "exists": idx.exists()})
    except Exception:
        pass
    if idx.exists():
        try:
            return FileResponse(path=str(idx), media_type="text/html; charset=utf-8")
        except Exception:
            logging.exception("failed_to_read_index")
    # fallback to CWD
    cwd_idx = Path.cwd() / "index.html"
    if cwd_idx.exists():
        try:
            logging.info("index_resolve_cwd", extra={"event": "index_resolve_cwd", "path": str(cwd_idx), "exists": True})
            return FileResponse(path=str(cwd_idx), media_type="text/html; charset=utf-8")
        except Exception:
            logging.exception("failed_to_read_index_cwd")
    return HTMLResponse("<h1>Error</h1><p>index.html not found.</p>", status_code=404)

@app.get("/index.html", response_class=HTMLResponse)
async def read_index_alias():
    idx = BASE_DIR / "index.html"
    if idx.exists():
        try:
            return FileResponse(path=str(idx), media_type="text/html; charset=utf-8")
        except Exception:
            logging.exception("failed_to_read_index_alias")
    cwd_idx = Path.cwd() / "index.html"
    if cwd_idx.exists():
        try:
            logging.info("index_resolve_cwd_alias", extra={"event": "index_resolve_cwd_alias", "path": str(cwd_idx), "exists": True})
            return FileResponse(path=str(cwd_idx), media_type="text/html; charset=utf-8")
        except Exception:
            logging.exception("failed_to_read_index_cwd_alias")
    return HTMLResponse("<h1>Error</h1><p>index.html not found.</p>", status_code=404)


if os.getenv("ENABLE_DEBUG_ENDPOINTS", "0") == "1":
    @app.get("/__debug/index")
    async def debug_index_path():
        base_dir = Path(__file__).resolve().parents[1]
        idx = base_dir / "index.html"
        cwd_idx = Path.cwd() / "index.html"
        return {
            "base_dir": str(base_dir),
            "resolved": str(idx),
            "resolved_exists": idx.exists(),
            "cwd": str(Path.cwd()),
            "cwd_resolved": str(cwd_idx),
            "cwd_exists": cwd_idx.exists(),
        }


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/summary")
async def get_summary():
    if _LAST_SUMMARY is None:
        raise HTTPException(
            status_code=404, detail="No summary available yet. Run a simulation first."
        )
    return _LAST_SUMMARY


@app.on_event("startup")
async def _start_jobs():
    try:
        JOB_MANAGER.start()
    except Exception:
        logging.exception("failed to start JobManager")


@app.on_event("shutdown")
async def _stop_jobs():
    try:
        JOB_MANAGER.stop()
    except Exception:
        logging.exception("failed to stop JobManager")
