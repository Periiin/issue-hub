"""数据归属校验：一处定义，所有路由共用。

**为什么单独成模块**：这套逻辑原来散在 `routers/issues.py` 里，`ai.py` 和
`fix.py` 各自又写了一份 `SELECT * FROM issue WHERE id=?` 的简化版，结果就是
「CRUD 有校验、AI 和改代码没有」——普通用户能改写别人的问题定性、能读别人的
代码路径、能驳回别人的改动。同一个东西写三遍必然漏两遍。

所以这里只留一份，新加接口一律 import 它，不要再手写查询。
"""
from fastapi import HTTPException

from .db import connect


def owner_filter(user: dict | None, column: str = "owner_id") -> tuple[str, list]:
    """按用户过滤的 SQL 片段 + 参数。

    admin 看全部；普通用户看自己的 + 历史遗留（owner_id 为空）。
    owner_id 为空是加鉴权之前录的数据，不该让它们凭空消失。

    返回 (sql, args)；sql 为空串表示不限制。
    """
    if not user or user.get("role") == "admin":
        return "", []
    return f"({column} = ? OR {column} IS NULL)", [user.get("id") or 0]


def load_issue(conn, issue_id: int, user: dict | None = None) -> dict:
    """读 issue 并校验归属。拿不到或无权都抛 404。

    **无权也返 404 而不是 403**：403 等于告诉对方「这个 id 存在，只是你没权限」，
    配合遍历就能摸清别人的数据规模。404 什么都不泄露。
    """
    row = conn.execute("SELECT * FROM issue WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "问题不存在")
    issue = dict(row)
    if user and user.get("role") != "admin":
        owner = issue.get("owner_id")
        if owner is not None and owner != user.get("id"):
            raise HTTPException(404, "问题不存在")
    return issue


def load_issue_by_id(issue_id: int, user: dict | None = None) -> dict:
    """自己开连接的版本，给不在 with connect() 里的地方用。"""
    with connect() as conn:
        return load_issue(conn, issue_id, user)


def require_owner(record: dict | None, user: dict | None, what: str = "记录") -> dict:
    """校验一条已查出来的记录归属（比如 project / channel / attempt）。"""
    if record is None:
        raise HTTPException(404, f"{what}不存在")
    if not user or user.get("role") == "admin":
        return record
    owner = record.get("owner_id")
    if owner is not None and owner != user.get("id"):
        raise HTTPException(404, f"{what}不存在")
    return record
