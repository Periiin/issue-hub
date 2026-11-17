"""请求/响应模型。字段都给了默认值，前端少传不会 422。"""
from typing import Any, Optional

from pydantic import BaseModel, Field


class IssueCreate(BaseModel):
    title: str = Field(default="", description="留空时用原文前 30 字兜底")
    raw_text: str = ""
    source: str = "wechat"
    reporter: str = ""
    module: str = ""
    code_scopes: list[str] = []


class IssuePatch(BaseModel):
    title: Optional[str] = None
    raw_text: Optional[str] = None
    source: Optional[str] = None
    reporter: Optional[str] = None
    module: Optional[str] = None
    status: Optional[str] = None
    severity: Optional[str] = None
    complexity: Optional[str] = None
    priority: Optional[str] = None
    # 分析用的代码目录（可多选，允许父目录）
    code_scopes: Optional[list[str]] = None
    # 改代码用的单个 git 仓库
    target_repo: Optional[str] = None


class AIRequest(BaseModel):
    provider: Optional[str] = None


class QualifyConfirm(BaseModel):
    title: str = ""
    phenomenon: str = ""
    repro_steps: list[str] = []
    expected: str = ""
    actual: str = ""
    scope: str = ""
    module: str = ""
    uncertainties: list[str] = []
    tags: list[str] = []


class FixRequest(BaseModel):
    provider: Optional[str] = None


class FixApplyReq(BaseModel):
    """开始改代码：在单个 git 仓库上建 worktree 让 agent 动手。"""
    provider: Optional[str] = None
    repo: Optional[str] = None
    message: Optional[str] = None


class FixAcceptReq(BaseModel):
    message: Optional[str] = None
    merge: bool = True


class SettingsUpdate(BaseModel):
    values: dict[str, Any]
