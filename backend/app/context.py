"""每个 issue 一份的「修复上下文」文件。

用途有两个，缺一不可：
1. **给人看**：用户能确认 AI 理解的边界对不对，不满意可以自己改。
2. **给 agent 看**：改代码时把这份边界塞进提示词，避免它越界改到别的仓库。

设计要点：
- 存在 issue-hub 的 data 目录，不写进用户的 git 仓库（不污染 diff、不改 .git 配置）。
- 文件里用固定标记划分「自动生成区」和「用户手写区」，重新生成时只覆盖前者，
  用户写的内容永远保留。
- 内容同时内联进提示词：agent 不一定愿意去 read 一个外部文件，内联最可靠。
"""
import re
from pathlib import Path

from .config import CONTEXT_DIR

# 自动生成区的起止标记。重新生成时只替换这一段之间的内容。
AUTO_BEGIN = "<!-- issue-hub:auto:begin 这一块由系统生成，重新生成会覆盖 -->"
AUTO_END = "<!-- issue-hub:auto:end -->"
USER_BEGIN = "<!-- issue-hub:user:begin 这一块由你维护，重新生成不会覆盖 -->"
USER_END = "<!-- issue-hub:user:end -->"

DEFAULT_USER_NOTE = """- （在这里补充系统不知道的信息，比如：这个模块的负责人、发布窗口、不能动的历史包袱等）
- 这些内容会原样带给改代码的 agent，作为额外约束。"""


def context_path(issue_id: int) -> Path:
    return CONTEXT_DIR / f"issue-{issue_id}.md"


def _render_auto(issue: dict, repos: list[dict], scopes: list[str],
                 project_notes: str, settings: dict | None = None) -> str:
    """生成自动区正文。repos 是本次要改的仓库（含 covers）。"""
    lines = [AUTO_BEGIN, "", f"# 问题 #{issue.get('id')} · 修复边界", ""]
    title = (issue.get("title") or "").strip()
    if title:
        lines += [f"**{title}**", ""]

    if repos:
        lines += ["## 可以修改的仓库", ""]
        for r in repos:
            lines.append(f"- `{r['path']}`　{r.get('name') or ''}")
            for c in (r.get("covers") or []):
                lines.append(f"  - 覆盖子目录：`{c}`")
        lines += ["", "**只能修改上面这些仓库 worktree 内的文件。**", ""]
    else:
        lines += ["## 可以修改的仓库", "", "- （还没有选择目标仓库）", ""]

    # 勾了但不在任何目标仓库内的目录：明确告诉 agent 别碰
    covered = [c for r in repos for c in [r["path"], *(r.get("covers") or [])]]
    outside = [s for s in scopes if not any(_is_under(s, c) for c in covered)]
    if outside:
        lines += ["## 不在本次修改范围内", "",
                  "下面这些目录被勾进了分析范围，但属于**其它仓库**，",
                  "本次 worktree 里访问不到，不要尝试修改：", ""]
        for s in outside:
            lines.append(f"- `{s}`")
        lines += ["", "如果根因确实在这些目录里，请在总结里直接说明「需要另外在 xxx 仓库修复」，"
                      "不要硬改、也不要把代码复制过来。", ""]

    if project_notes.strip():
        lines += ["## 项目说明（来自设置）", "", project_notes.strip(), ""]

    lines += [
        "## 硬性约束",
        "",
        "- 只改本 worktree 内的文件；不要碰其它仓库、父目录或用户主目录。",
        "- 不要执行 git commit / push / checkout / reset，改动留在工作区等人工审阅。",
        "- 不改依赖锁文件、不升级依赖、不改构建脚本，除非问题本身就在那里。",
        "- 判断不该改代码时（配置/数据问题），直接说明原因，不要硬改。",
        "",
        AUTO_END,
    ]
    return "\n".join(lines)


def _is_under(child: str, parent: str) -> bool:
    c = (child or "").replace("\\", "/").rstrip("/").lower()
    p = (parent or "").replace("\\", "/").rstrip("/").lower()
    if not c or not p:
        return False
    return c == p or c.startswith(p + "/")


def _split_user_part(text: str) -> str:
    """取出用户手写区的内容（不含标记本身）。没有就返回默认提示。"""
    m = re.search(re.escape(USER_BEGIN) + r"(.*?)" + re.escape(USER_END), text, re.S)
    if not m:
        return DEFAULT_USER_NOTE
    body = m.group(1).strip("\n")
    return body if body.strip() else DEFAULT_USER_NOTE


def build_text(issue: dict, repos: list[dict], scopes: list[str],
               project_notes: str = "", existing: str = "") -> str:
    """拼出完整文件内容：自动区 + 用户区（用户区沿用旧内容）。"""
    auto = _render_auto(issue, repos, scopes, project_notes)
    user_body = _split_user_part(existing) if existing else DEFAULT_USER_NOTE
    return "\n".join([
        auto, "", USER_BEGIN, user_body, USER_END, "",
    ])


def read(issue_id: int) -> str:
    p = context_path(issue_id)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def write(issue_id: int, text: str) -> Path:
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    p = context_path(issue_id)
    p.write_text(text, encoding="utf-8")
    return p


def ensure(issue_id: int, issue: dict, repos: list[dict], scopes: list[str],
           project_notes: str = "") -> str:
    """确保文件存在并刷新自动区；用户手写区保持不变。返回最终内容。"""
    existing = read(issue_id)
    text = build_text(issue, repos, scopes, project_notes, existing)
    write(issue_id, text)
    return text


def delete(issue_id: int) -> bool:
    p = context_path(issue_id)
    if p.exists():
        p.unlink()
        return True
    return False


def auto_block(text: str) -> str:
    """取出自动区（喂给提示词用，去掉标记注释）。"""
    if not text:
        return ""
    m = re.search(re.escape(AUTO_BEGIN) + r"(.*?)" + re.escape(AUTO_END), text, re.S)
    if not m:
        return text.strip()
    return m.group(1).strip()
