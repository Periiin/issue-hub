"""「操作解决」：分析（只读）→ 改代码（多仓库 worktree）→ 采纳/驳回。

和 routers/ai.py 的分工：
- /fix           只读分析，产出方案
- /fix/apply     给每个目标仓库建 worktree，让 agent 各自动手
- /fix/diff      重新收集 diff（可按仓库）
- /fix/accept    提交到分支，仓库干净时 ff 合并（可按仓库）
- /fix/reject    丢弃 worktree 和分支（可按仓库）

多仓库设计要点：
- 每个仓库一份独立状态，互不影响：一个失败不影响另一个已成功的改动。
- fix_state 结构：{"repos": {<repoPath>: {...}}, "context": "<文件路径>"}
- 旧数据（单仓库）读取时自动归一化成新结构，无需迁移。
"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .. import context as ctx
from .. import projects
from .. import memory as mem
from ..db import add_event, connect, get_settings, now
from ..fix import (FixError, collect_diff, commit_all, create_worktree, current_branch,
                   drop_all_worktrees, drop_worktree, ignore_list, is_repo_root,
                   list_code_roots, list_target_repos, list_attempts, merge_to_base,
                   next_attempt_seq, project_notes, worktree_path)
from ..prompts import APPLY_SYSTEM, build_apply_prompt, parse_apply_report
from ..channels import AIError, resolve_channel, run_ai
from ..schemas import (ContextUpdate, FixAcceptReq, FixApplyReq, FixRejectReq)

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


# ---------------- 目标仓库 ----------------

def _issue_repos(issue: dict) -> list[str]:
    """读 issue 的目标仓库列表。优先级：

    1. issue.target_repos（用户在详情页调整过的）
    2. issue.target_repo（旧的单值字段）
    3. 所属项目 project.repos（选了项目就默认整项目）

    去重按归一化路径：同一个仓库可能因分隔符不同被存成两份。
    """
    repos = _json(issue.get("target_repos")) or []
    if not repos and issue.get("project_id"):
        project = projects.get_project(issue["project_id"])
        if project and project.get("repos"):
            repos = project["repos"]
    # 旧字段只在「既没手选仓库、也没项目」时兜底，否则会盖掉项目范围
    if not repos and issue.get("target_repo"):
        repos = [issue["target_repo"]]
    seen, out = set(), []
    for r in repos:
        if not r:
            continue
        key = str(Path(r)).replace("\\", "/").rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _issue_scopes(issue: dict) -> list[str]:
    """分析用代码目录。issue 自己勾过就用它的，否则用所属项目的仓库集合。"""
    scopes = _json(issue.get("code_scopes")) or []
    if scopes:
        return scopes
    if issue.get("project_id"):
        project = projects.get_project(issue["project_id"])
        if project:
            return project.get("repos") or []
    return []


def _repo_info(path: str) -> dict:
    for r in list_target_repos():
        if str(Path(r["path"]).resolve()) == str(Path(path).resolve()):
            return r
    return {"path": path, "name": Path(path).name, "exists": Path(path).is_dir(),
            "isGit": is_repo_root(path), "covers": []}


def _norm_state(issue: dict) -> dict:
    """把 fix_state 归一化成 {repos: {path: {...}}}。

    旧版本是单仓库扁平结构（含 worktree/branch/repo 三个键），
    这里就地转换，前端和老 MCP 调用都不用改数据。
    """
    state = _json(issue.get("fix_state")) or {}
    if "repos" in state:
        return state
    if state.get("repo"):
        repo = state["repo"]
        inner = {k: v for k, v in state.items() if k not in ("repo",)}
        return {"repos": {repo: {"repo": repo, **inner}}, "context": ""}
    return {"repos": {}}


# ---------------- 代码范围 / 上下文文件 ----------------

@router.get("/code/roots")
def code_roots(project_id: int | None = None):
    """代码范围候选 + 目标仓库 + 忽略规则 + 项目说明。

    传 project_id 时只返回该项目里的仓库（详情页右栏用），
    不传则返回所有项目的仓库（设置页/兜底用）。
    """
    if project_id:
        project = projects.get_project(project_id)
        roots = []
        for path in (project or {}).get("repos") or []:
            p = Path(path)
            ok = is_repo_root(str(p))
            roots.append({"path": str(p), "name": p.name, "exists": p.is_dir(),
                          "isGit": ok, "repoRoot": str(p) if ok else None})
        notes = ((project or {}).get("notes") or "").strip()
        combined = "\n".join(x for x in (project_notes(), notes) if x).strip()
    else:
        roots = list_code_roots()
        combined = project_notes()
    return {"roots": roots, "ignore": ignore_list(),
            "projectNotes": combined,
            "targetRepos": [r for r in roots if r["isGit"] and r["exists"]]}


@router.get("/issues/{issue_id}/context")
def get_context(issue_id: int):
    """读修复上下文文件；不存在时按当前配置生成一份。"""
    with connect() as conn:
        issue = _issue(conn, issue_id)
    scopes = _json(issue.get("code_scopes")) or []
    repos = [_repo_info(r) for r in _issue_repos(issue)]
    text = ctx.read(issue_id)
    if not text:
        text = ctx.ensure(issue_id, issue, repos, scopes, project_notes())
    return {"text": text, "path": str(ctx.context_path(issue_id))}


@router.put("/issues/{issue_id}/context")
def put_context(issue_id: int, payload: ContextUpdate):
    """用户手动保存上下文文件（全文覆盖）。"""
    with connect() as conn:
        _issue(conn, issue_id)
    p = ctx.write(issue_id, payload.text or "")
    return {"ok": True, "path": str(p)}


@router.post("/issues/{issue_id}/context/regenerate")
def regenerate_context(issue_id: int):
    """按当前范围/目标仓库重新生成自动区，用户手写区保留。"""
    with connect() as conn:
        issue = _issue(conn, issue_id)
    scopes = _json(issue.get("code_scopes")) or []
    repos = [_repo_info(r) for r in _issue_repos(issue)]
    text = ctx.ensure(issue_id, issue, repos, scopes, project_notes())
    return {"ok": True, "text": text, "path": str(ctx.context_path(issue_id))}


@router.delete("/issues/{issue_id}/context")
def delete_context(issue_id: int):
    return {"ok": ctx.delete(issue_id)}


# ---------------- 改代码（多仓库） ----------------

@router.post("/issues/{issue_id}/fix/apply")
def apply_fix(issue_id: int, payload: FixApplyReq):
    with connect() as conn:
        issue = _issue(conn, issue_id)
    if not issue.get("qualify_final"):
        raise HTTPException(400, "还没有确认过的问题描述，先完成定性")
    confirmed = json.loads(issue["qualify_final"])

    repos = payload.repos or ([payload.repo] if payload.repo else []) or _issue_repos(issue)
    repos = [r for r in dict.fromkeys(repos) if r]
    if not repos:
        raise HTTPException(400, "请先选择目标仓库（详情页「目标仓库」里至少勾一个）")

    for r in repos:
        if not is_repo_root(r):
            raise HTTPException(400, f"{r} 不是 git 仓库根目录，不能作为修改目标")

    settings = get_settings()
    channel = resolve_channel(payload.channel_id)
    if channel and (channel.get("kind") or "").lower() == "mock":
        raise HTTPException(400, "Mock 通道不会真的改代码，请选一个真实通道")
    provider = channel.get("name") if channel else "mock"

    scopes = _issue_scopes(issue)
    plan = _json(issue.get("fix_plan"))

    # 生成/刷新上下文文件（用户手写区保留），并取出边界正文
    ctx_text = ctx.ensure(issue_id, issue, [_repo_info(r) for r in repos], scopes, project_notes())
    boundary = ctx.auto_block(ctx_text)
    ctx_file = str(ctx.context_path(issue_id))

    old = _norm_state(issue)
    state = {"repos": {}, "context": ctx_file, "updated_at": now()}
    # 保留本次没重新跑的仓库状态，避免把之前成功的改动丢掉
    for repo, st in old.get("repos", {}).items():
        if repo not in repos:
            state["repos"][repo] = st

    timeout = max(int(settings.get("ai.timeout") or 180), 600)
    for repo in repos:
        info = None
        try:
            info = create_worktree(repo, issue_id)
        except FixError as ex:
            state["repos"][repo] = {"repo": repo, "status": "failed", "error": str(ex),
                                    "provider": provider, "updated_at": now()}
            continue

        prompt = build_apply_prompt(confirmed, info["worktree"], plan,
                                   boundary=boundary, context_file=ctx_file)
        try:
            block = mem.build_memory_block(issue, list_attempts(issue_id), current_kind="apply")
            result = run_ai(payload.channel_id, prompt, APPLY_SYSTEM, cwd=info["worktree"],
                            issue_id=issue_id, kind="apply", memory_block=block,
                            timeout=timeout, allow_write=True)
        except AIError as ex:
            # 单个仓库失败不影响其它仓库，也不立刻删 worktree（便于人工排查）
            with connect() as conn:
                _record_run(conn, issue_id, "apply", None, False, f"{repo}: {ex}")
            state["repos"][repo] = {**info, "repo": repo, "status": "failed",
                                    "error": str(ex), "provider": provider, "updated_at": now()}
            continue

        try:
            diff = collect_diff(info["worktree"])
        except FixError as ex:
            diff = {"stat": "", "diff": "", "files": [], "empty": True, "error": str(ex)}

        with connect() as conn:
            _record_run(conn, issue_id, "apply", result, True)
        # agent 的结构化报告：与方案的出入、过程中发现的问题（解析失败就当纯文本总结）
        report = parse_apply_report(result.text or "")
        repo_state = {
            **info,
            "repo": repo,
            "name": _repo_info(repo).get("name") or Path(repo).name,
            "status": "changed" if not diff.get("empty") else "unchanged",
            "provider": result.provider,
            "duration_ms": result.duration_ms,
            "summary": (report or {}).get("summary") or (result.text or "")[:2000],
            "diff_stat": diff.get("stat", ""),
            "files": diff.get("files", []),
            "accepted": False,
            "updated_at": now(),
        }
        if report:
            repo_state["report"] = {
                "actual_root_cause": report.get("actual_root_cause") or "",
                "deviations": report.get("deviations") or [],
                "found_issues": report.get("found_issues") or [],
                "risks": report.get("risks") or [],
                "verification": report.get("verification") or "",
            }
        state["repos"][repo] = repo_state

    with connect() as conn:
        conn.execute("UPDATE issue SET fix_state = ?, status = '处理中', updated_at = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), now(), issue_id))
        changed = [r for r, s in state["repos"].items() if s.get("status") == "changed"]
        failed = [r for r, s in state["repos"].items() if s.get("status") == "failed"]
        note = f"worktree 修改（{provider}）：{len(changed)} 个仓库有改动"
        if failed:
            note += f"，{len(failed)} 个失败"
        add_event(conn, issue_id, "fix_apply", from_status=issue["status"], to_status="处理中", note=note)

    attempt = _save_attempt(issue_id, provider, state)
    return {"state": state, "diffs": _collect_diffs(state), "context": ctx_file,
            "attempt": attempt}


def _as_text(value) -> str:
    """模型返回的字段可能是字符串、数组或对象，统一成可入库的文本。

    实测：verification 有时给 ["a","b"]，有时给 "a；b"，直接 join 会 TypeError。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "；".join(str(x).strip() for x in value if str(x).strip())
    if isinstance(value, dict):
        return "；".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def _save_attempt(issue_id: int, provider: str, state: dict) -> dict:
    """把这次「开始修改」归档成一条 fix_attempt（第 N 次）。

    多仓库时把各仓库的报告汇总：出入/发现的问题/文件取并集，
    实际根因相同取一个、不同就逐仓库列出。
    """
    repo_states = state.get("repos") or {}
    deviations: list[str] = []
    found_issues: list[str] = []
    files: list[str] = []
    risks: list[str] = []
    roots: dict[str, str] = {}
    repo_brief: dict[str, dict] = {}

    for repo, st in repo_states.items():
        brief = {"status": st.get("status"), "error": st.get("error"),
                 "summary": (st.get("summary") or "")[:500],
                 "files": st.get("files") or []}
        report = st.get("report") or {}
        brief["deviations"] = report.get("deviations") or []
        brief["found_issues"] = report.get("found_issues") or []
        repo_brief[repo] = brief

        for key, bucket in (("deviations", deviations), ("found_issues", found_issues), ("risks", risks)):
            for item in report.get(key) or []:
                if item and item not in bucket:
                    bucket.append(item)
        for f in st.get("files") or []:
            if f and f not in files:
                files.append(f)
        root = (report.get("actual_root_cause") or "").strip()
        if root:
            roots[repo] = root

    # 实际根因：所有仓库说法一致就取一个，不一致逐仓库列
    unique_roots = list(dict.fromkeys(roots.values()))
    actual_root = unique_roots[0] if len(unique_roots) == 1 else \
        ("；".join(f"{Path(k).name}: {v}" for k, v in roots.items()) if roots else "")

    statuses = [st.get("status") for st in repo_states.values()]
    if not statuses:
        attempt_status = "failed"
    elif all(s == "failed" for s in statuses):
        attempt_status = "failed"
    elif all(s in ("changed", "unchanged") for s in statuses):
        attempt_status = "changed" if "changed" in statuses else "unchanged"
    else:
        attempt_status = "partial"

    with connect() as conn:
        seq = next_attempt_seq(issue_id)
        conn.execute(
            "INSERT INTO fix_attempt(issue_id, seq, provider, status, summary, actual_root_cause, "
            "deviations, found_issues, files, risks, verification, repos, raw_report, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (issue_id, seq, provider, attempt_status,
             "；".join(filter(None, (_as_text(st.get("summary"))[:300] for st in repo_states.values()))),
             actual_root,
             json.dumps(deviations, ensure_ascii=False),
             json.dumps(found_issues, ensure_ascii=False),
             json.dumps(files, ensure_ascii=False),
             json.dumps(risks, ensure_ascii=False),
             "；".join(filter(None, (_as_text((st.get("report") or {}).get("verification"))
                                     for st in repo_states.values()))),
             json.dumps(repo_brief, ensure_ascii=False),
             "；".join(filter(None, (_as_text(st.get("summary")) for st in repo_states.values())))[:5000],
             now()))
        row = conn.execute("SELECT * FROM fix_attempt WHERE issue_id = ? AND seq = ?",
                           (issue_id, seq)).fetchone()

    return _attempt_row(row)


