"""问题路由：薄壳。

真正的逻辑在 app/issues_core.py —— HTTP 和 MCP 共用同一层，
路由只做 pydantic 解析和异常转换。改行为去改 core，别在这里加逻辑。
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from .. import issues_core as core
from ..access import AccessDenied
from ..issues_core import PermissionDenied
from ..config import MAX_UPLOAD_BYTES
from ..db import now
from ..schemas import (CommentCreate, IssueBatchIds, IssueBatchPatch,
                       IssueCreate, IssuePatch, LinkCreate)
from .auth import require_user

router = APIRouter(prefix="/api/issues", tags=["issues"])


def _guard(fn, *args, **kwargs):
    """把 core 层的异常转成 HTTP 错误。所有端点都走这个包装，别在各处重复写。"""
    try:
        return fn(*args, **kwargs)
    except AccessDenied:
        raise  # access 层在 web 进程里抛的就是 HTTPException(404)
    except PermissionDenied as ex:
        raise HTTPException(403, str(ex))
    except ValueError as ex:
        raise HTTPException(400, str(ex))


@router.get("")
def list_issues(status: str = "", priority: str = "", module: str = "",
                q: str = "", tag: str = "", assignee: str = "",
                due: str = "", mine: str = "", project_id: int = 0,
                limit: int = Query(50, ge=1, le=200),
                offset: int = Query(0, ge=0),
                user: dict = Depends(require_user)):
    return core.list_issues(user, status=status, priority=priority, module=module,
                            q=q, tag=tag, assignee=assignee, due=due, mine=mine,
                            project_id=project_id, limit=limit, offset=offset)


@router.post("")
def create_issue(payload: IssueCreate, user: dict = Depends(require_user)):
    return {"id": core.create_issue(
        user, title=payload.title, raw_text=payload.raw_text, source=payload.source,
        reporter=payload.reporter, module=payload.module,
        code_scopes=payload.code_scopes, project_id=payload.project_id)}


@router.get("/{issue_id}")
def get_issue(issue_id: int, user: dict = Depends(require_user)):
    return _guard(core.get_issue, user, issue_id)


@router.get("/{issue_id}/memory")
def get_memory(issue_id: int, user: dict = Depends(require_user)):
    return _guard(core.get_memory, user, issue_id)


@router.delete("/{issue_id}/memory")
def clear_memory(issue_id: int, kind: str = "", user: dict = Depends(require_user)):
    return _guard(core.clear_memory, user, issue_id, kind)


@router.patch("/{issue_id}")
def patch_issue(issue_id: int, payload: IssuePatch, user: dict = Depends(require_user)):
    return _guard(core.patch_issue, user, issue_id,
                  {k: v for k, v in payload.model_dump().items() if v is not None or k == "project_id"})


@router.delete("/{issue_id}")
def delete_issue(issue_id: int, user: dict = Depends(require_user)):
    return _guard(core.delete_issue, user, issue_id)


# ---------------- 关联 ----------------

@router.get("/{issue_id}/links")
def list_links(issue_id: int, user: dict = Depends(require_user)):
    return _guard(core.list_links, user, issue_id)


@router.post("/{issue_id}/links")
def add_link(issue_id: int, payload: LinkCreate, user: dict = Depends(require_user)):
    return _guard(core.add_link, user, issue_id, payload.other_id, payload.kind)


@router.delete("/{issue_id}/links/{link_id}")
def remove_link(issue_id: int, link_id: int, user: dict = Depends(require_user)):
    return _guard(core.remove_link, user, issue_id, link_id)


# ---------------- 评论 ----------------

@router.get("/{issue_id}/comments")
def list_comments(issue_id: int, user: dict = Depends(require_user)):
    return _guard(core.list_comments, user, issue_id)


@router.post("/{issue_id}/comments")
def add_comment(issue_id: int, payload: CommentCreate, user: dict = Depends(require_user)):
    return _guard(core.add_comment, user, issue_id, payload.body)


@router.delete("/{issue_id}/comments/{comment_id}")
def delete_comment(issue_id: int, comment_id: int, user: dict = Depends(require_user)):
    return _guard(core.delete_comment, user, issue_id, comment_id)


# ---------------- 批量 ----------------

@router.post("/batch")
def batch_patch(payload: IssueBatchPatch, user: dict = Depends(require_user)):
    fields = {k: getattr(payload, k) for k in core.BATCH_FIELDS}
    return _guard(core.batch_patch, user, payload.ids, fields, payload.add_tags)


@router.post("/batch/delete")
def batch_delete(payload: IssueBatchIds, user: dict = Depends(require_user)):
    return _guard(core.batch_delete, user, payload.ids)


# ---------------- 附件 ----------------

@router.post("/{issue_id}/attachments")
async def upload_attachments(issue_id: int, files: list[UploadFile] = File(...),
                             user: dict = Depends(require_user)):
    from ..config import ATTACH_DIR
    from ..access import load_issue
    from ..db import connect
    with connect() as conn:
        load_issue(conn, issue_id, user)
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
    from ..config import ATTACH_DIR
    from ..access import load_issue
    from ..db import connect
    with connect() as conn:
        load_issue(conn, issue_id, user)
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
    return _guard(core.export_md, user, issue_id)
