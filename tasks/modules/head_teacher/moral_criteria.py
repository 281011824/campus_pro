# -*- coding: utf-8 -*-
"""政教处 · 德育指标库（两方向：掌声鼓励 / 有待改善）

指标项可增删改、可启停、按学期生效；事件只保存登记时的分值快照
（`dom_behavior.points`），修改指标分值不影响历史记录。
删除指标时若已有事件引用，则改为停用，不破坏历史。
"""

from tasks.shared import db

DIRECTIONS = ("praise", "improve")
POINTS_MIN = -20
POINTS_MAX = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS moral_criteria (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('praise','improve')),
  points INTEGER NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  term TEXT NOT NULL DEFAULT '',
  sort INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_moral_criteria_direction ON moral_criteria(direction, sort);
"""

# 首次播种的 8 条常用指标：掌声鼓励为正分、有待改善为负分
DEFAULT_CRITERIA = [
    ("P01", "拾金不昧", "praise", 2, "品德行为", 10),
    ("P02", "公益活动", "praise", 3, "社会实践", 20),
    ("P03", "竞赛获奖", "praise", 5, "学业特长", 30),
    ("I01", "迟到", "improve", -1, "考勤纪律", 10),
    ("I02", "旷课", "improve", -3, "考勤纪律", 20),
    ("I03", "抽烟", "improve", -3, "行为规范", 30),
    ("I04", "玩手机", "improve", -1, "课堂纪律", 40),
    ("I05", "打架", "improve", -5, "行为规范", 50),
]


def init():
    """幂等建表、补列、播种；重复调用不报错、不重复播种。"""
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
    _ensure_behavior_columns()
    _seed_default()


def _seed_default():
    """仅当指标表为空时播种默认指标；已有数据绝不覆盖。"""
    if count():
        return
    now = db.now()
    stmts = [
        ("INSERT OR IGNORE INTO moral_criteria"
         "(id,code,name,direction,points,category,enabled,term,sort,created_by,created_at,updated_at) "
         "VALUES(?,?,?,?,?,?,1,'',?,'system',?,?)",
         (db.uid("mc_"), code, name, direction, points, category, sort, now, now))
        for code, name, direction, points, category, sort in DEFAULT_CRITERIA
    ]
    db.exec_many(stmts)


def _ensure_behavior_columns():
    """兼容旧库：dom_behavior 缺列则补加；表不存在时跳过，不丢数据。"""
    c = db.connect()
    try:
        rows = c.execute("PRAGMA table_info(dom_behavior)").fetchall()
        if not rows:
            return
        cols = {r["name"] for r in rows}
        extra = [
            ("criteria_id", "TEXT"),
            ("recorded_by", "TEXT"),
            ("confirmed_by", "TEXT"),
            ("confirmed_at", "TEXT"),
        ]
        for name, ddl in extra:
            if name not in cols:
                c.execute("ALTER TABLE dom_behavior ADD COLUMN %s %s" % (name, ddl))
        c.commit()
    finally:
        c.close()


def _points(value):
    if isinstance(value, bool):
        raise ValueError("分值必须为整数")
    try:
        points = int(value)
    except (TypeError, ValueError):
        raise ValueError("分值必须为整数")
    if isinstance(value, float) and value != points:
        raise ValueError("分值必须为整数")
    if points < POINTS_MIN or points > POINTS_MAX:
        raise ValueError("分值需在 %d 到 %d 之间" % (POINTS_MIN, POINTS_MAX))
    return points


def _name(value):
    name = str(value or "").strip()
    if not name:
        raise ValueError("指标名称不能为空")
    return name


def _direction(value):
    direction = str(value or "").strip()
    if direction not in DIRECTIONS:
        raise ValueError("指标方向不合法")
    return direction


def count():
    try:
        row = db.q("SELECT COUNT(*) AS n FROM moral_criteria", one=True)
    except Exception:
        return 0
    return int(row["n"]) if row else 0


def list_all(enabled_only=False):
    sql = "SELECT * FROM moral_criteria"
    if enabled_only:
        sql += " WHERE enabled=1"
    sql += " ORDER BY direction, sort, id"
    return [dict(r) for r in db.q(sql)]


def get(cid):
    row = db.q("SELECT * FROM moral_criteria WHERE id=?", (str(cid),), one=True)
    return dict(row) if row else None


def _duplicate(direction, name, exclude_id=""):
    return db.q("SELECT id FROM moral_criteria WHERE direction=? AND name=? AND id<>?",
                (direction, name, str(exclude_id or "")), one=True)


def create(name, direction, points, category="", term="", actor=""):
    name = _name(name)
    direction = _direction(direction)
    points = _points(points)
    if _duplicate(direction, name):
        raise ValueError("同方向已存在同名指标：%s" % name)
    cid = db.uid("mc_")
    row = db.q("SELECT MAX(sort) AS s FROM moral_criteria WHERE direction=?",
               (direction,), one=True)
    sort = int(row["s"] or 0) + 10 if row else 10
    now = db.now()
    db.exec_(
        "INSERT INTO moral_criteria"
        "(id,code,name,direction,points,category,enabled,term,sort,created_by,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,1,?,?,?,?,?)",
        (cid, db.uid(direction[:1].upper() + "-"), name, direction, points, str(category or ""),
         str(term or ""), sort, str(actor or ""), now, now))
    return get(cid)


def update(cid, **fields):
    rec = get(cid)
    if not rec:
        raise ValueError("指标不存在")
    allowed = ("name", "direction", "points", "category", "term", "sort", "enabled")
    updates, args = [], []
    name = rec["name"]
    direction = rec["direction"]
    if "name" in fields:
        name = _name(fields["name"])
        updates.append("name=?")
        args.append(name)
    if "direction" in fields:
        direction = _direction(fields["direction"])
        updates.append("direction=?")
        args.append(direction)
    if "points" in fields:
        updates.append("points=?")
        args.append(_points(fields["points"]))
    if ("name" in fields or "direction" in fields) and _duplicate(direction, name, cid):
        raise ValueError("同方向已存在同名指标：%s" % name)
    if "category" in fields:
        updates.append("category=?")
        args.append(str(fields["category"] or ""))
    if "term" in fields:
        updates.append("term=?")
        args.append(str(fields["term"] or ""))
    if "sort" in fields:
        updates.append("sort=?")
        args.append(int(fields["sort"] or 0))
    if "enabled" in fields:
        updates.append("enabled=?")
        args.append(1 if fields["enabled"] else 0)
    if updates:
        updates.append("updated_at=?")
        args.append(db.now())
        args.append(str(cid))
        db.exec_("UPDATE moral_criteria SET %s WHERE id=?" % ",".join(updates), tuple(args))
    return get(cid)


def set_enabled(cid, enabled):
    rec = get(cid)
    if not rec:
        raise ValueError("指标不存在")
    db.exec_("UPDATE moral_criteria SET enabled=?, updated_at=? WHERE id=?",
             (1 if enabled else 0, db.now(), str(cid)))
    return get(cid)


def remove(cid):
    """有历史事件引用则改为停用，否则删除；返回 'disabled' / 'deleted'。"""
    rec = get(cid)
    if not rec:
        raise ValueError("指标不存在")
    referenced = False
    try:
        cols = {r["name"] for r in db.q("PRAGMA table_info(dom_behavior)")}
        if "criteria_id" in cols:
            row = db.q("SELECT COUNT(*) AS n FROM dom_behavior WHERE criteria_id=?",
                       (str(cid),), one=True)
            referenced = bool(row and row["n"])
    except Exception:
        referenced = False
    if referenced:
        db.exec_("UPDATE moral_criteria SET enabled=0, updated_at=? WHERE id=?",
                 (db.now(), str(cid)))
        return "disabled"
    db.exec_("DELETE FROM moral_criteria WHERE id=?", (str(cid),))
    return "deleted"


def snapshot_points(cid):
    """返回指标当前分值，供事件登记时写入分值快照；指标不存在返回 None。"""
    rec = get(cid)
    return int(rec["points"]) if rec else None
