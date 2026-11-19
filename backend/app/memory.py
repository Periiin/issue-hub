"""对话记忆：让「问题」拥有跨通道、跨轮次的上下文。

三条设计原则：

1. **记忆属于问题，不属于 agent**。同一个 issue 的同一类操作共用一个 session，
   换通道/换模型都不影响 —— 新模型进来先读历史，就知道之前讨论过什么。

2. **按操作类型隔离**。定性、定级、分析、改代码各一份 session。
   混在一起会让「整理一段话」被几十轮改代码的工具调用淹没，既贵又干扰。

3. **必须能裁剪**。工具循环会把 read_file 的几十 K 内容累积进 messages，
   不裁剪必然撞上下文上限。裁剪策略见 `trim_messages`。

token 估算故意用「字符数 / 2.5」这种粗糙公式：中英文混排下比 /4 更保守，
宁可多留余量也不要被 API 拒绝。精确计数要引 tiktoken，对单人工具不值。
"""
import json
import sqlite3
from typing import Any

from .db import connect, now

# 上下文预算：留一部分给输出和工具定义，不要吃满模型上限
DEFAULT_CONTEXT_BUDGET = 60_000   # 估算 token
# 单条 tool 结果最多回灌多少字符（read_file 本身已限 40K，这里再收一道）
MAX_TOOL_CHARS = 8_000
# 裁剪时至少保留最近几轮（assistant+tool 成对）
MIN_KEEP_ROUNDS = 3


def estimate_tokens(text: str) -> int:
    """粗估 token：中文约 1 字 1 token，英文约 4 字符 1 token，取 2.5 折中。"""
    if not text:
        return 0
    return int(len(text) / 2.5) + 1


def messages_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        total += estimate_tokens(str(m.get("content") or ""))
        for call in (m.get("tool_calls") or []):
            fn = call.get("function") or {}
            total += estimate_tokens(str(fn.get("arguments") or ""))
    return total


# ---------------- 工具结果去重 ----------------

def tool_key(name: str, args: dict) -> str:
    """工具调用的指纹：同名同参视为重复。"""
    try:
        return f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
    except (TypeError, ValueError):
        return f"{name}:{args}"


def dedupe_tool_output(seen: dict[str, str], name: str, args: dict, output: str) -> str:
    """同一个工具+参数重复调用时，不重复回灌全文。

    实测模型会反复 read_file 同一个文件（尤其改代码时来回确认），
    每次都塞 8K 字符纯属浪费。这里返回一句指代，让它知道内容在前面。
    """
    key = tool_key(name, args)
    if key in seen:
        return f"（与之前调用 {name} 的结果相同，内容已在上文，此处省略）"
    seen[key] = output
    return output


# ---------------- 裁剪 ----------------

def trim_messages(messages: list[dict], budget: int = DEFAULT_CONTEXT_BUDGET) -> tuple[list[dict], bool]:
    """把 messages 压到预算内，返回 (新列表, 是否裁剪过)。

    策略：
      1. 永远保留 system 和第一条 user（原始任务，丢了模型就不知道在干嘛）
      2. 从最旧的「assistant+tool」对话对开始丢，但不拆散 tool_calls 与其结果
      3. 丢掉的地方插一条说明，让模型知道有历史被省略

    为什么不按 token 逐条精确删：会把一条 tool 调用和它的结果拆开，
    OpenAI 协议要求 tool 消息必须紧跟对应的 assistant.tool_calls，拆了就 400。
    """
    if messages_tokens(messages) <= budget:
        return messages, False

    head: list[dict] = []
    rest: list[dict] = []
    for i, m in enumerate(messages):
        # system 全部保留；第一条 user 保留
        if m.get("role") == "system" and not rest:
            head.append(m)
        elif m.get("role") == "user" and not rest and not any(x.get("role") == "user" for x in head):
            head.append(m)
        else:
            rest.append(m)

    # 从尾部往前保留，直到接近预算（留 head 的余量）
    head_tokens = messages_tokens(head)
    keep: list[dict] = []
    used = head_tokens
    dropped = 0
    for m in reversed(rest):
        cost = messages_tokens([m])
        if used + cost > budget and len(keep) > MIN_KEEP_ROUNDS * 2:
            dropped += 1
            continue
        keep.insert(0, m)
        used += cost

    if not dropped:
        return messages, False

    marker = {
        "role": "assistant",
        "content": f"（为控制上下文长度，此处省略了 {dropped} 条较早的对话与工具结果；"
                   f"如需了解，可重新调用工具查看。）",
    }
    return head + [marker] + keep, True


# ---------------- session 读写 ----------------

def _row(r) -> dict:
    d = dict(r)
    try:
        d["messages"] = json.loads(d.get("messages") or "[]")
    except json.JSONDecodeError:
        d["messages"] = []
    return d


