"""项目接口：扫描、CRUD、合并。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..projects import (cluster_projects, create_project, delete_project, discover_repos,
                        get_project, list_projects, merge_projects, scan_roots,
                        suggest_merges, sync_scanned_projects, update_project)
from ..fix import is_repo_root
from .auth import require_user

router = APIRouter(prefix="/api", tags=["project"])


def _visible(projects: list[dict], user: dict) -> list[dict]:
    """admin 看全部；普通用户看自己的 + 共享（owner 为空）。"""
    if user.get("role") == "admin":
        return projects
    uid = user.get("id") or 0
    return [p for p in projects if p.get("owner_id") in (None, uid)]


def _assert_owner(project: dict | None, user: dict, action: str = "操作"):
    """改/删项目必须是自己（或 admin）。"""
    if not project:
        raise HTTPException(404, "项目不存在")
    if user.get("role") == "admin":
        return
    owner = project.get("owner_id")
    if owner is not None and owner != user.get("id"):
        raise HTTPException(403, f"无权{action}别人的项目")


class ProjectCreate(BaseModel):
    name: str = ""
    repos: list[str] = []
    notes: str = ""
    verify_cmd: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    repos: Optional[list[str]] = None
    notes: Optional[str] = None
    ignored: Optional[bool] = None
    # 采纳前跑的验证命令；留空则按仓库特征自动推断
    verify_cmd: Optional[str] = None


class ProjectMerge(BaseModel):
    target_id: int
    source_id: int
    name: Optional[str] = None


def _check_repos(repos: list[str]) -> list[str]:
    """只保留真正的 git 仓库根目录，避免把随便一个目录塞进项目。"""
    bad = [r for r in repos if not is_repo_root(r)]
    if bad:
        raise HTTPException(400, f"这些不是 git 仓库根目录：{', '.join(bad)}")
    return list(dict.fromkeys(repos))


@router.get("/projects")
def get_projects(user: dict = Depends(require_user)):
    return {"projects": _visible(list_projects(include_ignored=True), user)}


@router.post("/projects")
def add_project(payload: ProjectCreate, user: dict = Depends(require_user)):
    repos = _check_repos(payload.repos)
    if not repos:
        raise HTTPException(400, "至少要包含一个 git 仓库")
    pid = create_project(payload.name, repos, payload.notes, payload.verify_cmd,
                         owner_id=user.get("id"))
    return {"id": pid, "project": get_project(pid)}


@router.patch("/projects/{project_id}")
def patch_project(project_id: int, payload: ProjectUpdate, user: dict = Depends(require_user)):
    _assert_owner(get_project(project_id), user, "修改")
    repos = _check_repos(payload.repos) if payload.repos is not None else None
    update_project(project_id, name=payload.name, repos=repos,
                   notes=payload.notes, ignored=payload.ignored,
                   verify_cmd=payload.verify_cmd)
    return {"project": get_project(project_id)}


@router.delete("/projects/{project_id}")
def remove_project(project_id: int, user: dict = Depends(require_user)):
    _assert_owner(get_project(project_id), user, "删除")
    delete_project(project_id)
    return {"ok": True}


@router.post("/projects/merge")
def merge(payload: ProjectMerge, user: dict = Depends(require_user)):
    if payload.target_id == payload.source_id:
        raise HTTPException(400, "不能把自己合并到自己")
    _assert_owner(get_project(payload.target_id), user, "合并")
    _assert_owner(get_project(payload.source_id), user, "合并")
    merged = merge_projects(payload.target_id, payload.source_id, payload.name)
    if not merged:
        raise HTTPException(404, "项目不存在")
    return {"project": merged}


@router.get("/code/scan")
def scan(dry: bool = True, user: dict = Depends(require_user)):
    """扫描仓库并聚类。

    dry=true（默认）只返回候选，不入库，用于设置页预览；
    dry=false 会把新发现的候选项目写进库（已存在的跳过）。
    """
    roots = scan_roots()
    if not roots:
        return {"scanned": 0, "repos": [], "clusters": [], "created": [],
                "suggestions": [], "projects": list_projects(include_ignored=True),
                "roots": [], "hint": "还没有配置扫描根，去设置里填（例如 /src 或 E:/project）"}
    if dry:
        repos = discover_repos()
        clusters = cluster_projects(repos)
        return {"scanned": len(repos), "repos": repos, "clusters": clusters,
                "created": [], "suggestions": suggest_merges(clusters),
                "projects": list_projects(include_ignored=True), "roots": roots}
    result = sync_scanned_projects()
    result["roots"] = roots
    return result
