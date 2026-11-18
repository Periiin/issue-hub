"""把附件图片转成多模态消息内容。

为什么要单独一层：截图是甲方反馈里最关键的信息（报错、界面状态），
但纯文本提示词只能给文件路径 —— API 通道的模型看不到图。

OpenAI 兼容的多模态格式是 content 数组：
    [{"type": "text", "text": "..."},
     {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]

不同通道对图片的支持差异很大，所以这里只负责「生成内容块」，
是否真的发送由 provider 决定（有的模型只接受纯文本）。
"""
import base64
import mimetypes
from pathlib import Path

# 单张图转 base64 后的大小上限：4MB 原图 → 约 5.3MB base64，多数通道能接受
MAX_IMAGE_BYTES = 4 * 1024 * 1024
# 单次请求最多带几张图：太多会挤占上下文且贵
MAX_IMAGES = 6

SUPPORTED_IMAGE_MIMES = {
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif",
}


def _mime_of(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return (mime or "").lower()


def is_supported_image(path: str | Path) -> bool:
    p = Path(path)
    if not p.is_file():
        return False
    return _mime_of(p) in SUPPORTED_IMAGE_MIMES


def encode_image(path: str | Path) -> str | None:
    """转成 data URL；不支持/太大/读失败返回 None（调用方降级为纯文本）。"""
    p = Path(path)
    if not is_supported_image(p):
        return None
    try:
        size = p.stat().st_size
        if size > MAX_IMAGE_BYTES:
            return None
        raw = p.read_bytes()
    except OSError:
        return None
    mime = _mime_of(p)
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def build_content(text: str, image_paths: list[str] | None = None,
                  max_images: int = MAX_IMAGES) -> str | list[dict]:
    """生成消息的 content。

    没有可用图片时返回纯字符串（兼容只支持文本的模型/通道）；
    有图片时返回 OpenAI 多模态数组。
    """
    paths = [p for p in (image_paths or []) if p][:max_images]
    blocks: list[dict] = []
    skipped: list[str] = []

    for path in paths:
        url = encode_image(path)
        if url:
            blocks.append({"type": "image_url", "image_url": {"url": url}})
        else:
            skipped.append(Path(path).name)

    if not blocks:
        # 一张都编不进去：把「有哪些图但看不到」写进文本，避免模型臆造
        if skipped:
            text += ("\n\n【附件说明】有 " + str(len(skipped)) + " 个附件（"
                     + "、".join(skipped) + "）无法读取内容，"
                     "请不要猜测图中的信息，需要时向提出人确认。")
        return text

    if skipped:
        text += ("\n\n【附件说明】另有 " + str(len(skipped)) + " 个附件（"
                 + "、".join(skipped) + "）无法读取，请不要猜测其内容。")

    # 图片在前、文字在后：多数模型对前置图片的注意力更好
    return [*blocks, {"type": "text", "text": text}]


def describe_attachments(paths: list[str]) -> str:
    """给「能自己读文件的 agent」（claude/dsh）用的文本说明。"""
    if not paths:
        return "（无附件）"
    lines = []
    for p in paths[:MAX_IMAGES]:
        lines.append(f"- {p}")
    if len(paths) > MAX_IMAGES:
        lines.append(f"- …另有 {len(paths) - MAX_IMAGES} 个未列出")
    return "\n".join(lines)
