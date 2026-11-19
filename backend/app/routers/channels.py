"""通道接口：CRUD、拉模型列表、连通性测试。"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import channels as ch

router = APIRouter(prefix="/api/channels", tags=["channel"])


class ChannelCreate(BaseModel):
    name: str = ""
    kind: str = "api"          # api / agent / mock
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    command: str = ""
    args: str = ""
    temperature: float = 0.2
    max_rounds: int = 25
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None   # 空=不改，__CLEAR__=清空
    model: Optional[str] = None
    command: Optional[str] = None
    args: Optional[str] = None
    temperature: Optional[float] = None
    max_rounds: Optional[int] = None
    enabled: Optional[bool] = None


class ModelsReq(BaseModel):
    base_url: str = ""
    api_key: str = ""
    channel_id: Optional[int] = None   # 传了且没给 key 时用通道里存的 key


@router.get("")
def get_channels():
    return {"channels": ch.list_channels()}


@router.post("")
def add_channel(payload: ChannelCreate):
    if not payload.name.strip():
        raise HTTPException(400, "通道名称不能为空")
    if payload.kind == "api" and not payload.base_url.strip():
        raise HTTPException(400, "API 通道必须填 Base URL")
    if payload.kind == "agent" and not payload.command.strip():
        raise HTTPException(400, "本地 Agent 通道必须填命令")
    cid = ch.create_channel(payload.model_dump())
    return {"id": cid}


@router.patch("/{channel_id}")
def patch_channel(channel_id: int, payload: ChannelUpdate):
    if not ch.get_channel(channel_id):
        raise HTTPException(404, "通道不存在")
    ch.update_channel(channel_id, payload.model_dump(exclude_none=True))
    return {"ok": True}


@router.delete("/{channel_id}")
def remove_channel(channel_id: int):
    ch.delete_channel(channel_id)
    return {"ok": True}


@router.post("/models")
def models(payload: ModelsReq):
    """拉模型列表。key 可以现填，也可以用通道里已存的（前端不回显明文）。"""
    key = (payload.api_key or "").strip()
    if not key and payload.channel_id:
        saved = ch.get_channel(payload.channel_id)
        key = (saved or {}).get("api_key") or ""
    if not key:
        raise HTTPException(400, "需要 API Key 才能拉模型列表")
    try:
        return {"models": ch.list_models(payload.base_url, key)}
    except ch.AIError as ex:
        raise HTTPException(502, str(ex))


@router.post("/{channel_id}/test")
def test(channel_id: int, timeout: Optional[int] = None):
    try:
        return ch.test_channel(channel_id, timeout)
    except ch.AIError as ex:
        raise HTTPException(502, str(ex))
