"""AI 执行器：可插拔。

三种可用后端：
- deepseek：直接调 DeepSeek 的 OpenAI 兼容接口（快、便宜，看不到代码）
- dsh：DeepSeek Harness 无头模式（`dsh --profile headless "任务"`，同机可读仓库）
- claude：Claude Code 无头模式（`claude -p "任务"`，同机可读仓库）
- mock：返回固定 JSON，用来验证「定性 → 确认 → 定级」链路，不消耗额度

新增后端只要实现 run(prompt, system, cwd, timeout) 并在 REGISTRY 注册。
"""
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from .db import get_settings


class AIError(RuntimeError):
    pass


@dataclass
class AIResult:
    text: str
    model: str
    provider: str
    duration_ms: int


class BaseProvider:
    name = "base"

    def run(self, prompt: str, system: str = "", cwd: Optional[str] = None,
            timeout: int = 180, allow_write: bool = False) -> AIResult:
        raise NotImplementedError


class MockProvider(BaseProvider):
    """本地自测用：按提示词类型返回一份结构合法的假数据。"""

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
                "severity": "S2",
                "complexity": "中等",
                "priority": "P1",
                "reasons": ["影响会员查看预约信息", "有临时绕过（去预约管理页查）"],
                "suggested_owner": "后端",
                "estimated_effort": "1 天",
                "risks": ["需要回归会员详情的其它 tab"],
            }
        else:
            data = {
                "root_cause": "（示例）列表接口缺少必要的关联查询",
                "files": [],
                "changes": ["补充关联查询并加空值保护"],
                "verification": ["打开会员详情-预约记录，列表正常"],
                "risks": ["注意不要引入 N+1 查询"],
                "can_auto_fix": False,
            }
        return AIResult(text=json.dumps(data, ensure_ascii=False), model="mock",
                        provider=self.name, duration_ms=int((time.time() - started) * 1000))


class DeepSeekProvider(BaseProvider):
    name = "deepseek"

    def __init__(self, settings: dict[str, str]):
        self.base_url = (settings.get("deepseek.base_url") or "https://api.deepseek.com").rstrip("/")
        self.api_key = (settings.get("deepseek.api_key") or "").strip()
        self.model = (settings.get("deepseek.model") or "deepseek-chat").strip()

    def run(self, prompt: str, system: str = "", cwd: Optional[str] = None,
            timeout: int = 180, allow_write: bool = False) -> AIResult:
        if not self.api_key:
            raise AIError("未配置 DeepSeek API Key，请到「设置」里填写 deepseek.api_key")
        started = time.time()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "你是严谨的助手，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as ex:
            raise AIError(f"DeepSeek 返回 {ex.response.status_code}：{ex.response.text[:300]}") from ex
        except Exception as ex:  # 网络/DNS/超时
            raise AIError(f"调用 DeepSeek 失败：{ex}") from ex
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as ex:
            raise AIError(f"DeepSeek 响应格式异常：{str(data)[:300]}") from ex
        return AIResult(text=text, model=data.get("model", self.model),
                        provider=self.name, duration_ms=int((time.time() - started) * 1000))


class CliProvider(BaseProvider):
    """通过命令行调用的 agent（dsh / claude）。

    - cwd 指向仓库父目录，agent 自己用 grep/read 找代码；
    - 只读场景给 claude 白名单 `Read,Grep,Glob`，避免分析阶段误改文件。
    """

    def __init__(self, name: str, settings: dict[str, str]):
        self.name = name
        self.settings = settings

    def _bin(self) -> str:
        raw = (self.settings.get(f"{self.name}.bin") or self.name).strip()
        if Path(raw).is_absolute() and Path(raw).exists():
            return raw
        found = shutil.which(raw)
        if not found:
            raise AIError(
                f"找不到命令 `{raw}`。如果它装在 nvm 目录下，请在启动脚本里把 node bin 加进 PATH，"
                f"或把设置里的 {self.name}.bin 改成绝对路径"
            )
        return found

    def _command(self, prompt: str, allow_write: bool = False) -> list[str]:
        binary = self._bin()
        if self.name == "dsh":
            profile = (self.settings.get("dsh.profile") or "headless").strip()
            return [binary, "--profile", profile, prompt]
        # claude：只读分析时白名单不含写工具；改代码时放开 Edit/Write 并自动接受编辑
        tools = "Read,Grep,Glob" if not allow_write else "Read,Grep,Glob,Edit,Write"
        cmd = [binary, "-p", prompt, "--output-format", "json",
               "--allowedTools", tools]
        if allow_write:
            cmd += ["--permission-mode", "acceptEdits"]
        model = (self.settings.get("claude.model") or "").strip()
        if model:
            cmd += ["--model", model]
        return cmd

    def run(self, prompt: str, system: str = "", cwd: Optional[str] = None,
            timeout: int = 180, allow_write: bool = False) -> AIResult:
        started = time.time()
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        workdir = cwd or (self.settings.get("repo.root") or "").strip() or None
        if workdir and not Path(workdir).exists():
            workdir = None
        try:
            proc = subprocess.run(
                self._command(full_prompt, allow_write),
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as ex:
            raise AIError(f"{self.name} 执行超时（>{timeout}s）") from ex
        if proc.returncode != 0:
            raise AIError(f"{self.name} 退出码 {proc.returncode}：{(proc.stderr or proc.stdout)[:400]}")
        text = self._unwrap(proc.stdout)
        return AIResult(text=text, model=self.name, provider=self.name,
                        duration_ms=int((time.time() - started) * 1000))

    @staticmethod
    def _unwrap(stdout: str) -> str:
        """claude --output-format json 返回 {"result": "..."}，dsh 直接输出文本。"""
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


def run_ai(provider_name: str, prompt: str, system: str = "",
           cwd: Optional[str] = None, timeout: Optional[int] = None,
           allow_write: bool = False) -> AIResult:
    settings = get_settings()
    name = (provider_name or settings.get("ai.provider") or "mock").strip().lower()
    limit = int(timeout or settings.get("ai.timeout") or 180)
    if name == "mock":
        provider: BaseProvider = MockProvider()
    elif name == "deepseek":
        provider = DeepSeekProvider(settings)
    elif name in ("dsh", "claude"):
        provider = CliProvider(name, settings)
    else:
        raise AIError(f"不支持的 AI 执行器：{name}")
    return provider.run(prompt, system=system, cwd=cwd, timeout=limit,
                        allow_write=allow_write)


def provider_names() -> list[str]:
    return ["mock", "deepseek", "dsh", "claude"]
