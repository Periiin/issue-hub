"""用户级仓库副本。

为什么需要副本（而不是共享同一份仓库）：
- 共享时，A 的「采纳合并」会改到主仓库，B 下次开 worktree 就基于 A 的代码，
  两个人互相污染，diff 里会混进别人的改动。
- 各自副本后，每个用户的仓库状态完全独立：A 合并只影响 A 的副本。

布局：
    repos/user-<id>/<repoSlug>/        ← 用户自己的 clone（有 .git）
    worktrees/user-<id>/issue-<n>/...  ← 从这个 clone 切出来的 worktree

副本来源：从 `source`（管理员配的原始仓库路径）clone 一份。
首次使用自动 clone，之后可用 sync 拉最新（如果 source 有远端）。

注意：clone 的是**本地路径**，不是远端 URL —— 源仓库通常是本地已经
clone 好的项目（含未推送的提交），`git clone /path` 能把这些一起带过来。
"""
import shutil
import subprocess
from pathlib import Path

from .config import BASE_DIR
from .db import connect, now

REPOS_DIR = BASE_DIR / "repos"


class RepoError(RuntimeError):
    pass


def _git(args: list[str], cwd: str | Path, timeout: int = 300) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def slug(path: str) -> str:
    """仓库路径 → 目录名。与 fix.repo_slug 保持一致。"""
    import re
    name = Path(path).name
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "repo"
    return s.lower()


def copy_path(owner_id: int | None, source: str) -> Path:
    """用户副本的路径。owner 为空（单人本机）时直接用源仓库，不复制。"""
    if not owner_id:
        return Path(source)
    return REPOS_DIR / f"user-{owner_id}" / slug(source)


def is_copy(repo: str, owner_id: int | None) -> bool:
    return bool(owner_id) and str(Path(repo).resolve()).startswith(str(REPOS_DIR.resolve()))


def ensure_copy(source: str, owner_id: int | None, auto: bool = True) -> dict:
    """确保用户副本存在。返回 {path, created, source}。

    owner 为空时直接返回源仓库（单人本机不需要副本）。
    """
    if not owner_id:
        return {"path": source, "created": False, "source": source, "isCopy": False}

    src = Path(source)
    if not src.is_dir():
        raise RepoError(f"源仓库不存在：{source}")

    dst = copy_path(owner_id, source)
    if (dst / ".git").exists():
        return {"path": str(dst), "created": False, "source": source, "isCopy": True}

    if not auto:
        raise RepoError(f"用户副本尚未创建：{dst}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)

    # clone 本地路径：把源仓库的提交（含未推送的）一起带过来
    code, out, err = _git(["clone", "--quiet", str(src), str(dst)], dst.parent)
    if code != 0:
        raise RepoError(f"创建副本失败：{err or out}")
    return {"path": str(dst), "created": True, "source": source, "isCopy": True}


def sync_copy(source: str, owner_id: int | None) -> dict:
    """把源仓库的新提交同步到副本。

    用 `fetch` + `reset --hard` 而不是 `pull`：副本上不该有本地改动
    （所有改动都在 worktree 里），硬同步最简单也不会冲突。
    但如果有 worktree 正在用，跳过 reset 以免影响进行中的修改。
    """
    if not owner_id:
        return {"ok": True, "skipped": True, "reason": "单人模式不需要同步"}
    dst = copy_path(owner_id, source)
    if not (dst / ".git").exists():
        return ensure_copy(source, owner_id)

    # 有 worktree 在用就不动，避免把进行中的改动冲掉
    code, out, _ = _git(["worktree", "list", "--porcelain"], dst)
    active = [ln for ln in out.splitlines() if ln.startswith("worktree ")]
    if len(active) > 1:
        return {"ok": False, "skipped": True,
                "reason": f"有 {len(active) - 1} 个 worktree 正在使用，请先采纳或驳回再同步"}

    code, out, err = _git(["fetch", "--quiet", str(source), "+refs/heads/*:refs/remotes/origin/*"], dst)
    if code != 0:
        return {"ok": False, "error": f"fetch 失败：{err or out}"}

    # 跟随源仓库当前分支
    _, src_branch, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], source)
    src_branch = src_branch or "HEAD"
    code, out, err = _git(["reset", "--hard", f"origin/{src_branch}"], dst)
    if code != 0:
        return {"ok": False, "error": f"reset 失败：{err or out}"}
    return {"ok": True, "branch": src_branch, "commit": out.splitlines()[0] if out else ""}


def copy_status(source: str, owner_id: int | None) -> dict:
    """副本状态：是否存在、HEAD、是否有 worktree 占用。"""
    if not owner_id:
        return {"path": source, "exists": Path(source).is_dir(), "isCopy": False}
    dst = copy_path(owner_id, source)
    exists = (dst / ".git").exists()
    info = {"path": str(dst), "exists": exists, "source": source, "isCopy": True}
    if not exists:
        return info
    _, head, _ = _git(["rev-parse", "--short", "HEAD"], dst)
    _, branch, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], dst)
    _, wl, _ = _git(["worktree", "list", "--porcelain"], dst)
    _, dirty, _ = _git(["status", "--porcelain"], dst)
    info.update({
        "head": head,
        "branch": branch,
        "worktrees": max(0, len([x for x in wl.splitlines() if x.startswith("worktree ")]) - 1),
        "dirty": bool(dirty),
        "sizeMb": _du_mb(dst),
    })
    return info


def _du_mb(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return int(total / 1024 / 1024)


def all_copies(owner_id: int | None, sources: list[str]) -> list[dict]:
    return [copy_status(s, owner_id) for s in sources]


def delete_copy(source: str, owner_id: int | None) -> dict:
    if not owner_id:
        return {"ok": False, "error": "单人模式没有副本"}
    dst = copy_path(owner_id, source)
    if not dst.exists():
        return {"ok": True, "skipped": True}
    # 先清 worktree，否则 rmtree 后 git 元数据会残留
    _git(["worktree", "prune"], dst)
    shutil.rmtree(dst, ignore_errors=True)
    return {"ok": True, "path": str(dst)}
