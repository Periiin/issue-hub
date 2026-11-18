"""issue-hub 的 MCP Server（stdio）。

作用：让 AI 会话直接读写 issue 库，不用开网页点。

配到 ZCode（~/.zcode/cli/config.json）：
{
  "mcp": {
    "servers": {
      "issue-hub": {
        "type": "stdio",
        "command": "/src/issue-hub/backend/.venv-mcp/bin/python",
        "args": ["/src/issue-hub/backend/mcp_server.py"],
        "env": {}
      }
    }
  }
}

调试：
  printf '%s\\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' \
                '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
                '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | .venv-mcp/bin/python mcp_server.py
"""
import json
import sys
from pathlib import Path

# 让 `app` 包可导入（脚本在 backend/ 下）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app.config import ALL_STATUS, ATTACH_DIR, COMPLEXITIES, PRIORITIES, SEVERITIES  # noqa: E402
from app.db import add_event, connect, get_settings, init_db, list_rows, now, valid_status  # noqa: E402
from app.prompts import (FIX_SYSTEM, QUALIFY_SYSTEM, TRIAGE_SYSTEM, build_fix_prompt,  # noqa: E402
                         build_qualify_prompt, build_triage_prompt, extract_json)
from app.channels import AIError, run_ai  # noqa: E402

mcp = FastMCP("issue-hub")


# ---------- 内部工具 ----------

def _issue(issue_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM issue WHERE id = ?", (issue_id,)).fetchone()
    return dict(row) if row else None


def _parse(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _brief(row: dict) -> dict:
    return {k: row.get(k) for k in (
        "id", "title", "status", "priority", "severity", "complexity",
        "module", "reporter", "created_at", "updated_at")}


# ---------- 工具 ----------

@mcp.tool()
def list_issues(status: str = "", priority: str = "", module: str = "",
                q: str = "", limit: int = 50) -> dict:
    """列出问题，可按状态/优先级/模块/关键词筛选。返回精简列表 + 各状态数量。"""
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
    args.append(max(1, min(int(limit or 50), 200)))
    with connect() as conn:
        rows = list_rows(conn.execute(sql, args).fetchall())
        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) n FROM issue GROUP BY status").fetchall()}
    return {"list": [_brief(r) for r in rows], "counts": counts, "statuses": ALL_STATUS}


@mcp.tool()
def get_issue(issue_id: int) -> dict:
    """取一条问题的完整信息：原文、已确认描述、定级、修复方案、附件、时间线。"""
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    with connect() as conn:
        attachments = list_rows(conn.execute(
            "SELECT id, filename, path, mime, size FROM attachment WHERE issue_id = ?",
            (issue_id,)).fetchall())
        events = list_rows(conn.execute(
            "SELECT type, from_status, to_status, note, created_at FROM event "
            "WHERE issue_id = ? ORDER BY id DESC LIMIT 20", (issue_id,)).fetchall())
    for key in ("qualify_draft", "qualify_final", "triage", "fix_plan"):
        row[key] = _parse(row.get(key))
    for a in attachments:
        a["abs_path"] = str(ATTACH_DIR / a["path"])
    return {"issue": row, "attachments": attachments, "events": events}


@mcp.tool()
def create_issue(title: str, raw_text: str = "", reporter: str = "",
                 module: str = "", source: str = "manual") -> dict:
    """新建问题。title 为空时用原文前 30 字。"""
    title = (title or "").strip() or (raw_text or "").strip()[:30] or "未命名问题"
    ts = now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO issue(title, raw_text, source, reporter, module, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '待定性', ?, ?)",
            (title, raw_text, source, reporter, module, ts, ts))
        issue_id = cur.lastrowid
        add_event(conn, issue_id, "create", to_status="待定性", note="MCP 新建")
    return {"id": issue_id, "status": "待定性"}


