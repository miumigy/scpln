import logging
import os
import json
import contextvars
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exception_handlers import http_exception_handler as _default_http_exc_handler
from starlette.requests import Request as StarletteRequest
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
import uuid

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
app.mount("/static", StaticFiles(directory="static"), name="static")

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


class _RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = rid
        token = REQUEST_ID_VAR.set(rid)
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


@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>Error</h1><p>index.html not found.</p>", status_code=404
        )


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