def _attempt_row(row) -> dict:
    d = dict(row)
    for key in ("deviations", "found_issues", "files", "risks", "repos"):
        d[key] = _json(d.get(key))
    return d


@router.get("/issues/{issue_id}/fix/attempts")
def fix_attempts(issue_id: int):
    """修改轮次列表：每轮与方案的出入、发现的问题、实际根因、文件与风险。"""
    with connect() as conn:
        _issue(conn, issue_id)
    return {"attempts": list_attempts(issue_id)}


def _collect_diffs(state: dict) -> dict:
    """按仓库收集 diff，失败/无 worktree 的跳过。"""
    out = {}
    for repo, st in (state.get("repos") or {}).items():
        wt = st.get("worktree")
        if not wt:
            continue
        try:
            out[repo] = collect_diff(wt)
        except FixError as ex:
            out[repo] = {"stat": "", "diff": "", "files": [], "empty": True, "error": str(ex)}
    return out


@router.get("/issues/{issue_id}/fix/diff")
def fix_diff(issue_id: int, repo: str | None = None):
    """重新收集 diff。传 repo 只取一个，不传取全部。"""
    with connect() as conn:
        issue = _issue(conn, issue_id)
    state = _norm_state(issue)
    if not state.get("repos"):
        raise HTTPException(404, "还没有开始修改")

    if repo:
        if repo not in state["repos"]:
            raise HTTPException(404, f"{repo} 不在本次修改范围内")
        targets = [repo]
    else:
        targets = list(state["repos"].keys())

    diffs = {}
    for r in targets:
        st = state["repos"][r]
        wt = st.get("worktree")
        if not wt:
            continue
        try:
            d = collect_diff(wt)
        except FixError as ex:
            d = {"stat": "", "diff": "", "files": [], "empty": True, "error": str(ex)}
        st["diff_stat"] = d.get("stat", "")
        st["files"] = d.get("files", [])
        diffs[r] = d

    with connect() as conn:
        conn.execute("UPDATE issue SET fix_state = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), now(), issue_id))
    return {"state": state, "diffs": diffs}


@router.post("/issues/{issue_id}/fix/accept")
def accept_fix(issue_id: int, payload: FixAcceptReq):
    """采纳：按仓库独立提交/合并。不传 repo 时采纳全部有改动的仓库。"""
    with connect() as conn:
        issue = _issue(conn, issue_id)
    state = _norm_state(issue)
    repos = state.get("repos") or {}
    if not repos:
        raise HTTPException(404, "还没有开始修改")

    targets = [payload.repo] if payload.repo else list(repos.keys())
    results = {}
    for repo in targets:
        st = repos.get(repo)
        if not st:
            results[repo] = {"ok": False, "error": f"{repo} 不在本次修改范围内"}
            continue
        if st.get("accepted"):
            results[repo] = {"ok": True, "already": True}
            continue
        if st.get("status") == "failed" or not st.get("worktree"):
            results[repo] = {"ok": False, "error": st.get("error") or "没有可采纳的改动"}
            continue

        message = (payload.message or "").strip() or f"fix(issue-{issue_id}): {issue['title']}"
        try:
            committed = commit_all(st["worktree"], message)
        except FixError as ex:
            results[repo] = {"ok": False, "error": str(ex)}
            continue
        if not committed:
            results[repo] = {"ok": False, "error": "worktree 里没有改动"}
            continue

        merge_result = {"merged": False, "reason": "按请求不自动合并"}
        if payload.merge:
            try:
                merge_result = merge_to_base(st["repo"], st["branch"])
            except FixError as ex:
                merge_result = {"merged": False, "reason": str(ex),
                                "command": f"git -C {st['repo']} merge {st['branch']}"}

        st.update({"accepted": True, "accepted_at": now(),
                   "commit_message": message, "merge": merge_result})
        results[repo] = {"ok": True, "merge": merge_result}

    accepted = [r for r, s in repos.items() if s.get("accepted")]
    with connect() as conn:
        conn.execute("UPDATE issue SET fix_state = ?, status = '待验收', updated_at = ? WHERE id = ?",
                     (json.dumps(state, ensure_ascii=False), now(), issue_id))
        add_event(conn, issue_id, "fix_accept", from_status=issue["status"], to_status="待验收",
                  note=f"已采纳 {len(accepted)} 个仓库")
    return {"ok": True, "results": results, "state": state}


@router.post("/issues/{issue_id}/fix/reject")
def reject_fix(issue_id: int, payload: FixRejectReq | None = None):
    """驳回：丢弃指定仓库的 worktree；不传 repo 时全部丢弃。"""
    with connect() as conn:
        issue = _issue(conn, issue_id)
    state = _norm_state(issue)
    repos = state.get("repos") or {}
    if not repos:
        return {"ok": True}

    target = (payload.repo if payload else None)
    if target:
        if target not in repos:
            raise HTTPException(404, f"{target} 不在本次修改范围内")
        drop_all_worktrees(issue_id, [target])
        repos.pop(target, None)
    else:
        drop_all_worktrees(issue_id, list(repos.keys()))
        repos = {}

    if repos:
        state["repos"] = repos
        with connect() as conn:
            conn.execute("UPDATE issue SET fix_state = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(state, ensure_ascii=False), now(), issue_id))
            add_event(conn, issue_id, "fix_reject", note=f"已丢弃 {target or '全部'} 的 worktree")
    else:
        with connect() as conn:
            conn.execute("UPDATE issue SET fix_state = NULL, status = '待处理', updated_at = ? WHERE id = ?",
                         (now(), issue_id))
            add_event(conn, issue_id, "fix_reject", from_status=issue["status"], to_status="待处理",
                      note="已丢弃 worktree 与分支")
    return {"ok": True, "state": state if repos else None}
