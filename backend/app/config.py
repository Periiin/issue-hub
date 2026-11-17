"""路径与常量配置。所有可调项都能用环境变量覆盖，方便以后换机器。"""
import os
from pathlib import Path

# issue-hub 根目录：backend/app/config.py -> backend/app -> backend -> issue-hub
BASE_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.getenv("ISSUEHUB_DATA", str(BASE_DIR / "data")))
DB_PATH = Path(os.getenv("ISSUEHUB_DB", str(DATA_DIR / "issuehub.db")))
ATTACH_DIR = Path(os.getenv("ISSUEHUB_ATTACH", str(DATA_DIR / "attachments")))
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
    # AI 分析代码时的工作目录（单目录，兼容旧配置）
    "repo.root": "/src/gym-fold",
    # 代码范围候选：一行一个目录，详情页多选从这里来（可含父目录）
    "code.roots": "\n".join([
        "/src/gym-fold/gym-java-1",
        "/src/gym-fold/gym-vue-1",
        "/src/gym-fold/gym-admin-uniapp",
        "/src/gym-uniapp",
        "/src/gym-fold",
    ]),
    # 搜索时跳过的目录名（逗号分隔）：这些目录体量大且与业务无关
    "code.ignore": "node_modules,target,dist,build,backup,import-json,.git,.venv,.venv-mcp,worktrees",
    # 项目说明：告诉 AI 每个目录是什么，避免在父目录里乱撞
    "code.project_notes": "\n".join([
        "gym-java-1       后端（Spring Boot + MyBatis-Plus）",
        "gym-vue-1        PC 管理端（Vue3 + Element Plus）",
        "gym-uniapp       会员端小程序（uni-app）",
        "gym-admin-uniapp 管理端小程序（uni-app）",
    ]),
}
