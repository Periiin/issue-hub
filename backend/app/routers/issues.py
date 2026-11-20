"""问题 CRUD、附件、导出。"""
import datetime
import json
import shutil
import sqlite3
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse

from ..config import ALL_STATUS, ATTACH_DIR, MAX_UPLOAD_BYTES, STATUS_FINAL
from ..db import add_event, connect, dict_row, list_rows, now, valid_status
from .auth import require_user
from ..schemas import (CommentCreate, IssueBatchIds, IssueBatchPatch,
                       IssueCreate, IssuePatch, LinkCreate)

router = APIRouter(prefix="/api/issues", tags=["issues"])


def _owner_filter(user: dict) -> tuple[str, list]:
    """按用户过滤 SQL 片段。

    admin 看全部；普通用户只看自己的 + 历史遗留（owner_id 为空）。
    历史数据 owner_id 为空是因为加鉴权之前录的，不该让它们凭空消失。
    """
    if user.get("role") == "admin":
        return "", []
    return "(owner_id = ? OR owner_id IS NULL)", [user.get("id") or 0]


def _load_issue(conn, issue_id: int, user: dict | None = None) -> dict:
    """读 issue 并校验归属。

    所有单条接口都走这里 —— 一处校验比在每个端点重复写可靠，
    漏一个就是「拼 id 就能看别人问题」的越权。
    """
    row = conn.execute("SELECT * FROM issue WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "问题不存在")
    issue = dict(row)
    if user and user.get("role") != "admin":
        owner = issue.get("owner_id")
        # owner_id 为空 = 加鉴权之前的历史数据，允许读
        if owner is not None and owner != user.get("id"):
            raise HTTPException(404, "问题不存在")   # 不暴露「存在但无权」
    return issue


def _json_or_none(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


@router.get("")
def list_issues(status: str = "", priority: str = "", module: str = "",
                q: str = "", tag: str = "", assignee: str = "",
                due: str = "", mine: str = "",
                limit: int = Query(50, ge=1, le=200),
                offset: int = Query(0, ge=0),
                user: dict = Depends(require_user)):
    """问题列表（分页）。

    分页而不是「一次给 200 条」：攒到几百条后老问题会永远看不到，
    而且前端表格一次渲染几百行很卡。`total` 是当前筛选条件下的总数。
    """
    where, args = [], []
    owner_sql, owner_args = _owner_filter(user)
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
        # tags 是 JSON 数组文本，用带引号的匹配避免 "支付" 命中 "支付宝"
        where.append("tags LIKE ?")
        args.append(f'%"{tag}"%')
    if assignee:
        where.append("assignee = ?")
        args.append(assignee)
    if due:
        # due=overdue 只看逾期且未关闭；due=week 看 7 天内到期
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
    if mine:
        # mine=assigned 分配给我的；mine=reported 我提的
        me_name = user.get("username") or ""
        if mine == "assigned":
            where.append("assignee = ?")
            args.append(me_name)
        elif mine == "reported":
            where.append("reporter = ?")
            args.append(me_name)
    if q:
        # 搜索范围要覆盖「确认后的描述」——AI 整理过的现象往往比甲方原话准确，
        # 只搜 raw_text 会漏掉最该命中的那条
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
        # 状态计数只按 owner 过滤（不受当前筛选影响），否则 tab 上的数字会变成 0
        count_sql = "SELECT status, COUNT(*) n FROM issue"
        if owner_sql:
            count_sql += " WHERE " + owner_sql
        count_sql += " GROUP BY status"
        counts = {r["status"]: r["n"] for r in conn.execute(count_sql, owner_args).fetchall()}
    return {"list": rows, "counts": counts, "statuses": ALL_STATUS,
            "total": total, "limit": limit, "offset": offset,
            "tags": _all_tags(conn, owner_sql, owner_args)}


def _all_tags(conn, owner_sql: str, owner_args: list) -> list[str]:
    """汇总所有用过的标签（给前端筛选下拉）。空标签不算。"""
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


@router.post("")
def create_issue(payload: IssueCreate, user: dict = Depends(require_user)):
    title = (payload.title or "").strip() or (payload.raw_text or "").strip()[:30] or "未命名问题"
    ts = now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO issue(title, raw_text, source, reporter, module, status, owner_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, '待定性', ?, ?, ?)",
            (title, payload.raw_text, payload.source, payload.reporter, payload.module,
             user.get("id") or None, ts, ts),
        )
        issue_id = cur.lastrowid
        add_event(conn, issue_id, "create", to_status="待定性", note="新建问题",
                  actor=user.get("displayName") or user.get("username"))
    return {"id": issue_id}


@router.get("/{issue_id}")
def get_issue(issue_id: int, user: dict = Depends(require_user)):
    with connect() as conn:
        issue = _load_issue(conn, issue_id, user)
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
    # 兼容前端：target_repos 为空时回退到旧的单值字段
    if not issue.get("target_repos") and issue.get("target_repo"):
        issue["target_repos"] = [issue["target_repo"]]
    from ..fix import list_attempts
    # 所属项目一起返回：前端直接用，不必再拉一次项目列表
    project = None
    if issue.get("project_id"):
        from .. import projects as proj
        project = proj.get_project(issue["project_id"])
    return {"issue": issue, "project": project, "attachments": attachments, "runs": runs,
            "events": events, "attempts": list_attempts(issue_id)}


@router.get("/{issue_id}/memory")
def get_memory(issue_id: int, user: dict = Depends(require_user)):
    """查看这个问题的对话记忆：每类操作各一份，与通道无关。"""
    from .. import memory as mem
    with connect() as conn:
        _load_issue(conn, issue_id, user)
    sessions = mem.list_sessions(issue_id)
    for s in sessions:
        s["kindLabel"] = mem.KIND_LABELS.get(s["kind"], s["kind"])
    return {"sessions": sessions, "kinds": mem.KIND_LABELS}


@router.delete("/{issue_id}/memory")
def clear_memory(issue_id: int, kind: str = "", user: dict = Depends(require_user)):
    """清空记忆。kind 为空清全部；否则只清某一类（如只清「改代码」的）。"""
    from .. import memory as mem
    with connect() as conn:
        _load_issue(conn, issue_id, user)
    n = mem.clear_session(issue_id, kind or None)
    return {"ok": True, "cleared": n}


@router.patch("/{issue_id}")
def patch_issue(issue_id: int, payload: IssuePatch, user: dict = Depends(require_user)):
    data = payload.model_dump(exclude_none=True)
    if "status" in data and not valid_status(data["status"]):
        raise HTTPException(400, f"非法状态：{data['status']}")
    if "code_scopes" in data:
        data["code_scopes"] = json.dumps(data["code_scopes"], ensure_ascii=False)
    if "target_repos" in data:
        data["target_repos"] = json.dumps(data["target_repos"], ensure_ascii=False)
    # project_id=0 表示取消归属（前端 clearable 传 0）
    if "project_id" in data:
        data["project_id"] = data["project_id"] or None
    if "tags" in data:
        data["tags"] = json.dumps(data["tags"] or [], ensure_ascii=False)
    if "target_repo" in data and data["target_repo"]:
        from ..fix import is_repo_root
        if not is_repo_root(data["target_repo"]):
            raise HTTPException(400, "target_repo 必须是 git 仓库根目录")
    # 兼容：只传了旧字段 target_repo 时，同步进 target_repos，保证新逻辑能读到
    if "target_repo" in data and "target_repos" not in data:
        data["target_repos"] = json.dumps(
            [data["target_repo"]] if data["target_repo"] else [], ensure_ascii=False)
    data["updated_at"] = now()
    sets = ", ".join(f"{k} = ?" for k in data)
    with connect() as conn:
        # 归属校验必须在任何「提前返回」之前：否则空请求体能让任何人探到 200，
        # 虽然不改数据，但等于确认了「这个 id 存在」
        issue = _load_issue(conn, issue_id, user)
        conn.execute(f"UPDATE issue SET {sets} WHERE id = ?", [*data.values(), issue_id])
        if data.get("status") and data["status"] != issue["status"]:
            add_event(conn, issue_id, "status", from_status=issue["status"],
                      to_status=data["status"], actor=user.get("displayName") or user.get("username"))
    return {"ok": True}


@router.delete("/{issue_id}")
def delete_issue(issue_id: int, user: dict = Depends(require_user)):
    with connect() as conn:
        issue = _load_issue(conn, issue_id, user)
        conn.execute("DELETE FROM issue WHERE id = ?", (issue_id,))
        conn.execute("DELETE FROM attachment WHERE issue_id = ?", (issue_id,))
        conn.execute("DELETE FROM ai_run WHERE issue_id = ?", (issue_id,))
        conn.execute("DELETE FROM event WHERE issue_id = ?", (issue_id,))
    shutil.rmtree(ATTACH_DIR / str(issue["id"]), ignore_errors=True)
    return {"ok": True}


# ---------------- 关联（重复/相关） ----------------

LINK_KINDS = {"duplicate": "重复", "related": "相关", "blocks": "阻塞"}


@router.get("/{issue_id}/links")
def list_links(issue_id: int, user: dict = Depends(require_user)):
    """本问题的关联。双向查：别人把我标成重复，我这边也要看到。"""
    with connect() as conn:
        _load_issue(conn, issue_id, user)
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


@router.post("/{issue_id}/links")
def add_link(issue_id: int, payload: LinkCreate, user: dict = Depends(require_user)):
    other = int(payload.other_id or 0)
    if other == issue_id:
        raise HTTPException(400, "不能关联自己")
    kind = payload.kind or "duplicate"
    if kind not in LINK_KINDS:
        raise HTTPException(400, f"不支持的关联类型：{kind}")

    with connect() as conn:
        _load_issue(conn, issue_id, user)
        # 目标也必须有权访问，否则等于靠关联接口探别人有没有这个 id
        _load_issue(conn, other, user)
        try:
            conn.execute(
                "INSERT INTO issue_link(issue_id, other_id, kind, created_at) VALUES (?, ?, ?, ?)",
                (issue_id, other, kind, now()))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "已经关联过了")
        add_event(conn, issue_id, "link", note=f"{LINK_KINDS[kind]} #{other}",
                  actor=user.get("displayName") or user.get("username"))
    return {"ok": True}


