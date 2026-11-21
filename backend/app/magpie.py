"""从本机 Magpie 一键导入 AI 通道。

Magpie 是本地的一个 AI 网关：它把各家 provider（zcode / workbuddy / trae-cn …）
统一暴露成一个 **OpenAI 兼容端点**（`http://127.0.0.1:3425/v1`），并且
**不校验调用方 Key**（本机进程互信）。所以接入 issue-hub 不需要任何凭证。

这里做的事：
1. 读 Magpie 的 `gateway.json` 拿到它当前监听的地址（端口会变，不能写死）
2. 探一下 `/v1/models` 确认真的活着
3. 把选中的模型各建一条通道，重复的不重复建

**只在同一台机器上有效**：Magpie 绑的是 127.0.0.1，issue-hub 部署到服务器后
这个功能会探测失败（会给出明确提示，不是静默报错）。
"""
import json
from pathlib import Path

import httpx

from . import channels as ch
from .db import connect

# Magpie 的配置目录（Linux/macOS）。Windows 走 %APPDATA%，这里先支持类 Unix
CONFIG_DIRS = (
    Path.home() / ".config" / "magpie",
    Path.home() / "Library" / "Application Support" / "magpie",
)

# 探测超时：本机进程，超过 2 秒基本就是没起
PROBE_TIMEOUT = 3

# 通道名前缀，方便一眼看出是导入来的
NAME_PREFIX = "Magpie"


class MagpieError(RuntimeError):
    pass


def _config_dir() -> Path | None:
    for d in CONFIG_DIRS:
        if (d / "gateway.json").is_file():
            return d
    return None


