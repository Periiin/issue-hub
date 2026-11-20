"""周报导出：按优先级分组，直接粘给甲方或贴群里。"""
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from ..access import owner_filter
from ..db import connect, list_rows
from .auth import require_user

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("/weekly", response_class=PlainTextResponse)
def weekly(user: dict = Depends(require_user)):
    """周报。普通用户只看自己的（否则等于绕过列表权限看全部问题）。"""
    where, args = owner_filter(user)
    sql = ("SELECT id, title, status, priority, severity, module, created_at FROM issue")
    if where:
        sql += " WHERE " + where
    sql += " ORDER BY id DESC LIMIT 100"
    with connect() as conn:
        rows = list_rows(conn.execute(sql, args).fetchall())
    lines = ["# 问题跟踪周报", ""]
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["priority"] or "未定级", []).append(row)
    for key in ("P0", "P1", "P2", "P3", "未定级"):
        items = groups.get(key) or []
        if not items:
            continue
        lines.append(f"## {key}（{len(items)}）")
        for row in items:
            lines.append(f"- #{row['id']} {row['title']}　[{row['status']}]"
                         f"　{row['module'] or '-'}　{row['created_at'][:10]}")
        lines.append("")
    return "\n".join(lines)