@mcp.tool()
def update_issue(issue_id: int, status: str = "", title: str = "", module: str = "",
                 reporter: str = "", severity: str = "", complexity: str = "",
                 priority: str = "") -> dict:
    """改问题字段：状态/标题/模块/提出人/影响等级/复杂度/优先级。传空字符串表示不改。"""
    if status and not valid_status(status):
        return {"error": f"非法状态：{status}，可选 {ALL_STATUS}"}
    if severity and severity not in SEVERITIES:
        return {"error": f"影响等级只能是 {SEVERITIES}"}
    if complexity and complexity not in COMPLEXITIES:
        return {"error": f"复杂度只能是 {COMPLEXITIES}"}
    if priority and priority not in PRIORITIES:
        return {"error": f"优先级只能是 {PRIORITIES}"}
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    data = {k: v for k, v in {
        "status": status, "title": title, "module": module, "reporter": reporter,
        "severity": severity, "complexity": complexity, "priority": priority}.items() if v}
    if not data:
        return {"ok": True, "changed": []}
    data["updated_at"] = now()
    sets = ", ".join(f"{k} = ?" for k in data)
    with connect() as conn:
        conn.execute(f"UPDATE issue SET {sets} WHERE id = ?", [*data.values(), issue_id])
        if status and status != row["status"]:
            add_event(conn, issue_id, "status", from_status=row["status"], to_status=status,
                      note="MCP 修改")
    return {"ok": True, "changed": list(data.keys())}


@mcp.tool()
def add_note(issue_id: int, note: str) -> dict:
    """给问题加一条备注（写进时间线，不改变状态）。"""
    if not _issue(issue_id):
        return {"error": f"问题 #{issue_id} 不存在"}
    with connect() as conn:
        add_event(conn, issue_id, "note", note=note)
    return {"ok": True}


