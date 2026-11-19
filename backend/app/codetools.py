"""代码工具集：给纯 API 通道提供文件读写能力。

为什么要自己做：claude / dsh 这类 CLI agent 自带文件工具，但中转站/官方 API
只能返回文本。想让「填个 API 就能改代码」成立，就得自己实现 function calling
的工具循环 —— 模型决定调什么工具，我们执行并把结果回灌。

安全边界（每一层都要守住）：
1. 所有路径必须落在 root 之内（`_safe_path`），越界直接拒绝而不是静默截断。
2. 只读工具（read/list/grep）不限制；写工具（write/edit）只有 allow_write 时注册。
3. 单文件大小、单次输出长度都设上限，避免把几十 MB 的 min.js 灌进上下文。
4. 不提供 shell / delete / move，改动只能落在 worktree 里由 git diff 呈现。
"""
import fnmatch
import os
import re
from pathlib import Path

# 单次读取的字符上限：超过就截断并提示，避免上下文爆掉
MAX_READ_CHARS = 40_000
# grep 单次返回的最大命中数
MAX_GREP_HITS = 80
# list 单层最多列出的条目
MAX_LIST_ENTRIES = 400


class ToolError(RuntimeError):
    pass


def _safe_path(root: Path, raw: str) -> Path:
    """把模型给的相对路径解析到 root 内；越界抛错。"""
    if not raw:
        raise ToolError("路径不能为空")
    candidate = (root / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ToolError(f"路径 {raw} 超出工作目录，禁止访问") from None
    return candidate


def _skip(name: str, ignore: list[str]) -> bool:
    return name.startswith(".") or name in ignore


# ---------------- 只读工具 ----------------

def tool_list_dir(root: Path, path: str = ".", ignore: list[str] | None = None) -> str:
    ignore = ignore or []
    target = _safe_path(root, path)
    if not target.is_dir():
        raise ToolError(f"{path} 不是目录")
    lines, truncated = [], False
    try:
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    except PermissionError as ex:
        raise ToolError(f"无权限读取 {path}") from ex
    for entry in entries:
        if _skip(entry.name, ignore):
            continue
        if len(lines) >= MAX_LIST_ENTRIES:
            truncated = True
            break
        rel = entry.relative_to(root).as_posix()
        lines.append(f"{rel}/" if entry.is_dir() else rel)
    body = "\n".join(lines) or "（空目录）"
    if truncated:
        body += f"\n…（超过 {MAX_LIST_ENTRIES} 项，已截断，请指定更具体的子目录）"
    return body


def tool_read_file(root: Path, path: str, start: int = 1, end: int = 0) -> str:
    target = _safe_path(root, path)
    if not target.is_file():
        raise ToolError(f"{path} 不是文件")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as ex:
        raise ToolError(f"读取 {path} 失败：{ex}") from ex
    lines = text.splitlines()
    start = max(1, int(start or 1))
    end = int(end or 0) or len(lines)
    chunk = lines[start - 1:end]
    numbered = "\n".join(f"{i:>5}| {line}" for i, line in enumerate(chunk, start))
    if len(numbered) > MAX_READ_CHARS:
        numbered = numbered[:MAX_READ_CHARS] + "\n…（内容过长已截断，请用 start/end 分段读取）"
    return numbered or "（空文件）"


def tool_grep(root: Path, pattern: str, path: str = ".", glob: str = "",
              ignore: list[str] | None = None) -> str:
    """在目录里按正则搜索，返回 文件:行号: 内容。"""
    ignore = ignore or []
    if not pattern:
        raise ToolError("pattern 不能为空")
    try:
        regex = re.compile(pattern)
    except re.error as ex:
        raise ToolError(f"正则无效：{ex}") from ex
    base = _safe_path(root, path)
    hits: list[str] = []
    truncated = False

    def scan(file_path: Path) -> None:
        nonlocal truncated
        try:
            if file_path.stat().st_size > 2 * 1024 * 1024:
                return
            with file_path.open("r", encoding="utf-8", errors="replace") as fh:
                for no, line in enumerate(fh, 1):
                    if regex.search(line):
                        hits.append(f"{file_path.relative_to(root).as_posix()}:{no}: {line.rstrip()[:300]}")
                        if len(hits) >= MAX_GREP_HITS:
                            truncated = True
                            return
        except (OSError, UnicodeDecodeError):
            return

    if base.is_file():
        scan(base)
    else:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not _skip(d, ignore)]
            for name in filenames:
                if glob and not fnmatch.fnmatch(name, glob):
                    continue
                if _skip(name, ignore):
                    continue
                scan(Path(dirpath) / name)
                if truncated:
                    break
            if truncated:
                break

    body = "\n".join(hits) or "（没有匹配）"
    if truncated:
        body += f"\n…（命中超过 {MAX_GREP_HITS} 条，已截断，请缩小范围）"
    return body


