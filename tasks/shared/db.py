# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 存储层（SQLite，零依赖）

生产环境请替换为成长导航系统现有 MySQL/PostgreSQL 双库（growth_nav／growth_nav_psych
物理隔离）；本样本用单库多表模拟，便于直接运行。所有敏感内容不出库、不入审计。
"""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tasks.shared import config

DB_PATH = Path(config.get("DB_PATH", str(config.ROOT / "runtime" / "dywork.db")))

# 每次查询都新建连接并重复执行 WAL/foreign_keys PRAGMA，在 Windows 上单次约 5ms；
# 一个接口往往执行十几条查询，累计即成百毫秒。这里按线程复用连接：
# sqlite3 连接不跨线程共享，FastAPI 同步接口在各自线程内运行，天然安全。
_local = threading.local()


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def uid(prefix=""):
    return prefix + uuid.uuid4().hex[:16]


def _make_conn(path):
    c = sqlite3.connect(str(path), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _conn():
    """返回当前线程复用的连接；DB_PATH 变化（测试切换临时库）时自动重建。"""
    path = str(DB_PATH)
    state = getattr(_local, "state", None)
    if state and state[0] == path:
        return state[1]
    if state:
        try:
            state[1].close()
        except Exception:
            pass
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = _make_conn(path)
    _local.state = (path, c)
    return c


def close():
    """关闭当前线程的连接（进程退出或测试清理时调用）。"""
    state = getattr(_local, "state", None)
    if state:
        try:
            state[1].close()
        except Exception:
            pass
        _local.state = None


def connect():
    """新建独立连接，供一次性脚本 / executescript 使用；调用方负责关闭。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _make_conn(DB_PATH)