def detect(remote_base_url: str = "", remote_api_key: str = "") -> dict:
    """探测 Magpie 网关。

    remote_base_url 传了 → 探测远程网关（同网段另一台机器），带 Bearer key；
    不传 → 读本机 gateway.json（本机进程互信，通常不需要 key）。

    返回 {found, running, baseUrl, version, models, error}。
    本机路径下 found=配置在但没起进程，和 found=False 要分开说 ——
    前者让用户去开 Magpie，后者说明这台机器根本没装。
    """
    remote_base_url = (remote_base_url or "").strip()
    remote_api_key = (remote_api_key or "").strip()

    if remote_base_url:
        # 远程模式：地址直接用调用方给的；远程网关一般配了 key，必须带上
        base_url = remote_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        out = {"found": True, "running": False, "baseUrl": base_url,
               "version": "", "models": [], "error": "", "remote": True,
               "hasKey": bool(remote_api_key)}
        headers = {"Authorization": f"Bearer {remote_api_key}"} if remote_api_key else {}
        try:
            with httpx.Client(timeout=PROBE_TIMEOUT) as client:
                resp = client.get(f"{base_url}/models", headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            out["error"] = f"连不上 {base_url}（对方没开 Magpie 或不在同一网段）"
            return out
        except httpx.HTTPStatusError as ex:
            if ex.response.status_code == 401:
                out["error"] = "鉴权失败：gateway key 不对或已过期"
            else:
                out["error"] = f"Magpie 返回 {ex.response.status_code}：{ex.response.text[:150]}"
            return out
        except Exception as ex:
            out["error"] = f"探测失败：{ex}"
            return out
        models = _parse_models(data)
        if models is None:
            out["error"] = f"/v1/models 响应格式不对：{str(data)[:150]}"
            return out
        out["running"] = True
        out["models"] = models
        return out

    # ---------- 本机模式（原逻辑）----------
    cfg_dir = _config_dir()
    if cfg_dir is None:
        return {"found": False, "running": False, "baseUrl": "", "version": "",
                "models": [], "error": "没有找到 Magpie 配置（~/.config/magpie/gateway.json）"}

    try:
        gw = json.loads((cfg_dir / "gateway.json").read_text())
    except (OSError, json.JSONDecodeError) as ex:
        return {"found": True, "running": False, "baseUrl": "", "version": "",
                "models": [], "error": f"读 gateway.json 失败：{ex}"}

    addr = (gw.get("addr") or "").strip()
    if not addr:
        return {"found": True, "running": False, "baseUrl": "", "version": "",
                "models": [], "error": "gateway.json 里没有监听地址"}

    base_url = f"http://{addr}/v1"
    out = {"found": True, "running": False, "baseUrl": base_url,
           "version": gw.get("version") or "", "models": [], "error": "", "remote": False}

    try:
        with httpx.Client(timeout=PROBE_TIMEOUT) as client:
            resp = client.get(f"{base_url}/models")
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        out["error"] = f"Magpie 没有运行（连不上 {addr}），请先启动它"
        return out
    except httpx.HTTPStatusError as ex:
        out["error"] = f"Magpie 返回 {ex.response.status_code}：{ex.response.text[:150]}"
        return out
    except Exception as ex:
        out["error"] = f"探测失败：{ex}"
        return out

    models = _parse_models(data)
    if models is None:
        out["error"] = f"/v1/models 响应格式不对：{str(data)[:150]}"
        return out
    out["running"] = True
    out["models"] = models
    return out


def _parse_models(data) -> list | None:
    """从 /v1/models 响应里解析模型清单；格式不对返回 None。"""
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    models = []
    for it in items:
        if not isinstance(it, dict):
            continue
        mid = it.get("id")
        if not mid:
            continue
        params = it.get("supported_parameters") or []
        modalities = (it.get("modalities") or {}).get("input") or []
        models.append({
            "id": str(mid),
            "label": it.get("display_name") or it.get("magpie_label") or str(mid),
            "contextLength": it.get("context_length") or 0,
            # 这两个能力决定它能不能用来改代码（要 tools）和看截图（要 image）
            "tools": "tools" in params,
            "vision": "image" in modalities,
        })
    return models

    # 解析已移到 _parse_models（本机/远程共用），此处不会到达
    return out


def _existing_models(base_url: str, owner_id: int | None) -> set[str]:
    """已经导入过的（同 base_url + 同 owner + 同 model），用来去重。"""
    sql = "SELECT model FROM channel WHERE base_url = ?"
    args: list = [base_url]
    if owner_id:
        sql += " AND owner_id = ?"
        args.append(owner_id)
    else:
        sql += " AND owner_id IS NULL"
    with connect() as conn:
        return {r["model"] for r in conn.execute(sql, args).fetchall()}


def import_models(models: list[str], owner_id: int | None = None,
                  remote_base_url: str = "", remote_api_key: str = "") -> dict:
    """把选中的模型各建一条通道。

    remote_base_url 传了 → 从远程网关导入（通道里带上 api_key）。

    返回 {created: [名字], skipped: [模型]}；已存在的不重复建，
    但如果之前被删过（enabled=0 且同名）也不复活 —— 保持用户意图。
    """
    info = detect(remote_base_url, remote_api_key)
    if not info["running"]:
        raise MagpieError(info["error"] or "Magpie 不可用")
    api_key = remote_api_key if info.get("remote") else ""

    base_url = info["baseUrl"]
    available = {m["id"]: m for m in info["models"]}
    wanted = [m for m in (models or []) if m]
    if not wanted:
        raise MagpieError("请至少选一个模型")

    unknown = [m for m in wanted if m not in available]
    if unknown:
        raise MagpieError(f"这些模型当前不可用：{', '.join(unknown[:5])}")

    existing = _existing_models(base_url, owner_id)
    created: list[str] = []
    skipped: list[str] = []

    for mid in wanted:
        if mid in existing:
            skipped.append(mid)
            continue
        meta = available[mid]
        # 名字用「Magpie · 模型短名」，列表里一眼能认出来源
        short = mid.split("/", 1)[-1]
        ch.create_channel({
            "name": f"{NAME_PREFIX} · {short}",
            "kind": "api",
            "base_url": base_url,
            # 本机网关不校验 Key留空；远程网关带上调用方给的 key
            "api_key": api_key,
            "model": mid,
            "temperature": 0.2,
            # 改代码要读写多轮，给足轮数
            "max_rounds": 30,
            "owner_id": owner_id,
            "enabled": True,
        })
        created.append(mid)

    return {"created": created, "skipped": skipped, "baseUrl": base_url}
