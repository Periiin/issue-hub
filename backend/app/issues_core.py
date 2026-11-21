"""问题核心逻辑：CRUD / 批量 / 评论 / 关联 / 导出。

**为什么单独一层**：HTTP 路由和 MCP server 需要的是**同一套行为**——
同样的归属校验、同样的字段处理、同样的事件流。原来 MCP 自己手写了一份
SQL，大改 HTTP 之后它悄悄退化（没有分页、没有归属校验、没有新筛选），
还成了绕过权限层的旁路。

规则：**这一层不 import fastapi**。错误用两种异常表达：
- 归属/不存在 → access 层的异常（web 下 HTTPException(404)，MCP 下 AccessDenied）
- 参数/校验错误 → ValueError(message)（路由层转 HTTPException(400)，MCP 直接显示）

路由层只做：pydantic 解析 → 调这里 → 异常转换。
MCP 直接调这里。
"""
import datetime
import json
import shutil
import sqlite3

from .access import load_issue, owner_filter
from .config import ALL_STATUS, ATTACH_DIR, STATUS_FINAL
from .db import add_event, connect, list_rows, now, valid_status

LINK_KINDS = {"duplicate": "重复", "related": "相关", "blocks": "阻塞"}


class PermissionDenied(Exception):
    """有这个资源，但它不是你的（路由层转 403；MCP 直接显示文案）。"""


def _actor(user: dict | None) -> str:
    return (user or {}).get("displayName") or (user or {}).get("username") or "me"


def _json_or_none(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _need(cond: bool, message: str) -> None:
    if not cond:
        raise ValueError(message)


# ---------------- 列表 ----------------

def list_issues(user: dict | None, status: str = "", priority: str = "",
                module: str = "", q: str = "", tag: str = "", assignee: str = "",
                due: str = "", mine: str = "", project_id: int = 0,
                limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))

    where, args = [], []
    owner_sql, owner_args = owner_filter(user)
    if owner_sql:
        where.append(owner_sql)
        args += owner_args
    if status:
        where.append("status = ?")
        args.append(status)
    if priority:
        where.append("priority = ?")
        args.append(priority)
    if module:
        where.append("module LIKE ?")
        args.append(f"%{module}%")
    if tag:
        # tags 是 JSON 数组文本，带引号匹配避免「支付」命中「支付宝」
        where.append("tags LIKE ?")
        args.append(f'%"{tag}"%')
    if assignee:
        where.append("assignee = ?")
        args.append(assignee)
    if due:
        marks = ",".join("?" * len(STATUS_FINAL))
        if due == "overdue":
            where.append(f"due_date IS NOT NULL AND due_date != '' AND due_date < ? "
                         f"AND status NOT IN ({marks})")
            args.append(datetime.date.today().isoformat())
            args += list(STATUS_FINAL)
        elif due == "week":
            today = datetime.date.today()
            where.append("due_date >= ? AND due_date <= ?")
            args += [today.isoformat(), (today + datetime.timedelta(days=7)).isoformat()]
    if project_id:
        # -1 = 未归属；0 = 不筛
        if project_id == -1:
            where.append("project_id IS NULL")
        else:
            where.append("project_id = ?")
            args.append(project_id)
    if mine:
        me_name = (user or {}).get("username") or ""
        if mine == "assigned":
            where.append("assignee = ?")
            args.append(me_name)
        elif mine == "reported":
            where.append("reporter = ?")
            args.append(me_name)
    if q:
        like = f"%{q}%"
        where.append("(title LIKE ? OR raw_text LIKE ? OR module LIKE ? OR reporter LIKE ? "
                     "OR qualify_final LIKE ? OR tags LIKE ?)")
        args += [like] * 6

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    order = (" ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 "
             "WHEN 'P3' THEN 3 ELSE 4 END, id DESC")

    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM issue{clause}", args).fetchone()["c"]
        rows = list_rows(conn.execute(
            f"SELECT * FROM issue{clause}{order} LIMIT ? OFFSET ?",
            [*args, limit, offset]).fetchall())
        count_sql = "SELECT status, COUNT(*) n FROM issue"
        if owner_sql:
            count_sql += " WHERE " + owner_sql
        count_sql += " GROUP BY status"
        counts = {r["status"]: r["n"] for r in conn.execute(count_sql, owner_args).fetchall()}
        project_counts = _project_counts(conn, owner_sql, owner_args)
    return {"list": rows, "counts": counts, "statuses": ALL_STATUS,
            "total": total, "limit": limit, "offset": offset,
            "tags": _all_tags(conn, owner_sql, owner_args),
            "projectCounts": project_counts,
            "unassigned": project_counts.get("none", 0)}