def q(sql, args=(), one=False):
    cur = _conn().execute(sql, args)
    rows = [dict(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows


def exec_(sql, args=()):
    c = _conn()
    cur = c.execute(sql, args)
    c.commit()
    return cur.lastrowid


def exec_many(statements):
    c = _conn()
    for sql, args in statements:
        c.execute(sql, args)
    c.commit()


SCHEMA = """
-- 企业微信通讯录同步结果：一个 userid 可对应多个 post_id（兼任职务）
CREATE TABLE IF NOT EXISTS org_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL, name TEXT NOT NULL, dept_path TEXT NOT NULL,
  post_id TEXT NOT NULL UNIQUE, post_name TEXT NOT NULL,
  agent_id TEXT NOT NULL, agent_name TEXT NOT NULL,
  level TEXT NOT NULL, data_scope TEXT NOT NULL,
  portal TEXT NOT NULL DEFAULT 'admin',
  class_ids TEXT NOT NULL DEFAULT '[]', primary_flag INTEGER NOT NULL DEFAULT 1,
  committee_line INTEGER NOT NULL DEFAULT 0,
  level_source TEXT NOT NULL DEFAULT '通讯录部门路径自动判定',
  level_pending INTEGER NOT NULL DEFAULT 0,
  in_chain INTEGER NOT NULL DEFAULT 1,
  auto_level TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active', valid_from TEXT, valid_to TEXT,
  synced_at TEXT NOT NULL
);

-- 会话：切换职务即作废旧会话，上一职务上下文 / pending / dunDraft 全部作废
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, post_id TEXT NOT NULL,
  agent_id TEXT NOT NULL, level TEXT NOT NULL, data_scope TEXT NOT NULL,
  portal TEXT NOT NULL DEFAULT 'admin',
  class_ids TEXT NOT NULL DEFAULT '[]', committee_line INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, ended_at TEXT
);

-- 三元组审计：userid ＋ post_id ＋ agent_id 分别留痕
CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  user_id TEXT, post_id TEXT, agent_id TEXT, level TEXT,
  action TEXT NOT NULL, resource TEXT, result TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);

-- 敏感拦截只记计数，绝不记内容（安全／舆情零系统留痕）
CREATE TABLE IF NOT EXISTS redline_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  user_id TEXT, post_id TEXT, agent_id TEXT, category TEXT NOT NULL
);

-- 会话消息（按 session 隔离，切换职务即删除；只存非敏感文本）
CREATE TABLE IF NOT EXISTS chat_turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  session_id TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, card_json TEXT
);

-- 共建空间（PC015）：一个角色一个空间，秘书智能体＋工作台共享同一份上下文
-- space_id 由服务端按 userid＋post_id＋agent_id 生成并绑定会话，前端不可指定
CREATE TABLE IF NOT EXISTS spaces (
  space_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
  user_id TEXT NOT NULL, post_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  portal TEXT NOT NULL, level TEXT NOT NULL,
  shared_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
  archived_at TEXT
);
-- 共建留痕：秘书对话与工作台模块读写共享上下文，按四元组留痕（不记原文）
CREATE TABLE IF NOT EXISTS space_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  space_id TEXT NOT NULL, user_id TEXT, post_id TEXT, agent_id TEXT,
  source TEXT NOT NULL, fields TEXT NOT NULL, result TEXT NOT NULL
);

-- 同类横向协同（PC016）：只读聚合留痕，不记业务数据原文、不记对话原文
CREATE TABLE IF NOT EXISTS federation_queries (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  pool_id TEXT NOT NULL, user_id TEXT, post_id TEXT, agent_id TEXT,
  level TEXT, portal TEXT, metric TEXT NOT NULL,
  keyword_len INTEGER NOT NULL DEFAULT 0,
  member_count INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL
);

-- 协同教育推送（PC017）：任课绑定由教务处课表／企微通讯录同步（PC010 待补录）
CREATE TABLE IF NOT EXISTS coedu_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_post_id TEXT NOT NULL, teacher_user_id TEXT NOT NULL, teacher_name TEXT,
  class_id TEXT NOT NULL, subject TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '演示样本内置（PC010 待教务处补录）',
  status TEXT NOT NULL DEFAULT 'active',
  UNIQUE(teacher_post_id, class_id, subject)
);
-- 协同教育推送留痕：只记收件人／班级／科目／指标与脱敏汇总，不记学生名单与对话原文
CREATE TABLE IF NOT EXISTS coedu_pushes (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL,
  teacher_user_id TEXT, teacher_post_id TEXT, teacher_agent_id TEXT, teacher_name TEXT,
  class_id TEXT NOT NULL, subject TEXT NOT NULL, batch TEXT NOT NULL, metric TEXT NOT NULL,
  bzr_user_id TEXT, bzr_post_id TEXT, bzr_agent_id TEXT, bzr_name TEXT,
  summary_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'delivered',
  self_user INTEGER NOT NULL DEFAULT 0
);

-- 两段式写入：草稿不落业务库
CREATE TABLE IF NOT EXISTS pending_writes (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT NOT NULL,
  user_id TEXT NOT NULL, post_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  kind TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS write_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  user_id TEXT NOT NULL, post_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  kind TEXT NOT NULL, payload_json TEXT NOT NULL
);

-- 周报（未经人审确认不归档）
CREATE TABLE IF NOT EXISTS weekly_reports (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, class_id TEXT NOT NULL, week TEXT NOT NULL,
  level TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
  archived_at TEXT, archived_by TEXT
);

-- 六级自动推送流
CREATE TABLE IF NOT EXISTS push_flow (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  level TEXT NOT NULL, period TEXT NOT NULL, report_id TEXT,
  target_user_ids TEXT NOT NULL DEFAULT '[]', channel TEXT NOT NULL,
  status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
);

-- 「本周待确认红点」集中待办（D2，2026-11-15）：独立于两段式写入草稿；
-- 不含姓名、成绩、家长电话；销号留三元组审计、销号后不再出现
CREATE TABLE IF NOT EXISTS todo_items (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, week TEXT NOT NULL,
  owner_user_id TEXT NOT NULL, owner_post_id TEXT NOT NULL, owner_agent_id TEXT NOT NULL,
  class_id TEXT NOT NULL, kind TEXT NOT NULL,
  student_id TEXT, category TEXT NOT NULL, fact TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open', created_via TEXT NOT NULL DEFAULT 'manual',
  handled_at TEXT, handled_by TEXT
);

-- 转介单（D4 方案 B）：L1 事实转介 → L2 劝返台账三态回执；
-- 只写事实不作定性，不写台账本体，不回流学生明细
CREATE TABLE IF NOT EXISTS referral_slips (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, todo_id TEXT NOT NULL,
  class_id TEXT NOT NULL, student_id TEXT, category TEXT NOT NULL, fact TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  received_at TEXT, received_by TEXT, closed_at TEXT, closed_by TEXT,
  created_by_user TEXT, created_by_post TEXT
);

-- 上级催办闭环：逐级不越级，先回显、确认下达、限时反馈、超时升级
CREATE TABLE IF NOT EXISTS duns (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL,
  from_user_id TEXT NOT NULL, from_post_id TEXT NOT NULL, from_agent_id TEXT NOT NULL,
  from_level TEXT NOT NULL, to_user_id TEXT NOT NULL, to_level TEXT NOT NULL,
  content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'echo',
  deadline TEXT, confirmed_at TEXT, reply_at TEXT, reply_text TEXT,
  escalated INTEGER NOT NULL DEFAULT 0
);

-- 智能体统一台账（一岗一智能体）
CREATE TABLE IF NOT EXISTS agent_registry (
  agent_id TEXT PRIMARY KEY, post_id TEXT NOT NULL, level TEXT NOT NULL,
  agent_name TEXT NOT NULL, prompt_file TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'shadow', review_term TEXT NOT NULL DEFAULT '每学期复核'
);

-- mock 模式下的企业微信应用消息发件箱（便于验证推送与卡片）
CREATE TABLE IF NOT EXISTS wecom_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  to_user TEXT NOT NULL, msg_type TEXT NOT NULL, payload_json TEXT NOT NULL,
  mode TEXT NOT NULL, result TEXT NOT NULL
);
"""


def _ensure_columns():
    """兼容已有库：补加真实通讯录接入与三端划分所需的标记列。"""
    c = connect()
    try:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(org_posts)").fetchall()}
        extra = [
            ("level_source", "TEXT NOT NULL DEFAULT '通讯录部门路径自动判定'"),
            ("level_pending", "INTEGER NOT NULL DEFAULT 0"),
            ("in_chain", "INTEGER NOT NULL DEFAULT 1"),
            ("auto_level", "TEXT NOT NULL DEFAULT ''"),
            ("portal", "TEXT NOT NULL DEFAULT 'admin'"),
        ]
        for name, ddl in extra:
            if name not in cols:
                c.execute("ALTER TABLE org_posts ADD COLUMN %s %s" % (name, ddl))
        scols = {r["name"] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
        if "portal" not in scols:
            c.execute("ALTER TABLE sessions ADD COLUMN portal TEXT NOT NULL DEFAULT 'admin'")
        c.commit()
    finally:
        c.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
    _ensure_columns()
    # 学生成长门户建表（函数内 import，避免循环依赖）；旧库启动即升级
    from tasks.modules.student import student_portal
    student_portal.ensure_schema()


def audit(ctx, action, result="ok", resource="", detail=""):
    """ctx 可为 dict 或 None；三元组缺一不补猜，缺失记 '-'。"""
    ctx = ctx or {}
    exec_(
        "INSERT INTO audit_logs(ts,user_id,post_id,agent_id,level,action,resource,result,detail) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (now(), ctx.get("user_id", "-"), ctx.get("post_id", "-"),
         ctx.get("agent_id", "-"), ctx.get("level", "-"),
         action, resource, result, detail[:500]),
    )


def redline(ctx, category):
    """敏感拦截：只记分类与三元组，绝不记请求内容。"""
    ctx = ctx or {}
    exec_("INSERT INTO redline_events(ts,user_id,post_id,agent_id,category) VALUES(?,?,?,?,?)",
          (now(), ctx.get("user_id"), ctx.get("post_id"), ctx.get("agent_id"), category))


def clear_session_state(session_id):
    """切换职务／切换登录账号：上一职务会话上下文、待确认写入、催办草稿全部作废。

    PC015：同时归档该会话的共建空间并清空其共享上下文——空间之间不继承、
    不打通（新空间由 org._make_ctx 重建，不复制本条记录的 shared_json）。
    """
    exec_many([
        ("DELETE FROM chat_turns WHERE session_id=?", (session_id,)),
        ("UPDATE pending_writes SET status='discarded', resolved_at=? "
         "WHERE session_id=? AND status='pending'", (now(), session_id)),
        ("UPDATE spaces SET status='archived', archived_at=?, shared_json='{}' "
         "WHERE session_id=? AND status='active'", (now(), session_id)),
        ("UPDATE sessions SET status='expired', ended_at=? WHERE session_id=?",
         (now(), session_id)),
    ])


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def loads(s, default=None):
    try:
        return json.loads(s) if s else (default if default is not None else {})
    except Exception:
        return default if default is not None else {}
