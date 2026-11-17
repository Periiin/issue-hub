"""「操作解决」的 git 编排：worktree → 收集 diff → 人工采纳/驳回。

安全边界（必须守住）：
- 只在独立 worktree 里改，绝不碰主仓库工作区（那里通常有未提交的改动）
- 不 push、不部署、不动数据库
- 采纳时先检查主仓库是否干净，不干净就只提交到分支并给出合并命令
"""
import os
import shutil
import subprocess
from pathlib import Path

from .config import BASE_DIR
from .db import get_settings

WORKTREES_DIR = BASE_DIR / "worktrees"
DIFF_LIMIT = 300 * 1024  # 单次返回的 diff 上限，超出截断并提示


class FixError(RuntimeError):
    pass


def _git(args: list[str], cwd: str | Path, timeout: int = 120) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def repo_root(path: str | None) -> str | None:
    """返回 path 所属仓库的根目录；不是 git 仓库返回 None。"""
    if not path:
        return None
    p = Path(path).expanduser()
    if not p.is_dir():
        return None
    code, out, _ = _git(["rev-parse", "--show-toplevel"], p)
    if code != 0 or not out:
        return None
    return out


def is_repo_root(path: str | None) -> bool:
    """只有「目录本身就是仓库根」才算可作为修改目标（父目录不行）。"""
    root = repo_root(path)
    if not root:
        return False
    return Path(root).resolve() == Path(path).expanduser().resolve()


def current_branch(repo: str) -> str:
    code, out, err = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    if code != 0:
        raise FixError(f"读取分支失败：{err}")
    return out


def is_clean(repo: str) -> bool:
    code, out, _ = _git(["status", "--porcelain"], repo)
    return code == 0 and not out


def worktree_path(issue_id: int) -> Path:
    return WORKTREES_DIR / f"issue-{issue_id}"


def branch_name(issue_id: int) -> str:
    return f"issue-{issue_id}"


def create_worktree(repo: str, issue_id: int) -> dict:
    """在 repo 上建独立 worktree（分支 issue-<id>），返回位置信息。"""
    if not is_repo_root(repo):
        raise FixError(f"{repo} 不是 git 仓库根目录，不能作为修改目标")
    wt = worktree_path(issue_id)
    branch = branch_name(issue_id)
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)

    # 清理上一次的残留（重复点「开始修改」时）
    if wt.exists():
        _git(["worktree", "remove", "--force", str(wt)], repo)
        shutil.rmtree(wt, ignore_errors=True)
    _git(["worktree", "prune"], repo)
    _git(["branch", "-D", branch], repo)

    code, out, err = _git(["worktree", "add", "-b", branch, str(wt), "HEAD"], repo)
    if code != 0:
        raise FixError(f"创建 worktree 失败：{err or out}")
    return {"worktree": str(wt), "branch": branch, "repo": repo,
            "base_branch": current_branch(repo), "base_commit": _head(repo)}


def _head(repo: str) -> str:
    _, out, _ = _git(["rev-parse", "--short", "HEAD"], repo)
    return out


def collect_diff(wt: str) -> dict:
    """把 worktree 的改动全部 stage 后取 stat + 完整 diff。"""
    if not Path(wt).exists():
        raise FixError("worktree 不存在，可能已被清理")
    _git(["add", "-A"], wt)
    _, stat, _ = _git(["diff", "--cached", "--stat"], wt)
    _, full, _ = _git(["diff", "--cached", "--no-color", "--unified=3"], wt)
    _, names, _ = _git(["diff", "--cached", "--name-only"], wt)
    truncated = False
    if len(full.encode("utf-8", "ignore")) > DIFF_LIMIT:
        full = full.encode("utf-8", "ignore")[:DIFF_LIMIT].decode("utf-8", "ignore")
        truncated = True
    return {"stat": stat, "diff": full, "files": [n for n in names.splitlines() if n],
            "truncated": truncated, "empty": not bool(names.strip())}


def commit_all(wt: str, message: str) -> bool:
    """提交 worktree 里的改动；没有改动返回 False。"""
    _git(["add", "-A"], wt)
    code, out, err = _git(["commit", "-m", message], wt)
    if code != 0:
        if "nothing to commit" in (out + err):
            return False
        raise FixError(f"提交失败：{err or out}")
    return True


def merge_to_base(repo: str, branch: str) -> dict:
    """把分支合回主仓库当前分支。主仓库不干净时拒绝，交回人工处理。"""
    base = current_branch(repo)
    if not is_clean(repo):
        return {"merged": False, "base_branch": base,
                "reason": "主仓库有未提交改动，未自动合并",
                "command": f"git -C {repo} merge {branch}"}
    code, out, err = _git(["merge", "--ff-only", branch], repo)
    if code != 0:
        return {"merged": False, "base_branch": base, "reason": err or out,
                "command": f"git -C {repo} merge {branch}"}
    return {"merged": True, "base_branch": base, "output": out}


def drop_worktree(repo: str, issue_id: int) -> None:
    wt = worktree_path(issue_id)
    branch = branch_name(issue_id)
    if Path(repo).exists():
        _git(["worktree", "remove", "--force", str(wt)], repo)
        _git(["worktree", "prune"], repo)
        _git(["branch", "-D", branch], repo)
    shutil.rmtree(wt, ignore_errors=True)


# ---------------- 代码范围 ----------------

def list_code_roots() -> list[dict]:
    """设置里配置的候选目录 + 是否 git 仓库 / 是否存在。"""
    raw = get_settings().get("code.roots") or ""
    result = []
    for line in raw.splitlines():
        path = line.strip()
        if not path:
            continue
        p = Path(path).expanduser()
        root = repo_root(str(p))
        result.append({
            "path": str(p),
            "name": p.name,
            "exists": p.is_dir(),
            "isGit": bool(root) and Path(root).resolve() == p.resolve(),
            "repoRoot": root,
        })
    return result


def ignore_list() -> list[str]:
    raw = get_settings().get("code.ignore") or ""
    return [s.strip() for s in raw.split(",") if s.strip()]


def project_notes() -> str:
    return (get_settings().get("code.project_notes") or "").strip()
