"""AI 流程核心：定性 / 确认定性 / 定级 / 生成修复方案。

与 issues_core 同理：HTTP 和 MCP 必须是**同一套行为**。原来 MCP 自己写了一份
简化流程，结果：不落 ai_run（Web 端「运行记录」看不到 MCP 跑的）、不写
prompt_version、事件不带 actor。抽到这里，两个入口一条路径。

错误约定同 issues_core：归属错误由 access 层抛，业务错误抛 ValueError。
"""
import json

from .access import load_issue
from .config import COMPLEXITIES, PRIORITIES, RUBRIC_VERSION, SEVERITIES
from .db import add_event, connect, get_settings, now
from .prompts import (FIX_SYSTEM, QUALIFY_SYSTEM, TRIAGE_SYSTEM, build_fix_prompt,
                      build_qualify_prompt, build_triage_prompt, extract_json)
from .channels import AIError, run_ai
from . import memory as mem


def _actor(user: dict | None) -> str:
    return (user or {}).get("displayName") or (user or {}).get("username") or "me"


def record_run(conn, issue_id: int, kind: str, result, ok: bool, error: str | None = None):
    """落一条 ai_run。失败也要记，出问题能回看当时模型返回了什么。"""
    conn.execute(
        "INSERT INTO ai_run(issue_id, kind, provider, model, duration_ms, ok, error, output, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (issue_id, kind,
         getattr(result, "provider", "-"), getattr(result, "model", "-"),
         getattr(result, "duration_ms", 0), 1 if ok else 0, error,
         (getattr(result, "text", "") or "")[:20000], now()),
    )


def _issue_images(issue_id: int) -> list[str]:
    """附件图片绝对路径；vision 层会过滤非图片/超大/读失败的。"""
    from .config import ATTACH_DIR
    with connect() as conn:
        rows = conn.execute("SELECT path FROM attachment WHERE issue_id = ?",
                            (issue_id,)).fetchall()
    return [str(ATTACH_DIR / r["path"]) for r in rows]


def _common_cwd(scopes: list[str]) -> str | None:
    """多个目录时取公共父目录，让 agent 能跨项目搜索；单目录直接用。"""
    import os
    if not scopes:
        return None
    if len(scopes) == 1:
        return scopes[0]
    try:
        return os.path.commonpath([str(x) for x in scopes])
    except ValueError:
        return None


def _json_list(raw) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


# ---------------- 定性 ----------------