@mcp.tool()
def run_qualify(issue_id: int, channel_id: int = 0) -> dict:
    """跑 AI 定性，返回结构化草稿（不落库为最终值，需要人工确认）。channel_id 传 0 用默认通道。"""
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    with connect() as conn:
        paths = [str(ATTACH_DIR / a["path"]) for a in conn.execute(
            "SELECT path FROM attachment WHERE issue_id = ?", (issue_id,)).fetchall()]
    prompt = build_qualify_prompt(row, paths)
    try:
        result = run_ai(channel_id or None, prompt, QUALIFY_SYSTEM)
        data = extract_json(result.text)
    except (AIError, ValueError) as ex:
        return {"error": str(ex)}
    with connect() as conn:
        conn.execute("UPDATE issue SET qualify_draft = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), now(), issue_id))
        add_event(conn, issue_id, "qualify", note=f"MCP 定性（{result.provider}）")
    return {"draft": data, "provider": result.provider, "duration_ms": result.duration_ms}


@mcp.tool()
def confirm_qualify(issue_id: int, phenomenon: str, title: str = "",
                    repro_steps: str = "", expected: str = "", actual: str = "",
                    scope: str = "", module: str = "", uncertainties: str = "") -> dict:
    """确认定性结果并进入「待定级」。repro_steps / uncertainties 用换行分隔多条。"""
    if not phenomenon.strip():
        return {"error": "phenomenon 不能为空"}
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    data = {
        "title": (title or "").strip() or row["title"],
        "phenomenon": phenomenon.strip(),
        "repro_steps": [s.strip() for s in repro_steps.splitlines() if s.strip()],
        "expected": expected.strip(),
        "actual": actual.strip(),
        "scope": scope.strip(),
        "module": module.strip() or row.get("module") or "",
        "uncertainties": [s.strip() for s in uncertainties.splitlines() if s.strip()],
        "tags": [],
    }
    with connect() as conn:
        conn.execute(
            "UPDATE issue SET qualify_final = ?, title = ?, module = ?, status = '待定级', "
            "updated_at = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), data["title"], data["module"], now(), issue_id))
        add_event(conn, issue_id, "confirm", from_status=row["status"], to_status="待定级",
                  note="MCP 确认定性")
    return {"ok": True, "status": "待定级"}


@mcp.tool()
def run_triage(issue_id: int, channel_id: int = 0) -> dict:
    """基于已确认描述跑 AI 定级，返回 S/复杂度/P 并写回问题（状态变「待处理」）。"""
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    if not row.get("qualify_final"):
        return {"error": "还没确认过定性，先 confirm_qualify"}
    confirmed = json.loads(row["qualify_final"])
    try:
        result = run_ai(channel_id or None, build_triage_prompt(confirmed), TRIAGE_SYSTEM)
        data = extract_json(result.text)
    except (AIError, ValueError) as ex:
        return {"error": str(ex)}
    if data.get("severity") not in SEVERITIES or data.get("complexity") not in COMPLEXITIES \
            or data.get("priority") not in PRIORITIES:
        return {"error": f"定级结果取值非法：{data}"}
    with connect() as conn:
        conn.execute(
            "UPDATE issue SET triage = ?, severity = ?, complexity = ?, priority = ?, "
            "status = '待处理', updated_at = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), data["severity"], data["complexity"],
             data["priority"], now(), issue_id))
        add_event(conn, issue_id, "triage", from_status=row["status"], to_status="待处理",
                  note=f"MCP 定级：{data['priority']} / {data['severity']}")
    return {"triage": data, "provider": result.provider}


@mcp.tool()
def make_fix_plan(issue_id: int, channel_id: int = 0, code_scope: str = "") -> dict:
    """让 agent 在代码目录里定位根因、给修复方案（只读，不改代码）。

    code_scope 为空时用设置里的 repo.root；也可以临时指定一个或多个目录（逗号分隔），
    这时会把它们列进提示词，cwd 用第一个目录的父目录，方便跨项目搜索。
    """
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    if not row.get("qualify_final"):
        return {"error": "还没确认过定性"}
    confirmed = json.loads(row["qualify_final"])
    settings = get_settings()
    scopes = [s.strip() for s in (code_scope or "").split(",") if s.strip()]
    root = scopes[0] if scopes else (settings.get("repo.root") or "").strip()
    cwd = root
    if len(scopes) > 1:
        try:
            cwd = str(Path(*Path(scopes[0]).parts[:len(Path(scopes[0]).parts) - 1]))
        except Exception:
            cwd = root
    from app.fix import ignore_list, project_notes
    prompt = build_fix_prompt(confirmed, scopes or ([root] if root else []),
                              ignore_list(), project_notes())
    try:
        result = run_ai(channel_id or None, prompt, FIX_SYSTEM, cwd=cwd or None)
        data = extract_json(result.text)
    except (AIError, ValueError) as ex:
        return {"error": str(ex)}
    with connect() as conn:
        conn.execute("UPDATE issue SET fix_plan = ?, status = '处理中', updated_at = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), now(), issue_id))
        add_event(conn, issue_id, "fix", from_status=row["status"], to_status="处理中",
                  note=f"MCP 生成修复方案（{result.provider}）")
    return {"plan": data, "provider": result.provider}


@mcp.tool()
def weekly_report() -> str:
    """按优先级分组输出周报 Markdown，可直接贴给甲方或群里。"""
    with connect() as conn:
        rows = list_rows(conn.execute(
            "SELECT id, title, status, priority, severity, module, created_at "
            "FROM issue ORDER BY id DESC LIMIT 100").fetchall())
    lines = ["# 问题跟踪周报", ""]
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["priority"] or "未定级", []).append(row)
    for key in ("P0", "P1", "P2", "P3", "未定级"):
        items = groups.get(key) or []
        if not items:
            continue
        lines.append(f"## {key}（{len(items)}）")
        for row in items:
            lines.append(f"- #{row['id']} {row['title']}　[{row['status']}]"
                         f"　{row['module'] or '-'}　{row['created_at'][:10]}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def list_code_roots() -> dict:
    """列出设置里配置的代码目录，带 isGit/exists，便于决定分析范围和目标仓库。"""
    from app.fix import ignore_list, list_code_roots as _roots, project_notes
    return {"roots": _roots(), "ignore": ignore_list(), "projectNotes": project_notes()}


def _norm_state(row: dict) -> dict:
    """把 fix_state 归一化成 {repos: {path: {...}}}（兼容旧的单仓库结构）。"""
    state = _parse(row.get("fix_state")) or {}
    if not isinstance(state, dict):
        return {"repos": {}}
    if "repos" in state:
        return state
    if state.get("repo"):
        repo = state["repo"]
        inner = {k: v for k, v in state.items() if k != "repo"}
        return {"repos": {repo: {"repo": repo, **inner}}, "context": ""}
    return {"repos": {}}


@mcp.tool()
def get_fix_diff(issue_id: int) -> dict:
    """查看某个 issue 各仓库 worktree 的当前 diff（人工改过也会体现）。"""
    from app.fix import FixError, collect_diff
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    state = _norm_state(row)
    if not state.get("repos"):
        return {"error": "还没有开始修改（fix_state 为空）"}
    diffs = {}
    for repo, st in state["repos"].items():
        wt = st.get("worktree")
        if not wt:
            diffs[repo] = {"error": st.get("error") or "没有 worktree"}
            continue
        try:
            diffs[repo] = collect_diff(wt)
        except FixError as ex:
            diffs[repo] = {"error": str(ex)}
    return {"state": state, "diffs": diffs}


@mcp.tool()
def accept_fix(issue_id: int, repo: str = "", message: str = "", merge: bool = True) -> dict:
    """采纳 worktree 改动：提交到分支，主仓库干净时 ff 合并。

    多仓库时按仓库独立采纳；repo 传空表示采纳全部已成功的仓库。
    """
    from app.fix import FixError, commit_all, merge_to_base
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    state = _norm_state(row)
    repos = state.get("repos") or {}
    if not repos:
        return {"error": "还没有开始修改"}

    targets = [repo] if repo else list(repos.keys())
    results = {}
    for r in targets:
        st = repos.get(r)
        if not st:
            results[r] = {"ok": False, "error": "不在本次修改范围内"}
            continue
        if st.get("accepted"):
            results[r] = {"ok": True, "already": True}
            continue
        if st.get("status") == "failed" or not st.get("worktree"):
            results[r] = {"ok": False, "error": st.get("error") or "没有可采纳的改动"}
            continue
        msg = message.strip() or f"fix(issue-{issue_id}): {row['title']}"
        try:
            if not commit_all(st["worktree"], msg):
                results[r] = {"ok": False, "error": "worktree 里没有改动"}
                continue
        except FixError as ex:
            results[r] = {"ok": False, "error": str(ex)}
            continue
        merge_result = {"merged": False, "reason": "未请求合并"}
        if merge:
            try:
                merge_result = merge_to_base(st["repo"], st["branch"])
            except FixError as ex:
                merge_result = {"merged": False, "reason": str(ex),
                                "command": f"git -C {st['repo']} merge {st['branch']}"}
        st.update({"accepted": True, "accepted_at": now(),
                   "commit_message": msg, "merge": merge_result})
        results[r] = {"ok": True, "merge": merge_result}

    with connect() as conn:
        conn.execute("UPDATE issue SET fix_state = ?, status = '待验收', updated_at = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), now(), issue_id))
        add_event(conn, issue_id, "fix_accept", from_status=row["status"], to_status="待验收",
                  note="MCP 采纳")
    return {"ok": True, "results": results}


@mcp.tool()
def reject_fix(issue_id: int, repo: str = "") -> dict:
    """丢弃 worktree 和分支。repo 传空表示全部丢弃。"""
    from app.fix import drop_all_worktrees
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    state = _norm_state(row)
    repos = state.get("repos") or {}
    if not repos:
        return {"ok": True}
    targets = [repo] if repo else list(repos.keys())
    if repo and repo not in repos:
        return {"error": f"{repo} 不在本次修改范围内"}
    drop_all_worktrees(issue_id, targets)
    for r in targets:
        repos.pop(r, None)

    with connect() as conn:
        if repos:
            state["repos"] = repos
            conn.execute("UPDATE issue SET fix_state = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(state, ensure_ascii=False), now(), issue_id))
        else:
            conn.execute("UPDATE issue SET fix_state = NULL, status = '待处理', updated_at = ? WHERE id = ?",
                         (now(), issue_id))
        add_event(conn, issue_id, "fix_reject",
                  note=f"MCP 驳回：{repo or '全部'}")
    return {"ok": True, "repos": list(repos.keys())}


@mcp.tool()
def get_fix_attempts(issue_id: int) -> dict:
    """查看某个 issue 的修改轮次：每轮与方案的出入、过程中发现的问题、实际根因、文件改动与风险。"""
    # 注意从 app.fix 导入：app.routers.fix 会带进 fastapi，MCP venv 里没有
    from app.fix import list_attempts
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    return {"attempts": list_attempts(issue_id)}


@mcp.tool()
def get_fix_context(issue_id: int) -> dict:
    """读取该 issue 的「修复边界」上下文文件（用户可编辑，会喂给改代码的 agent）。"""
    from app import context as ctx
    row = _issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    text = ctx.read(issue_id)
    if not text:
        scopes = _parse(row.get("code_scopes")) or []
        repos = _parse(row.get("target_repos")) or ([row["target_repo"]] if row.get("target_repo") else [])
        text = ctx.ensure(issue_id, row, [{"path": r, "name": r.split("\\")[-1].split("/")[-1]} for r in repos],
                          scopes, get_settings().get("code.project_notes") or "")
    return {"text": text, "path": str(ctx.context_path(issue_id))}


if __name__ == "__main__":
    # 幂等建表：MCP 可能在 web 服务没启动时被调起（比如刚重启电脑）
    init_db()
    mcp.run(transport="stdio")
