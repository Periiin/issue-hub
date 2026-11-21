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
    # 归属项目；不传时按 module / code_scopes 里的路径自动猜
    project_id: Optional[int] = None


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
    # 负责人（app_user.username）；空串表示取消分配
    assignee: Optional[str] = None
    # 承诺给甲方的截止日期 YYYY-MM-DD；空串表示清空
    due_date: Optional[str] = None
    # 标签（整组覆盖）
    tags: Optional[list[str]] = None


class LinkCreate(BaseModel):
    other_id: int
    kind: str = "duplicate"


class CommentCreate(BaseModel):
    body: str = ""


class IssueBatchIds(BaseModel):
    ids: list[int]


class IssueBatchPatch(BaseModel):
    """批量改：只允许改「一排人一起改」有意义的字段。

    标题/描述/复现步骤这类逐条不同的内容不放进批量，
    否则一次误操作能把 50 条问题改成同一个标题。
    """
    ids: list[int]
    status: Optional[str] = None
    priority: Optional[str] = None
    severity: Optional[str] = None
    complexity: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    module: Optional[str] = None
    # 归属项目：0 或 null 表示取消归属
    project_id: Optional[int] = None
    # 标签是「加」不是「覆盖」：批量打标签的语义是追加
    add_tags: Optional[list[str]] = None


class AIRequest(BaseModel):
    # 通道 id；不传则用设置里的默认通道
    channel_id: Optional[int] = None


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
    channel_id: Optional[int] = None
    # 临时指定分析范围（优先级高于 issue 已勾的和项目仓库）
    code_scopes: Optional[list[str]] = None


class FixApplyReq(BaseModel):
    """开始改代码：给每个目标仓库建 worktree，让模型各自动手。"""
    channel_id: Optional[int] = None
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