def qualify(user: dict | None, issue_id: int, channel_id: int | None = None) -> dict:
    """AI 定性：把甲方原话整理成结构化描述（草稿，需人工确认）。"""
    from .config import ATTACH_DIR
    with connect() as conn:
        issue = load_issue(conn, issue_id, user)
        attachments = [str(a["path"]) for a in conn.execute(
            "SELECT path FROM attachment WHERE issue_id = ?", (issue_id,)).fetchall()]
    paths = [str(ATTACH_DIR / p) for p in attachments]
    prompt = build_qualify_prompt(issue, paths)
    try:
        block = mem.build_memory_block(issue, current_kind="qualify")
        result = run_ai(channel_id or None, prompt, QUALIFY_SYSTEM,
                        issue_id=issue_id, kind="qualify", memory_block=block,
                        images=paths)
        data = extract_json(result.text)
    except (AIError, ValueError) as ex:
        with connect() as conn:
            record_run(conn, issue_id, "qualify", None, False, str(ex))
        raise ValueError(f"定性失败：{ex}") from ex
    with connect() as conn:
        record_run(conn, issue_id, "qualify", result, True)
        conn.execute(
            "UPDATE issue SET qualify_draft = ?, prompt_version = ?, updated_at = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), RUBRIC_VERSION, now(), issue_id))
        add_event(conn, issue_id, "qualify", note=f"AI 定性（{result.provider}）",
                  actor=_actor(user))
    return {"draft": data, "provider": result.provider, "model": result.model,
            "durationMs": result.duration_ms, "rounds": result.rounds,
            "toolCalls": result.tool_calls}


# ---------------- 确认定性 ----------------

def confirm_qualify(user: dict | None, issue_id: int, data: dict) -> dict:
    data = dict(data or {})
    with connect() as conn:
        # 先校验归属再看参数：否则 400 本身就是「这个 id 存在」的探测信号
        issue = load_issue(conn, issue_id, user)
        if not (data.get("phenomenon") or "").strip():
            raise ValueError("请先填写「现象」再确认")
        conn.execute(
            "UPDATE issue SET qualify_final = ?, title = ?, module = ?, status = ?, updated_at = ? "
            "WHERE id = ?",
            (json.dumps(data, ensure_ascii=False),
             data.get("title") or issue["title"],
             data.get("module") or issue["module"],
             "待定级", now(), issue_id),
        )
        add_event(conn, issue_id, "confirm", from_status=issue["status"], to_status="待定级",
                  note="人工确认定性结果", actor=_actor(user))
    return {"ok": True, "status": "待定级"}


# ---------------- 定级 ----------------

def triage(user: dict | None, issue_id: int, channel_id: int | None = None) -> dict:
    with connect() as conn:
        issue = load_issue(conn, issue_id, user)
    if not issue.get("qualify_final"):
        raise ValueError("还没有确认过的问题描述，先完成定性确认")
    confirmed = json.loads(issue["qualify_final"])
    prompt = build_triage_prompt(confirmed)
    try:
        block = mem.build_memory_block(issue, current_kind="triage")
        result = run_ai(channel_id or None, prompt, TRIAGE_SYSTEM,
                        issue_id=issue_id, kind="triage", memory_block=block,
                        images=_issue_images(issue_id))
        data = extract_json(result.text)
    except (AIError, ValueError) as ex:
        with connect() as conn:
            record_run(conn, issue_id, "triage", None, False, str(ex))
        raise ValueError(f"定级失败：{ex}") from ex
    if (data.get("severity") not in SEVERITIES or data.get("complexity") not in COMPLEXITIES
            or data.get("priority") not in PRIORITIES):
        with connect() as conn:
            record_run(conn, issue_id, "triage", None, False, f"取值非法：{data}")
        raise ValueError(f"定级结果取值非法：{data}")
    with connect() as conn:
        record_run(conn, issue_id, "triage", result, True)
        conn.execute(
            "UPDATE issue SET triage = ?, severity = ?, complexity = ?, priority = ?, status = ?, "
            "updated_at = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), data["severity"], data["complexity"],
             data["priority"], "待处理", now(), issue_id))
        add_event(conn, issue_id, "triage", from_status=issue["status"], to_status="待处理",
                  note=f"AI 定级：{data['priority']} / {data['severity']} / {data['complexity']}",
                  actor=_actor(user))
    return {"triage": data, "provider": result.provider, "model": result.model,
            "durationMs": result.duration_ms}


# ---------------- 修复方案（只读分析） ----------------

def fix_plan(user: dict | None, issue_id: int, channel_id: int | None = None,
             code_scopes: list[str] | None = None) -> dict:
    """让 agent 在代码目录里定位根因并给方案（不改代码）。

    代码范围优先级：调用方显式给的 → issue 自己勾的 → 项目仓库 → 全局 repo.root。
    """
    from .fix import ignore_list, list_attempts, project_notes
    with connect() as conn:
        issue = load_issue(conn, issue_id, user)
    if not issue.get("qualify_final"):
        raise ValueError("还没有确认过的问题描述，先完成定性")
    confirmed = json.loads(issue["qualify_final"])

    scopes = [s.strip() for s in (code_scopes or []) if s and s.strip()]
    if not scopes:
        scopes = _json_list(issue.get("code_scopes"))
    if not scopes and issue.get("project_id"):
        from . import projects as proj
        scopes = (proj.get_project(issue["project_id"]) or {}).get("repos") or []
    if not scopes:
        scopes = [(get_settings().get("repo.root") or "").strip()]
    scopes = [s for s in scopes if s]
    cwd = _common_cwd(scopes)
    prompt = build_fix_prompt(confirmed, scopes, ignore_list(), project_notes())
    try:
        block = mem.build_memory_block(issue, list_attempts(issue_id), current_kind="analysis")
        result = run_ai(channel_id or None, prompt, FIX_SYSTEM, cwd=cwd,
                        issue_id=issue_id, kind="analysis", memory_block=block,
                        images=_issue_images(issue_id))
        data = extract_json(result.text)
    except (AIError, ValueError) as ex:
        with connect() as conn:
            record_run(conn, issue_id, "fix", None, False, str(ex))
        raise ValueError(f"生成修复方案失败：{ex}") from ex
    with connect() as conn:
        record_run(conn, issue_id, "fix", result, True)
        conn.execute("UPDATE issue SET fix_plan = ?, status = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), "处理中", now(), issue_id))
        add_event(conn, issue_id, "fix", from_status=issue["status"], to_status="处理中",
                  note=f"AI 生成修复方案（{result.provider}）", actor=_actor(user))
    return {"plan": data, "provider": result.provider, "model": result.model,
            "durationMs": result.duration_ms}
