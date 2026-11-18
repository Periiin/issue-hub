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
    # 改代码用的 git 仓库（可多个）
    target_repos: Optional[list[str]] = None
    # 所属项目：0 或 null 表示取消归属
    project_id: Optional[int] = None
    # 兼容旧字段：单个仓库，写入时会合并进 target_repos
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
    """开始改代码：给每个目标仓库建 worktree，让 agent 各自动手。"""
    provider: Optional[str] = None
    # 本次要改的仓库列表；不传则用 issue.target_repos
    repos: Optional[list[str]] = None
    # 兼容旧字段：单个仓库
    repo: Optional[str] = None
    message: Optional[str] = None


class FixAcceptReq(BaseModel):
    """采纳：不传 repo 时采纳全部已成功的仓库。"""
    repo: Optional[str] = None
    message: Optional[str] = None
    merge: bool = True


class FixRejectReq(BaseModel):
    """驳回：不传 repo 时丢弃全部。"""
    repo: Optional[str] = None


class ContextUpdate(BaseModel):
    """用户手动编辑的上下文文件全文。"""
    text: str = ""


class SettingsUpdate(BaseModel):
    values: dict[str, Any]