def get_session(issue_id: int, kind: str) -> dict | None:
    try:
        with connect() as conn:
            r = conn.execute(
                "SELECT * FROM ai_session WHERE issue_id = ? AND kind = ?", (issue_id, kind)
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return _row(r) if r else None


def save_session(issue_id: int, kind: str, messages: list[dict],
                 rounds_add: int = 0, tokens: int | None = None) -> None:
    """写回 session。messages 存完整历史（已裁剪过的），turns 累加调用次数。"""
    payload = json.dumps(messages, ensure_ascii=False)
    total_tokens = tokens if tokens is not None else messages_tokens(messages)
    ts = now()
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT id, rounds, turns FROM ai_session WHERE issue_id = ? AND kind = ?",
                (issue_id, kind)).fetchone()
            if row:
                conn.execute(
                    "UPDATE ai_session SET messages = ?, rounds = ?, turns = ?, tokens = ?, "
                    "updated_at = ? WHERE id = ?",
                    (payload, row["rounds"] + rounds_add, row["turns"] + 1,
                     total_tokens, ts, row["id"]))
            else:
                conn.execute(
                    "INSERT INTO ai_session(issue_id, kind, messages, rounds, turns, tokens, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                    (issue_id, kind, payload, rounds_add, total_tokens, ts, ts))
    except sqlite3.OperationalError:
        pass


def clear_session(issue_id: int, kind: str | None = None) -> int:
    with connect() as conn:
        if kind:
            cur = conn.execute("DELETE FROM ai_session WHERE issue_id = ? AND kind = ?",
                               (issue_id, kind))
        else:
            cur = conn.execute("DELETE FROM ai_session WHERE issue_id = ?", (issue_id,))
        return cur.rowcount


def list_sessions(issue_id: int) -> list[dict]:
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT id, kind, rounds, turns, tokens, created_at, updated_at "
                "FROM ai_session WHERE issue_id = ? ORDER BY kind", (issue_id,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


# ---------------- 历史记忆注入 ----------------

KIND_LABELS = {
    "qualify": "定性",
    "triage": "定级",
    "analysis": "分析",
    "apply": "改代码",
}


def build_memory_block(issue: dict, attempts: list[dict] | None = None,
                       current_kind: str = "") -> str:
    """把「这个问题的已知信息」拼成一段给模型看的背景。

    内容都是**结论性**的（不是原始对话）：已确认描述、定级结论、历次修改的
    实际根因与偏离。原始对话在 session.messages 里，这里只放提炼后的事实，
    避免同一段话在上下文里出现两遍。

    为什么把历次修改档案也放进来：模型最常犯的错是「重复上一轮的错误结论」。
    告诉它「第 1 轮你以为是 A，实际是 B」，它就不会再往 A 方向走。
    """
    lines: list[str] = []

    final = issue.get("qualify_final")
    if isinstance(final, str):
        try:
            final = json.loads(final)
        except json.JSONDecodeError:
            final = None
    if isinstance(final, dict) and final:
        lines.append("## 已确认的问题描述（人工确认过，视为事实）")
        for label, key in (("现象", "phenomenon"), ("期望", "expected"), ("实际", "actual"),
                           ("影响范围", "scope"), ("归属模块", "module")):
            if final.get(key):
                lines.append(f"- {label}：{final[key]}")
        steps = final.get("repro_steps") or []
        if steps:
            lines.append("- 复现步骤：" + "；".join(str(s) for s in steps))
        unsure = final.get("uncertainties") or []
        if unsure:
            lines.append("- 仍待确认：" + "；".join(str(s) for s in unsure))
        lines.append("")

    triage = issue.get("triage")
    if isinstance(triage, str):
        try:
            triage = json.loads(triage)
        except json.JSONDecodeError:
            triage = None
    if isinstance(triage, dict) and triage:
        lines.append("## 定级结论")
        lines.append(f"- 优先级 {triage.get('priority', '-')} / 影响 {triage.get('severity', '-')}"
                     f" / 复杂度 {triage.get('complexity', '-')}")
        if triage.get("reasons"):
            lines.append("- 依据：" + "；".join(str(x) for x in triage["reasons"]))
        lines.append("")

    plan = issue.get("fix_plan")
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError:
            plan = None
    if isinstance(plan, dict) and plan and current_kind == "apply":
        lines.append("## 上一轮的分析结论（供参考，可能与实际不符）")
        if plan.get("root_cause"):
            lines.append(f"- 根因：{plan['root_cause']}")
        if plan.get("changes"):
            lines.append("- 改动点：" + "；".join(str(x) for x in plan["changes"]))
        lines.append("")

    if attempts and current_kind in ("apply", "analysis"):
        lines.append("## 历史修改记录（重点看「实际根因」和「与方案的出入」）")
        for a in attempts[:3]:
            lines.append(f"### 第 {a.get('seq')} 次修改（{a.get('status')}）")
            if a.get("actual_root_cause"):
                lines.append(f"- 实际根因：{a['actual_root_cause']}")
            devs = a.get("deviations") or []
            if devs:
                lines.append("- 与方案的出入：" + "；".join(str(x) for x in devs))
            found = a.get("found_issues") or []
            if found:
                lines.append("- 当时发现的新问题：" + "；".join(str(x) for x in found))
            files = a.get("files") or []
            if files:
                lines.append("- 当时改过的文件：" + "、".join(str(x) for x in files))
            lines.append("")
        lines.append("**不要重复上面已经踩过的坑；如果判断与历史结论不同，请说明依据。**")
        lines.append("")

    return "\n".join(lines).strip()
