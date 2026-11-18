"""采纳前的验证：在 worktree 里跑项目的编译/类型检查。

为什么必须做：模型「改完代码」不等于「代码能编译」。让用户点「采纳并合并」
时才发现编译不过，等于把验证成本又推回给人，这个工具就白做了。

设计：
- 验证命令配在项目上（`project.verify_cmd`），因为不同技术栈命令完全不同。
- 没配命令时**按仓库特征自动推断**，避免用户一开始必须去填。
- 在 worktree 里跑（不是主仓库），失败只影响这次采纳，不污染主工作区。
- 超时保护：Maven 首次编译可能几分钟，给足时间但必须有上限。
"""
import subprocess
from pathlib import Path

# 输出截断：编译失败的完整日志可能有几万行，只留尾部
MAX_OUTPUT = 6_000
DEFAULT_TIMEOUT = 420   # 7 分钟：Maven 冷启动编译足够


class VerifyError(RuntimeError):
    pass


def detect_verify_cmd(repo: str) -> str:
    """按仓库里的特征文件推断验证命令。

    顺序有意为之：先看构建文件（最可靠），再看 package.json 的脚本。
    推断不出来返回空串 —— 表示「这个仓库没法自动验证」，不阻塞采纳但要提示。
    """
    root = Path(repo)
    if not root.is_dir():
        return ""

    # Java / Maven：多模块项目用 -am 带上依赖模块
    if (root / "pom.xml").exists():
        return "mvn -q -DskipTests compile"
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return "./gradlew -q compileJava --offline || ./gradlew -q compileJava"

    pkg = root / "package.json"
    if pkg.exists():
        try:
            import json
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            data = {}
        scripts = (data.get("scripts") or {}) if isinstance(data, dict) else {}
        # 优先用项目自己的检查脚本；vue-tsc 是 Vue 项目最常见的类型检查
        for name in ("type-check", "typecheck", "lint", "build"):
            if name in scripts:
                return f"npm run {name}"
        if (root / "tsconfig.json").exists():
            return "npx --no-install vue-tsc --noEmit || npx --no-install tsc --noEmit"

    if (root / "go.mod").exists():
        return "go build ./..."
    if (root / "Cargo.toml").exists():
        return "cargo check --quiet"
    return ""


def run_verify(repo: str, cmd: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """在 repo 里执行验证命令，返回结果（不抛异常，由调用方决定是否阻断）。"""
    if not cmd:
        return {"ok": None, "skipped": True, "reason": "没有可用的验证命令"}
    if not Path(repo).is_dir():
        return {"ok": False, "error": f"{repo} 不存在"}

    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=repo, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "cmd": cmd, "timeout": True,
                "output": f"验证超时（>{timeout}s）"}
    except Exception as ex:
        return {"ok": False, "cmd": cmd, "error": f"{type(ex).__name__}: {ex}"}

    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if len(output) > MAX_OUTPUT:
        output = "…（前部省略）\n" + output[-MAX_OUTPUT:]
    return {
        "ok": proc.returncode == 0,
        "cmd": cmd,
        "returncode": proc.returncode,
        "output": output,
    }


def verify_worktree(repo: str, worktree: str, project_verify_cmd: str = "",
                    timeout: int = DEFAULT_TIMEOUT) -> dict:
    """验证 worktree。

    注意 cwd 用 worktree 而不是 repo —— 要看的是「这次改动后」能不能编译，
    主仓库里没有这些改动。
    """
    cmd = (project_verify_cmd or "").strip() or detect_verify_cmd(worktree)
    result = run_verify(worktree, cmd, timeout)
    result["repo"] = repo
    result["worktree"] = worktree
    result["detected"] = not bool((project_verify_cmd or "").strip())
    return result
