"""AI 相关接口：定性 / 确认定性 / 定级 / 生成修复方案。

每次调用都落一条 ai_run（成功失败都记），出问题能回看当时模型返回了什么。
"""
import json

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..config import COMPLEXITIES, PRIORITIES, RUBRIC_VERSION, SEVERITIES
from ..db import add_event, connect, get_settings, now
from ..fix import ignore_list, project_notes
from ..prompts import (QUALIFY_SYSTEM, FIX_SYSTEM, TRIAGE_SYSTEM, build_fix_prompt,
                       build_qualify_prompt, build_triage_prompt, extract_json)
from ..schemas import AIRequest, FixRequest, QualifyConfirm
from ..providers import AIError, run_ai

router = APIRouter(prefix="/api/issues", tags=["ai"])


def _issue(conn, issue_id: int) -> dict:
    row = conn.execute("SELECT * FROM issue WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "问题不存在")
    return dict(row)


def _record_run(conn, issue_id: int, kind: str, result, ok: bool, error: str | None = None):
    conn.execute(
        "INSERT INTO ai_run(issue_id, kind, provider, model, duration_ms, ok, error, output, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (issue_id, kind,
         getattr(result, "provider", "-"), getattr(result, "model", "-"),
         getattr(result, "duration_ms", 0), 1 if ok else 0, error,
         (getattr(result, "text", "") or "")[:20000], now()),
    )


def _json_list(raw) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _common_cwd(scopes: list[str]) -> str | None:
    """多个目录时取公共父目录，让 agent 能跨项目搜索；单目录直接用它。"""
    if not scopes:
        return None
    if len(scopes) == 1:
        return scopes[0]
    import os
    try:
        return os.path.commonpath([str(Path(x).resolve()) for x in scopes])
    except ValueError:
        return None


@router.post("/{issue_id}/qualify")
def qualify(issue_id: int, payload: AIRequest):
    """AI 定性：把甲方原话整理成结构化问题描述（草稿，需人工确认）。"""
    with connect() as conn:
        issue = _issue(conn, issue_id)
        attachments = [str(a["path"]) for a in conn.execute(
            "SELECT path FROM attachment WHERE issue_id = ?", (issue_id,)).fetchall()]
    # 附件转绝对路径，带工具的 agent（claude/dsh）能直接打开图片
    from ..config import ATTACH_DIR
    paths = [str(ATTACH_DIR / p) for p in attachments]
    prompt = build_qualify_prompt(issue, paths)
    try:
        result = run_ai(payload.provider or "", prompt, QUALIFY_SYSTEM)
        data = extract_json(result.text)
    except (AIError, ValueError) as ex:
        with connect() as conn:
            _record_run(conn, issue_id, "qualify", None, False, str(ex))
        raise HTTPException(502, f"定性失败：{ex}")
    with connect() as conn:
        _record_run(conn, issue_id, "qualify", result, True)
        conn.execute("UPDATE issue SET qualify_draft = ?, prompt_version = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), RUBRIC_VERSION, now(), issue_id))
        add_event(conn, issue_id, "qualify", note=f"AI 定性（{result.provider}）")
    return {"draft": data, "provider": result.provider, "model": result.model,
            "durationMs": result.duration_ms}


@router.post("/{issue_id}/qualify/confirm")
def confirm_qualify(issue_id: int, payload: QualifyConfirm):
    """人工确认定性结果：确认后才允许进入定级。"""
    data = payload.model_dump()
    if not (data.get("phenomenon") or "").strip():
        raise HTTPException(400, "请先填写「现象」再确认")
    with connect() as conn:
        issue = _issue(conn, issue_id)
        conn.execute(
            "UPDATE issue SET qualify_final = ?, title = ?, module = ?, status = ?, updated_at = ? "
            "WHERE id = ?",
            (json.dumps(data, ensure_ascii=False),
             data.get("title") or issue["title"],
             data.get("module") or issue["module"],
             "待定级", now(), issue_id),
        )
        add_event(conn, issue_id, "confirm", from_status=issue["status"], to_status="待定级",
                  note="人工确认定性结果")
    return {"ok": True, "status": "待定级"}


@router.post("/{issue_id}/triage")
def triage(issue_id: int, payload: AIRequest):
    """AI 定级：基于已确认的描述给出 S/复杂度/P，并把结果写回问题。"""
    with connect() as conn:
        issue = _issue(conn, issue_id)
    if not issue.get("qualify_final"):
        raise HTTPException(400, "还没有确认过的问题描述，先完成定性确认")
    confirmed = json.loads(issue["qualify_final"])
    prompt = build_triage_prompt(confirmed)
    try:
        result = run_ai(payload.provider or "", prompt, TRIAGE_SYSTEM)
        data = extract_json(result.text)
    except (AIError, ValueError) as ex:
        with connect() as conn:
            _record_run(conn, issue_id, "triage", None, False, str(ex))
        raise HTTPException(502, f"定级失败：{ex}")
    severity = data.get("severity")
    complexity = data.get("complexity")
    priority = data.get("priority")
    if severity not in SEVERITIES or complexity not in COMPLEXITIES or priority not in PRIORITIES:
        with connect() as conn:
            _record_run(conn, issue_id, "triage", None, False, f"取值非法：{data}")
        raise HTTPException(502, f"定级结果取值非法：{data}")
    with connect() as conn:
        _record_run(conn, issue_id, "triage", result, True)
        conn.execute(
            "UPDATE issue SET triage = ?, severity = ?, complexity = ?, priority = ?, status = ?, "
            "updated_at = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), severity, complexity, priority,
             "待处理", now(), issue_id),
        )
        add_event(conn, issue_id, "triage", from_status=issue["status"], to_status="待处理",
                  note=f"AI 定级：{priority} / {severity} / {complexity}")
    return {"triage": data, "provider": result.provider, "durationMs": result.duration_ms}


@router.post("/{issue_id}/fix")
def make_fix_plan(issue_id: int, payload: FixRequest):
    """「操作解决」第一步：让 agent 在仓库里定位根因并给方案（不改代码）。"""
    with connect() as conn:
        issue = _issue(conn, issue_id)
    if not issue.get("qualify_final"):
        raise HTTPException(400, "还没有确认过的问题描述，先完成定性")
    confirmed = json.loads(issue["qualify_final"])
    scopes = _json_list(issue.get("code_scopes")) or [(get_settings().get("repo.root") or "").strip()]
    scopes = [s for s in scopes if s]
    cwd = _common_cwd(scopes)
    prompt = build_fix_prompt(confirmed, scopes, ignore_list(), project_notes())
    try:
        result = run_ai(payload.provider or "", prompt, FIX_SYSTEM, cwd=cwd)
        data = extract_json(result.text)
    except (AIError, ValueError) as ex:
        with connect() as conn:
            _record_run(conn, issue_id, "fix", None, False, str(ex))
        raise HTTPException(502, f"生成修复方案失败：{ex}")
    with connect() as conn:
        _record_run(conn, issue_id, "fix", result, True)
        conn.execute("UPDATE issue SET fix_plan = ?, status = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), "处理中", now(), issue_id))
        add_event(conn, issue_id, "fix", from_status=issue["status"], to_status="处理中",
                  note=f"AI 生成修复方案（{result.provider}）")
    return {"plan": data, "provider": result.provider, "durationMs": result.duration_ms}
