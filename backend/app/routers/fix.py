"""「操作解决」：分析（只读）→ 改代码（worktree）→ 采纳/驳回。

和 routers/ai.py 的分工：
- /fix           只读分析，产出方案
- /fix/apply     在 git worktree 里让 agent 真的改
- /fix/diff      重新收集 diff（人工改过也能看到）
- /fix/accept    提交到分支，仓库干净时 ff 合回主分支
- /fix/reject    丢弃 worktree 和分支
"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..db import add_event, connect, get_settings, now
from ..fix import (FixError, collect_diff, commit_all, create_worktree, current_branch,
                   drop_worktree, ignore_list, is_repo_root, list_code_roots,
                   merge_to_base, project_notes, worktree_path)
from ..prompts import APPLY_SYSTEM, build_apply_prompt
from ..providers import AIError, run_ai
from ..schemas import FixAcceptReq, FixApplyReq

router = APIRouter(prefix="/api", tags=["fix"])

# 只有能改文件的 agent 允许跑 apply（DeepSeek API 只能出文本）
WRITE_PROVIDERS = {"claude", "dsh"}


def _issue(conn, issue_id: int) -> dict:
    row = conn.execute("SELECT * FROM issue WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "问题不存在")
    return dict(row)


def _json(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _record_run(conn, issue_id: int, kind: str, result, ok: bool, error: str | None = None):
    conn.execute(
        "INSERT INTO ai_run(issue_id, kind, provider, model, duration_ms, ok, error, output, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (issue_id, kind, getattr(result, "provider", "-"), getattr(result, "model", "-"),
         getattr(result, "duration_ms", 0), 1 if ok else 0, error,
         (getattr(result, "text", "") or "")[:20000], now()))


@router.get("/code/roots")
def code_roots():
    """代码范围候选：设置里配的目录，带是否 git 仓库标记。"""
    return {"roots": list_code_roots(), "ignore": ignore_list(),
            "projectNotes": project_notes()}


@router.post("/issues/{issue_id}/fix/apply")
def apply_fix(issue_id: int, payload: FixApplyReq):
    with connect() as conn:
        issue = _issue(conn, issue_id)
    if not issue.get("qualify_final"):
        raise HTTPException(400, "还没有确认过的问题描述，先完成定性")
    confirmed = json.loads(issue["qualify_final"])

    repo = (payload.repo or issue.get("target_repo") or "").strip()
    if not repo:
        raise HTTPException(400, "请先选择目标仓库（详情页「代码范围」里标了 git 的那一个）")
    if not is_repo_root(repo):
        raise HTTPException(400, f"{repo} 不是 git 仓库根目录，不能作为修改目标")

    settings = get_settings()
    provider = (payload.provider or settings.get("ai.provider") or "").strip().lower()
    if provider not in WRITE_PROVIDERS:
        raise HTTPException(
            400, f"当前执行器 {provider or '未配置'} 不能改代码；请切到 claude 或 dsh（它们能在工作目录里编辑文件）")

    plan = _json(issue.get("fix_plan"))
    try:
        info = create_worktree(repo, issue_id)
    except FixError as ex:
        raise HTTPException(400, str(ex))

    prompt = build_apply_prompt(confirmed, info["worktree"], plan)
    try:
        # 改代码比分析慢，单独给 10 分钟，不吃全局 ai.timeout
        result = run_ai(provider, prompt, APPLY_SYSTEM, cwd=info["worktree"],
                        timeout=max(int(settings.get("ai.timeout") or 180), 600),
                        allow_write=True)
    except AIError as ex:
        drop_worktree(repo, issue_id)
        with connect() as conn:
            _record_run(conn, issue_id, "apply", None, False, str(ex))
        raise HTTPException(502, f"修改失败：{ex}")

    try:
        diff = collect_diff(info["worktree"])
    except FixError as ex:
        diff = {"stat": "", "diff": "", "files": [], "empty": True, "error": str(ex)}

    state = {
        **info,
        "provider": result.provider,
        "duration_ms": result.duration_ms,
        "summary": (result.text or "")[:4000],
        "diff_stat": diff.get("stat", ""),
        "files": diff.get("files", []),
        "created_at": now(),
        "accepted": False,
    }
    with connect() as conn:
        _record_run(conn, issue_id, "apply", result, True)
        conn.execute("UPDATE issue SET fix_state = ?, status = '处理中', updated_at = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), now(), issue_id))
        add_event(conn, issue_id, "fix_apply", from_status=issue["status"], to_status="处理中",
                  note=f"worktree 修改（{result.provider}）{len(state['files'])} 个文件")
    return {"state": state, "diff": diff, "summary": state["summary"]}


@router.get("/issues/{issue_id}/fix/diff")
def fix_diff(issue_id: int):
    with connect() as conn:
        issue = _issue(conn, issue_id)
    state = _json(issue.get("fix_state"))
    if not state:
        raise HTTPException(404, "还没有开始修改")
    try:
        diff = collect_diff(state["worktree"])
    except FixError as ex:
        raise HTTPException(400, str(ex))
    state["diff_stat"] = diff.get("stat", "")
    state["files"] = diff.get("files", [])
    with connect() as conn:
        conn.execute("UPDATE issue SET fix_state = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), now(), issue_id))
    return {"state": state, "diff": diff}


@router.post("/issues/{issue_id}/fix/accept")
def accept_fix(issue_id: int, payload: FixAcceptReq):
    with connect() as conn:
        issue = _issue(conn, issue_id)
    state = _json(issue.get("fix_state"))
    if not state:
        raise HTTPException(404, "还没有开始修改")
    if state.get("accepted"):
        return {"ok": True, "already": True, "state": state}

    message = (payload.message or "").strip() or f"fix(issue-{issue_id}): {issue['title']}"
    try:
        committed = commit_all(state["worktree"], message)
    except FixError as ex:
        raise HTTPException(400, str(ex))
    if not committed:
        raise HTTPException(400, "worktree 里没有改动，没什么可采纳的")

    merge_result = {"merged": False, "reason": "按请求不自动合并"}
    if payload.merge:
        try:
            merge_result = merge_to_base(state["repo"], state["branch"])
        except FixError as ex:
            merge_result = {"merged": False, "reason": str(ex),
                            "command": f"git -C {state['repo']} merge {state['branch']}"}

    state.update({
        "accepted": True,
        "accepted_at": now(),
        "commit_message": message,
        "merge": merge_result,
    })
    with connect() as conn:
        conn.execute("UPDATE issue SET fix_state = ?, status = '待验收', updated_at = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), now(), issue_id))
        add_event(conn, issue_id, "fix_accept", from_status=issue["status"], to_status="待验收",
                  note=("已合并到 " + merge_result.get("base_branch", "")) if merge_result.get("merged")
                  else "已提交到分支，需人工合并")
    return {"ok": True, "commit": committed, "merge": merge_result, "state": state}


@router.post("/issues/{issue_id}/fix/reject")
def reject_fix(issue_id: int):
    with connect() as conn:
        issue = _issue(conn, issue_id)
    state = _json(issue.get("fix_state"))
    if not state:
        return {"ok": True}
    try:
        drop_worktree(state["repo"], issue_id)
    except Exception:
        pass
    with connect() as conn:
        conn.execute("UPDATE issue SET fix_state = NULL, status = '待处理', updated_at = ? WHERE id = ?",
                     (now(), issue_id))
        add_event(conn, issue_id, "fix_reject", from_status=issue["status"], to_status="待处理",
                  note="已丢弃 worktree 与分支")
    return {"ok": True}
