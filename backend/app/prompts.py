"""AI 提示词。

设计原则：
1. 定性（qualify）和定级（triage）分开两段，中间必须有人工确认 —— 一次到位
   会让模型把「描述事实」和「判断严重性」混在一起，出错也没法定位。
2. 全部要求输出 JSON，解析失败时把原文存进 ai_run 便于回看。
3. 附件以绝对路径写进提示词：claude / dsh 这类带工具的 agent 能直接读图。
"""
import json
import re
from typing import Any

from .config import RUBRIC_VERSION

QUALIFY_SYSTEM = "你是健身房 SaaS 项目的问题分析助手，输出必须是合法 JSON，不要输出任何解释或 Markdown 代码块标记。"

QUALIFY_TEMPLATE = """下面是一条由甲方（健身房运营方）反馈的问题，原文可能口语化、信息零散，可能附带微信截图。

【原始描述】
{raw_text}

【补充信息】
提出人：{reporter}
归属模块（可能为空，可自行修正）：{module}
来源：{source}

【附件绝对路径】（如果你是能读图的 agent，请打开查看；否则忽略，不要臆造图里的内容）
{attachments}

请整理成结构化的问题描述，严格输出如下 JSON（字段值用中文，不要加注释）：
{{
  "title": "一句话概括，不超过 30 字",
  "phenomenon": "现象：用户看到/遇到了什么",
  "repro_steps": ["复现步骤，按 1/2/3 拆开，信息不足就写推测并标注(待确认)"],
  "expected": "期望结果",
  "actual": "实际结果",
  "scope": "影响范围：哪些门店/角色/会员/数据，能判断多少写多少",
  "module": "归属模块：尽量落到具体功能，如 会员详情/预约记录/合同/营收报表",
  "uncertainties": ["必须向甲方确认的问题点"],
  "tags": ["分类标签，如 前端/后端/数据/权限/报表"]
}}

要求：
- 只根据原文和附件推断，**不要臆造事实**；信息不足的写进 uncertainties。
- 如果原文只是情绪化描述没有具体现象，phenomenon 里如实写「描述不明确」。
"""

TRIAGE_SYSTEM = "你是项目负责人，负责给客户问题定级。输出必须是合法 JSON，不要输出任何解释或 Markdown 代码块标记。"

TRIAGE_TEMPLATE = """请基于下面这条**已由人工确认**的问题描述，评估影响等级、修复复杂度和优先级。

【问题描述】
{description}

【评分规则（{rubric_version}）】
影响等级：
- S1：线上不可用 / 资损 / 数据错乱 / 核心流程完全阻断且无绕过方案
- S2：核心流程受阻但有临时绕过，或只影响单个门店/少数会员
- S3：体验或显示问题，不影响业务达成
- S4：优化建议、文案调整类

修复复杂度：
- 简单：单文件改动或配置调整
- 中等：跨模块但不动表结构，1~2 天
- 复杂：动表结构 / 需要数据修复 / 多端联调 / 涉及第三方

优先级：
- P0：S1 且 简单或中等 —— 当天处理
- P1：S1 复杂，或 S2 简单/中等 —— 3 天内
- P2：S2 复杂，或 S3 —— 本周排期
- P3：S4 —— 有空再做

严格输出 JSON：
{{
  "severity": "S1|S2|S3|S4",
  "complexity": "简单|中等|复杂",
  "priority": "P0|P1|P2|P3",
  "reasons": ["定这个等级的理由，2~4 条，要引用描述里的具体事实"],
  "suggested_owner": "建议谁来处理（前端/后端/数据/运维），不确定写空串",
  "estimated_effort": "预估工作量，如 半天 / 1 天",
  "risks": ["修复可能带来的风险或需要联调的点"]
}}
"""

FIX_SYSTEM = "你是这个项目的开发负责人，负责给出可执行的修复方案。输出必须是合法 JSON，不要输出 Markdown 代码块标记。"

