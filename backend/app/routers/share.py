"""甲方只读分享路由。生成/撤销走正常鉴权；读取在 main.py 的 auth_guard 放行。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import share_core
from ..access import AccessDenied
from .auth import require_user

router = APIRouter(prefix="/api", tags=["share"])


class ShareCreate(BaseModel):
    days: int = 30   # 有效期，默认 30 天


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AccessDenied:
        raise  # web 进程下 access 抛的就是 HTTPException(404)
    except ValueError as ex:
        raise HTTPException(400, str(ex))


@router.get("/issues/{issue_id}/share")
def get_share(issue_id: int, user: dict = Depends(require_user)):
    """查问题的当前分享状态（详情页弹窗）。"""
    return _guard(share_core.get_token_info, user, issue_id)


@router.post("/issues/{issue_id}/share")
def create_share(issue_id: int, payload: ShareCreate, user: dict = Depends(require_user)):
    """生成分享链接（重复生成给新 token，旧的保留但不展示）。"""
    return _guard(share_core.create_token, user, issue_id, payload.days)


@router.delete("/issues/{issue_id}/share")
def revoke_share(issue_id: int, token: str = "", user: dict = Depends(require_user)):
    """撤销分享。token 传空撤销全部。"""
    return _guard(share_core.revoke_token, user, issue_id, token or "")


@router.get("/share/{token}")
def read_shared(token: str):
    """甲方访问入口：token 即凭证，不需要登录。见 share_core 的「给什么」说明。"""
    data = share_core.resolve(token)
    if not data:
        raise HTTPException(404, "链接无效或已过期")
    return data
