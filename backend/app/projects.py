"""项目（Project）：一组协作开发的 git 仓库。

为什么需要这一层：
- 现实里「一个项目」经常是多个仓库（gym = java + vue + 两个 uniapp），
  而且它们不一定在同一个父目录下（mes-java-2 和 mes-vue-2.0 就在 /src 同级）。
- 每个 issue 只属于一个项目，选定项目就自动带出「分析范围」和「可改仓库」，
  不用每条问题都重新勾一遍目录。

仓库仍然是各自独立的 git 仓库：worktree / branch / merge 都在单个仓库里做，
项目只是它们的集合。
"""
import json
import sqlite3
import os
from pathlib import Path

from .config import SCAN_MAX_DEPTH, SCAN_SKIP_DIRS
from .db import connect, get_settings, list_rows, now


# ---------------- 扫描 ----------------

def scan_roots() -> list[str]:
    """扫描根目录。优先用 code.scan_roots，空了回落到旧的 code.roots（兼容）。"""
    settings = get_settings()
    raw = (settings.get("code.scan_roots") or "").strip()
    if not raw:
        raw = (settings.get("code.roots") or "").strip()
    roots = []
    for line in raw.splitlines():
        p = line.strip()
        if not p:
            continue
        expanded = os.path.expanduser(p)
        if os.path.isdir(expanded):
            roots.append(expanded)
    return roots


def _is_git_repo(path: Path) -> bool:
    # .git 可能是目录（普通仓库）或文件（worktree / submodule）
    return (path / ".git").exists()


def discover_repos(max_depth: int = SCAN_MAX_DEPTH) -> list[dict]:
    """从扫描根往下找 git 仓库。

    找到仓库就不再往下钻（仓库内部不会有我们需要的仓库），
    名字命中 SCAN_SKIP_DIRS 的目录整体跳过。
    """
    found: list[dict] = []
    seen: set[str] = set()

    def walk(current: Path, depth: int, root: str) -> None:
        if depth > max_depth:
            return
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            return
        for entry in entries:
            if not entry.is_dir():
                continue
            name = entry.name
            if name.startswith(".") or name in SCAN_SKIP_DIRS:
                continue
            try:
                if _is_git_repo(entry):
                    real = str(entry.resolve())
                    if real not in seen:
                        seen.add(real)
                        found.append({
                            "path": real,
                            "name": entry.name,
                            "parent": str(entry.parent.resolve()),
                            "root": root,
                            "depth": depth,
                        })
                    # 仓库内部不再深入
                    continue
            except OSError:
                continue
            walk(entry, depth + 1, root)

    for root in scan_roots():
        rp = Path(root)
        # 扫描根本身就是仓库也要收
        if _is_git_repo(rp):
            real = str(rp.resolve())
            if real not in seen:
                seen.add(real)
                found.append({"path": real, "name": rp.name, "parent": str(rp.parent.resolve()),
                              "root": root, "depth": 0})
            continue
        walk(rp, 1, root)
    return found


def cluster_projects(repos: list[dict]) -> list[dict]:
    """把扫描到的仓库按父目录聚类成候选项目。

    规则（关键，避免 /src 这种「平铺目录」把所有仓库归成一个项目）：
    - depth == 1（扫描根的直接子仓库）→ 各自独立项目
    - depth >= 2（扫描根的子目录里的仓库）→ 按该子目录聚成一个项目
    - 只提示不改：名字前缀相近但不在同一父目录的，不自动合并
    """
    groups: dict[str, dict] = {}
    for r in repos:
        if r["depth"] <= 1:
            key = r["path"]
        else:
            # 取扫描根下的第一层目录作为项目归并键
            parts = Path(r["path"]).relative_to(Path(r["root"])).parts
            key = str(Path(r["root"]) / parts[0])
        g = groups.setdefault(key, {
            "key": key,
            "name": Path(key).name,
            "repos": [],
            "depth": r["depth"],
        })
        g["repos"].append(r["path"])
    return sorted(groups.values(), key=lambda g: (-len(g["repos"]), g["name"].lower()))


def suggest_merges(clusters: list[dict]) -> list[dict]:
    """找出「看起来像同一个项目但被拆开」的候选，只建议、不自动合并。

    判定：项目名去掉后缀数字/版本号后相同（mes-java-2 与 mes-vue-2.0 都是 mes*），
    或者一个名字是另一个的前缀（gym 与 gym-uniapp）。
    前缀相同但通常不同项目的（gym-fold 里的 4 个仓库已在同一项目内）不会命中。
    """
    def norm(name: str) -> str:
        base = name.lower()
        for sep in ("-", "_", "."):
            if sep in base:
                base = base.split(sep)[0]
        return base

    buckets: dict[str, list[dict]] = {}
    for c in clusters:
        # 多仓库的（已按父目录聚好）不参与建议
        if len(c["repos"]) > 1:
            continue
        buckets.setdefault(norm(c["name"]), []).append(c)

    suggestions = []
    for base, items in buckets.items():
        if len(items) < 2:
            continue
        suggestions.append({
            "reason": f"名字都像「{base}」，可能是同一项目的多个仓库",
            "projects": [{"name": i["name"], "key": i["key"], "repos": i["repos"]} for i in items],
            "mergedName": base,
            "mergedRepos": [r for i in items for r in i["repos"]],
        })
    return suggestions