def _project_counts(conn, owner_sql: str, owner_args: list) -> dict:
    """各项目问题数（chips 角标）。故意不受当前筛选影响。"""
    sql = "SELECT project_id, COUNT(*) n FROM issue"
    if owner_sql:
        sql += f" WHERE {owner_sql}"
    sql += " GROUP BY project_id"
    out: dict = {}
    for r in conn.execute(sql, owner_args).fetchall():
        key = r["project_id"] if r["project_id"] is not None else "none"
        out[key] = r["n"]
    return out


def _all_tags(conn, owner_sql: str, owner_args: list) -> list[str]:
    sql = "SELECT tags FROM issue WHERE tags IS NOT NULL AND tags != ''"
    if owner_sql:
        sql += f" AND {owner_sql}"
    seen: list[str] = []
    for row in conn.execute(sql, owner_args).fetchall():
        try:
            for t in json.loads(row["tags"] or "[]"):
                if t and t not in seen:
                    seen.append(t)
        except (json.JSONDecodeError, TypeError):
            continue
    return seen


def guess_project_id(module: str = "", code_scopes: list[str] | None = None) -> int | None:
    """按代码路径或模块名猜项目归属。拿不准返回 None——猜错比不猜更难发现。"""
    from . import projects as proj

    all_projects = proj.list_projects(include_ignored=True)
    if not all_projects:
        return None

    for scope in (code_scopes or []):
        if not scope:
            continue
        for p in all_projects:
            for repo in p.get("repos") or []:
                if scope == repo or scope.startswith(repo.rstrip("/") + "/"):
                    return p["id"]

    name = (module or "").strip().lower()
    if name:
        hits = [p for p in all_projects if p["name"].lower() in name]
        if len(hits) == 1:
            return hits[0]["id"]
    return None


# ---------------- 单条 CRUD ----------------

def create_issue(user: dict | None, title: str = "", raw_text: str = "",
                 source: str = "manual", reporter: str = "", module: str = "",
                 code_scopes: list[str] | None = None,
                 project_id: int | None = None) -> int:
    title = (title or "").strip() or (raw_text or "").strip()[:30] or "未命名问题"
    ts = now()
    pid = project_id or guess_project_id(module, code_scopes)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO issue(title, raw_text, source, reporter, module, status, owner_id, "
            "project_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '待定性', ?, ?, ?, ?)",
            (title, raw_text, source, reporter, module,
             (user or {}).get("id") or None, pid, ts, ts))
        issue_id = cur.lastrowid
        add_event(conn, issue_id, "create", to_status="待定性", note="新建问题",
                  actor=_actor(user))
    # 通知放事务外：webhook 慢不能拖慢创建（notify 内部是 daemon 线程）
    from . import notify
    from . import projects as _proj
    pname = ""
    if pid:
        pname = (_proj.get_project(pid) or {}).get("name") or ""
    try:
        notify.notify_new_issue({"id": issue_id, "title": title, "module": module,
                                 "reporter": reporter}, project_name=pname)
    except Exception:
        pass  # 通知失败绝不影响主流程
    return issue_id


