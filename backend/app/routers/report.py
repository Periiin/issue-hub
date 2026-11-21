"""周报路由：薄壳。统计与渲染在 app/report_core.py（HTTP 与 MCP 共用）。"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from .. import report_core
from .auth import require_user

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("/weekly", response_class=PlainTextResponse)
def weekly(days: int = Query(0, ge=0, le=365),
           user: dict = Depends(require_user)):
    """周报 Markdown。普通用户只看自己的（否则等于绕过列表权限看全部问题）。"""
    return report_core.render_weekly(user, days)
