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

身份：
  默认以「本机管理员」运行（stdio 是本机可信边界）。
  多用户部署时想限权，给 env 配 ISSUEHUB_MCP_TOKEN=<登录token>，
  就以那个用户的身份跑（看谁的问题、走谁的 owner 过滤）。
  ⚠️ 之前 MCP 完全没有身份与归属校验，是绕过权限层的旁路。

工具（30 个）：
  问题     list_issues / get_issue / create_issue / update_issue / add_note
           batch_update / batch_delete
  讨论     list_comments / add_comment / delete_comment
  关联     list_links / add_link / remove_link
  AI      run_qualify / confirm_qualify / run_triage / make_fix_plan
  修复    verify_fix / accept_fix / reject_fix / get_fix_diff / get_fix_attempts / get_fix_context
  记忆    get_memory / clear_memory
  配置    list_channels / test_channel / list_projects / list_code_roots
  审计    login_logs
  报表    weekly_report

与 Web 端行为一致：同一套归属校验、同一套记忆、同一套 ai_run 落库、
采纳前同样强制验证。**核心逻辑全部走 app.issues_core / app.ai_core /
app.report_core**——不在这里手写 SQL，大改 Web 之后 MCP 才不会悄悄退化
（这个坑已经踩过一次）。

调试：
  printf '%s\\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' \
                '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
                '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | .venv-mcp/bin/python mcp_server.py
