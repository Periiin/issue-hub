"""用户仓库副本管理：查看状态、同步、删除。"""
from fastapi import APIRouter, Depends, HTTPException

from .. import projects as proj_mod
from .. import repos as repos_mod
from .auth import require_user

router = APIRouter(prefix="/api/repos", tags=["repos"])


def _my_sources(user: dict) -> list[str]:
    """当前用户可见的源仓库（来自他可见的项目）。"""
    projects = proj_mod.list_projects(include_ignored=True)
    if user.get("role") != "admin":
        uid = user.get("id") or 0
        projects = [p for p in projects if p.get("owner_id") in (None, uid)]
    out: list[str] = []
    for p in projects:
        for r in p.get("repos") or []:
            if r not in out:
                out.append(r)
    return out


@router.get("")
def list_copies(user: dict = Depends(require_user)):
    """每个源仓库对应的用户副本状态。"""
    owner = user.get("id")
    sources = _my_sources(user)
    items = []
    for src in sources:
        st = repos_mod.copy_status(src, owner)
        items.append(st)
    total = sum(i.get("sizeMb") or 0 for i in items)
    return {"copies": items, "totalMb": total,
            "mode": "copy" if owner else "shared"}


@router.post("/sync")
def sync_one(source: str, user: dict = Depends(require_user)):
    try:
        return repos_mod.sync_copy(source, user.get("id"))
    except repos_mod.RepoError as ex:
        raise HTTPException(400, str(ex))


@router.post("/sync-all")
def sync_all(user: dict = Depends(require_user)):
    results = {}
    for src in _my_sources(user):
        try:
            results[src] = repos_mod.sync_copy(src, user.get("id"))
        except repos_mod.RepoError as ex:
            results[src] = {"ok": False, "error": str(ex)}
    return {"results": results}


@router.delete("")
def delete_one(source: str, user: dict = Depends(require_user)):
    return repos_mod.delete_copy(source, user.get("id"))