# ---------------- 项目读写 ----------------

def _row(r) -> dict:
    d = dict(r)
    try:
        d["repos"] = json.loads(d.get("repos") or "[]")
    except json.JSONDecodeError:
        d["repos"] = []
    d["ignored"] = bool(d.get("ignored"))
    d["verify_cmd"] = d.get("verify_cmd") or ""
    d["owner_id"] = d.get("owner_id")
    return d


def list_projects(include_ignored: bool = False) -> list[dict]:
    sql = "SELECT * FROM project"
    if not include_ignored:
        sql += " WHERE ignored = 0"
    sql += " ORDER BY sort, id"
    try:
        with connect() as conn:
            rows = conn.execute(sql).fetchall()
    except sqlite3.OperationalError:
        # 库还没建表（首次启动 init_db 之前被调用）：当空处理，别让页面 500
        return []
    return [_row(r) for r in rows]


def get_project(project_id: int) -> dict | None:
    try:
        with connect() as conn:
            r = conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return _row(r) if r else None


def find_project_by_repo(repo: str) -> dict | None:
    """反查某个仓库属于哪个项目（用于 issue 没选项目时的兜底）。"""
    for p in list_projects(include_ignored=True):
        if repo in p["repos"]:
            return p
    return None


def create_project(name: str, repos: list[str], notes: str = "",
                   verify_cmd: str = "", owner_id: int | None = None) -> int:
    ts = now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO project(name, repos, notes, verify_cmd, owner_id, ignored, sort, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)",
            (name.strip() or "未命名项目", json.dumps(repos, ensure_ascii=False), notes,
             (verify_cmd or "").strip(), owner_id, ts, ts))
        return cur.lastrowid


def update_project(project_id: int, name: str | None = None, repos: list[str] | None = None,
                   notes: str | None = None, ignored: bool | None = None,
                   verify_cmd: str | None = None) -> bool:
    fields, args = [], []
    if name is not None:
        fields.append("name = ?")
        args.append(name.strip() or "未命名项目")
    if repos is not None:
        fields.append("repos = ?")
        args.append(json.dumps(repos, ensure_ascii=False))
    if notes is not None:
        fields.append("notes = ?")
        args.append(notes)
    if ignored is not None:
        fields.append("ignored = ?")
        args.append(1 if ignored else 0)
    if verify_cmd is not None:
        fields.append("verify_cmd = ?")
        args.append(verify_cmd.strip())
    if not fields:
        return False
    fields.append("updated_at = ?")
    args.append(now())
    args.append(project_id)
    with connect() as conn:
        conn.execute(f"UPDATE project SET {', '.join(fields)} WHERE id = ?", args)
    return True


def delete_project(project_id: int) -> bool:
    """删项目；关联 issue 的 project_id 置空（不删 issue）。"""
    with connect() as conn:
        conn.execute("UPDATE issue SET project_id = NULL WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM project WHERE id = ?", (project_id,))
    return True


def merge_projects(target_id: int, source_id: int, name: str | None = None) -> dict | None:
    """把 source 的仓库并进 target，然后把 source 删掉；issue 也一起迁过去。"""
    target = get_project(target_id)
    source = get_project(source_id)
    if not target or not source:
        return None
    repos = list(dict.fromkeys([*target["repos"], *source["repos"]]))
    update_project(target_id, name=name or target["name"], repos=repos)
    with connect() as conn:
        conn.execute("UPDATE issue SET project_id = ? WHERE project_id = ?", (target_id, source_id))
        conn.execute("DELETE FROM project WHERE id = ?", (source_id,))
    return get_project(target_id)


def sync_scanned_projects() -> dict:
    """扫描 + 聚类，把还没入库的候选项目补进去（已存在同名同仓库的跳过）。

    不删除任何已有项目：用户改过名的项目不能被扫描结果覆盖。
    """
    repos = discover_repos()
    clusters = cluster_projects(repos)
    existing = list_projects(include_ignored=True)
    existing_repo_sets = {tuple(sorted(p["repos"])) for p in existing}
    ignored_names = {p["name"] for p in existing if p["ignored"]}

    created = []
    for c in clusters:
        key = tuple(sorted(c["repos"]))
        if key in existing_repo_sets:
            continue
        if c["name"] in ignored_names:
            continue
        pid = create_project(c["name"], c["repos"])
        created.append({"id": pid, "name": c["name"], "repos": c["repos"]})

    return {
        "scanned": len(repos),
        "repos": repos,
        "clusters": clusters,
        "created": created,
        "suggestions": suggest_merges(clusters),
        "projects": list_projects(),
    }
