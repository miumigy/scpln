import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from app import metrics as app_metrics

# 詳細なログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

from app.ui_plans import router as ui_plans_router  # noqa: E402
from app.ui_configs import router as ui_configs_router  # Import ui_configs router
from app import simulation_api as _simulation_api
from app import run_compare_api as _run_compare_api
from app import run_list_api as _run_list_api
from app import trace_export_api as _trace_export_api
from app import ui_runs as _ui_runs
from app import ui_compare as _ui_compare
from app import jobs_api as _jobs_api
from app import ui_jobs as _ui_jobs
from app import config_api as _config_api
from app import scenario_api as _scenario_api
from app import ui_scenarios as _ui_scenarios
from app import ui_planning as _ui_planning
from app import plans_api as _plans_api
from app import ui_plans
from app import runs_api as _runs_api

app.include_router(ui_plans_router, prefix="/ui")
app.include_router(ui_configs_router, prefix="/ui")  # Include ui_configs router
app.include_router(_simulation_api.router)
app.include_router(_run_compare_api.router)
app.include_router(_run_list_api.router)
app.include_router(_trace_export_api.router)
app.include_router(_ui_runs.router)
app.include_router(_ui_compare.router)
app.include_router(_jobs_api.router)
app.include_router(_ui_jobs.router)
app.include_router(_config_api.router)
app.include_router(_scenario_api.router)
app.include_router(_ui_scenarios.router)
app.include_router(_ui_planning.router)
app.include_router(_plans_api.router)
app.include_router(ui_plans.router)
app.include_router(_runs_api.router)

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


@app.get("/metrics")
def metrics():
    return app_metrics.metrics_snapshot()


# ルートパス（/ui/plansへのリダイレクト）
@app.get("/")
async def root():
    return RedirectResponse(url="/ui/plans", status_code=301)
