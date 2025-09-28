from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
import logging
from starlette.middleware.cors import CORSMiddleware

# 詳細なログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    リクエストバリデーションエラーを捕捉し、詳細なリクエスト情報をログに出力する。
    """
    logger.error(f"Validation error for: {request.method} {request.url}")
    logger.error(f"Request Headers: {request.headers}")
    try:
        # multipart/form-data の場合、form()で内容を取得
        form_data = await request.form()
        logger.error(f"Request Form Data: {form_data}")
    except Exception as e:
        logger.error(f"Could not parse form data: {e}")
        try:
            # form()が失敗した場合、body()を試す
            body = await request.body()
            logger.error(f"Request Body: {body.decode(errors='ignore')}")
        except Exception as e_body:
            logger.error(f"Could not read request body: {e_body}")

    # 元々のエラーレスポンスを返す
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


# 静的ファイルのマウント
_BASE_DIR = Path(__file__).resolve().parents[1]
static_path = _BASE_DIR / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.on_event("startup")
async def seed_defaults_if_empty() -> None:
    """Render 無料版などでDBが空のとき、最小のシナリオを投入する。
    既に1件以上ある場合は何もしない（冪等）。
    """
    try:
        from app import db  # 遅延import（起動順の安定化）

        db.init_db()  # DB初期化

        # 1) シナリオのシード
        try:
            scenarios = db.list_scenarios(limit=1)
            if not scenarios:
                sid = db.create_scenario(
                    name="default",
                    parent_id=None,
                    tag="seed",
                    description="auto-seeded for empty DB",
                    locked=False,
                )
                logger.info(f"seed: created default scenario id={sid}")
        except Exception as e:
            logger.warning(f"seed: scenario seed skipped: {e}")

        # 2) 旧configsテーブルは廃止済みのため、追加シードは行わない
    except Exception as e:
        logger.warning(f"seed: startup seeding failed: {e}")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ルートパス（/ui/plansへのリダイレクト）
@app.get("/")
async def root():
    return RedirectResponse(url="/ui/plans", status_code=301)