def get_issue(user: dict | None, issue_id: int) -> dict:
    with connect() as conn:
        issue = load_issue(conn, issue_id, user)
        attachments = list_rows(conn.execute(
            "SELECT * FROM attachment WHERE issue_id = ? ORDER BY id", (issue_id,)).fetchall())
        runs = list_rows(conn.execute(
            "SELECT id, kind, provider, model, duration_ms, ok, error, created_at "
            "FROM ai_run WHERE issue_id = ? ORDER BY id DESC LIMIT 20", (issue_id,)).fetchall())
        events = list_rows(conn.execute(
            "SELECT * FROM event WHERE issue_id = ? ORDER BY id DESC", (issue_id,)).fetchall())
    for key in ("qualify_draft", "qualify_final", "triage", "fix_plan",
                "code_scopes", "target_repos", "fix_state"):
        issue[key] = _json_or_none(issue.get(key))
    if not issue.get("target_repos") and issue.get("target_repo"):
        issue["target_repos"] = [issue["target_repo"]]
    from .fix import list_attempts
    project = None
    if issue.get("project_id"):
        from . import projects as proj
        project = proj.get_project(issue["project_id"])
    return {"issue": issue, "project": project, "attachments": attachments, "runs": runs,
            "events": events, "attempts": list_attempts(issue_id)}


# patch 允许改的字段（白名单，防止调用方塞任意列名进 SQL）
PATCH_FIELDS = {"title", "raw_text", "source", "reporter", "module", "status",
                "severity", "complexity", "priority", "assignee", "due_date",
                "code_scopes", "target_repos", "target_repo", "project_id", "tags"}


def patch_issue(user: dict | None, issue_id: int, data: dict) -> dict:
    bad = set(data.keys()) - PATCH_FIELDS
    _need(not bad, f"不支持修改这些字段：{', '.join(sorted(bad))}")
    if "status" in data and data["status"] and not valid_status(data["status"]):
        raise ValueError(f"非法状态：{data['status']}")
    data = {k: v for k, v in data.items() if v is not None or k in ("project_id",)}
    if "code_scopes" in data:
        data["code_scopes"] = json.dumps(data["code_scopes"] or [], ensure_ascii=False)
    if "target_repos" in data:
        data["target_repos"] = json.dumps(data["target_repos"] or [], ensure_ascii=False)
    # project_id=0 表示取消归属
    if "project_id" in data:
        data["project_id"] = data["project_id"] or None
    if "tags" in data:
        data["tags"] = json.dumps(data["tags"] or [], ensure_ascii=False)
    if "target_repo" in data and data["target_repo"]:
        from .fix import is_repo_root
        _need(is_repo_root(data["target_repo"]), "target_repo 必须是 git 仓库根目录")
    if "target_repo" in data and "target_repos" not in data:
        data["target_repos"] = json.dumps(
            [data["target_repo"]] if data["target_repo"] else [], ensure_ascii=False)
    data["updated_at"] = now()
    sets = ", ".join(f"{k} = ?" for k in data)
    with connect() as conn:
        # 归属校验必须在任何「提前返回」之前（空 data 也是一次探测）
        issue = load_issue(conn, issue_id, user)
        conn.execute(f"UPDATE issue SET {sets} WHERE id = ?", [*data.values(), issue_id])
        if data.get("status") and data["status"] != issue["status"]:
            add_event(conn, issue_id, "status", from_status=issue["status"],
                      to_status=data["status"], actor=_actor(user))
    return {"ok": True}


def delete_issue(user: dict | None, issue_id: int) -> dict:
    with connect() as conn:
        issue = load_issue(conn, issue_id, user)
        conn.execute("DELETE FROM issue WHERE id = ?", (issue_id,))
        conn.execute("DELETE FROM attachment WHERE issue_id = ?", (issue_id,))
        conn.execute("DELETE FROM ai_run WHERE issue_id = ?", (issue_id,))
        conn.execute("DELETE FROM event WHERE issue_id = ?", (issue_id,))
        conn.execute("DELETE FROM comment WHERE issue_id = ?", (issue_id,))
        conn.execute("DELETE FROM issue_link WHERE issue_id = ? OR other_id = ?",
                     (issue_id, issue_id))
    shutil.rmtree(ATTACH_DIR / str(issue["id"]), ignore_errors=True)
    return {"ok": True}


