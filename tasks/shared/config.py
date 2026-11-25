# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 配置层（零第三方依赖，仅标准库）

配置优先级：进程环境变量 > 同目录 .env > 默认值。
真实企业微信凭证只放 .env，不进代码、不进文档、不进日志（环境部署手册 v1.1）。
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def _load_dotenv():
    if not ENV_FILE.exists():
        return {}
    out = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


_DOT = _load_dotenv()


def get(key, default=""):
    return os.environ.get(key) or _DOT.get(key) or default


def flag(key, default=False):
    v = get(key, "").lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on", "y")


# ---------------------------------------------------------------- 运行态
# 云端发布 / 容器平台会注入 PORT 环境变量并反向代理，此时必须绑定 0.0.0.0；
# 本地直接 python run.py 时无 PORT，仍保持 127.0.0.1 仅本机可访问。
_PORT_ENV = os.environ.get("PORT")
APP_HOST = "0.0.0.0" if _PORT_ENV else get("APP_HOST", "127.0.0.1")
APP_PORT = int(_PORT_ENV or get("APP_PORT", "8123"))  # 8123：避开成长导航校内网 8090
APP_ENV = get("ENV", "staging")                      # staging / prod
DOCS_ENABLED = flag("DOCS_ENABLED", False)           # 校内网默认关闭在线文档
BASE_URL = get("BASE_URL", "http://127.0.0.1:8123")  # 企微卡片跳转地址

# ---------------------------------------------------------------- 企业微信
WECOM_MODE = get("WECOM_MODE", "mock")               # mock | real
WECOM_CORP_ID = get("WECOM_CORP_ID", "")
WECOM_CORP_SECRET = get("WECOM_CORP_SECRET", "")     # 只存 .env
WECOM_AGENT_ID = get("WECOM_AGENT_ID", "")
WECOM_TOKEN = get("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = get("WECOM_ENCODING_AES_KEY", "")
WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"

# ---------------------------------------------------------------- 成长导航 / 智慧校园
GROWTH_NAV_MODE = get("GROWTH_NAV_MODE", "fixture") # fixture | http
GROWTH_NAV_BASE = get("GROWTH_NAV_BASE", "http://127.0.0.1:8091/api/v1")
CAMPUS_API_BASE = get("CAMPUS_API_BASE", "http://172.16.7.12:8026")
CAMPUS_MODE = get("CAMPUS_MODE", "fixture")
# 大模型不直连智慧校园平台：本服务只访问成长导航数据服务 API
NO_DIRECT_CAMPUS_ACCESS = True

# 单 token 风险（MCP 工具扩展记录 v0.1）：principal = 校长角色单 token，禁止给 L1 下发数据
TOKEN_SCOPE = get("TOKEN_SCOPE", "role_class")       # role_class | principal
LLM_ENABLED = flag("LLM_ENABLED", False)             # 样本默认走规则引擎，可切换大模型
LLM_BASE = get("LLM_BASE", "")
LLM_MODEL = get("LLM_MODEL", "")

# ---------------------------------------------------------------- 部署基线（环境部署手册 v1.1）
CODE_BASELINE = "Alembic head=0016_campus_ods · 路由 139 · pytest 70 过 2 跳"
SYNC_TASKS = {
    "GrowthNav-Campus-Fast": "每 15 分钟：归寝（当日与前一日）＋请假（近 30 日）",
    "GrowthNav-Campus-Daily": "每日 02:10：学生全量＋组织＋归寝＋请假＋对账",
}

# 校内试用态九项上线前置（上线检查表第 15 项 · 一票否决）
READINESS_ITEMS = [
    ("sms_real", "真实短信通道（SMS_MODE=real）", flag("READY_SMS_REAL")),
    ("env_prod", "ENV=prod ＋ 强密钥", APP_ENV == "prod" and bool(get("SECRET_KEY"))),
    ("https", "HTTPS 接入", flag("READY_HTTPS")),
    ("security_audit", "等保测评／渗透测试", flag("READY_SECURITY_AUDIT")),
    ("account_review", "账号权限复核", flag("READY_ACCOUNT_REVIEW")),
    ("ntp", "服务器时间同步 NTP", flag("READY_NTP")),
    ("readonly_account", "只读专用账号替换临时高权限账号", flag("READY_READONLY_ACCOUNT")),
    ("mock_cleaned", "演示贴源数据已清空、无 mock 残留", flag("READY_MOCK_CLEANED")),
    ("campus_tasks_observed", "两个 campus 任务连续观察两天 LastResult=0", flag("READY_CAMPUS_TASKS")),
]


def readiness():
    items = [{"key": k, "name": n, "done": bool(v)} for k, n, v in READINESS_ITEMS]
    done = sum(1 for i in items if i["done"])
    return {
        "state": "校内试用态" if done < 9 else "正式上线态",
        "done": done,
        "total": 9,
        "items": items,
        "token_scope": TOKEN_SCOPE,
        "token_scope_ok": TOKEN_SCOPE == "role_class",
        "code_baseline": CODE_BASELINE,
        "wecom_mode": WECOM_MODE,
        "growth_mode": GROWTH_NAV_MODE,
        "docs_enabled": DOCS_ENABLED,
    }


def public_settings():
    """绝不返回 corp_secret / aes_key / token 等密钥。"""
    return {
        "app_env": APP_ENV,
        "wecom_mode": WECOM_MODE,
        "wecom_configured": bool(WECOM_CORP_ID and WECOM_CORP_SECRET and WECOM_AGENT_ID),
        "callback_configured": bool(WECOM_TOKEN and WECOM_ENCODING_AES_KEY),
        "growth_nav_mode": GROWTH_NAV_MODE,
        "growth_nav_base": GROWTH_NAV_BASE,
        "campus_api_base": CAMPUS_API_BASE,
        "no_direct_campus_access": NO_DIRECT_CAMPUS_ACCESS,
        "token_scope": TOKEN_SCOPE,
        "llm_enabled": LLM_ENABLED,
        "docs_enabled": DOCS_ENABLED,
        "code_baseline": CODE_BASELINE,
    }
