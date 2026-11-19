"""采纳前的验证：在 worktree 里跑项目的编译/类型检查。

为什么必须做：模型「改完代码」不等于「代码能编译」。让用户点「采纳并合并」
时才发现编译不过，等于把验证成本又推回给人，这个工具就白做了。

安全模型（多用户部署时必须理解这一层）：
  1. **不用 shell**：命令用 shlex 拆成 argv 直接 exec，杜绝 `|`、`;`、`$()` 注入。
  2. **构建脚本被改过就跳过**：`package.json` / `pom.xml` / `gradlew` 等如果出现在
     本次 diff 里，说明可能被模型改过，自动推断出的命令不再执行（降级为人工验证）。
  3. **bwrap 沙箱**（可用时）：根目录只读 + 只有 worktree 可写 + 断网 + 独立 PID。
     断网意味着依赖必须已缓存，否则编译会失败 —— 这是刻意的取舍：
     宁可让用户手动 warm 一次缓存，也不给一条数据外传的通道。
  4. **资源上限**：超时 + 输出截断。bwrap 不管 CPU/内存，靠 timeout 兜。
"""
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from .db import get_settings

# 输出截断：编译失败的完整日志可能有几万行，只留尾部
MAX_OUTPUT = 6_000
DEFAULT_TIMEOUT = 420   # 7 分钟：Maven 冷启动编译足够

# 这些文件决定了「验证命令本身」。它们被改动时不能自动执行推断命令，
# 否则等于让模型有机会通过改构建脚本执行任意命令。
BUILD_FILES = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "gradlew", "gradlew.bat", "Makefile", "makefile",
    "tsconfig.json", "vite.config.ts", "vite.config.js", "webpack.config.js",
    "go.mod", "Cargo.toml", "requirements.txt", "setup.py", "pyproject.toml",
}

# bwrap 是否存在（不存在则降级为「无沙箱但无 shell」）
BWRAP = shutil.which("bwrap")


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

    if (root / "pom.xml").exists():
        return "mvn -q -DskipTests compile"
    if (root / "gradlew").exists():
        return "./gradlew -q compileJava"
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return "./gradlew -q compileJava"

    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            data = {}
        scripts = (data.get("scripts") or {}) if isinstance(data, dict) else {}
        for name in ("type-check", "typecheck", "lint", "build"):
            if name in scripts:
                return f"npm run {name}"
        if (root / "tsconfig.json").exists():
            return "npx --no-install vue-tsc --noEmit"

    if (root / "go.mod").exists():
        return "go build ./..."
    if (root / "Cargo.toml").exists():
        return "cargo check --quiet"
    return ""


def changed_build_files(worktree: str) -> list[str]:
    """worktree 里被改动的构建脚本（相对路径）。git 不可用就返回空。"""
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=worktree, capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            proc = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=worktree, capture_output=True, text=True, timeout=30,
            )
        names = (proc.stdout or "").splitlines()
    except (OSError, subprocess.SubprocessError):
        return []
    hit = []
    for n in names:
        base = Path(n).name
        if base in BUILD_FILES:
            hit.append(n)
    return hit


def _wrap_sandbox(repo: str, argv: list[str], sandbox: bool,
                  allow_network: bool = False) -> tuple[list[str], str]:
    """给命令套上 bwrap。返回 (最终 argv, 说明)。

    断网（--unshare-net）是刻意的：验证只需要读本地依赖编译，
    联网只会给「模型改了代码顺手把数据传出去」留通道。
    代价是依赖没缓存会失败，提示用户先手动构建一次。
    """
    if not sandbox or not BWRAP:
        return argv, "no-sandbox"

    # 注意：worktree 可能就在 /tmp 下（issue-hub 的 worktrees 目录）。
    # 如果给 /tmp 挂 tmpfs，worktree 会被盖掉导致 chdir 失败。
    # 所以只在 worktree 不在 /tmp 下时才隔离 /tmp。
    repo_resolved = str(Path(repo).resolve())
    isolate_tmp = not repo_resolved.startswith("/tmp/") and repo_resolved != "/tmp"

    args = [
        BWRAP,
        "--ro-bind", "/", "/",          # 整个文件系统只读
        "--dev", "/dev",
        "--proc", "/proc",
    ]
    # 联网开关：验证时 npm/maven 可能要下载依赖。
    # 默认允许（多用户各自副本首次构建几乎必然要联网），
    # 想更严就设 verify.allow_network=0，代价是依赖未缓存会失败。
    if not allow_network:
        args.append("--unshare-net")
    args += [
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
    ]
    if isolate_tmp:
        args += ["--tmpfs", "/tmp"]
    # 只有 worktree 可写（放在 ro-bind / 之后，覆盖成可写）
    args += ["--bind", repo_resolved, repo_resolved, "--chdir", repo_resolved, "--", *argv]
    # 已缓存的依赖要能读到：~/.m2（Maven）、node_modules（项目内已可写目录内）
    home = Path.home()
    m2 = home / ".m2"
    if m2.is_dir():
        # 插到 -- 之前，注意要在 --ro-bind / 之后（顺序覆盖）
        idx = args.index("--")
        args[idx:idx] = ["--ro-bind", str(m2), str(m2)]
    npm_cache = home / ".npm"
    if npm_cache.is_dir():
        idx = args.index("--")
        args[idx:idx] = ["--ro-bind", str(npm_cache), str(npm_cache)]
    return args, "bwrap"