# ---------------- 写工具 ----------------

def tool_write_file(root: Path, path: str, content: str) -> str:
    target = _safe_path(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    return f"{'覆盖' if existed else '新建'} {path}（{len(content)} 字符）"


def tool_edit_file(root: Path, path: str, old: str, new: str) -> str:
    """精确替换一处。old 必须唯一命中，否则报错让模型自己缩小范围。"""
    target = _safe_path(root, path)
    if not target.is_file():
        raise ToolError(f"{path} 不存在，先 read_file 确认")
    text = target.read_text(encoding="utf-8", errors="replace")
    count = text.count(old)
    if count == 0:
        raise ToolError("old 在文件里没找到，请先 read_file 看实际内容")
    if count > 1:
        raise ToolError(f"old 命中了 {count} 处，请提供更长的上下文让它唯一")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"已修改 {path}"


# ---------------- 工具定义（OpenAI function calling 格式） ----------------

def tool_specs(allow_write: bool) -> list[dict]:
    specs = [
        {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "列出目录内容（相对工作目录的路径）。先用它熟悉项目结构。",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "相对路径，默认当前目录"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "读取文件内容，带行号。大文件用 start/end 分段读。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "相对路径"},
                        "start": {"type": "integer", "description": "起始行，从 1 开始"},
                        "end": {"type": "integer", "description": "结束行，0 表示到文件末尾"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "grep",
                "description": "按正则搜索代码，返回 文件:行号: 内容。定位实现最快的方式。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Python 正则"},
                        "path": {"type": "string", "description": "搜索的目录或文件，默认整个工作目录"},
                        "glob": {"type": "string", "description": "文件名过滤，如 *.java"},
                    },
                    "required": ["pattern"],
                },
            },
        },
    ]
    if allow_write:
        specs += [
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "写入整个文件（覆盖或新建）。只在需要新建文件时用，改已有文件优先用 edit_file。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string", "description": "完整文件内容"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "把文件里唯一命中的 old 替换成 new。old 要带足够上下文保证唯一。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "old": {"type": "string", "description": "要被替换的原文（必须唯一命中）"},
                            "new": {"type": "string", "description": "替换成的内容"},
                        },
                        "required": ["path", "old", "new"],
                    },
                },
            },
        ]
    return specs


def dispatch(root: Path, name: str, args: dict, allow_write: bool,
             ignore: list[str] | None = None) -> str:
    """执行一次工具调用，返回给模型的文本结果。异常转成文本，让模型自己纠正。"""
    try:
        if name == "list_dir":
            return tool_list_dir(root, args.get("path") or ".", ignore)
        if name == "read_file":
            return tool_read_file(root, args.get("path") or "",
                                  args.get("start") or 1, args.get("end") or 0)
        if name == "grep":
            return tool_grep(root, args.get("pattern") or "", args.get("path") or ".",
                             args.get("glob") or "", ignore)
        if name == "write_file":
            if not allow_write:
                return "错误：当前是只读模式，不能写文件"
            return tool_write_file(root, args.get("path") or "", args.get("content") or "")
        if name == "edit_file":
            if not allow_write:
                return "错误：当前是只读模式，不能改文件"
            return tool_edit_file(root, args.get("path") or "",
                                  args.get("old") or "", args.get("new") or "")
        return f"错误：未知工具 {name}"
    except ToolError as ex:
        return f"错误：{ex}"
    except Exception as ex:  # 工具内部异常不能让整个循环挂掉
        return f"错误：{type(ex).__name__}: {ex}"
