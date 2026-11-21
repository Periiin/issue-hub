"""新问题 / 新评论的 Webhook 通知（企业微信群机器人 / 飞书 / 钉钉）。

设计要点：
- **异步 fire-and-forget**：daemon 线程 + 5 秒超时。webhook 挂了绝不能拖慢
  「新建问题」这个主流程——通知失败只写一行日志，不重试不排队（这不是
  关键路径，丢一条通知可以接受，挂一串重试不可接受）。
- 三种格式的差异只在请求体结构；消息文案统一在这里拼。
- 读取设置每次现读（不缓存）：用户改完 webhook 立即生效，不用重启。

为什么挂在 issues_core 而不是路由层：MCP / Web 两个入口共用 core，
哪边创建问题都该通知——「甲方提了新问题」这件事跟入口无关。
"""
import json
import threading
from datetime import datetime

import httpx

from .db import get_settings

TIMEOUT = 5

KIND_LABELS = {"wecom": "企业微信", "feishu": "飞书", "dingtalk": "钉钉"}


def _enabled() -> tuple[bool, str, str]:
    s = get_settings()
    url = (s.get("notify.webhook_url") or "").strip()
    enabled = (s.get("notify.enabled") or "0").strip() in ("1", "true", "yes")
    kind = (s.get("notify.webhook_kind") or "wecom").strip()
    return (enabled and bool(url)), url, kind


def _payload(kind: str, text: str) -> dict:
    if kind == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    # 企微与钉钉的 text 格式一致
    return {"msgtype": "text", "text": {"content": text}}


def _send(url: str, kind: str, text: str) -> None:
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(url, json=_payload(kind, text))
            if resp.status_code >= 300:
                print(f"[notify] webhook 返回 {resp.status_code}：{resp.text[:150]}", flush=True)
    except Exception as ex:
        print(f"[notify] 发送失败：{ex}", flush=True)


def _fire(text: str) -> None:
    """enabled 才发；daemon 线程，主流程不等它。"""
    enabled, url, kind = _enabled()
    if not enabled:
        return
    threading.Thread(target=_send, args=(url, kind, text), daemon=True).start()


def _fmt_time() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def notify_new_issue(issue: dict, project_name: str = "") -> None:
    """新问题进来了。"""
    title = (issue.get("title") or "").strip()
    where = f"【{project_name}】" if project_name else ""
    text = (f"🔔 新问题 {where}#{issue.get('id')} {title}\n"
            f"模块：{issue.get('module') or '-'}　提出人：{issue.get('reporter') or '-'}\n"
            f"{_fmt_time()}")
    _fire(text)


def notify_new_comment(issue_id: int, issue_title: str,
                       author: str, body: str) -> None:
    """新讨论：甲方追问或内部结论，群里跟一句，避免「说了没人看到」。"""
    snippet = (body or "").strip().replace("\n", " ")[:120]
    text = (f"💬 问题 #{issue_id} {issue_title} 有新讨论\n"
            f"{author}：{snippet}\n{_fmt_time()}")
    _fire(text)


def send_test() -> dict:
    """设置页的「发送测试消息」。同步发送（要给用户即时反馈），失败返回错误。"""
    enabled, url, kind = _enabled()
    if not (url and kind in KIND_LABELS):
        return {"ok": False, "error": "请先填写 Webhook 地址"}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(url, json=_payload(kind, f"✅ issue-hub 测试消息（{KIND_LABELS.get(kind, kind)}）\n{_fmt_time()}"))
        if resp.status_code >= 300:
            return {"ok": False, "error": f"返回 {resp.status_code}：{resp.text[:200]}"}
        # 企微/飞书/钉钉业务失败也是 200，body 里有 errcode/StatusCode/code
        try:
            body = resp.json()
        except Exception:
            body = {}
        err = body.get("errcode", body.get("StatusCode", body.get("code", 0)))
        if err not in (0, None, 200, "200", "success"):
            return {"ok": False, "error": f"机器人返回错误：{str(body)[:200]}"}
        return {"ok": True}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