def get_memory(user: dict | None, issue_id: int) -> dict:
    from . import memory as mem
    with connect() as conn:
        load_issue(conn, issue_id, user)
    sessions = mem.list_sessions(issue_id)
    for s in sessions:
        s["kindLabel"] = mem.KIND_LABELS.get(s["kind"], s["kind"])
    return {"sessions": sessions, "kinds": mem.KIND_LABELS}


def clear_memory(user: dict | None, issue_id: int, kind: str = "") -> dict:
    from . import memory as mem
    with connect() as conn:
        load_issue(conn, issue_id, user)
    n = mem.clear_session(issue_id, kind or None)
    return {"ok": True, "cleared": n}


# ---------------- 关联 ----------------

def list_links(user: dict | None, issue_id: int) -> dict:
    with connect() as conn:
        load_issue(conn, issue_id, user)
        rows = list_rows(conn.execute(
            "SELECT l.id, l.kind, l.created_at, "
            "       CASE WHEN l.issue_id = ? THEN l.other_id ELSE l.issue_id END AS target_id, "
            "       CASE WHEN l.issue_id = ? THEN 'out' ELSE 'in' END AS direction, "
            "       i.title, i.status "
            "FROM issue_link l JOIN issue i "
            "  ON i.id = CASE WHEN l.issue_id = ? THEN l.other_id ELSE l.issue_id END "
            "WHERE l.issue_id = ? OR l.other_id = ? ORDER BY l.id DESC",
            (issue_id, issue_id, issue_id, issue_id, issue_id)).fetchall())
    for r in rows:
        r["kindLabel"] = LINK_KINDS.get(r["kind"], r["kind"])
    return {"links": rows}


def add_link(user: dict | None, issue_id: int, other_id: int, kind: str = "duplicate") -> dict:
    other = int(other_id or 0)
    _need(other != issue_id, "不能关联自己")
    kind = kind or "duplicate"
    _need(kind in LINK_KINDS, f"不支持的关联类型：{kind}")
    with connect() as conn:
        load_issue(conn, issue_id, user)
        # 目标也要有权访问，否则等于靠关联接口探别人有没有这个 id
        load_issue(conn, other, user)
        try:
            conn.execute(
                "INSERT INTO issue_link(issue_id, other_id, kind, created_at) VALUES (?, ?, ?, ?)",
                (issue_id, other, kind, now()))
        except sqlite3.IntegrityError:
            raise ValueError("已经关联过了")
        add_event(conn, issue_id, "link", note=f"{LINK_KINDS[kind]} #{other}",
                  actor=_actor(user))
    return {"ok": True}


def remove_link(user: dict | None, issue_id: int, link_id: int) -> dict:
    with connect() as conn:
        load_issue(conn, issue_id, user)
        conn.execute("DELETE FROM issue_link WHERE id = ? AND (issue_id = ? OR other_id = ?)",
                     (link_id, issue_id, issue_id))
    return {"ok": True}


# ---------------- 评论 ----------------

def list_comments(user: dict | None, issue_id: int) -> dict:
    with connect() as conn:
        load_issue(conn, issue_id, user)
        rows = list_rows(conn.execute(
            "SELECT id, author, author_id, body, created_at FROM comment "
            "WHERE issue_id = ? ORDER BY id", (issue_id,)).fetchall())
    return {"comments": rows}


