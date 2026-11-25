# -*- coding: utf-8 -*-
"""学生成长门户业务层（量表测评 / 画像 / 时间轴 / 待办 / 计划打卡 / 分享 / 家长绑定）。

口径：
- 同步 sqlite3，风格与 db.py / roster.py 一致；所有建表 IF NOT EXISTS，可重复执行。
- 只返回本人数据；分享与家长端只给摘要白名单，绝不下发原始作答与维度原始分。
- 无数据一律返回空数组或 None，不估算、不臆造。

参照包 growth-nav 的计分规则（app/services/scoring.py）：
- Likert：选项分值 1..k，reverse 记 k+1-v；维度取 item.dimension；
- choice：option_dims_json 非空时按选项归维，选中维度 +1；
- std = round(raw / 维度满分 * 100)；优势 ≥70、待发展 ≤40。
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone

from tasks.shared import db

# ---------------------------------------------------------------- 业务异常
class PortalError(Exception):
    """业务异常基类：status 供接口层映射 HTTP 状态码。"""

    status = 400


class InvalidInput(PortalError):
    status = 400


class Forbidden(PortalError):
    status = 403


class NotFound(PortalError):
    status = 404


class Conflict(PortalError):
    status = 409


class TooManyRequests(PortalError):
    status = 429


class InvalidShare(NotFound):
    """分享码 / token 失效统一按 404「分享已失效」。"""


SCHEMA = """
-- 量表（从参照包导入，status=1 启用）
CREATE TABLE IF NOT EXISTS scales (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL,
  version TEXT NOT NULL,
  title TEXT NOT NULL,
  item_count INTEGER NOT NULL DEFAULT 0,
  minutes INTEGER NOT NULL DEFAULT 0,
  dimension_json TEXT NOT NULL DEFAULT '{}',
  status INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  UNIQUE(code, version)
);
CREATE INDEX IF NOT EXISTS idx_scales_code ON scales(code, status);

-- 题目（reverse/dimension 只落库，不下发前端）
CREATE TABLE IF NOT EXISTS scale_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scale_id INTEGER NOT NULL,
  item_no INTEGER NOT NULL,
  stem TEXT NOT NULL,
  options_json TEXT NOT NULL DEFAULT '[]',
  dimension TEXT NOT NULL DEFAULT '',
  reverse INTEGER NOT NULL DEFAULT 0,
  option_dims_json TEXT,
  UNIQUE(scale_id, item_no)
);
CREATE INDEX IF NOT EXISTS idx_scale_items_scale ON scale_items(scale_id, item_no);

-- 测评：0 进行中 / 1 断点 / 2 已提交
CREATE TABLE IF NOT EXISTS assessments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  scale_code TEXT NOT NULL,
  scale_version TEXT NOT NULL,
  batch_id INTEGER,
  status INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL,
  submitted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_assessments_student
  ON assessments(student_id, scale_code, status);
CREATE INDEX IF NOT EXISTS idx_assessments_class ON assessments(class_id, student_id);

CREATE TABLE IF NOT EXISTS assessment_answers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assessment_id INTEGER NOT NULL,
  item_no INTEGER NOT NULL,
  option_no INTEGER NOT NULL,
  answered_at TEXT NOT NULL,
  UNIQUE(assessment_id, item_no)
);
CREATE INDEX IF NOT EXISTS idx_answers_assessment ON assessment_answers(assessment_id);

-- 维度分（raw 仅落库，不对外）
CREATE TABLE IF NOT EXISTS scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assessment_id INTEGER NOT NULL,
  dimension TEXT NOT NULL,
  raw INTEGER NOT NULL DEFAULT 0,
  std_score INTEGER NOT NULL DEFAULT 0,
  UNIQUE(assessment_id, dimension)
);
CREATE INDEX IF NOT EXISTS idx_scores_assessment ON scores(assessment_id);

CREATE TABLE IF NOT EXISTS profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  term TEXT NOT NULL,
  radar_json TEXT NOT NULL DEFAULT '{}',
  tags_json TEXT NOT NULL DEFAULT '[]',
  advice_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  UNIQUE(student_id, term)
);
CREATE INDEX IF NOT EXISTS idx_profiles_student ON profiles(student_id, term);

CREATE TABLE IF NOT EXISTS assess_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  term TEXT NOT NULL,
  name TEXT NOT NULL,
  scale_codes_json TEXT NOT NULL DEFAULT '[]',
  start_at TEXT,
  end_at TEXT
);

