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
4. 画一张故障链路流程图（Mermaid flowchart），让人一眼看出问题出在哪一步。
5. **这一轮只做分析，不要修改任何文件。**

【流程图规则】flow 字段必须是可直接渲染的 Mermaid flowchart 源码：
- 第一行固定 `flowchart TD`，节点从上到下排。
- **所有节点标签和连线标签必须用双引号包起来**，例如 `A["前端请求 /app/user/login"]`、
  `B{{"token 有效?"}}`、`C -->|"校验失败"| D["返回 401"]`。
  路径里的 `/`、`@`、`:` 等字符不加引号会导致 Mermaid 解析失败。
- 只画关键步骤（5~12 个节点），不要把所有代码细节都塞进去。
- 用 `style` 标出问题节点，例如 `style D fill:#ffe0e0,stroke:#d33`。
- 不要输出 Markdown 代码块标记，不要有 ```mermaid 包裹。

严格输出 JSON：
{{
  "root_cause": "根因说明",
  "files": ["涉及的文件路径"],
  "changes": ["具体改动点，每条一句话"],
  "verification": ["怎么验证修好了"],
  "risks": ["风险/回归点"],
  "flow": "flowchart TD\n  A[\"起点\"] --> B{{\"判断\"}}\n  B -->|\"失败\"| C[\"出问题的一步\"]\n  style C fill:#ffe0e0,stroke:#d33",
  "can_auto_fix": true
}}
"""

APPLY_SYSTEM = (
    "你是这个项目的开发工程师，现在要直接修改代码修复问题。"
    "只改必要的地方，不要重构、不要顺手改无关文件。最后用中文简要说明改了什么。"
)

APPLY_TEMPLATE = """在下面这个独立的工作目录里修复问题（这是一个 git worktree，可以放心修改）：

工作目录：{worktree}

【本次修复边界】（由 issue-hub 生成，用户可能已修改，请严格遵守）
{boundary}

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
7. 如果根因不在本 worktree 覆盖的目录内，**不要硬改**，在总结里说明「需要在 xxx 仓库修复」。

【输出】
先用中文简要说明你做了什么（供人直接阅读），然后**在最后输出一个 JSON 报告**（用 ```json 围栏包住）。
这个报告会被记录成「第 N 次修改」的档案，重点是**实际改的过程与分析方案的出入**——
发现方案不对、走弯路、根因和预想不一样，都要如实写，这对校准后续分析非常关键：

```json
{{
  "actual_root_cause": "实际根因；与分析一致就照抄，不一致就写清楚差在哪",
  "deviations": ["与既定修复思路的出入点，每条一句话；完全按方案改就给空数组"],
  "found_issues": ["修改过程中顺带发现的新问题/隐患（本次没修的），没有就空数组"],
  "files": ["实际改动的文件路径"],
  "risks": ["遗留风险/回归点"],
  "verification": "怎么验证的；没验证就说明原因",
  "summary": "一两句话总结本次修改"
}}
```
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
                       plan: dict[str, Any] | None = None,
                       boundary: str = "", context_file: str = "") -> str:
    """boundary 是「修复边界」正文（来自 context 文件），会内联进提示词。

    agent 不一定愿意去 read 一个外部文件，内联最可靠；同时给出文件路径，
    方便它想看完整版时自己打开。
    """
    if boundary:
        boundary_block = boundary.strip()
        if context_file:
            boundary_block += f"\n\n（完整文件：{context_file}）"
    else:
        boundary_block = "（无额外边界说明，只改本 worktree 内的文件）"
    return APPLY_TEMPLATE.format(
        worktree=worktree,
        description=json.dumps(qualify_final, ensure_ascii=False, indent=2),
        plan=json.dumps(plan or {}, ensure_ascii=False, indent=2) if plan else "（无，自行判断）",
        boundary=boundary_block,
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


_LAST_FENCE = re.compile(r"```json\s*(\{.*?\})\s*```", re.IGNORECASE | re.S)


def _balanced_objects(text: str) -> list[str]:
    """按花括号配对找出所有完整的 {...} 子串（含嵌套），按出现顺序返回。"""
    out, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    out.append(text[start:i + 1])
    return out


def parse_apply_report(text: str) -> dict[str, Any] | None:
    """从「改代码」agent 的输出里抠出末尾的 JSON 报告。

    改代码的 agent 会先写一大段中文说明再给 JSON，正文里可能有花括号
    （代码片段），所以不能用「第一个 { 到最后一个 }」的宽松策略：
    1. 优先找最后一个 ```json 围栏；
    2. 失败则扫描所有平衡的 {...}，从后往前试解析（报告在末尾）。
    解析不出来返回 None——报告只是锦上添花，不能因为它把一次成功的
    修改判成失败。
    """
    if not text or not text.strip():
        return None
    fences = _LAST_FENCE.findall(text)
    for raw in reversed(fences):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    for raw in reversed(_balanced_objects(text)):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return None
