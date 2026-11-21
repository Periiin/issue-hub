"""路径与常量配置。所有可调项都能用环境变量覆盖，方便以后换机器。"""
import os
from pathlib import Path

# issue-hub 根目录：backend/app/config.py -> backend/app -> backend -> issue-hub
BASE_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.getenv("ISSUEHUB_DATA", str(BASE_DIR / "data")))
DB_PATH = Path(os.getenv("ISSUEHUB_DB", str(DATA_DIR / "issuehub.db")))
ATTACH_DIR = Path(os.getenv("ISSUEHUB_ATTACH", str(DATA_DIR / "attachments")))
# 每个 issue 一份的「修复上下文」Markdown：给用户看、可编辑，也是喂给 agent 的边界说明
CONTEXT_DIR = Path(os.getenv("ISSUEHUB_CONTEXT", str(DATA_DIR / "issue-context")))
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

# 允许的附件类型（截图为主，顺带支持 PDF）
ALLOW_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
ALLOW_FILE_MIMES = ALLOW_IMAGE_MIMES | {"application/pdf"}

# 单文件上限 20MB：手机截图通常 <1MB，给 PDF 留余量
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# 问题状态机（顺序即流转方向；"不修/无法复现"是终态分支）
STATUS_FLOW = ["待定性", "待定级", "待处理", "处理中", "待验收", "已解决"]
STATUS_FINAL = ["已解决", "不修", "无法复现"]
ALL_STATUS = STATUS_FLOW + ["不修", "无法复现"]

# 定级维度取值
SEVERITIES = ["S1", "S2", "S3", "S4"]
COMPLEXITIES = ["简单", "中等", "复杂"]
PRIORITIES = ["P0", "P1", "P2", "P3"]

# 规则版本：改 rubric 时递增，历史记录能追溯当时用的是哪版
RUBRIC_VERSION = "v1"

DEFAULT_SETTINGS = {
    # AI 执行器：deepseek（HTTP API）/ dsh（DeepSeek harness）/ claude（Claude Code）/ mock（自测）
    "ai.provider": "mock",
    "ai.timeout": "180",
    # DeepSeek API
    "deepseek.base_url": "https://api.deepseek.com",
    "deepseek.api_key": "",
    "deepseek.model": "deepseek-chat",
    # DeepSeek harness CLI
    "dsh.bin": "dsh",
    "dsh.profile": "headless",
    # Claude Code CLI
    "claude.bin": "claude",
    "claude.model": "",
    # 鉴权：默认关闭（单人本机）。开启后要求账号密码 + IP 白名单
    "auth.enabled": "0",
    # IP 白名单：一行一个，支持 CIDR（如 192.168.110.0/24）与单个 IP。空=不限制
    "auth.ip_allowlist": "",
    # 限流（防爆破）。rate.enabled=0 可整体关闭（调试时用）
    "rate.enabled": "1",
    "rate.login_per_ip": "10",        # 每 IP 每分钟登录尝试
    "rate.fail_limit": "5",           # 连续失败几次锁定
    "rate.fail_lock_minutes": "15",   # 锁多久
    "rate.api_per_min": "300",        # 每分钟 API 请求
    "rate.heavy_per_hour": "30",      # 重操作（改代码/分析）每小时
    # 验证时是否允许联网（npm/maven 下载依赖需要）。0=断网更安全但依赖未缓存会失败
    "verify.allow_network": "1",
    # 可信反代地址：只有来自这些 IP 的请求，X-Forwarded-For 才被采信。
    # 回环与常见 docker 网关已内置，额外加 nginx 的地址写这里（逗号或换行分隔）
    "auth.trusted_proxies": "",
    # 新问题/新评论 Webhook 通知（企业微信群机器人 / 飞书 / 钉钉自定义机器人）
    "notify.enabled": "0",
    "notify.webhook_kind": "wecom",     # wecom / feishu / dingtalk
    "notify.webhook_url": "",
    # 对外访问地址（如 http://192.168.110.12:8090）：通知消息里拼详情页链接用，
    # 不配则消息不带链接
    "notify.base_url": "",
    # AI 分析代码时的工作目录（单目录，兼容旧配置）
    "repo.root": "/src/gym-fold",
    # 扫描根：一行一个，从这些目录往下找 git 仓库并自动聚成项目。
    # 换机器/加项目只改这里，不用维护一堆具体目录。
    "code.scan_roots": "\n".join([
        "/src",
    ]),
    # 兼容旧配置：直接指定候选目录（有值时会跳过扫描，仅作兜底）
    "code.roots": "",
    # 搜索时跳过的目录名（逗号分隔）：这些目录体量大且与业务无关
    "code.ignore": "node_modules,target,dist,build,backup,import-json,.git,.venv,.venv-mcp,worktrees",
    # 项目说明：告诉 AI 每个仓库是什么，避免在父目录里乱撞
    "code.project_notes": "\n".join([
        "gym-java-1       后端（Spring Boot + MyBatis-Plus）",
        "gym-vue-1        PC 管理端（Vue3 + Element Plus）",
        "gym-uniapp       会员端小程序（uni-app）",
        "gym-admin-uniapp 管理端小程序（uni-app）",
    ]),
}

# 扫描时不再深入的目录（名字命中即跳过，避免遍历 node_modules 这种）
SCAN_SKIP_DIRS = {
    "node_modules", "target", "dist", "build", "out", ".git", ".idea", ".vscode",
    "__pycache__", ".venv", ".venv-mcp", "venv", "worktrees", ".next", ".nuxt",
    "vendor", "Pods", ".gradle", ".m2", "coverage", ".cache",
}

# 扫描最大深度：扫描根往下几层找仓库。/src/gym-fold/gym-java-1 是 2 层，
# 再深一般是仓库内部的子目录，没必要继续挖。
SCAN_MAX_DEPTH = 3
