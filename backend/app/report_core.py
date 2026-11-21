"""周报核心：按真实时间范围统计（本周新增 / 本期解决 / 当前未关闭）。

和「列表前 100 条」的区别：
- 列表前 100 条既不看时间也不看状态，三个月前已解决的问题会混进本周周报里
- 周报要回答的是「这周发生了什么」

纯逻辑层，HTTP 与 MCP 共用。days=0 是本周（周一至今），days=N 是最近 N 天。
"""
from datetime import datetime, timedelta

from .access import owner_filter
from .config import STATUS_FINAL
from .db import connect, list_rows

# 未关闭 = 不在终态里。用 NOT IN 而不是列一遍中间态，以后加状态不用改这里
_OPEN_EXCLUDE = tuple(STATUS_FINAL)

_COLS = ("id, title, status, priority, severity, complexity, module, "
         "reporter, assignee, due_date, created_at, updated_at")


def _range(days: int) -> tuple[str, str, str]:
    end = datetime.now()
    if days > 0:
        start = end - timedelta(days=days)
        label = f"最近 {days} 天（{start:%m-%d} ~ {end:%m-%d}）"
    else:
        start = (end - timedelta(days=end.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0)
        label = f"本周（{start:%m-%d} ~ {end:%m-%d}）"
    fmt = "%Y-%m-%d %H:%M:%S"
    return start.strftime(fmt), end.strftime(fmt), label


def _fmt_issue(row: dict) -> str:
    bits = [f"#{row['id']} {row['title']}", f"[{row['status']}]"]
    if row.get("severity"):
        bits.append(row["severity"])
    bits.append(row.get("module") or "-")
    if row.get("assignee"):
        bits.append(f"@{row['assignee']}")
    if row.get("due_date"):
        bits.append(f"截止 {row['due_date'][:10]}")
    return "　".join(bits)


def build_weekly(user: dict | None, days: int = 0) -> dict:
    start, end, label = _range(days)
    owner_sql, owner_args = owner_filter(user)

    def scope(extra: str = "", extra_args: list | None = None):
        parts, args = [], []
        if owner_sql:
            parts.append(owner_sql)
            args += owner_args
        if extra:
            parts.append(extra)
            args += (extra_args or [])
        return (" WHERE " + " AND ".join(parts)) if parts else "", args

    marks = ",".join("?" * len(_OPEN_EXCLUDE))

    with connect() as conn:
        w, a = scope("created_at >= ? AND created_at <= ?", [start, end])
        created = list_rows(conn.execute(
            f"SELECT {_COLS} FROM issue{w} ORDER BY id DESC", a).fetchall())

        # 「本期解决」按 updated_at 判：终态是最后一步，改到终态的时间就是解决时间
        w, a = scope(f"status IN ({marks}) AND updated_at >= ? AND updated_at <= ?",
                     [*_OPEN_EXCLUDE, start, end])
        resolved = list_rows(conn.execute(
            f"SELECT {_COLS} FROM issue{w} ORDER BY updated_at DESC", a).fetchall())

        w, a = scope(f"status NOT IN ({marks})", list(_OPEN_EXCLUDE))
        open_rows = list_rows(conn.execute(
            f"SELECT {_COLS} FROM issue{w} "
            "ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 "
            "WHEN 'P3' THEN 3 ELSE 4 END, id DESC", a).fetchall())

    return {"label": label, "start": start, "end": end,
            "created": created, "resolved": resolved, "open": open_rows}


def render_weekly(user: dict | None, days: int = 0) -> str:
    d = build_weekly(user, days)
    created, resolved, open_rows = d["created"], d["resolved"], d["open"]

    # days=0 是「本周」，其他是「最近 N 天」，措辞跟着变，否则 30 天的报告也写「本周」
    span = "本周" if days == 0 else "本期"
    lines = [f"# 问题跟踪周报 · {d['label']}", ""]
    lines.append(f"**{span}新增 {len(created)}　{span}解决 {len(resolved)}　"
                 f"当前未关闭 {len(open_rows)}**")
    lines.append("")

    if created:
        lines.append(f"## 一、{span}新增（{len(created)}）")
        lines += [f"- {_fmt_issue(r)}" for r in created]
        lines.append("")

    if resolved:
        lines.append(f"## 二、{span}解决（{len(resolved)}）")
        lines += [f"- {_fmt_issue(r)}" for r in resolved]
        lines.append("")

    if open_rows:
        lines.append(f"## 三、当前未关闭（{len(open_rows)}）")
        groups: dict[str, list[dict]] = {}
        for row in open_rows:
            groups.setdefault(row.get("priority") or "未定级", []).append(row)
        for key in ("P0", "P1", "P2", "P3", "未定级"):
            items = groups.get(key) or []
            if not items:
                continue
            lines.append(f"### {key}（{len(items)}）")
            lines += [f"- {_fmt_issue(r)}" for r in items]
            lines.append("")

    if not (created or resolved or open_rows):
        lines += [f"{span}没有问题变动。", ""]

    return "\n".join(lines)
