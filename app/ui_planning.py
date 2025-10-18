from fastapi import APIRouter
from fastapi.responses import RedirectResponse

# 旧UI互換。/ui/planning へアクセスされた場合は新UIへリダイレクトする。
router = APIRouter()


@router.get("/ui/planning", include_in_schema=False)
async def redirect_legacy_ui():
    return RedirectResponse(url="/ui/plans", status_code=307)
