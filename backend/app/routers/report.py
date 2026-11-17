"""周报导出：按优先级分组，直接粘给甲方或贴群里。"""
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from ..db import connect, list_rows

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("/weekly", response_class=PlainTextResponse)
def weekly():
    with connect() as conn:
        rows = list_rows(conn.execute(
            "SELECT id, title, status, priority, severity, module, created_at "
            "FROM issue ORDER BY id DESC LIMIT 100").fetchall())
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