FIX_TEMPLATE = """针对下面这条问题，请在代码仓库中定位相关实现并给出修复方案。

【可搜索的代码目录】
{scopes}

【项目说明】
{project_notes}

【搜索时请跳过这些目录】（体量大且与业务无关）
{ignore}

【问题描述】
{description}

【输出要求】
1. 先定位问题根因（能定位到文件/函数就写出来）。
2. 给出修复方案和改动点（文件路径 + 改什么）。
3. 评估风险与回归点。
4. **这一轮只做分析，不要修改任何文件。**

严格输出 JSON：
{{
  "root_cause": "根因说明",
  "files": ["涉及的文件路径"],
  "changes": ["具体改动点，每条一句话"],
  "verification": ["怎么验证修好了"],
  "risks": ["风险/回归点"],
  "can_auto_fix": true
}}
"""

APPLY_SYSTEM = (
    "你是这个项目的开发工程师，现在要直接修改代码修复问题。"
    "只改必要的地方，不要重构、不要顺手改无关文件。最后用中文简要说明改了什么。"
)

APPLY_TEMPLATE = """在下面这个独立的工作目录里修复问题（这是一个 git worktree，可以放心修改）：

工作目录：{worktree}

【问题描述】
{description}

【已经确认的修复思路（可参考，也可自行判断）】
{plan}

【硬性约束】
1. **只能修改 {worktree} 目录下的文件**，不要碰其它仓库或父目录。
2. **不要执行 git commit / git push / git checkout / git reset**，改动留在工作区即可，由人工审阅后提交。
3. 不要改动依赖锁文件、不要升级依赖、不要改构建脚本，除非问题本身就在那里。
4. 不要编写或修改测试来"绕过"问题；如果仓库已有相关测试，可以补一条最直接的回归用例。
5. 改完如果有把握，跑一次最小编译/类型检查（如 `mvn -q -pl <module> compile`、`npx vue-tsc --noEmit`），把结果写进总结；跑不动就跳过，不要卡住。
6. 如果判断不该改代码（比如是配置或数据问题），直接说明原因，不要硬改。

【输出】
用中文给出：
- 根因（一两句）
- 改了哪些文件、每处改了什么
- 怎么验证
- 有没有遗留风险
"""


def _scopes_block(scopes: list[str]) -> str:
    return "\n".join(f"- {s}" for s in scopes) if scopes else "- （未配置）"


def build_qualify_prompt(issue: dict[str, Any], attachments: list[str]) -> str:
    return QUALIFY_TEMPLATE.format(
        raw_text=(issue.get("raw_text") or "").strip() or "（无文字描述，只有截图）",
        reporter=issue.get("reporter") or "未填写",
        module=issue.get("module") or "",
        source=issue.get("source") or "manual",
        attachments="\n".join(attachments) if attachments else "（无附件）",
    )


def build_triage_prompt(qualify_final: dict[str, Any]) -> str:
    return TRIAGE_TEMPLATE.format(
        description=json.dumps(qualify_final, ensure_ascii=False, indent=2),
        rubric_version=RUBRIC_VERSION,
    )


def build_fix_prompt(qualify_final: dict[str, Any], scopes: list[str] | None = None,
                     ignore: list[str] | None = None, project_notes: str = "") -> str:
    return FIX_TEMPLATE.format(
        scopes=_scopes_block(scopes or []),
        ignore="、".join(ignore or []) or "（无）",
        project_notes=project_notes or "（未配置）",
        description=json.dumps(qualify_final, ensure_ascii=False, indent=2),
    )


def build_apply_prompt(qualify_final: dict[str, Any], worktree: str,
                       plan: dict[str, Any] | None = None) -> str:
    return APPLY_TEMPLATE.format(
        worktree=worktree,
        description=json.dumps(qualify_final, ensure_ascii=False, indent=2),
        plan=json.dumps(plan or {}, ensure_ascii=False, indent=2) if plan else "（无，自行判断）",
    )


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出里抠出 JSON 对象。

    模型即使被要求「只输出 JSON」，也经常加代码块或前后解释，所以：
    1. 去掉 ```json 围栏；
    2. 找第一个 `{` 和最后一个 `}`，截中间解析；
    3. 都失败就抛 ValueError，由调用方记录原始输出。
    """
    if not text or not text.strip():
        raise ValueError("模型返回为空")
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        return json.loads(cleaned[start:end + 1])
    raise ValueError(f"模型输出不是 JSON：{text[:200]}")