def run_verify(repo: str, cmd: str, timeout: int = DEFAULT_TIMEOUT,
               sandbox: bool = True, allow_network: bool | None = None) -> dict:
    """执行验证命令，返回结果（不抛异常，由调用方决定是否阻断）。

    注意：`sandbox=False` 只跳过 bwrap，**仍然不用 shell**。
    """
    if not cmd:
        return {"ok": None, "skipped": True, "reason": "没有可用的验证命令"}
    if not Path(repo).is_dir():
        return {"ok": False, "error": f"{repo} 不存在"}

    try:
        argv = shlex.split(cmd)
    except ValueError as ex:
        return {"ok": False, "cmd": cmd, "error": f"命令无法解析：{ex}"}
    if not argv:
        return {"ok": None, "skipped": True, "reason": "命令为空"}

    if allow_network is None:
        allow_network = (get_settings().get("verify.allow_network") or "1").strip() in ("1", "true", "yes")
    full_argv, mode = _wrap_sandbox(repo, argv, sandbox, allow_network)

    try:
        proc = subprocess.run(
            full_argv, cwd=repo, capture_output=True, text=True,
            timeout=timeout, shell=False,     # 关键：绝不 shell
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "cmd": cmd, "timeout": True,
                "output": f"验证超时（>{timeout}s）", "sandbox": mode}
    except FileNotFoundError as ex:
        return {"ok": False, "cmd": cmd, "sandbox": mode,
                "error": f"命令不存在：{ex}"}
    except Exception as ex:
        return {"ok": False, "cmd": cmd, "sandbox": mode,
                "error": f"{type(ex).__name__}: {ex}"}

    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if len(output) > MAX_OUTPUT:
        output = "…（前部省略）\n" + output[-MAX_OUTPUT:]

    result = {
        "ok": proc.returncode == 0,
        "cmd": cmd,
        "returncode": proc.returncode,
        "output": output,
        "sandbox": mode,
    }
    # 沙箱断网导致依赖下载失败的典型报错，给一句人话提示
    if result["ok"] is False and mode == "bwrap":
        low = output.lower()
        if any(k in low for k in ("could not resolve", "network is unreachable",
                                  "offline", "etimedout", "connection refused",
                                  "unknownhost", "no such host")):
            result["hint"] = "沙箱已断网，依赖可能未缓存。请先在主仓库手动构建一次，再重试验证。"
    return result


def verify_worktree(repo: str, worktree: str, project_verify_cmd: str = "",
                    timeout: int = DEFAULT_TIMEOUT, sandbox: bool = True,
                    allow_network: bool | None = None) -> dict:
    """验证 worktree。

    cwd 用 worktree 而不是 repo —— 要看的是「这次改动后」能不能编译，
    主仓库里没有这些改动。
    """
    explicit = bool((project_verify_cmd or "").strip())

    # 构建脚本被本次改动碰过：不执行推断命令（可能已被篡改）
    if not explicit:
        touched = changed_build_files(worktree)
        if touched:
            return {
                "ok": None,
                "skipped": True,
                "reason": "本次改动包含构建脚本（" + "、".join(touched[:3])
                          + "），已跳过自动验证，请人工确认后手动构建。",
                "repo": repo,
                "worktree": worktree,
                "detected": True,
                "touchedBuildFiles": touched,
            }

    cmd = (project_verify_cmd or "").strip() or detect_verify_cmd(worktree)
    result = run_verify(worktree, cmd, timeout, sandbox=sandbox,
                        allow_network=allow_network)
    result["repo"] = repo
    result["worktree"] = worktree
    result["detected"] = not explicit
    return result