-- 个人成长目标（设定权归学生本人）
CREATE TABLE IF NOT EXISTS student_goals (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  term TEXT NOT NULL,
  text TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_student_goals ON student_goals(student_id, term);

CREATE TABLE IF NOT EXISTS student_plan_checks (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  date TEXT NOT NULL,
  text TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  UNIQUE(student_id, date)
);

-- 待办处理状态（done / ignore），销号后不再重复出现
CREATE TABLE IF NOT EXISTS student_todos_state (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_todos_state_student
  ON student_todos_state(student_id, state);

-- 成长分享：库里只存 sha256，明文只回给本人一次
CREATE TABLE IF NOT EXISTS shares (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  code_hash TEXT NOT NULL UNIQUE,
  code_masked TEXT NOT NULL DEFAULT '',
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_shares_student ON shares(student_id, status);

CREATE TABLE IF NOT EXISTS share_access_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  ip TEXT NOT NULL DEFAULT '',
  result TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_share_access_logs ON share_access_logs(ip, ts);

-- 家长账号（PBKDF2-SHA256 加盐，零依赖）
CREATE TABLE IF NOT EXISTS parent_accounts (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  student_no TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parent_accounts_no ON parent_accounts(student_no);

CREATE TABLE IF NOT EXISTS parent_bindings (
  id TEXT PRIMARY KEY,
  parent_id TEXT NOT NULL,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  relation TEXT NOT NULL DEFAULT '家长',
  mobile TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_parent_bindings_student
  ON parent_bindings(student_id, status);

-- 家长授权范围（预留：当前只读摘要，不做细粒度授权）
CREATE TABLE IF NOT EXISTS parent_grants (
  id TEXT PRIMARY KEY,
  binding_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- 绑定码：10 分钟一次性，只存 sha256
CREATE TABLE IF NOT EXISTS parent_bind_codes (
  code_hash TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  student_no TEXT NOT NULL,
  relation TEXT NOT NULL DEFAULT '家长',
  mobile TEXT NOT NULL DEFAULT '',
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_at TEXT NOT NULL
);
"""

TERM_DAYS = 7
MAX_SHARE_HOURS = 168
BIND_CODE_TTL_MINUTES = 10
SHARE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PBKDF2_ITERATIONS = 120000
VERIFY_FAIL_WINDOW_SECONDS = 60
VERIFY_FAIL_LIMIT = 10


# ---------------------------------------------------------------- 基础工具
def ensure_schema():
    """幂等建表；旧库启动即升级。"""
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()


def _loads(text, default):
    try:
        value = json.loads(text) if text else default
        return default if value is None else value
    except Exception:
        return default


def _dumps(value):
    return json.dumps(value, ensure_ascii=False)


def _now_dt():
    return datetime.now(timezone.utc).astimezone()


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _parse_dt(text):
    try:
        return datetime.fromisoformat(str(text))
    except Exception:
        return None


def _expired(expires_at):
    dt = _parse_dt(expires_at)
    if dt is None:
        return True
    now = _now_dt()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    return dt <= now


def _hash(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    ).hex()


def _check_password(password, salt, digest):
    return hmac.compare_digest(_hash_password(password, salt), str(digest))


def current_term(day=None):
    """学期号：Y-Y+1-1（9 月—次年 1 月）/ Y-1-Y-2（2—8 月）。"""
    d = day or date.today()
    y, m = d.year, d.month
    if 2 <= m <= 8:
        return "%d-%d-2" % (y - 1, y)
    if m >= 9:
        return "%d-%d-1" % (y, y + 1)
    return "%d-%d-1" % (y - 1, y)


def _week_range(day=None):
    d = day or date.today()
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def _mask_name(name):
    """分享/家长端昵称：姓 + *，不出全名。"""
    text = str(name or "").strip()
    if not text:
        return "学生*"
    return text[0] + "*"


def _mask_mobile(mobile):
    text = str(mobile or "").strip()
    if len(text) < 7:
        return text
    return text[:3] + "****" + text[-4:]


# ---------------------------------------------------------------- 量表
def import_scales(scales):
    """导入量表与题目；按 code+version / scale_id+item_no 去重，可重复执行。"""
    if not isinstance(scales, list):
        raise InvalidInput("量表数据格式错误")
    added = updated = items_added = items_updated = 0
    now = db.now()
    for raw in scales:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip()
        if not code:
            raise InvalidInput("量表缺少 code")
        version = str(raw.get("version") or "v1").strip() or "v1"
        title = str(raw.get("title") or code).strip()
        dims = raw.get("dimension_json", raw.get("dimensions", {}))
        dims_text = dims if isinstance(dims, str) else _dumps(dims or {})
        try:
            status = int(raw.get("status", 1))
        except (TypeError, ValueError):
            status = 1
        items = raw.get("items") or []
        item_count = raw.get("item_count")
        if item_count is None:
            item_count = len(items)
        try:
            item_count = int(item_count)
            minutes = int(raw.get("minutes") or 0)
        except (TypeError, ValueError):
            raise InvalidInput("量表题目数或时长格式错误：%s" % code)

        old = db.q("SELECT id FROM scales WHERE code=? AND version=?", (code, version), one=True)
        if old:
            scale_id = int(old["id"])
            db.exec_(
                "UPDATE scales SET title=?,item_count=?,minutes=?,dimension_json=?,status=? "
                "WHERE id=?",
                (title, item_count, minutes, dims_text, status, scale_id))
            updated += 1
        else:
            scale_id = db.exec_(
                "INSERT INTO scales(code,version,title,item_count,minutes,dimension_json,"
                "status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (code, version, title, item_count, minutes, dims_text, status, now))
            added += 1

        for pos, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            try:
                item_no = int(item.get("item_no") or pos + 1)
            except (TypeError, ValueError):
                raise InvalidInput("题号格式错误：%s" % code)
            options = item.get("options", item.get("options_json")) or []
            if isinstance(options, str):
                options = _loads(options, [])
            options = [str(x) for x in options]
            option_dims = item.get("option_dims", item.get("option_dims_json"))
            if isinstance(option_dims, str):
                option_dims = _loads(option_dims, [])
            option_dims_text = _dumps(option_dims) if option_dims else None
            try:
                reverse = 1 if int(item.get("reverse") or 0) else 0
            except (TypeError, ValueError):
                reverse = 0
            stem = str(item.get("stem") or "")
            dimension = str(item.get("dimension") or "")
            old_item = db.q(
                "SELECT id FROM scale_items WHERE scale_id=? AND item_no=?",
                (scale_id, item_no), one=True)
            if old_item:
                db.exec_(
                    "UPDATE scale_items SET stem=?,options_json=?,dimension=?,reverse=?,"
                    "option_dims_json=? WHERE id=?",
                    (stem, _dumps(options), dimension, reverse, option_dims_text,
                     int(old_item["id"])))
                items_updated += 1
            else:
                db.exec_(
                    "INSERT INTO scale_items(scale_id,item_no,stem,options_json,dimension,"
                    "reverse,option_dims_json) VALUES(?,?,?,?,?,?,?)",
                    (scale_id, item_no, stem, _dumps(options), dimension, reverse,
                     option_dims_text))
                items_added += 1
    return {"scales_added": added, "scales_updated": updated,
            "items_added": items_added, "items_updated": items_updated}


def list_scales(active_only=True):
    sql = "SELECT * FROM scales"
    args = ()
    if active_only:
        sql += " WHERE status=1"
    sql += " ORDER BY code, version"
    out = []
    for row in db.q(sql, args):
        item = dict(row)
        item["dimension_json"] = _loads(item.get("dimension_json"), {})
        out.append(item)
    return out


def get_scale(code, version=None):
    code = str(code or "").strip()
    if not code:
        return None
    if version:
        row = db.q("SELECT * FROM scales WHERE code=? AND version=?",
                   (code, str(version)), one=True)
    else:
        row = db.q("SELECT * FROM scales WHERE code=? ORDER BY status DESC, id DESC LIMIT 1",
                   (code,), one=True)
    if not row:
        return None
    item = dict(row)
    item["dimension_json"] = _loads(item.get("dimension_json"), {})
    return item


def get_scale_items(scale_id):
    rows = db.q("SELECT * FROM scale_items WHERE scale_id=? ORDER BY item_no", (int(scale_id),))
    out = []
    for row in rows:
        item = dict(row)
        item["options"] = _loads(item.get("options_json"), [])
        item["option_dims"] = _loads(item.get("option_dims_json"), []) or []
        out.append(item)
    return out


def count_scales(active_only=True):
    sql = "SELECT COUNT(*) AS n FROM scales" + (" WHERE status=1" if active_only else "")
    row = db.q(sql, one=True)
    return int(row["n"]) if row else 0


def count_items(active_only=True):
    if active_only:
        row = db.q("SELECT COUNT(*) AS n FROM scale_items si JOIN scales s ON s.id=si.scale_id "
                   "WHERE s.status=1", one=True)
    else:
        row = db.q("SELECT COUNT(*) AS n FROM scale_items", one=True)
    return int(row["n"]) if row else 0


def add_batch(term, name, scale_codes, start_at=None, end_at=None):
    """新增施测批次（管理端/脚本可用），返回批次 id。"""
    codes = [str(c) for c in (scale_codes or [])]
    if not codes:
        raise InvalidInput("批次至少包含一个量表")
    return db.exec_(
        "INSERT INTO assess_batches(term,name,scale_codes_json,start_at,end_at) "
        "VALUES(?,?,?,?,?)",
        (term or current_term(), str(name or "测评批次"), _dumps(codes), start_at, end_at))


# ---------------------------------------------------------------- 测评
def get_assessment(assessment_id):
    row = db.q("SELECT * FROM assessments WHERE id=?", (int(assessment_id),), one=True)
    return dict(row) if row else None


def _answered_nos(assessment_id):
    rows = db.q("SELECT item_no FROM assessment_answers WHERE assessment_id=? ORDER BY item_no",
                (int(assessment_id),))
    return [int(r["item_no"]) for r in rows]


def _batch_for_scale(code):
    """按当前学期与时间窗匹配批次；匹配不到返回 None（开始测评不依赖批次）。"""
    today = date.today().isoformat()
    for row in db.q("SELECT * FROM assess_batches ORDER BY id"):
        codes = _loads(row["scale_codes_json"], [])
        if code not in codes:
            continue
        start = str(row["start_at"] or "")[:10]
        end = str(row["end_at"] or "")[:10]
        if start and today < start:
            continue
        if end and today > end:
            continue
        return int(row["id"])
    return None


def start_assessment(class_id, student_id, code):
    """开始测评：同一量表已有进行中/断点则复用，返回 assessment 与已答题号。"""
    scale = get_scale(code)
    if not scale:
        raise NotFound("量表不存在或未启用")
    existing = db.q(
        "SELECT * FROM assessments WHERE class_id=? AND student_id=? AND scale_code=? "
        "AND status IN (0,1) ORDER BY id DESC LIMIT 1",
        (str(class_id), str(student_id), scale["code"]), one=True)
    if existing:
        assessment = dict(existing)
    else:
        batch_id = _batch_for_scale(scale["code"])
        aid = db.exec_(
            "INSERT INTO assessments(class_id,student_id,scale_code,scale_version,batch_id,"
            "status,started_at) VALUES(?,?,?,?,?,0,?)",
            (str(class_id), str(student_id), scale["code"], scale["version"], batch_id,
             db.now()))
        assessment = get_assessment(aid)
    return {"assessment": assessment, "answered": _answered_nos(assessment["id"])}


def assessment_items(assessment_id):
    """下发题目：只给题号/题干/选项，不含 reverse、dimension 等计分元数据。"""
    assessment = get_assessment(assessment_id)
    if not assessment:
        raise NotFound("测评不存在")
    scale = get_scale(assessment["scale_code"], assessment["scale_version"])
    if not scale:
        raise NotFound("量表不存在")
    items = [{"no": int(it["item_no"]), "stem": it["stem"], "options": it["options"]}
             for it in get_scale_items(scale["id"])]
    answers = {int(r["item_no"]): int(r["option_no"]) for r in db.q(
        "SELECT item_no,option_no FROM assessment_answers WHERE assessment_id=?",
        (int(assessment_id),))}
    return {"title": scale["title"], "items": items, "answers": answers,
            "status": int(assessment["status"])}


def save_answers(assessment_id, answers):
    """保存作答：校验题号与选项范围；未提交前可反复续答。"""
    assessment = get_assessment(assessment_id)
    if not assessment:
        raise NotFound("测评不存在")
    if int(assessment["status"]) == 2:
        raise Conflict("该测评已提交，不能修改")
    scale = get_scale(assessment["scale_code"], assessment["scale_version"])
    if not scale:
        raise NotFound("量表不存在")
    items = {int(it["item_no"]): it for it in get_scale_items(scale["id"])}
    if not isinstance(answers, dict) or not answers:
        raise InvalidInput("没有可保存的作答")
    parsed = {}
    for key, value in answers.items():
        try:
            item_no = int(key)
            option_no = int(value)
        except (TypeError, ValueError):
            raise InvalidInput("作答格式错误")
        item = items.get(item_no)
        if not item:
            raise InvalidInput("题号不存在：%s" % item_no)
        option_count = len(item["options"])
        if option_count and (option_no < 1 or option_no > option_count):
            raise InvalidInput("第 %d 题选项超出范围" % item_no)
        parsed[item_no] = option_no
    ts = db.now()
    db.exec_many([
        ("INSERT INTO assessment_answers(assessment_id,item_no,option_no,answered_at) "
         "VALUES(?,?,?,?) ON CONFLICT(assessment_id,item_no) DO UPDATE SET "
         "option_no=excluded.option_no, answered_at=excluded.answered_at",
         (int(assessment_id), no, opt, ts))
        for no, opt in sorted(parsed.items())])
    # 保存但未提交 → 断点（1）
    db.exec_("UPDATE assessments SET status=1 WHERE id=? AND status<>2", (int(assessment_id),))
    return {"answered": _answered_nos(assessment_id)}


def _compute_scores(assessment):
    """按参照包规则计分，返回 {radar_key: std}、tags、advice 并落 scores。"""
    scale = get_scale(assessment["scale_code"], assessment["scale_version"])
    if not scale:
        raise NotFound("量表不存在")
    labels = scale.get("dimension_json") or {}
    items = get_scale_items(scale["id"])
    answers = {int(r["item_no"]): int(r["option_no"]) for r in db.q(
        "SELECT item_no,option_no FROM assessment_answers WHERE assessment_id=?",
        (int(assessment["id"]),))}

    max_by_dim = {}
    for item in items:
        if item["option_dims"]:
            for dim in item["option_dims"]:
                max_by_dim[dim] = max_by_dim.get(dim, 0) + 1
        else:
            max_by_dim[item["dimension"]] = (
                max_by_dim.get(item["dimension"], 0) + (len(item["options"]) or 4))

    raw_by_dim = {}
    for item in items:
        value = answers.get(int(item["item_no"]))
        if not value or value < 1:
            continue
        if item["option_dims"]:
            dims = item["option_dims"]
            if value <= len(dims):
                raw_by_dim[dims[value - 1]] = raw_by_dim.get(dims[value - 1], 0) + 1
        else:
            k = len(item["options"]) or 4
            val = (k + 1 - value) if item["reverse"] else value
            raw_by_dim[item["dimension"]] = raw_by_dim.get(item["dimension"], 0) + val

    radar, score_rows = {}, []
    for dim, full in max_by_dim.items():
        raw = raw_by_dim.get(dim, 0)
        std = round(raw * 100.0 / full) if full else 0
        key = "%s:%s" % (scale["code"], labels.get(dim, dim))
        radar[key] = std
        score_rows.append((int(assessment["id"]), dim, raw, std))
    if score_rows:
        db.exec_many([
            ("INSERT INTO scores(assessment_id,dimension,raw,std_score) VALUES(?,?,?,?) "
             "ON CONFLICT(assessment_id,dimension) DO UPDATE SET raw=excluded.raw,"
             "std_score=excluded.std_score", row) for row in score_rows])
    return radar, labels


def _build_tags(radar):
    tags = []
    strengths = [k for k, v in sorted(radar.items(), key=lambda x: -x[1]) if v >= 70]
    for key in strengths[:3]:
        tags.insert(0, {"type": "strength", "dim": key, "score": radar[key]})
    for key, value in sorted(radar.items(), key=lambda x: x[1]):
        if value <= 40:
            tags.append({"type": "develop", "dim": key, "score": value})
    for tag in tags:
        name = tag["dim"].split(":", 1)[-1]
        tag["label"] = ("优势·" if tag["type"] == "strength" else "待发展·") + name
    return tags


TRACK_MAP = {
    "升学": ["语言", "逻辑", "读写", "研究", "自我认识"],
    "就业": ["动手", "现实", "事务", "人际", "社会", "自我管理"],
    "特长": ["艺术", "音乐", "身体", "自然", "视觉"],
}


def _build_advice(radar, tags):
    strengths = [t["dim"] for t in tags if t["type"] == "strength"]
    advice = []
    for track, keywords in TRACK_MAP.items():
        hit = [k for k in strengths if any(w in k for w in keywords)]
        if hit:
            name = hit[0].split(":", 1)[-1]
            advice.append({"track": track, "basis": hit[:2],
                           "text": "%s方向：发挥%s优势" % (track, name)})
        else:
            advice.append({"track": track, "basis": [],
                           "text": "%s方向：暂无突出优势维度，先补基础" % track})
    advice = sorted(advice, key=lambda a: -len(a["basis"]))[:3]
    return advice


def _rebuild_profile(class_id, student_id, term):
    """学期画像：已完成量表的最新维度分 → 雷达/标签/三轨建议（唯一 student+term）。"""
    rows = db.q(
        "SELECT id,scale_code,scale_version,submitted_at FROM assessments "
        "WHERE student_id=? AND status=2 ORDER BY submitted_at DESC, id DESC",
        (str(student_id),))
    seen, radar = set(), {}
    for row in rows:
        code = row["scale_code"]
        if code in seen:
            continue
        seen.add(code)
        scale = get_scale(code, row["scale_version"])
        if not scale:
            continue
        labels = scale.get("dimension_json") or {}
        for s in db.q("SELECT dimension,std_score FROM scores WHERE assessment_id=?",
                      (int(row["id"]),)):
            key = "%s:%s" % (code, labels.get(s["dimension"], s["dimension"]))
            radar[key] = int(s["std_score"])
    if not radar:
        return None
    tags = _build_tags(radar)
    advice = _build_advice(radar, tags)
    now = db.now()
    db.exec_(
        "INSERT INTO profiles(class_id,student_id,term,radar_json,tags_json,advice_json,"
        "created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(student_id,term) DO UPDATE SET "
        "radar_json=excluded.radar_json, tags_json=excluded.tags_json, "
        "advice_json=excluded.advice_json, created_at=excluded.created_at",
        (str(class_id), str(student_id), term, _dumps(radar), _dumps(tags),
         _dumps(advice), now))
    return {"term": term, "radar": radar, "tags": tags, "advice": advice}


def submit_assessment(assessment_id):
    """提交测评：必须全题作答；重复提交抛 Conflict（接口 409）。"""
    assessment = get_assessment(assessment_id)
    if not assessment:
        raise NotFound("测评不存在")
    if int(assessment["status"]) == 2:
        raise Conflict("该测评已提交，请勿重复提交")
    scale = get_scale(assessment["scale_code"], assessment["scale_version"])
    if not scale:
        raise NotFound("量表不存在")
    total = len(get_scale_items(scale["id"]))
    answered = set(_answered_nos(assessment["id"]))
    missing = [it["item_no"] for it in get_scale_items(scale["id"])
               if int(it["item_no"]) not in answered]
    if missing:
        raise InvalidInput("还有 %d 题未作答，暂不能提交" % len(missing))
    radar, _labels = _compute_scores(assessment)
    db.exec_("UPDATE assessments SET status=2, submitted_at=? WHERE id=? AND status<>2",
             (db.now(), int(assessment_id)))
    profile = _rebuild_profile(assessment["class_id"], assessment["student_id"],
                               current_term())
    return {"assessment_id": int(assessment_id), "total": total,
            "radar": radar,
            "tags": profile["tags"] if profile else [],
            "advice": profile["advice"] if profile else []}


def get_profile(student_id, term=None):
    if term:
        row = db.q("SELECT * FROM profiles WHERE student_id=? AND term=?",
                   (str(student_id), str(term)), one=True)
    else:
        row = db.q("SELECT * FROM profiles WHERE student_id=? "
                   "ORDER BY created_at DESC, id DESC LIMIT 1", (str(student_id),), one=True)
    if not row:
        return None
    return {"id": int(row["id"]), "class_id": row["class_id"],
            "student_id": row["student_id"], "term": row["term"],
            "radar": _loads(row["radar_json"], {}),
            "tags": _loads(row["tags_json"], []),
            "advice": _loads(row["advice_json"], []),
            "created_at": row["created_at"]}


def profile_history(student_id):
    rows = db.q("SELECT * FROM profiles WHERE student_id=? ORDER BY created_at DESC, id DESC",
                (str(student_id),))
    return [{"term": r["term"], "radar": _loads(r["radar_json"], {}),
             "tags": _loads(r["tags_json"], []),
             "advice": _loads(r["advice_json"], []),
             "created_at": r["created_at"]} for r in rows]


def assess_overview(class_id, student_id, term=None):
    """测评清单：批次 + 量表完成度（0 未开始 / 1 进行中 / 2 已完成）。"""
    term = term or current_term()
    active = {s["code"]: s for s in list_scales()}
    recent = {}
    for row in db.q("SELECT * FROM assessments WHERE class_id=? AND student_id=? "
                    "ORDER BY id DESC", (str(class_id), str(student_id))):
        recent.setdefault(row["scale_code"], dict(row))
    batches = []
    for row in db.q("SELECT * FROM assess_batches WHERE term=? ORDER BY id", (term,)):
        codes = [c for c in _loads(row["scale_codes_json"], []) if c in active]
        if not codes:
            continue
        batches.append({"id": int(row["id"]), "name": row["name"],
                        "start_at": row["start_at"], "end_at": row["end_at"],
                        "_codes": codes})
    if not batches and active:
        # 未配置批次时按启用量表归一组，不臆造数字
        batches = [{"id": None, "name": "本学期测评", "start_at": None, "end_at": None,
                    "_codes": list(active)}]
    out = []
    for batch in batches:
        scales = []
        for code in batch["_codes"]:
            scale = active[code]
            total = len(get_scale_items(scale["id"])) or int(scale.get("item_count") or 0)
            assessment = recent.get(code)
            answered = 0
            if assessment:
                answered = (total if int(assessment["status"]) == 2
                            else len(_answered_nos(assessment["id"])))
            scales.append({
                "code": code, "title": scale["title"],
                "minutes": int(scale.get("minutes") or 0),
                "status": int(assessment["status"]) if assessment else 0,
                "assessment_id": int(assessment["id"]) if assessment else None,
                "answered": answered, "total": total,
            })
        out.append({"id": batch["id"], "name": batch["name"],
                    "start_at": batch["start_at"], "end_at": batch["end_at"],
                    "scales": scales})
    return {"term": term, "batches": out}


# ---------------------------------------------------------------- 首页 / 时间轴
def moral_summary(class_id, student_id):
    start, end = _week_range()
    rows = db.q(
        "SELECT points FROM dom_behavior WHERE class_id=? AND student_id=? "
        "AND status='confirmed' AND event_date BETWEEN ? AND ?",
        (str(class_id), str(student_id), start.isoformat(), end.isoformat()))
    delta = sum(int(r["points"] or 0) for r in rows)
    return {"total_score": 100 + delta, "week_delta": delta, "event_count": len(rows)}


def attendance_summary(class_id, student_id):
    today = date.today()
    start, end = _week_range()
    rows = db.q(
        "SELECT date,status FROM dom_attendance WHERE class_id=? AND student_id=? "
        "AND date BETWEEN ? AND ? ORDER BY date, session_no",
        (str(class_id), str(student_id), start.isoformat(), end.isoformat()))
    present = total = 0
    today_flags = []
    for row in rows:
        total += 1
        if row["status"] == "present":
            present += 1
        if row["date"] == today.isoformat():
            today_flags.append(row["status"])
    today_status = None
    if today_flags:
        today_status = "present"
        for bad in ("absent", "late", "leave"):
            if bad in today_flags:
                today_status = bad
                break
    return {"today_status": today_status,
            "week_rate": round(present * 100.0 / total, 1) if total else None}


def homework_summary(class_id, student_id):
    start, end = _week_range()
    rows = db.q(
        "SELECT submitted FROM dom_homework WHERE class_id=? AND student_id=? "
        "AND date BETWEEN ? AND ?",
        (str(class_id), str(student_id), start.isoformat(), end.isoformat()))
    total = len(rows)
    done = sum(1 for r in rows if int(r["submitted"] or 0))
    return {"rate": round(done * 100.0 / total, 1) if total else None,
            "submitted": done, "total": total, "missed_count": total - done}


def home(class_id, student_id, student_no, name):
    """学生首页聚合：档案 / 德育 / 考勤 / 作业 / 成长。"""
    cls = db.q("SELECT name FROM classes WHERE class_id=?", (str(class_id),), one=True)
    profile = get_profile(student_id)
    done = db.q("SELECT COUNT(DISTINCT scale_code) AS n FROM assessments "
                "WHERE class_id=? AND student_id=? AND status=2",
                (str(class_id), str(student_id)), one=True)
    return {
        "profile": {"name": name, "class_name": (cls["name"] if cls else str(class_id)),
                    "student_no": str(student_no or student_id)},
        "moral": moral_summary(class_id, student_id),
        "attendance": attendance_summary(class_id, student_id),
        "homework": homework_summary(class_id, student_id),
        "growth": {
            "assess_done": int(done["n"]) if done else 0,
            "assess_total": count_scales(),
            "latest_profile": ({"term": profile["term"], "tags": profile["tags"]}
                               if profile else None),
        },
    }


ATTENDANCE_LABELS = {"absent": "缺勤", "late": "迟到", "leave": "请假",
                     "present": "出勤"}


def _timeline_rows(class_id, student_id, kind="all", limit=200):
    """聚合五类成长事件；德育只取 confirmed。"""
    items = []
    if kind in ("all", "moral"):
        for row in db.q(
                "SELECT id,event_date,category,points,fact FROM dom_behavior "
                "WHERE class_id=? AND student_id=? AND status='confirmed' "
                "ORDER BY event_date DESC, ts DESC LIMIT ?",
                (str(class_id), str(student_id), int(limit))):
            items.append({"id": "moral:%s" % row["id"], "type": "moral",
                          "date": row["event_date"], "title": row["category"],
                          "detail": row["fact"] or "",
                          "points": int(row["points"] or 0)})
    if kind in ("all", "assess"):
        for row in db.q(
                "SELECT a.id,a.submitted_at,s.title FROM assessments a "
                "LEFT JOIN scales s ON s.code=a.scale_code "
                "WHERE a.class_id=? AND a.student_id=? AND a.status=2 "
                "ORDER BY a.submitted_at DESC LIMIT ?",
                (str(class_id), str(student_id), int(limit))):
            items.append({"id": "assess:%s" % row["id"], "type": "assess",
                          "date": str(row["submitted_at"] or "")[:10],
                          "title": "完成测评《%s》" % (row["title"] or "量表"),
                          "detail": "测评结果已生成"})
    if kind in ("all", "attendance"):
        for row in db.q(
                "SELECT date,session_no,status FROM dom_attendance "
                "WHERE class_id=? AND student_id=? AND status<>'present' "
                "ORDER BY date DESC LIMIT ?",
                (str(class_id), str(student_id), int(limit))):
            items.append({"id": "attendance:%s:%s" % (row["date"], row["session_no"]),
                          "type": "attendance", "date": row["date"],
                          "title": "考勤异常·%s" % ATTENDANCE_LABELS.get(row["status"],
                                                                      row["status"]),
                          "detail": "第 %s 节" % (int(row["session_no"]) + 1)})
    if kind in ("all", "homework"):
        for row in db.q(
                "SELECT date,subject FROM dom_homework "
                "WHERE class_id=? AND student_id=? AND submitted=0 "
                "ORDER BY date DESC LIMIT ?",
                (str(class_id), str(student_id), int(limit))):
            items.append({"id": "homework:%s:%s" % (row["date"], row["subject"]),
                          "type": "homework", "date": row["date"],
                          "title": "%s作业未交" % (row["subject"] or "未分科"),
                          "detail": "请尽快补交"})
    if kind in ("all", "plan"):
        for row in db.q(
                "SELECT id,date,text FROM student_plan_checks "
                "WHERE class_id=? AND student_id=? AND done=1 "
                "ORDER BY date DESC LIMIT ?",
                (str(class_id), str(student_id), int(limit))):
            items.append({"id": "plan:%s" % row["id"], "type": "plan",
                          "date": row["date"],
                          "title": "计划打卡", "detail": row["text"] or ""})
    items.sort(key=lambda x: (x["date"] or "", x["id"]), reverse=True)
    return items


def timeline(class_id, student_id, kind="all", page=1, size=20):
    kind = str(kind or "all").lower()
    if kind not in ("all", "moral", "assess", "attendance", "homework", "plan"):
        raise InvalidInput("未知的时间轴类型")
    try:
        page = max(1, int(page or 1))
        size = max(1, min(50, int(size or 20)))
    except (TypeError, ValueError):
        raise InvalidInput("分页参数格式错误")
    items = _timeline_rows(class_id, student_id, kind)
    start = (page - 1) * size
    return {"items": items[start:start + size], "page": page,
            "has_more": page * size < len(items)}


# ---------------------------------------------------------------- 待办
def _pending_todos(class_id, student_id):
    """由业务事实生成待办；不写死文案、不臆造数量。"""
    today = date.today()
    todos = []
    # 1. 未完成的测评
    for row in db.q(
            "SELECT id,scale_code,status FROM assessments WHERE class_id=? AND student_id=? "
            "AND status IN (0,1) ORDER BY started_at DESC",
            (str(class_id), str(student_id))):
        scale = get_scale(row["scale_code"])
        total = len(get_scale_items(scale["id"])) if scale else 0
        answered = len(_answered_nos(row["id"]))
        todos.append({
            "id": "assess:%s" % row["id"], "type": "assess",
            "title": "完成测评《%s》" % (scale["title"] if scale else row["scale_code"]),
            "meta": "已答 %d/%d 题" % (answered, total), "due": None,
        })
    # 2. 近 7 天未交作业
    start = today - timedelta(days=today.weekday())
    for row in db.q(
            "SELECT date,subject FROM dom_homework WHERE class_id=? AND student_id=? "
            "AND submitted=0 AND date BETWEEN ? AND ? ORDER BY date DESC",
            (str(class_id), str(student_id), start.isoformat(), today.isoformat())):
        todos.append({
            "id": "homework:%s:%s" % (row["date"], row["subject"]), "type": "homework",
            "title": "补交%s作业" % (row["subject"] or "未分科"),
            "meta": row["date"], "due": row["date"],
        })
    # 3. 今日计划尚未打卡
    checked = db.q("SELECT 1 FROM student_plan_checks WHERE student_id=? AND date=? AND done=1",
                   (str(student_id), today.isoformat()), one=True)
    if not checked:
        todos.append({"id": "plan:%s" % today.isoformat(), "type": "plan",
                      "title": "今日成长计划打卡", "meta": "每天记录一条",
                      "due": today.isoformat()})
    return todos


def todos(class_id, student_id):
    """待办清单：未处理 + 最近已处理（done / ignore）。"""
    pending = _pending_todos(class_id, student_id)
    state_rows = db.q(
        "SELECT id,type,title,state,updated_at FROM student_todos_state "
        "WHERE class_id=? AND student_id=? AND state<>'pending' "
        "ORDER BY updated_at DESC LIMIT 20",
        (str(class_id), str(student_id)))
    handled = {row["id"]: row for row in state_rows}
    out = [dict(item, state="pending") for item in pending if item["id"] not in handled]
    for row in state_rows:
        out.append({"id": row["id"], "type": row["type"], "title": row["title"],
                    "meta": "", "due": None, "state": row["state"],
                    "updated_at": row["updated_at"]})
    return {"items": out}


def todo_action(class_id, student_id, todo_id, action):
    """完成或忽略待办；已处理过可覆盖状态（幂等）。"""
    if action not in ("done", "ignore"):
        raise InvalidInput("未知的待办操作")
    todo_id = str(todo_id or "").strip()
    if not todo_id:
        raise InvalidInput("待办编号不能为空")
    row = next((t for t in _pending_todos(class_id, student_id) if t["id"] == todo_id), None)
    if not row:
        old = db.q("SELECT * FROM student_todos_state WHERE id=? AND class_id=? AND student_id=?",
                   (todo_id, str(class_id), str(student_id)), one=True)
        if not old:
            raise NotFound("待办不存在或已处理")
        row = {"type": old["type"], "title": old["title"]}
    db.exec_(
        "INSERT INTO student_todos_state(id,class_id,student_id,type,title,state,updated_at) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state, "
        "title=excluded.title, type=excluded.type, updated_at=excluded.updated_at",
        (todo_id, str(class_id), str(student_id), row["type"], row["title"], action,
         db.now()))
    return {"id": todo_id, "state": action}


# ---------------------------------------------------------------- 成长计划
def get_plan(class_id, student_id):
    term = current_term()
    goals = db.q("SELECT id,text,progress FROM student_goals WHERE class_id=? AND student_id=? "
                 "AND term=? ORDER BY created_at", (str(class_id), str(student_id), term))
    checks = db.q("SELECT date,text,done FROM student_plan_checks "
                  "WHERE class_id=? AND student_id=? ORDER BY date DESC LIMIT 60",
                  (str(class_id), str(student_id)))
    return {"term": term,
            "goals": [{"id": g["id"], "text": g["text"], "progress": int(g["progress"] or 0)}
                      for g in goals],
            "checks": [{"date": c["date"], "text": c["text"], "done": int(c["done"] or 0)}
                       for c in checks]}


def add_goal(class_id, student_id, text):
    text = str(text or "").strip()
    if not text:
        raise InvalidInput("目标内容不能为空")
    if len(text) > 200:
        raise InvalidInput("目标内容不超过 200 字")
    gid = db.uid("goal_")
    db.exec_("INSERT INTO student_goals(id,class_id,student_id,term,text,progress,created_at) "
             "VALUES(?,?,?,?,?,0,?)",
             (gid, str(class_id), str(student_id), current_term(), text, db.now()))
    return {"id": gid, "text": text, "progress": 0}


def delete_goal(class_id, student_id, goal_id):
    row = db.q("SELECT id FROM student_goals WHERE id=? AND class_id=? AND student_id=?",
               (str(goal_id), str(class_id), str(student_id)), one=True)
    if not row:
        raise NotFound("目标不存在")
    db.exec_("DELETE FROM student_goals WHERE id=?", (str(goal_id),))
    return True


def checkin(class_id, student_id, day=None, text=""):
    day = str(day or date.today().isoformat()).strip()
    try:
        date.fromisoformat(day)
    except ValueError:
        raise InvalidInput("打卡日期格式应为 YYYY-MM-DD")
    text = str(text or "").strip() or "完成今日计划"
    if len(text) > 200:
        raise InvalidInput("打卡内容不超过 200 字")
    db.exec_(
        "INSERT INTO student_plan_checks(id,class_id,student_id,date,text,done,created_at) "
        "VALUES(?,?,?,?,?,1,?) ON CONFLICT(student_id,date) DO UPDATE SET "
        "text=excluded.text, done=1, created_at=excluded.created_at",
        (db.uid("chk_"), str(class_id), str(student_id), day, text, db.now()))
    return {"date": day, "text": text, "done": 1}


# ---------------------------------------------------------------- 分享
def _share_status(row):
    if row["status"] != "active":
        return row["status"]
    return "expired" if _expired(row["expires_at"]) else "active"


def _new_share_code():
    return "".join(secrets.choice(SHARE_CODE_ALPHABET) for _ in range(8))


def create_share(class_id, student_id, hours=24):
    try:
        hours = int(hours or 24)
    except (TypeError, ValueError):
        raise InvalidInput("有效时长格式错误")
    hours = max(1, min(MAX_SHARE_HOURS, hours))
    expires = _iso(_now_dt() + timedelta(hours=hours))
    for _ in range(5):
        code = _new_share_code()
        code_hash = _hash(code)
        if db.q("SELECT 1 FROM shares WHERE code_hash=?", (code_hash,), one=True):
            continue
        share_id = db.uid("sh_")
        db.exec_("INSERT INTO shares(id,class_id,student_id,code_hash,code_masked,expires_at,"
                 "status,created_at) VALUES(?,?,?,?,?,?, 'active',?)",
                 (share_id, str(class_id), str(student_id), code_hash,
                  code[:2] + "••••" + code[-2:], expires, db.now()))
        return {"id": share_id, "code": code, "expires_at": expires,
                "url": "/s/%s" % code}
    raise Conflict("分享码生成失败，请重试")


def list_shares(student_id):
    rows = db.q("SELECT * FROM shares WHERE student_id=? ORDER BY created_at DESC",
                (str(student_id),))
    return [{"id": r["id"], "masked_code": r["code_masked"],
             "expires_at": r["expires_at"], "status": _share_status(r),
             "created_at": r["created_at"]} for r in rows]


def revoke_share(student_id, share_id):
    row = db.q("SELECT id FROM shares WHERE id=? AND student_id=?",
               (str(share_id), str(student_id)), one=True)
    if not row:
        raise NotFound("分享不存在")
    db.exec_("UPDATE shares SET status='revoked', revoked_at=? WHERE id=?",
             (db.now(), str(share_id)))
    return True


def _log_access(code_hash, ip, result):
    db.exec_("INSERT INTO share_access_logs(ts,code_hash,ip,result) VALUES(?,?,?,?)",
             (db.now(), code_hash, str(ip or ""), result))


def verify_share(code, ip=""):
    """校验分享码：1 分钟内失败超过 10 次即 429；成功返回分享记录。"""
    code = str(code or "").strip().upper()
    if not code:
        raise InvalidShare("分享已失效")
    code_hash = _hash(code)
    since = _iso(_now_dt() - timedelta(seconds=VERIFY_FAIL_WINDOW_SECONDS))
    fails = db.q("SELECT COUNT(*) AS n FROM share_access_logs WHERE ip=? AND result='fail' "
                 "AND ts>=?", (str(ip or ""), since), one=True)
    if int(fails["n"] or 0) >= VERIFY_FAIL_LIMIT:
        _log_access(code_hash, ip, "blocked")
        raise TooManyRequests("尝试次数过多，请稍后再试")
    row = db.q("SELECT * FROM shares WHERE code_hash=?", (code_hash,), one=True)
    if not row or _share_status(row) != "active":
        _log_access(code_hash, ip, "fail")
        raise InvalidShare("分享已失效")
    _log_access(code_hash, ip, "ok")
    return dict(row)


def get_share(share_id):
    row = db.q("SELECT * FROM shares WHERE id=?", (str(share_id),), one=True)
    if not row or _share_status(row) != "active":
        raise InvalidShare("分享已失效")
    return dict(row)


def share_content(share_id):
    """分享内容白名单：昵称（姓+*）、班级、画像摘要、时间轴标题；绝不含学号/全名/电话/作答。"""
    share = get_share(share_id)
    info = db.q(
        "SELECT s.name, COALESCE(c.name,s.class_id) AS class_name FROM students s "
        "LEFT JOIN classes c ON c.class_id=s.class_id "
        "WHERE s.class_id=? AND s.student_id=?",
        (share["class_id"], share["student_id"]), one=True)
    profile = get_profile(share["student_id"])
    items = _timeline_rows(share["class_id"], share["student_id"], "all")[:20]
    return {
        "nickname": _mask_name(info["name"] if info else ""),
        "class_name": (info["class_name"] if info else share["class_id"]),
        "profile": ({"term": profile["term"], "radar": profile["radar"],
                     "tags": profile["tags"], "advice": profile["advice"]}
                    if profile else None),
        "timeline": [{"date": it["date"], "title": it["title"]} for it in items],
    }


# ---------------------------------------------------------------- 隐私（学生本人视角）
def privacy(student):
    bindings = db.q("SELECT * FROM parent_bindings WHERE class_id=? AND student_id=? "
                    "ORDER BY created_at DESC",
                    (str(student["class_id"]), str(student["student_id"])))
    return {
        "visible": [
            {"role": "班主任", "scope": "德育确认记录 / 考勤 / 作业 / 画像摘要"},
            {"role": "家长", "scope": "画像摘要 / 成长时间轴 / 待办（不含原始作答）"},
        ],
        "bindings": [{"id": b["id"], "relation": b["relation"],
                      "masked_mobile": _mask_mobile(b["mobile"]),
                      "status": b["status"], "created_at": b["created_at"]}
                     for b in bindings],
        "shares": list_shares(student["student_id"]),
    }


def create_bind_code(student):
    """学生生成家长绑定码（10 分钟一次性）。"""
    now = _now_dt()
    expires = _iso(now + timedelta(minutes=BIND_CODE_TTL_MINUTES))
    for _ in range(5):
        code = "%06d" % secrets.randbelow(1000000)
        code_hash = _hash(code)
        if db.q("SELECT 1 FROM parent_bind_codes WHERE code_hash=?", (code_hash,), one=True):
            continue
        db.exec_("INSERT INTO parent_bind_codes(code_hash,class_id,student_id,student_no,"
                 "relation,mobile,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                 (code_hash, str(student["class_id"]), str(student["student_id"]),
                  str(student.get("student_no") or student["student_id"]), "家长", "",
                  expires, db.now()))
        return {"code": code, "expires_at": expires}
    raise Conflict("绑定码生成失败，请重试")


def revoke_binding(student, binding_id):
    row = db.q("SELECT * FROM parent_bindings WHERE id=? AND class_id=? AND student_id=?",
               (str(binding_id), str(student["class_id"]), str(student["student_id"])), one=True)
    if not row:
        raise NotFound("绑定关系不存在")
    now = db.now()
    db.exec_many([
        ("UPDATE parent_bindings SET status='revoked', revoked_at=? WHERE id=?",
         (now, str(binding_id))),
        ("UPDATE parent_accounts SET status='disabled' WHERE id=?",
         (row["parent_id"],)),
    ])
    return True


# ---------------------------------------------------------------- 家长端
def _student_by_no(student_no):
    acc = str(student_no or "").strip()
    if not acc:
        return None
    try:
        rows = db.q("SELECT class_id,student_id,student_no,name FROM students "
                    "WHERE student_no=? OR student_id=? LIMIT 2", (acc, acc))
    except sqlite3.Error:
        return None
    return dict(rows[0]) if len(rows) == 1 else None


def bind_parent(student_no, code, password, relation="家长", mobile=""):
    """家长用绑定码注册：密码≥6 位，绑定码 10 分钟一次性。"""
    password = str(password or "")
    if len(password) < 6:
        raise InvalidInput("密码至少 6 位")
    student = _student_by_no(student_no)
    if not student:
        raise NotFound("学号不存在或无法唯一识别")
    code_hash = _hash(str(code or "").strip())
    record = db.q("SELECT * FROM parent_bind_codes WHERE code_hash=?", (code_hash,), one=True)
    if (not record or record["used_at"] or _expired(record["expires_at"])
            or str(record["student_no"]) != str(student.get("student_no") or "")
            or str(record["student_id"]) != str(student["student_id"])):
        raise InvalidInput("绑定码无效或已过期")
    salt = secrets.token_hex(16)
    parent_id = db.uid("pa_")
    binding_id = db.uid("pb_")
    now = db.now()
    db.exec_many([
        ("INSERT INTO parent_accounts(id,class_id,student_id,student_no,password_salt,"
         "password_hash,status,created_at) VALUES(?,?,?,?,?,?, 'active',?)",
         (parent_id, str(student["class_id"]), str(student["student_id"]),
          str(student.get("student_no") or student["student_id"]), salt,
          _hash_password(password, salt), now)),
        ("INSERT INTO parent_bindings(id,parent_id,class_id,student_id,relation,mobile,"
         "status,created_at) VALUES(?,?,?,?,?,?, 'active',?)",
         (binding_id, parent_id, str(student["class_id"]), str(student["student_id"]),
          str(relation or "家长"), str(mobile or ""), now)),
        ("UPDATE parent_bind_codes SET used_at=? WHERE code_hash=?", (now, code_hash)),
    ])
    return {"binding_id": binding_id, "parent_id": parent_id,
            "class_id": str(student["class_id"]), "student_id": str(student["student_id"]),
            "student_no": str(student.get("student_no") or student["student_id"])}


def parent_login(student_no, password):
    """家长登录：按学号匹配任一家长账号的密码（PBKDF2）。"""
    student = _student_by_no(student_no)
    if not student:
        raise NotFound("学号或密码错误")
    rows = db.q(
        "SELECT pa.*, pb.id AS binding_id FROM parent_accounts pa "
        "JOIN parent_bindings pb ON pb.parent_id=pa.id AND pb.status='active' "
        "WHERE pa.student_no=? AND pa.status='active' ORDER BY pb.created_at DESC",
        (str(student.get("student_no") or student["student_id"]),))
    for row in rows:
        if _check_password(password, row["password_salt"], row["password_hash"]):
            return {"binding_id": row["binding_id"], "parent_id": row["id"],
                    "class_id": row["class_id"], "student_id": row["student_id"]}
    raise NotFound("学号或密码错误")


def get_binding(binding_id):
    """读取有效绑定（家长会话校验用）；已撤回返回 None。"""
    row = db.q("SELECT * FROM parent_bindings WHERE id=? AND status='active'",
               (str(binding_id),), one=True)
    return dict(row) if row else None


def parent_student(binding):
    row = db.q("SELECT * FROM students WHERE class_id=? AND student_id=?",
               (str(binding["class_id"]), str(binding["student_id"])), one=True)
    return dict(row) if row else None


def parent_home(binding):
    student = parent_student(binding)
    if not student:
        raise NotFound("学生不存在")
    data = home(binding["class_id"], binding["student_id"],
                student.get("student_no") or student["student_id"], student["name"])
    # 家长只看画像摘要，姓名按脱敏昵称返回
    data["profile"]["name"] = _mask_name(student["name"])
    data["profile"].pop("student_no", None)
    return data


def parent_timeline(binding, kind="all", page=1, size=20):
    return timeline(binding["class_id"], binding["student_id"], kind, page, size)


def parent_profile(binding):
    """家长画像：只给雷达/标签/建议摘要，不含原始作答与维度原始分。"""
    profile = get_profile(binding["student_id"])
    student = parent_student(binding)
    return {"nickname": _mask_name(student["name"] if student else ""),
            "profile": ({"term": profile["term"], "radar": profile["radar"],
                         "tags": profile["tags"], "advice": profile["advice"]}
                        if profile else None)}


def parent_todos(binding):
    return todos(binding["class_id"], binding["student_id"])
