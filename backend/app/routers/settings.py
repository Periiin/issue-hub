"""配置读写。

注意：API Key 现在存在 channel 表里（每条通道一份），这里的 SECRET_KEYS
只保留历史遗留项，避免老库里的值被明文回显。
"""
from fastapi import APIRouter, HTTPException

from ..channels import list_channels
from ..config import PRIORITIES, RUBRIC_VERSION, SEVERITIES
from ..db import get_settings, save_settings
from ..schemas import SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

SECRET_KEYS = {"deepseek.api_key"}


@router.get("")
def read_settings():
    data = get_settings()
    for key in SECRET_KEYS:
        value = data.get(key) or ""
        data[key] = ""
        data[f"{key}_set"] = bool(value.strip())
    channels = list_channels()
    return {"settings": data,
            # 兼容旧前端：providers 现在等于通道名列表
            "providers": [c["name"] for c in channels],
            "channels": channels,
            "rubricVersion": RUBRIC_VERSION,
            "severities": SEVERITIES, "priorities": PRIORITIES}


@router.put("")
def update_settings(payload: SettingsUpdate):
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
