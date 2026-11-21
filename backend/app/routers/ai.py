"""AI 路由：薄壳。真正的流程在 app/ai_core.py（HTTP 与 MCP 共用一条路径）。

这样 MCP 跑 AI 时也会落 ai_run、写 prompt_version、事件带 actor——
原来 MCP 自己写了一份简化流程，Web 端「运行记录」根本看不到它跑过。
"""
from fastapi import APIRouter, Depends, HTTPException

from .. import ai_core
from ..access import AccessDenied
from ..schemas import AIRequest, FixRequest, QualifyConfirm
from .auth import require_user

router = APIRouter(prefix="/api/issues", tags=["ai"])


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AccessDenied:
        raise  # web 进程下 access 抛的就是 HTTPException(404)
    except ValueError as ex:
        raise HTTPException(400, str(ex))


@router.post("/{issue_id}/qualify")
def qualify(issue_id: int, payload: AIRequest, user: dict = Depends(require_user)):
    """AI 定性：把甲方原话整理成结构化问题描述（草稿，需人工确认）。"""
    return _guard(ai_core.qualify, user, issue_id, payload.channel_id)


@router.post("/{issue_id}/qualify/confirm")
def confirm_qualify(issue_id: int, payload: QualifyConfirm,
                    user: dict = Depends(require_user)):
    """人工确认定性结果：确认后才允许进入定级。"""
    return _guard(ai_core.confirm_qualify, user, issue_id, payload.model_dump())


@router.post("/{issue_id}/triage")
def triage(issue_id: int, payload: AIRequest, user: dict = Depends(require_user)):
    """AI 定级：基于已确认的描述给出 S/复杂度/P，并把结果写回问题。"""
    return _guard(ai_core.triage, user, issue_id, payload.channel_id)


@router.post("/{issue_id}/fix")
def make_fix_plan(issue_id: int, payload: FixRequest, user: dict = Depends(require_user)):
    """「操作解决」第一步：让 agent 在仓库里定位根因并给方案（不改代码）。"""
    return _guard(ai_core.fix_plan, user, issue_id, payload.channel_id,
                  payload.code_scopes)