def add_comment(user: dict | None, issue_id: int, body: str) -> dict:
    body = (body or "").strip()
    _need(body, "内容不能为空")
    _need(len(body) <= 5000, "单条评论最多 5000 字")
    author = (user or {}).get("displayName") or (user or {}).get("username") or "我"
    with connect() as conn:
        load_issue(conn, issue_id, user)
        cur = conn.execute(
            "INSERT INTO comment(issue_id, author, author_id, body, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (issue_id, author, (user or {}).get("id") or None, body, now()))
        add_event(conn, issue_id, "note", note=f"评论：{body[:60]}", actor=author)
        issue_title = dict(conn.execute("SELECT title FROM issue WHERE id = ?",
                                        (issue_id,)).fetchone())["title"]
        row = dict(conn.execute("SELECT id, author, author_id, body, created_at "
                                "FROM comment WHERE id = ?", (cur.lastrowid,)).fetchone())
    from . import notify
    try:
        notify.notify_new_comment(issue_id, issue_title, author, body)
    except Exception:
        pass
    return {"comment": row}


def delete_comment(user: dict | None, issue_id: int, comment_id: int) -> dict:
    with connect() as conn:
        load_issue(conn, issue_id, user)
        row = conn.execute("SELECT * FROM comment WHERE id = ? AND issue_id = ?",
                           (comment_id, issue_id)).fetchone()
        if not row:
            from .access import _not_found
            _not_found("评论")
        if not (user and (user.get("role") == "admin" or row["author_id"] == user.get("id"))):
            raise PermissionDenied("只能删除自己的评论")
        conn.execute("DELETE FROM comment WHERE id = ?", (comment_id,))
    return {"ok": True}


# ---------------- 批量 ----------------

BATCH_FIELDS = {"status", "priority", "severity", "complexity",
                "assignee", "due_date", "module", "project_id"}


def batch_patch(user: dict | None, ids: list[int], fields: dict,
                add_tags: list[str] | None = None) -> dict:
    """批量改。只处理有权的 id，其余静默跳过（返回 403 等于告诉对方「这些 id 存在」）。"""
    ids = [int(i) for i in (ids or [])]
    _need(ids, "请先选择问题")
    _need(len(ids) <= 500, "一次最多处理 500 条")

    data: dict[str, object] = {}
    if fields.get("status") is not None:
        _need(valid_status(fields["status"]), f"非法状态：{fields['status']}")
        data["status"] = fields["status"]
    # project_id 单独处理：0 表示取消归属
    if fields.get("project_id") is not None:
        data["project_id"] = fields["project_id"] or None
    for field in ("priority", "severity", "complexity", "assignee", "due_date", "module"):
        if fields.get(field) is not None:
            data[field] = fields[field]
    _need(data or add_tags is not None, "没有要修改的字段")

    marks = ",".join("?" * len(ids))
    owner_sql, owner_args = owner_filter(user)

    with connect() as conn:
        sql = f"SELECT id, status, tags FROM issue WHERE id IN ({marks})"
        args: list = list(ids)
        if owner_sql:
            sql += f" AND {owner_sql}"
            args += owner_args
        rows = {r["id"]: dict(r) for r in conn.execute(sql, args).fetchall()}
        if not rows:
            return {"ok": True, "updated": 0, "skipped": len(ids)}

        sets = dict(data)
        sets["updated_at"] = now()

        if add_tags is not None:
            extra = [t for t in add_tags if t]
            for iid, row in rows.items():
                try:
                    current = json.loads(row.get("tags") or "[]")
                except json.JSONDecodeError:
                    current = []
                merged = list(dict.fromkeys([*current, *extra]))
                conn.execute("UPDATE issue SET tags = ? WHERE id = ?",
                             (json.dumps(merged, ensure_ascii=False), iid))

        if sets:
            col_sql = ", ".join(f"{k} = ?" for k in sets)
            conn.executemany(
                f"UPDATE issue SET {col_sql} WHERE id = ?",
                [[*sets.values(), iid] for iid in rows])

        for iid, row in rows.items():
            if data.get("status") and data["status"] != row["status"]:
                add_event(conn, iid, "status", from_status=row["status"],
                          to_status=str(data["status"]), note="批量修改",
                          actor=_actor(user))
    return {"ok": True, "updated": len(rows), "skipped": len(ids) - len(rows)}


def batch_delete(user: dict | None, ids: list[int]) -> dict:
    ids = [int(i) for i in (ids or [])]
    _need(ids, "请先选择问题")
    _need(len(ids) <= 500, "一次最多删除 500 条")

    marks = ",".join("?" * len(ids))
    owner_sql, owner_args = owner_filter(user)
    with connect() as conn:
        sql = f"SELECT id FROM issue WHERE id IN ({marks})"
        args: list = list(ids)
        if owner_sql:
            sql += f" AND {owner_sql}"
            args += owner_args
        allowed = [r["id"] for r in conn.execute(sql, args).fetchall()]
        if not allowed:
            return {"ok": True, "deleted": 0, "skipped": len(ids)}
        m2 = ",".join("?" * len(allowed))
        conn.execute(f"DELETE FROM issue WHERE id IN ({m2})", allowed)
        conn.execute(f"DELETE FROM attachment WHERE issue_id IN ({m2})", allowed)
        conn.execute(f"DELETE FROM ai_run WHERE issue_id IN ({m2})", allowed)
        conn.execute(f"DELETE FROM event WHERE issue_id IN ({m2})", allowed)
        conn.execute(f"DELETE FROM comment WHERE issue_id IN ({m2})", allowed)
        conn.execute(f"DELETE FROM issue_link WHERE issue_id IN ({m2}) OR other_id IN ({m2})",
                     [*allowed, *allowed])
    for iid in allowed:
        shutil.rmtree(ATTACH_DIR / str(iid), ignore_errors=True)
    return {"ok": True, "deleted": len(allowed), "skipped": len(ids) - len(allowed)}


# ---------------- 导出 ----------------

def export_md(user: dict | None, issue_id: int) -> str:
    with connect() as conn:
        issue = load_issue(conn, issue_id, user)
        attachments = list_rows(conn.execute(
            "SELECT filename, path FROM attachment WHERE issue_id = ?", (issue_id,)).fetchall())
    final = _json_or_none(issue.get("qualify_final")) or {}
    triage = _json_or_none(issue.get("triage")) or {}
    lines = [
        f"# #{issue['id']} {issue['title']}",
        "",
        f"- 状态：{issue['status']}　优先级：{issue.get('priority') or '-'}　"
        f"等级：{issue.get('severity') or '-'}　复杂度：{issue.get('complexity') or '-'}",
        f"- 提出人：{issue.get('reporter') or '-'}　模块：{issue.get('module') or '-'}　"
        f"创建：{issue['created_at']}",
        "",
        "## 原始描述",
        issue.get("raw_text") or "（无）",
        "",
        "## 已确认的问题描述",
        final.get("phenomenon") or "（未确认）",
    ]
    if final.get("repro_steps"):
        lines += ["", "### 复现步骤"] + [f"{i}. {s}" for i, s in enumerate(final["repro_steps"], 1)]
    for label, key in (("期望", "expected"), ("实际", "actual"), ("影响范围", "scope")):
        if final.get(key):
            lines += ["", f"**{label}**：{final[key]}"]
    if final.get("uncertainties"):
        lines += ["", "### 待确认"] + [f"- {s}" for s in final["uncertainties"]]
    if triage:
        lines += ["", "## 定级依据", *[f"- {s}" for s in triage.get("reasons", [])]]
    if issue.get("fix_plan"):
        plan = _json_or_none(issue["fix_plan"]) or {}
        lines += ["", "## 修复方案", plan.get("root_cause") or ""]
        if plan.get("changes"):
            lines += [f"- {s}" for s in plan["changes"]]
    if attachments:
        lines += ["", "## 附件"] + [f"- {a['filename']}" for a in attachments]
    return "\n".join(lines) + "\n"
