"""配置读写。

注意：API Key 现在存在 channel 表里（每条通道一份），这里的 SECRET_KEYS
只保留历史遗留项，避免老库里的值被明文回显。
"""
from fastapi import APIRouter, Depends, HTTPException

from ..channels import list_channels
from ..config import PRIORITIES, RUBRIC_VERSION, SEVERITIES
from ..db import get_settings, save_settings
from ..schemas import SettingsUpdate
from .auth import require_admin, require_user

router = APIRouter(prefix="/api/settings", tags=["settings"])

SECRET_KEYS = {"deepseek.api_key"}


# 普通用户不该看到的全局配置：白名单、鉴权开关、全局代码范围、AI 端点。
# 不是「机密」而是「改了就影响所有人」，读出来只会让人以为能改。
ADMIN_ONLY_KEYS = {
    "auth.enabled", "auth.ip_allowlist", "auth.trusted_proxies",
    "rate.enabled", "rate.login_per_ip", "rate.fail_limit",
    "rate.fail_lock_minutes", "rate.api_per_min", "rate.heavy_per_hour",
    "code.scan_roots", "code.roots", "code.ignore", "code.project_notes",
    "repo.root", "ai.provider", "ai.channel_id", "deepseek.base_url",
    "deepseek.model", "dsh.bin", "dsh.profile", "claude.bin", "claude.model",
    "verify.allow_network",
}


@router.get("")
def read_settings(user: dict = Depends(require_user)):
    data = get_settings()
    for key in SECRET_KEYS:
        value = data.get(key) or ""
        data[key] = ""
        data[f"{key}_set"] = bool(value.strip())
    if user.get("role") != "admin":
        # 普通用户：抹掉全局项，只留跟他有关的（外观、超时这类无害的）
        for key in ADMIN_ONLY_KEYS:
            data.pop(key, None)
    channels = list_channels()
    return {"settings": data,
            # 兼容旧前端：providers 现在等于通道名列表
            "providers": [c["name"] for c in channels],
            "channels": channels,
            "rubricVersion": RUBRIC_VERSION,
            "severities": SEVERITIES, "priorities": PRIORITIES}


@router.post("/notify/test")
def test_notify(user: dict = Depends(require_user)):
    """发送一条测试消息到配置的 Webhook。普通用户也能点（配置项本身他们看得到）。"""
    from .. import notify
    return notify.send_test()


@router.put("")
def update_settings(payload: SettingsUpdate, user: dict = Depends(require_admin)):
    """保存全局配置。**限管理员** —— 这里能改 IP 白名单和登录开关，
    普通用户可写等于给了「把所有人锁在门外」的能力。"""
    values = {}
    for key, value in payload.values.items():
        text = "" if value is None else str(value)
        # 空字符串不覆盖密钥；要清空显式传 __CLEAR__
        if key in SECRET_KEYS:
            if text == "__CLEAR__":
                values[key] = ""
            elif text.strip():
                values[key] = text.strip()
            continue
        values[key] = text
    if not values:
        raise HTTPException(400, "没有可保存的配置")
    save_settings(values)
    return {"ok": True}
