import os
from pathlib import Path

from toollib.utils import ConfModel, FrozenVar

from app import APP_DIR

_CONFIG_DIR = APP_DIR.parent.joinpath("config")

DOTENV_PATH = _CONFIG_DIR.joinpath(".env")
# 私密配置从 config/.env 读取（系统环境变量优先，.env 只补缺失项）；
# 文件权限 600 且不入库，可用 DOTENV_PATH 环境变量指向其他密钥文件。
if not DOTENV_PATH.is_file():
    DOTENV_PATH = None
YAML_PATH = _CONFIG_DIR.joinpath(f"app_{os.environ.get('APP_ENV', 'dev')}.yaml")


class Config(ConfModel):
    """配置"""

    APP_DIR: FrozenVar[Path] = APP_DIR
    # #
    APP_ENV: str = "dev"
    YAML_PATH: Path = YAML_PATH
    # #
    APP_TITLE: str = "xApp"
    APP_SUMMARY: str = "xxApp"
    APP_DESCRIPTION: str = "xxxApp"
    APP_VERSION: str = "1.0.0"
    APP_DEBUG: bool = True
    APP_LOG_SERIALIZE: bool = False
    APP_LOG_OUTDIR: str = "./logs"
    APP_DISABLE_DOCS: bool = False
    APP_ALLOW_CREDENTIALS: bool = True
    APP_ALLOW_ORIGINS: list = ["*"]
    APP_ALLOW_METHODS: list = ["*"]
    APP_ALLOW_HEADERS: list = ["*"]
    # # 班主任工作台独立 Redis 请求/响应通道
    HEAD_TEACHER_WORKBENCH_REDIS_URL: str = "redis://127.0.0.1:6379/0"
    HEAD_TEACHER_WORKBENCH_REQUEST_QUEUE: str = "head_teacher_workbench:requests"
    HEAD_TEACHER_WORKBENCH_RESPONSE_PREFIX: str = "head_teacher_workbench:response:"
    HEAD_TEACHER_WORKBENCH_REQUEST_TIMEOUT_SECONDS: float = 5.0
    HEAD_TEACHER_WORKBENCH_RESPONSE_TTL_SECONDS: int = 30
    # # 本地账号登录（过渡方案）：形如 "userid:sha256hex,userid2:sha256hex"，留空则关闭
    LOCAL_LOGIN_USERS: str = ""
    # # 企业微信 OAuth2 身份校验（默认关闭；开启后身份来自会话而非请求头）
    WECOM_OAUTH_ENABLED: bool = False
    WECOM_CORP_ID: str = ""
    WECOM_AGENT_ID: str = ""
    WECOM_SECRET: str = ""
    WECOM_OAUTH_REDIRECT_URI: str = ""
    AUTH_COOKIE_SECRET: str = ""


def init_config() -> Config:
    return Config(
        dotenv_path=DOTENV_PATH,
        yaml_path=YAML_PATH,
    )
