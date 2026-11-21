"""甲方只读分享：带 token 的只读视图。

**模型**：token 即凭证。生成时 `secrets.token_urlsafe(32)`，不可枚举；
可撤销（revoked=1）、可过期（expires_at）。甲方不用登录、不用装任何东西。

**给甲方看什么**（这是产品判断，不是技术限制）：
- 给：标题、状态、优先级/等级、模块、提出人、时间线、原文（甲方自己写的）、
  确认后的现象与复现步骤（内部整理过的描述给甲方看反而专业）
- 不给：评论（内部讨论）、修复方案与代码范围（代码细节）、负责人、
  AI 运行记录、其他任何问题（token 只绑一个问题）

**为什么 share 接口绕过 IP 白名单**：甲方的核心场景就是「人在外网看进度」，
开了 IP 白名单就等于没做这个功能。放权是有意的、收窄的：一个 token 只读
一个问题，可撤销，仍受限流（按 IP）。挂 nginx 后记得把 `auth.trusted_proxies`
配好，否则限流的 IP 维度会全是 nginx 的 IP。
"""
import secrets
from datetime import datetime, timedelta

from .access import load_issue
from .db import connect, list_rows, now

SHARE_DAYS = 30  # 默认有效期；过期后链接自动失效，避免甲方半年后点开看到过期状态


def create_token(user: dict, issue_id: int, days: int = SHARE_DAYS) -> dict:
    """为问题生成（或重新生成）分享 token。

    同一问题重复生成会给新 token、旧 token 保留但不再展示——
    简单且不破坏已经发出去的链接（想作废走撤销）。
    """
    from .access import AccessDenied
    try:
        with connect() as conn:
            load_issue(conn, issue_id, user)
    except AccessDenied:
        raise
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=max(1, min(days or SHARE_DAYS, 365)))
               ).strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        conn.execute(
            "INSERT INTO share_token(token, issue_id, created_by, created_at, expires_at, revoked) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (token, issue_id, (user or {}).get("id") or None, now(), expires))
    return {"token": token, "expiresAt": expires}


def get_token_info(user: dict, issue_id: int) -> dict:
    """查问题的当前分享状态（详情页弹窗用）。只返回最新的未撤销 token。"""
    from .access import AccessDenied
    with connect() as conn:
        load_issue(conn, issue_id, user)
        row = conn.execute(
            "SELECT token, expires_at, created_at FROM share_token "
            "WHERE issue_id = ? AND revoked = 0 ORDER BY id DESC LIMIT 1",
            (issue_id,)).fetchone()
    if not row:
        return {"token": None}
    return {"token": row["token"], "expiresAt": row["expires_at"],
            "createdAt": row["created_at"]}


def revoke_token(user: dict, issue_id: int, token: str | None = None) -> dict:
    """撤销分享。token 传空撤销该问题全部（「不让甲方再看了」）。"""
    from .access import AccessDenied
    with connect() as conn:
        load_issue(conn, issue_id, user)
        if token:
            conn.execute("UPDATE share_token SET revoked = 1 WHERE token = ? AND issue_id = ?",
                         (token, issue_id))
        else:
            conn.execute("UPDATE share_token SET revoked = 1 WHERE issue_id = ?", (issue_id,))
    return {"ok": True}


def _valid(row: dict, now_str: str) -> bool:
    if row["revoked"]:
        return False
    if row["expires_at"]:
        try:
            if datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S") < datetime.now():
                return False
        except ValueError:
            return False
    return True


def resolve(token: str) -> dict | None:
    """token → 只读视图数据。无效/过期/撤销都返回 None（不区分原因，不泄露）。"""
    token = (token or "").strip()
    if not token or len(token) > 128:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM share_token WHERE token = ?", (token,)).fetchone()
        if not row or not _valid(dict(row), now()):
            return None
        issue_id = row["issue_id"]
        issue = dict(conn.execute(
            "SELECT id, title, status, priority, severity, complexity, module, reporter, "
            "raw_text, qualify_final, created_at, updated_at "
            "FROM issue WHERE id = ?", (issue_id,)).fetchone())
        raw_events = list_rows(conn.execute(
            "SELECT type, from_status, to_status, note, created_at FROM event "
            "WHERE issue_id = ? ORDER BY id DESC LIMIT 50", (issue_id,)).fetchall())
        # 评论的事件摘要会带正文前 60 字——内部讨论不能从这里泄露给甲方，
        # 所以分享视图里整类过滤（甲方只看状态流转）
        events = [e for e in raw_events
                  if not (e["type"] == "note" and (e["note"] or "").startswith("评论："))]
        attachments = list_rows(conn.execute(
            "SELECT id, filename, mime, size FROM attachment WHERE issue_id = ? ORDER BY id",
            (issue_id,)).fetchall())

    import json
    def _parse(raw):
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    final = _parse(issue.get("qualify_final")) or {}
    return {
        "issue": {
            "id": issue["id"], "title": issue["title"], "status": issue["status"],
            "priority": issue.get("priority"), "severity": issue.get("severity"),
            "complexity": issue.get("complexity"), "module": issue.get("module"),
            "reporter": issue.get("reporter"), "createdAt": issue["created_at"],
            "updatedAt": issue["updated_at"],
            "rawText": issue.get("raw_text") or "",
            "phenomenon": final.get("phenomenon") or "",
            "reproSteps": final.get("repro_steps") or [],
            "expected": final.get("expected") or "",
            "actual": final.get("actual") or "",
        },
        "events": events,
        "attachments": attachments,
        "sharedAt": row["created_at"],
    }
