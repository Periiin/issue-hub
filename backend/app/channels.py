"""AI 通道：把「选执行器」换成「配通道」。

一个通道 = 一个模型入口，两种类型：
- api   —— OpenAI 兼容端点（官方 / 中转站 / 自建都行）。通过 function calling
           的工具循环获得读文件、grep、写文件的能力，因此也能改代码。
- agent —— 本地 CLI（claude / dsh）。自带文件工具，开箱能改代码。
- mock  —— 假数据，验证流程用。

这层抽象的目的：用户拥有的是一组 API 端点和模型名，而不是「三选一」。
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

from . import codetools, memory
from .db import connect, get_settings, now


class AIError(RuntimeError):
    pass


@dataclass
class AIResult:
    text: str
    model: str
    provider: str
    duration_ms: int
    rounds: int = 0
    tool_calls: int = 0


# ---------------- 通道读写 ----------------

def _row(r) -> dict:
    d = dict(r)
    d["enabled"] = bool(d.get("enabled"))
    d["hasKey"] = bool((d.get("api_key") or "").strip())
    # 密钥不回传明文，前端只需要知道有没有配
    d.pop("api_key", None)
    return d


def list_channels(include_disabled: bool = True) -> list[dict]:
    sql = "SELECT * FROM channel"
    if not include_disabled:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY sort, id"
    try:
        with connect() as conn:
            rows = conn.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return []
    return [_row(r) for r in rows]


def get_channel(channel_id: int) -> dict | None:
    """取通道原始记录（含 api_key），仅供内部调用。"""
    try:
        with connect() as conn:
            r = conn.execute("SELECT * FROM channel WHERE id = ?", (channel_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return dict(r) if r else None


def create_channel(data: dict) -> int:
    ts = now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO channel(name, kind, base_url, api_key, model, command, args, "
            "temperature, max_rounds, enabled, sort, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data.get("name") or "未命名通道", data.get("kind") or "api",
             data.get("base_url") or "", data.get("api_key") or "", data.get("model") or "",
             data.get("command") or "", data.get("args") or "",
             float(data.get("temperature") if data.get("temperature") is not None else 0.2),
             int(data.get("max_rounds") or 25),
             1 if data.get("enabled", True) else 0, int(data.get("sort") or 0), ts, ts))
        return cur.lastrowid


def update_channel(channel_id: int, data: dict) -> bool:
    fields, args = [], []
    for key in ("name", "kind", "base_url", "model", "command", "args"):
        if key in data and data[key] is not None:
            fields.append(f"{key} = ?")
            args.append(data[key])
    # 密钥：空字符串表示不改，__CLEAR__ 表示清空
    if "api_key" in data:
        value = data["api_key"]
        if value == "__CLEAR__":
            fields.append("api_key = ?")
            args.append("")
        elif value and value.strip():
            fields.append("api_key = ?")
            args.append(value.strip())
    for key in ("temperature", "max_rounds", "sort"):
        if data.get(key) is not None:
            fields.append(f"{key} = ?")
            args.append(float(data[key]) if key == "temperature" else int(data[key]))
    if "enabled" in data and data["enabled"] is not None:
        fields.append("enabled = ?")
        args.append(1 if data["enabled"] else 0)
    if not fields:
        return False
    fields.append("updated_at = ?")
    args.append(now())
    args.append(channel_id)
    with connect() as conn:
        conn.execute(f"UPDATE channel SET {', '.join(fields)} WHERE id = ?", args)
    return True


def delete_channel(channel_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM channel WHERE id = ?", (channel_id,))


# ---------------- 模型列表 ----------------

def list_models(base_url: str, api_key: str, timeout: int = 20) -> list[str]:
    """拉 /v1/models。中转站基本都支持；不支持时由前端让用户手填。"""
    url = (base_url or "").rstrip("/")
    if not url:
        raise AIError("Base URL 不能为空")
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{url}/models",
                              headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as ex:
        raise AIError(f"获取模型列表失败（{ex.response.status_code}）：{ex.response.text[:200]}") from ex
    except Exception as ex:
        raise AIError(f"获取模型列表失败：{ex}") from ex
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise AIError(f"响应里没有模型列表：{str(data)[:200]}")
    names = []
    for it in items:
        if isinstance(it, dict):
            name = it.get("id") or it.get("name")
            if name:
                names.append(str(name))
        elif isinstance(it, str):
            names.append(it)
    return sorted(dict.fromkeys(names))


# ---------------- Mock ----------------

class MockProvider:
    name = "mock"

    def run(self, prompt: str, system: str = "", cwd: Optional[str] = None,
            timeout: int = 180, allow_write: bool = False) -> AIResult:
        started = time.time()
        if "结构化的问题描述" in prompt:
            data = {
                "title": "（示例）会员详情预约记录打不开",
                "phenomenon": "点击会员详情的预约记录后页面空白",
                "repro_steps": ["进入会员详情", "切换到预约记录 tab"],
                "expected": "展示该会员的预约列表",
                "actual": "接口报错，列表空白",
                "scope": "待确认：是否所有会员都受影响",
                "module": "会员详情/预约记录",
                "uncertainties": ["是否只影响个别会员", "是否有报错截图"],
                "tags": ["后端", "待复现"],
            }
        elif "评估影响等级" in prompt:
            data = {
                "severity": "S2", "complexity": "中等", "priority": "P1",
                "reasons": ["影响会员查看预约信息", "有临时绕过（去预约管理页查）"],
                "suggested_owner": "后端", "estimated_effort": "1 天",
                "risks": ["需要回归会员详情的其它 tab"],
            }
        elif "修复" in prompt or "改" in prompt:
            data = {
                "root_cause": "（示例）列表接口缺少必要的关联查询",
                "files": [], "changes": ["补充关联查询并加空值保护"],
                "verification": ["打开会员详情-预约记录，列表正常"],
                "risks": ["注意不要引入 N+1 查询"], "can_auto_fix": False,
            }
        else:
            data = {"summary": "（mock）没有实际改动"}
        return AIResult(text=json.dumps(data, ensure_ascii=False), model="mock",
                        provider=self.name, duration_ms=int((time.time() - started) * 1000))


# ---------------- API 通道（带工具循环） ----------------

class ApiChannelProvider:
    """OpenAI 兼容通道 + function calling 工具循环。

    循环逻辑：
      1. 发 messages（含 tools 定义）
      2. 模型返回 tool_calls → 逐个执行 codetools.dispatch → 结果作为 tool 消息回灌
      3. 没有 tool_calls 或达到 max_rounds → 取 content 作为最终答案

    只读场景（allow_write=False）不注册写工具，模型看不到也就不会尝试。
    """

    def __init__(self, channel: dict, session: dict | None = None,
                 issue_id: int | None = None, kind: str = ""):
        self.channel = channel
        self.name = f"channel:{channel['id']}"
        self.base_url = (channel.get("base_url") or "").rstrip("/")
        self.api_key = (channel.get("api_key") or "").strip()
        self.model = (channel.get("model") or "").strip()
        self.temperature = float(channel.get("temperature") or 0.2)
        self.max_rounds = int(channel.get("max_rounds") or 25)
        # 记忆：issue_id + kind 定位一条 session，与通道无关
        self.session = session
        self.issue_id = issue_id
        self.kind = kind

    def _post(self, messages: list[dict], tools: list[dict] | None, timeout: int) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as ex:
            body = ex.response.text[:400]
            # 常见坑：端点少了 /v1、模型名不对、key 无效
            raise AIError(f"通道返回 {ex.response.status_code}：{body}") from ex
        except Exception as ex:
            raise AIError(f"请求通道失败：{ex}") from ex

    def run(self, prompt: str, system: str = "", cwd: Optional[str] = None,
            timeout: int = 180, allow_write: bool = False) -> AIResult:
        if not self.base_url:
            raise AIError("通道缺少 Base URL")
        if not self.model:
            raise AIError("通道缺少模型名")
        started = time.time()

        # 没有工作目录（比如定性/定级）就不给工具，纯文本往返更快
        root = Path(cwd).resolve() if cwd and Path(cwd).is_dir() else None
        tools = codetools.tool_specs(allow_write) if root else None
        ignore = _ignore_list()

        # ===== 记忆：读历史 =====
        # 历史只放「结论性事实」，原始对话在 session.messages 里。
        # 这样既让模型知道前情，又不会把旧工具结果重复塞进上下文。
        history: list[dict] = []
        if self.session and self.session.get("messages"):
            history = [
                m for m in self.session["messages"]
                if m.get("role") in ("user", "assistant") and m.get("content")
            ][-6:]   # 只带最近几条对话轮，细节靠 memory_block

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        for m in history:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": prompt})

        rounds = 0
        tool_calls = 0
        text = ""
        seen_tools: dict[str, str] = {}
        trimmed_any = False
        while rounds < self.max_rounds:
            rounds += 1
            # 发请求前裁剪：工具结果累积很容易撞上限
            messages, trimmed = memory.trim_messages(messages)
            trimmed_any = trimmed_any or trimmed
            data = self._post(messages, tools, timeout)
            try:
                message = data["choices"][0]["message"]
            except (KeyError, IndexError) as ex:
                raise AIError(f"通道响应格式异常：{str(data)[:300]}") from ex

            calls = message.get("tool_calls") or []
            content = message.get("content") or ""
            if not calls:
                text = content
                break

            # 把助手的工具调用意图原样带回（OpenAI 要求）
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {"id": c.get("id"), "type": "function",
                     "function": {"name": c["function"]["name"],
                                  "arguments": c["function"].get("arguments") or "{}"}}
                    for c in calls
                ],
            })
            for call in calls:
                tool_calls += 1
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                output = codetools.dispatch(root, name, args, allow_write, ignore) if root \
                    else "错误：没有可访问的工作目录"
                # 同参数重复调用不重复回灌；单条结果再收一道长度
                output = memory.dedupe_tool_output(seen_tools, name, args, output)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": output[:memory.MAX_TOOL_CHARS],
                })
        else:
            # 用完轮数还没收敛：把已有内容当结论，并提示模型可能没做完
            text = (messages[-1].get("content") or "") if messages else ""
            text = f"（达到工具调用上限 {self.max_rounds} 轮，以下可能不完整）\n{text}"

        # ===== 记忆：写回 =====
        # 只存「干净的对话轮」：user 提问 + assistant 最终结论。
        # 工具调用的中间过程不存 —— 它们只是过程，存下来会让下次上下文爆炸，
        # 而且模型下次可以重新调用工具获取最新内容（代码可能已经变了）。
        _append_session_turn(self.issue_id, self.kind, self.session, prompt, text, rounds)

        return AIResult(text=text, model=self.model, provider=self.name,
                        duration_ms=int((time.time() - started) * 1000),
                        rounds=rounds, tool_calls=tool_calls)


def _ignore_list() -> list[str]:
    raw = get_settings().get("code.ignore") or ""
    return [s.strip() for s in raw.split(",") if s.strip()]


# ---------------- 本地 Agent 通道 ----------------

class AgentChannelProvider:
    """本地 CLI agent（claude / dsh）。自带文件工具，allow_write 时放开写权限。"""

    def __init__(self, channel: dict):
        self.channel = channel
        self.name = f"channel:{channel['id']}"
        self.kind = (channel.get("kind") or "agent").strip()
        self.command = (channel.get("command") or "").strip()
        self.extra_args = (channel.get("args") or "").split()

    def _bin(self) -> str:
        raw = self.command
        if not raw:
            raise AIError("通道缺少命令（如 claude 或 dsh）")
        if Path(raw).is_absolute() and Path(raw).exists():
            return raw
        found = shutil.which(raw)
        if not found:
            raise AIError(
                f"找不到命令 `{raw}`。若装在 nvm 目录下，请填绝对路径，"
                f"或用 ./start.sh 启动（会补 nvm 的 PATH）")
        return found

    def _command(self, prompt: str, allow_write: bool) -> list[str]:
        binary = self._bin()
        if binary.endswith("dsh") or "dsh" in self.command:
            profile = "headless"
            for i, a in enumerate(self.extra_args):
                if a == "--profile" and i + 1 < len(self.extra_args):
                    profile = self.extra_args[i + 1]
            return [binary, "--profile", profile, prompt]
        tools = "Read,Grep,Glob" if not allow_write else "Read,Grep,Glob,Edit,Write"
        cmd = [binary, "-p", prompt, "--output-format", "json", "--allowedTools", tools]
        if allow_write:
            cmd += ["--permission-mode", "acceptEdits"]
        return cmd + self.extra_args

    def run(self, prompt: str, system: str = "", cwd: Optional[str] = None,
            timeout: int = 180, allow_write: bool = False) -> AIResult:
        started = time.time()
        full = f"{system}\n\n{prompt}" if system else prompt
        workdir = cwd if cwd and Path(cwd).is_dir() else None
        try:
            proc = subprocess.run(self._command(full, allow_write), cwd=workdir,
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as ex:
            raise AIError(f"{self.command} 执行超时（>{timeout}s）") from ex
        if proc.returncode != 0:
            raise AIError(f"{self.command} 退出码 {proc.returncode}：{(proc.stderr or proc.stdout)[:400]}")
        return AIResult(text=self._unwrap(proc.stdout), model=self.command,
                        provider=self.name, duration_ms=int((time.time() - started) * 1000))

    @staticmethod
    def _unwrap(stdout: str) -> str:
        raw = (stdout or "").strip()
        if raw.startswith("{"):
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    for key in ("result", "text", "content", "output"):
                        value = data.get(key)
                        if isinstance(value, str) and value.strip():
                            return value
            except json.JSONDecodeError:
                pass
        return raw


# ---------------- 统一入口 ----------------

def resolve_channel(channel_id: int | None) -> dict | None:
    """按 id 取通道；不传则用设置里的默认通道。"""
    if channel_id:
        return get_channel(channel_id)
    settings = get_settings()
    default_id = (settings.get("ai.channel_id") or "").strip()
    if default_id.isdigit():
        ch = get_channel(int(default_id))
        if ch and ch.get("enabled"):
            return ch
    # 没配默认：取第一个启用的
    channels = list_channels(include_disabled=False)
    return get_channel(channels[0]["id"]) if channels else None


def _append_session_turn(issue_id: int | None, kind: str, session: dict | None,
                         prompt: str, text: str, rounds: int) -> None:
    """把这一轮「提问 + 结论」追加进记忆。

    只存对话轮，不存工具调用过程：过程又长又会过期（代码改了就不准），
    模型下次可以重新调用工具拿最新内容。
    """
    if not issue_id or not kind:
        return
    try:
        prior = [
            m for m in (session or {}).get("messages") or []
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        merged = prior + [{"role": "user", "content": prompt},
                          {"role": "assistant", "content": text or "（无输出）"}]
        merged = merged[-40:]   # 最多留 20 轮
        memory.save_session(issue_id, kind, merged, rounds_add=rounds,
                            tokens=memory.messages_tokens(merged))
    except Exception:
        pass


def run_ai(channel_id: int | None, prompt: str, system: str = "",
           cwd: Optional[str] = None, timeout: Optional[int] = None,
           allow_write: bool = False,
           issue_id: int | None = None, kind: str = "",
           memory_block: str = "") -> AIResult:
    """所有 AI 调用的唯一入口。

    issue_id + kind 用于对话记忆：记忆挂在「问题 + 操作类型」上，与通道无关，
    所以换通道、换模型都能接着上次聊。memory_block 是调用方提炼好的历史事实
    （已确认描述、历次修改档案等），会拼在提示词前面。

    channel_id 为 None 时用默认通道。
    """
    settings = get_settings()
    limit = int(timeout or settings.get("ai.timeout") or 180)
    channel = resolve_channel(channel_id)

    # 记忆块拼在最前面：模型先看背景再看当前任务
    full_prompt = prompt
    if memory_block:
        full_prompt = f"# 这个问题的已知背景\n\n{memory_block}\n\n---\n\n# 当前任务\n\n{prompt}"

    session = memory.get_session(issue_id, kind) if (issue_id and kind) else None
    provider_kind = (channel.get("kind") or "api").lower() if channel else "mock"

    if not channel or provider_kind == "mock":
        # 没有可用通道 / 显式选了 mock：仍走记忆写回，方便验证整条链路
        result = MockProvider().run(full_prompt, system=system, cwd=cwd,
                                    timeout=limit, allow_write=allow_write)
        _append_session_turn(issue_id, kind, session, full_prompt, result.text, result.rounds)
        return result
    if provider_kind == "agent":
        provider = AgentChannelProvider(channel)
        return provider.run(full_prompt, system=system, cwd=cwd, timeout=limit,
                            allow_write=allow_write)
    provider = ApiChannelProvider(channel, session=session, issue_id=issue_id, kind=kind)
    return provider.run(full_prompt, system=system, cwd=cwd, timeout=limit,
                        allow_write=allow_write)


def test_channel(channel_id: int, timeout: int | None = None) -> dict:
    """连通性测试：发一句最短的话，确认通道能用。

    agent 类型冷启动可能要几十秒（claude 起 node 进程 + 握手），
    所以默认给 90s，比 API 通道宽松。
    """
    channel = get_channel(channel_id)
    if not channel:
        raise AIError("通道不存在")
    kind = (channel.get("kind") or "api").lower()
    limit = timeout or (90 if kind == "agent" else 40)
    started = time.time()
    result = run_ai(channel_id, "回复两个字：可用", "你是一个连通性测试助手，直接回答。",
                    timeout=limit)
    return {"ok": True, "model": result.model, "reply": (result.text or "")[:120],
            "durationMs": int((time.time() - started) * 1000)}