"""
import json
import os
import sys
from pathlib import Path

# 让 `app` 包可导入（脚本在 backend/ 下）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app.access import AccessDenied  # noqa: E402
from app.issues_core import PermissionDenied  # noqa: E402
from app.db import connect, get_settings, init_db, now  # noqa: E402
from app.channels import AIError  # noqa: E402
from app import issues_core as icore  # noqa: E402
from app import ai_core as acore  # noqa: E402
from app import report_core as rcore  # noqa: E402
from app import memory as mem  # noqa: E402

mcp = FastMCP("issue-hub")


# ---------- 身份 ----------

def _user() -> dict:
    """MCP 的运行身份。

    env 配了 ISSUEHUB_MCP_TOKEN → 按该 token 的用户跑（可受限账号）；
    没配 → 本机管理员。token 失效时明确报错，而不是静默变成 admin。
    """
    token = (os.getenv("ISSUEHUB_MCP_TOKEN") or "").strip()
    if not token:
        return {"id": 0, "username": "local", "displayName": "本机", "role": "admin"}
    from app import auth as auth_mod
    user = auth_mod.get_session_user(token)
    if not user:
        raise RuntimeError(
            "ISSUEHUB_MCP_TOKEN 已失效，请重新登录并在 MCP 配置里更新 token")
    return user


def _guard(fn, *args, **kwargs):
    """统一把 core 层异常转成 MCP 的 {"error": ...}，别在每个工具里重复。"""
    try:
        return fn(*args, **kwargs)
    except AccessDenied as ex:
        return {"error": str(ex)}
    except PermissionDenied as ex:
        return {"error": str(ex)}
    except ValueError as ex:
        return {"error": str(ex)}
    except AIError as ex:
        return {"error": str(ex)}
    except RuntimeError as ex:
        return {"error": str(ex)}


def _issue_or_none(issue_id: int) -> dict | None:
    """仅用于给错误信息带上 id 的旧式检查（归属校验一律走 core 层）。"""
    with connect() as conn:
        row = conn.execute("SELECT id FROM issue WHERE id = ?", (issue_id,)).fetchone()
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
        "module", "reporter", "assignee", "due_date", "project_id",
        "created_at", "updated_at")}


# ---------- 问题 ----------

@mcp.tool()
def list_issues(status: str = "", priority: str = "", module: str = "",
                q: str = "", tag: str = "", assignee: str = "",
                due: str = "", mine: str = "", project_id: int = 0,
                limit: int = 50, offset: int = 0) -> dict:
    """列出问题，可按状态/优先级/模块/关键词/标签/负责人/截止/项目筛选。

    q 会搜标题、原文、确认后描述、模块、提出人、标签。
    project_id 传 -1 表示只看「未归属」；due 传 overdue 或 week；
    mine 传 assigned（分配给我的）或 reported（我提的）。
    返回精简列表 + 各状态数量 + 各项目数量 + total（配合 offset 分页）。
    """
    u = _user()
    r = _guard(icore.list_issues, u, status=status, priority=priority, module=module,
               q=q, tag=tag, assignee=assignee, due=due, mine=mine,
               project_id=project_id, limit=limit, offset=offset)
    if "error" in r:
        return r
    r["list"] = [_brief(x) for x in r["list"]]
    return r


@mcp.tool()
def get_issue(issue_id: int) -> dict:
    """取一条问题的完整信息：原文、已确认描述、定级、修复方案、附件、时间线、评论。"""
    u = _user()
    r = _guard(icore.get_issue, u, issue_id)
    if "error" in r:
        return r
    r["comments"] = _guard(icore.list_comments, u, issue_id).get("comments", [])
    return r


@mcp.tool()
def create_issue(title: str, raw_text: str = "", reporter: str = "",
                 module: str = "", source: str = "manual",
                 project_id: int = 0) -> dict:
    """新建问题。title 为空时用原文前 30 字；project_id 不传时按模块名/路径自动猜。"""
    nid = _guard(icore.create_issue, _user(), title=title, raw_text=raw_text,
                 reporter=reporter, module=module, source=source,
                 project_id=project_id or None)
    return {"id": nid, "status": "待定性"}


@mcp.tool()
def update_issue(issue_id: int, status: str = "", title: str = "", module: str = "",
                 reporter: str = "", severity: str = "", complexity: str = "",
                 priority: str = "", assignee: str = "", due_date: str = "",
                 project_id: int = 0, tags: str = "") -> dict:
    """改问题字段。传空字符串表示不改；tags 用逗号分隔（整组覆盖）；
    project_id 传正数设置归属、传 -1 取消归属、传 0 不动。"""
    data: dict = {}
    for key, val in (("status", status), ("title", title), ("module", module),
                     ("reporter", reporter), ("severity", severity),
                     ("complexity", complexity), ("priority", priority),
                     ("assignee", assignee), ("due_date", due_date)):
        if val:
            data[key] = val
    if tags:
        data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    if project_id > 0:
        data["project_id"] = project_id
    elif project_id == -1:
        # -1 = 显式取消归属（0 表示「没传」，避免误清）
        data["project_id"] = None
    return _guard(icore.patch_issue, _user(), issue_id, data)


@mcp.tool()
def add_note(issue_id: int, note: str) -> dict:
    """给问题加一条备注（写进时间线，不改变状态）。要参与讨论请用 add_comment。"""
    if not _issue_or_none(issue_id):
        return {"error": f"问题 #{issue_id} 不存在"}
    from app.db import add_event
    with connect() as conn:
        add_event(conn, issue_id, "note", note=note, actor=_user().get("displayName") or "MCP")
    return {"ok": True}


@mcp.tool()
def batch_update(ids: list[int], status: str = "", priority: str = "",
                 assignee: str = "", due_date: str = "", module: str = "",
                 project_id: int = 0, add_tags: str = "") -> dict:
    """批量修改。ids 是问题编号列表；无权的 id 会静默跳过（返回 skipped）。

    add_tags 用逗号分隔，是「追加」不是覆盖。
    """
    fields = {}
    for key, val in (("status", status), ("priority", priority), ("assignee", assignee),
                     ("due_date", due_date), ("module", module)):
        if val:
            fields[key] = val
    if project_id:
        fields["project_id"] = project_id
    tags = [t.strip() for t in (add_tags or "").split(",") if t.strip()]
    return _guard(icore.batch_patch, _user(), ids, fields, tags or None)


@mcp.tool()
def batch_delete(ids: list[int]) -> dict:
    """批量删除问题（附件/记录一起删）。无权的 id 会静默跳过。"""
    return _guard(icore.batch_delete, _user(), ids)


# ---------- 讨论区 ----------

@mcp.tool()
def list_comments(issue_id: int) -> dict:
    """列出问题的讨论（甲方追问、内部结论都在这里）。"""
    return _guard(icore.list_comments, _user(), issue_id)


@mcp.tool()
def add_comment(issue_id: int, body: str) -> dict:
    """给问题加一条讨论。会同时写进时间线。"""
    return _guard(icore.add_comment, _user(), issue_id, body)


@mcp.tool()
def delete_comment(issue_id: int, comment_id: int) -> dict:
    """删除一条讨论（作者本人或管理员）。"""
    return _guard(icore.delete_comment, _user(), issue_id, comment_id)


# ---------- 关联 ----------

@mcp.tool()
def list_links(issue_id: int) -> dict:
    """列出问题的关联（重复/相关/阻塞），双向可见。"""
    return _guard(icore.list_links, _user(), issue_id)


@mcp.tool()
def add_link(issue_id: int, other_id: int, kind: str = "duplicate") -> dict:
    """关联两个问题。kind: duplicate（重复）/ related（相关）/ blocks（阻塞）。"""
    return _guard(icore.add_link, _user(), issue_id, other_id, kind)


@mcp.tool()
def remove_link(issue_id: int, link_id: int) -> dict:
    """移除一条关联。"""
    return _guard(icore.remove_link, _user(), issue_id, link_id)


# ---------- AI ----------

@mcp.tool()
def run_qualify(issue_id: int, channel_id: int = 0) -> dict:
    """跑 AI 定性，返回结构化草稿（不落库为最终值，需要人工确认）。channel_id 传 0 用默认通道。"""
    return _guard(acore.qualify, _user(), issue_id, channel_id or None)


@mcp.tool()
def confirm_qualify(issue_id: int, phenomenon: str, title: str = "",
                    repro_steps: str = "", expected: str = "", actual: str = "",
                    scope: str = "", module: str = "", uncertainties: str = "") -> dict:
    """确认定性结果并进入「待定级」。repro_steps / uncertainties 用换行分隔多条。"""
    row = _issue_or_none(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    data = {
        "title": (title or "").strip(),
        "phenomenon": phenomenon.strip(),
        "repro_steps": [s.strip() for s in repro_steps.splitlines() if s.strip()],
        "expected": expected.strip(),
        "actual": actual.strip(),
        "scope": scope.strip(),
        "module": module.strip(),
        "uncertainties": [s.strip() for s in uncertainties.splitlines() if s.strip()],
        "tags": [],
    }
    return _guard(acore.confirm_qualify, _user(), issue_id, data)


@mcp.tool()
def run_triage(issue_id: int, channel_id: int = 0) -> dict:
    """基于已确认描述跑 AI 定级，返回 S/复杂度/P 并写回问题（状态变「待处理」）。"""
    return _guard(acore.triage, _user(), issue_id, channel_id or None)


@mcp.tool()
def make_fix_plan(issue_id: int, channel_id: int = 0, code_scope: str = "") -> dict:
    """让 agent 在代码目录里定位根因、给修复方案（只读，不改代码）。

    code_scope 逗号分隔可传多个目录；留空则用 issue 勾的范围 → 项目仓库 → 全局配置。
    """
    scopes = [s.strip() for s in (code_scope or "").split(",") if s.strip()]
    return _guard(acore.fix_plan, _user(), issue_id, channel_id or None, scopes or None)


# ---------- 修复（worktree） ----------

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


def _owned_issue(issue_id: int) -> dict | None:
    """带归属校验地读 issue；无权返回 None（由各工具转成 error）。"""
    try:
        from app.access import load_issue_by_id
        return load_issue_by_id(issue_id, _user())
    except AccessDenied as ex:
        return {"error": str(ex)}  # type: ignore[return-value]


@mcp.tool()
def get_fix_diff(issue_id: int) -> dict:
    """查看某个 issue 各仓库 worktree 的当前 diff（人工改过也会体现）。"""
    from app.fix import FixError, collect_diff
    row = _owned_issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    if "error" in row:  # type: ignore[operator]
        return row
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
    与 Web 端同一规则：采纳前强制验证，失败不提交。
    """
    from app.fix import FixError, commit_all, merge_to_base
    row = _owned_issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    if "error" in row:  # type: ignore[operator]
        return row
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
        # 与 Web 端一致：采纳前先验证，失败不提交
        from app import verify as vfy
        from app import projects as proj_mod
        project = proj_mod.get_project(row["project_id"]) if row.get("project_id") else None
        v = vfy.verify_worktree(st["repo"], st["worktree"], (project or {}).get("verify_cmd") or "")
        st["verify"] = v
        if v.get("ok") is False:
            results[r] = {"ok": False, "error": "验证未通过，已阻止采纳", "verify": v}
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
        results[r] = {"ok": True, "merge": merge_result, "verify": v}

    accepted = [r for r, s in repos.items() if s.get("accepted")]
    with connect() as conn:
        from app.db import add_event
        conn.execute("UPDATE issue SET fix_state = ?, status = '待验收', updated_at = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), now(), issue_id))
        add_event(conn, issue_id, "fix_accept", from_status=row["status"], to_status="待验收",
                  note=f"MCP 已采纳 {len(accepted)} 个仓库",
                  actor=_user().get("displayName") or "MCP")
    return {"ok": True, "results": results}


@mcp.tool()
def verify_fix(issue_id: int, repo: str = "") -> dict:
    """只跑编译/类型检查，不提交。采纳时也会自动跑，这里用于提前确认。"""
    from app import verify as vfy
    from app import projects as proj_mod
    row = _owned_issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    if "error" in row:  # type: ignore[operator]
        return row
    state = _norm_state(row)
    repos = state.get("repos") or {}
    targets = [repo] if repo else [r for r, st in repos.items() if st.get("worktree")]
    if not targets:
        return {"error": "还没有可验证的 worktree"}
    project = proj_mod.get_project(row["project_id"]) if row.get("project_id") else None
    out = {}
    for r in targets:
        st = repos.get(r) or {}
        if not st.get("worktree"):
            out[r] = {"ok": False, "error": "没有 worktree"}
            continue
        out[r] = vfy.verify_worktree(r, st["worktree"], (project or {}).get("verify_cmd") or "")
        st["verify"] = out[r]
        repos[r] = st
    state["repos"] = repos
    with connect() as conn:
        conn.execute("UPDATE issue SET fix_state = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), now(), issue_id))
    return {"results": out}


@mcp.tool()
def reject_fix(issue_id: int, repo: str = "") -> dict:
    """丢弃 worktree 和分支。repo 传空表示全部丢弃。"""
    from app.fix import drop_all_worktrees
    row = _owned_issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    if "error" in row:  # type: ignore[operator]
        return row
    state = _norm_state(row)
    repos = state.get("repos") or {}
    if not repos:
        return {"ok": True}
    targets = [repo] if repo else list(repos.keys())
    if repo and repo not in repos:
        return {"error": f"{repo} 不在本次修改范围内"}
    # owner_id 必须传：多用户时 worktree 在 worktrees/user-<id>/ 下，
    # 不传会按旧路径找，等于删错地方（worktree 还在，分支被丢）
    drop_all_worktrees(issue_id, targets, row.get("owner_id"))
    for r in targets:
        repos.pop(r, None)

    with connect() as conn:
        from app.db import add_event
        if repos:
            state["repos"] = repos
            conn.execute("UPDATE issue SET fix_state = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(state, ensure_ascii=False), now(), issue_id))
        else:
            conn.execute("UPDATE issue SET fix_state = NULL, status = '待处理', updated_at = ? WHERE id = ?",
                         (now(), issue_id))
        add_event(conn, issue_id, "fix_reject",
                  note=f"MCP 驳回：{repo or '全部'}",
                  actor=_user().get("displayName") or "MCP")
    return {"ok": True, "repos": list(repos.keys())}


@mcp.tool()
def get_fix_attempts(issue_id: int) -> dict:
    """查看某个 issue 的修改轮次：每轮与方案的出入、过程中发现的问题、实际根因、文件改动与风险。"""
    from app.fix import list_attempts
    row = _owned_issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    if "error" in row:  # type: ignore[operator]
        return row
    return {"attempts": list_attempts(issue_id)}


@mcp.tool()
def get_fix_context(issue_id: int) -> dict:
    """读取该 issue 的「修复边界」上下文文件（用户可编辑，会喂给改代码的 agent）。"""
    from app import context as ctx
    row = _owned_issue(issue_id)
    if not row:
        return {"error": f"问题 #{issue_id} 不存在"}
    if "error" in row:  # type: ignore[operator]
        return row
    text = ctx.read(issue_id)
    if not text:
        scopes = _parse(row.get("code_scopes")) or []
        repos = _parse(row.get("target_repos")) or ([row["target_repo"]] if row.get("target_repo") else [])
        text = ctx.ensure(issue_id, row, [{"path": r, "name": r.split("\\")[-1].split("/")[-1]} for r in repos],
                          scopes, get_settings().get("code.project_notes") or "")
    return {"text": text, "path": str(ctx.context_path(issue_id))}


# ---------- 记忆 ----------

@mcp.tool()
def get_memory(issue_id: int) -> dict:
    """查看该问题的对话记忆（每类操作的调用次数与 token）。"""
    return _guard(icore.get_memory, _user(), issue_id)


@mcp.tool()
def clear_memory(issue_id: int, kind: str = "") -> dict:
    """清空对话记忆。kind 为空清全部（qualify/triage/analysis/apply 之一）。"""
    return _guard(icore.clear_memory, _user(), issue_id, kind)


# ---------- 配置 ----------

@mcp.tool()
def list_channels() -> dict:
    """列出 AI 通道（名称/类型/模型/是否配 Key），用于确认当前有哪些可用。"""
    from app import channels as ch
    return {"channels": ch.list_channels()}


@mcp.tool()
def test_channel(channel_id: int) -> dict:
    """测试通道连通性（会真的发一次请求）。"""
    from app import channels as ch
    try:
        return ch.test_channel(channel_id)
    except ch.AIError as ex:
        return {"error": str(ex)}


@mcp.tool()
def list_projects() -> dict:
    """列出项目（一个项目 = 一组各自独立的 git 仓库），带每个项目当前的问题数。"""
    from app import projects as proj_mod
    from app.access import owner_filter
    from app.db import connect
    projects = proj_mod.list_projects(include_ignored=True)
    owner_sql, owner_args = owner_filter(_user())
    sql = "SELECT project_id, COUNT(*) n FROM issue"
    if owner_sql:
        sql += f" WHERE {owner_sql}"
    sql += " GROUP BY project_id"
    with connect() as conn:
        counts = {r["project_id"]: r["n"] for r in conn.execute(sql, owner_args).fetchall()}
    for p in projects:
        p["issueCount"] = counts.get(p["id"], 0)
    return {"projects": projects}


@mcp.tool()
def list_code_roots() -> dict:
    """列出设置里配置的代码目录，带 isGit/exists，便于决定分析范围和目标仓库。"""
    from app.fix import ignore_list, list_code_roots as _roots, project_notes
    return {"roots": _roots(), "ignore": ignore_list(), "projectNotes": project_notes()}


# ---------- 审计 / 报表 ----------

@mcp.tool()
def login_logs(limit: int = 30, keyword: str = "", result: str = "") -> dict:
    """查登录记录（管理员）：时间/用户/IP/归属地/客户端/结果。"""
    from app import auth as auth_mod
    u = _user()
    if u.get("role") != "admin":
        return {"error": "需要管理员权限"}
    return auth_mod.list_login_logs(limit=max(1, min(int(limit or 30), 200)),
                                    username="", result=result.strip(),
                                    keyword=keyword.strip())


@mcp.tool()
def weekly_report(days: int = 0) -> str:
    """按真实时间范围输出周报 Markdown（本期新增 / 本期解决 / 当前未关闭）。

    days=0 是本周（周一至今）；days=7 / days=30 是最近 N 天。
    管理员看全部，普通用户只看自己的。
    """
    return rcore.render_weekly(_user(), max(0, min(int(days or 0), 365)))


if __name__ == "__main__":
    # 幂等建表：MCP 可能在 web 服务没启动时被调起（比如刚重启电脑）
    init_db()
    mcp.run(transport="stdio")
