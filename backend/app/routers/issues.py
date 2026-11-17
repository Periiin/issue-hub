"""问题 CRUD、附件、导出。"""
import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from ..config import ALL_STATUS, ATTACH_DIR, MAX_UPLOAD_BYTES
from ..db import add_event, connect, dict_row, list_rows, now, valid_status
from ..schemas import IssueCreate, IssuePatch

router = APIRouter(prefix="/api/issues", tags=["issues"])


def _load_issue(conn, issue_id: int) -> dict:
    row = conn.execute("SELECT * FROM issue WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "问题不存在")
    return dict(row)


def _json_or_none(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


@router.get("")
def list_issues(status: str = "", priority: str = "", module: str = "",
                q: str = "", limit: int = Query(200, le=500)):
    where, args = [], []
    if status:
        where.append("status = ?")
        args.append(status)
    if priority:
        where.append("priority = ?")
        args.append(priority)
    if module:
        where.append("module LIKE ?")
        args.append(f"%{module}%")
    if q:
        where.append("(title LIKE ? OR raw_text LIKE ?)")
        args += [f"%{q}%", f"%{q}%"]
    sql = "SELECT * FROM issue"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += (" ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 "
            "WHEN 'P3' THEN 3 ELSE 4 END, id DESC LIMIT ?")
    args.append(limit)
    with connect() as conn:
        rows = list_rows(conn.execute(sql, args).fetchall())
        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) n FROM issue GROUP BY status").fetchall()}
    return {"list": rows, "counts": counts, "statuses": ALL_STATUS}


@router.post("")
def create_issue(payload: IssueCreate):
    title = (payload.title or "").strip() or (payload.raw_text or "").strip()[:30] or "未命名问题"
    ts = now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO issue(title, raw_text, source, reporter, module, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '待定性', ?, ?)",
            (title, payload.raw_text, payload.source, payload.reporter, payload.module, ts, ts),
        )
        issue_id = cur.lastrowid
        add_event(conn, issue_id, "create", to_status="待定性", note="新建问题")
    return {"id": issue_id}


@router.get("/{issue_id}")
def get_issue(issue_id: int):
    with connect() as conn:
        issue = _load_issue(conn, issue_id)
        attachments = list_rows(conn.execute(
            "SELECT * FROM attachment WHERE issue_id = ? ORDER BY id", (issue_id,)).fetchall())
        runs = list_rows(conn.execute(
            "SELECT id, kind, provider, model, duration_ms, ok, error, created_at "
            "FROM ai_run WHERE issue_id = ? ORDER BY id DESC LIMIT 20", (issue_id,)).fetchall())
        events = list_rows(conn.execute(
            "SELECT * FROM event WHERE issue_id = ? ORDER BY id DESC", (issue_id,)).fetchall())
    for key in ("qualify_draft", "qualify_final", "triage", "fix_plan",
                "code_scopes", "fix_state"):
        issue[key] = _json_or_none(issue.get(key))
    return {"issue": issue, "attachments": attachments, "runs": runs, "events": events}


@router.patch("/{issue_id}")
def patch_issue(issue_id: int, payload: IssuePatch):
    data = payload.model_dump(exclude_none=True)
    if "status" in data and not valid_status(data["status"]):
        raise HTTPException(400, f"非法状态：{data['status']}")
    if "code_scopes" in data:
        data["code_scopes"] = json.dumps(data["code_scopes"], ensure_ascii=False)
    if "target_repo" in data and data["target_repo"]:
        from ..fix import is_repo_root
        if not is_repo_root(data["target_repo"]):
            raise HTTPException(400, "target_repo 必须是 git 仓库根目录")
    if not data:
        return {"ok": True}
    data["updated_at"] = now()
    sets = ", ".join(f"{k} = ?" for k in data)
    with connect() as conn:
        issue = _load_issue(conn, issue_id)
        conn.execute(f"UPDATE issue SET {sets} WHERE id = ?", [*data.values(), issue_id])
        if data.get("status") and data["status"] != issue["status"]:
            add_event(conn, issue_id, "status", from_status=issue["status"], to_status=data["status"])
    return {"ok": True}


@router.delete("/{issue_id}")
def delete_issue(issue_id: int):
    with connect() as conn:
        issue = _load_issue(conn, issue_id)
        conn.execute("DELETE FROM issue WHERE id = ?", (issue_id,))
        conn.execute("DELETE FROM attachment WHERE issue_id = ?", (issue_id,))
        conn.execute("DELETE FROM ai_run WHERE issue_id = ?", (issue_id,))
        conn.execute("DELETE FROM event WHERE issue_id = ?", (issue_id,))
    shutil.rmtree(ATTACH_DIR / str(issue["id"]), ignore_errors=True)
    return {"ok": True}


# ---------------- 附件 ----------------

@router.post("/{issue_id}/attachments")
async def upload_attachments(issue_id: int, files: list[UploadFile] = File(...)):
    with connect() as conn:
        _load_issue(conn, issue_id)
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
def delete_attachment(issue_id: int, attachment_id: int):
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
def export_issue_md(issue_id: int):
    with connect() as conn:
        issue = _load_issue(conn, issue_id)
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