@router.delete("/{issue_id}/links/{link_id}")
def remove_link(issue_id: int, link_id: int, user: dict = Depends(require_user)):
    with connect() as conn:
        _load_issue(conn, issue_id, user)
        conn.execute("DELETE FROM issue_link WHERE id = ? AND (issue_id = ? OR other_id = ?)",
                     (link_id, issue_id, issue_id))
    return {"ok": True}


# ---------------- 讨论区 ----------------

@router.get("/{issue_id}/comments")
def list_comments(issue_id: int, user: dict = Depends(require_user)):
    with connect() as conn:
        _load_issue(conn, issue_id, user)
        rows = list_rows(conn.execute(
            "SELECT id, author, author_id, body, created_at FROM comment "
            "WHERE issue_id = ? ORDER BY id", (issue_id,)).fetchall())
    return {"comments": rows}


@router.post("/{issue_id}/comments")
def add_comment(issue_id: int, payload: CommentCreate,
                user: dict = Depends(require_user)):
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(400, "内容不能为空")
    if len(body) > 5000:
        raise HTTPException(400, "单条评论最多 5000 字")
    author = user.get("displayName") or user.get("username") or "我"
    with connect() as conn:
        _load_issue(conn, issue_id, user)
        cur = conn.execute(
            "INSERT INTO comment(issue_id, author, author_id, body, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (issue_id, author, user.get("id") or None, body, now()))
        # 时间线里也记一条，翻记录时不用两个地方对着看
        add_event(conn, issue_id, "note", note=f"评论：{body[:60]}", actor=author)
        row = dict(conn.execute("SELECT id, author, author_id, body, created_at "
                                "FROM comment WHERE id = ?",
                                (cur.lastrowid,)).fetchone())
    return {"comment": row}


@router.delete("/{issue_id}/comments/{comment_id}")
def delete_comment(issue_id: int, comment_id: int,
                   user: dict = Depends(require_user)):
    """删评论：作者本人或管理员。"""
    with connect() as conn:
        _load_issue(conn, issue_id, user)
        row = conn.execute("SELECT * FROM comment WHERE id = ? AND issue_id = ?",
                           (comment_id, issue_id)).fetchone()
        if not row:
            raise HTTPException(404, "评论不存在")
        if user.get("role") != "admin" and row["author_id"] != user.get("id"):
            raise HTTPException(403, "只能删除自己的评论")
        conn.execute("DELETE FROM comment WHERE id = ?", (comment_id,))
    return {"ok": True}


# ---------------- 批量 ----------------

@router.post("/batch")
def batch_patch(payload: IssueBatchPatch, user: dict = Depends(require_user)):
    """批量改状态/优先级/负责人/截止日期/模块/标签。

    只处理调用者有权访问的 id，其余的静默跳过（返回 skipped 数量）——
    返回 403 等于告诉对方「这些 id 存在」。
    """
    ids = [int(i) for i in (payload.ids or [])]
    if not ids:
        raise HTTPException(400, "请先选择问题")
    if len(ids) > 500:
        raise HTTPException(400, "一次最多处理 500 条")

    data: dict[str, object] = {}
    if payload.status is not None:
        if not valid_status(payload.status):
            raise HTTPException(400, f"非法状态：{payload.status}")
        data["status"] = payload.status
    for field in ("priority", "severity", "complexity", "assignee", "due_date", "module"):
        value = getattr(payload, field)
        if value is not None:
            data[field] = value
    if not data and payload.add_tags is None:
        raise HTTPException(400, "没有要修改的字段")

    marks = ",".join("?" * len(ids))
    owner_sql, owner_args = _owner_filter(user)

    with connect() as conn:
        # 先取出有权的 id 和它们当前的状态（用于写事件）
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

        if payload.add_tags is not None:
            # 标签按「并集」追加，不覆盖原有标签
            extra = [t for t in payload.add_tags if t]
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

        # 逐条写事件，时间线才看得出「谁在什么时候批量改的」
        for iid, row in rows.items():
            if data.get("status") and data["status"] != row["status"]:
                add_event(conn, iid, "status", from_status=row["status"],
                          to_status=str(data["status"]), note="批量修改",
                          actor=user.get("displayName") or user.get("username"))

    return {"ok": True, "updated": len(rows), "skipped": len(ids) - len(rows)}


@router.post("/batch/delete")
def batch_delete(payload: IssueBatchIds, user: dict = Depends(require_user)):
    """批量删除。只删有权的，其余跳过。"""
    ids = [int(i) for i in (payload.ids or [])]
    if not ids:
        raise HTTPException(400, "请先选择问题")
    if len(ids) > 500:
        raise HTTPException(400, "一次最多删除 500 条")

    marks = ",".join("?" * len(ids))
    owner_sql, owner_args = _owner_filter(user)
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


# ---------------- 附件 ----------------

@router.post("/{issue_id}/attachments")
async def upload_attachments(issue_id: int, files: list[UploadFile] = File(...),
                            user: dict = Depends(require_user)):
    with connect() as conn:
        _load_issue(conn, issue_id, user)
    saved = []
    target_dir = ATTACH_DIR / str(issue_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        blob = await f.read()
        if len(blob) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, f"{f.filename} 超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB")
        suffix = Path(f.filename or "").suffix.lower() or ".png"
        name = f"{uuid.uuid4().hex}{suffix}"
        (target_dir / name).write_bytes(blob)
        rel = f"{issue_id}/{name}"
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO attachment(issue_id, filename, path, mime, size, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (issue_id, f.filename or name, rel, f.content_type, len(blob), now()),
            )
            saved.append({"id": cur.lastrowid, "filename": f.filename or name,
                          "path": rel, "mime": f.content_type, "size": len(blob)})
    return {"attachments": saved}


@router.delete("/{issue_id}/attachments/{attachment_id}")
def delete_attachment(issue_id: int, attachment_id: int, user: dict = Depends(require_user)):
    with connect() as conn:
        row = conn.execute("SELECT * FROM attachment WHERE id = ? AND issue_id = ?",
                           (attachment_id, issue_id)).fetchone()
        if row is None:
            raise HTTPException(404, "附件不存在")
        conn.execute("DELETE FROM attachment WHERE id = ?", (attachment_id,))
    (ATTACH_DIR / row["path"]).unlink(missing_ok=True)
    return {"ok": True}


# ---------------- 导出 ----------------

@router.get("/{issue_id}/export", response_class=PlainTextResponse)
def export_issue_md(issue_id: int, user: dict = Depends(require_user)):
    with connect() as conn:
        issue = _load_issue(conn, issue_id, user)
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



