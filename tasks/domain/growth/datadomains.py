# -*- coding: utf-8 -*-
"""德育工作台 · 数据域采集与聚合层（SQLite 轻量实现）

对照《京山中职德育 AI 赋能与数字化实施方案（草稿 v1.0）》十四个数据域：
- 落地：考勤到课、请假出入、晚寝内务、行为事件（德育量化）、就餐、图书借阅、
  校医就诊、活动签到、课堂参与、作业完成、学业成绩档位。
- 只采结构与规律，不采内容细节；不采人脸/声纹，不做表情与情绪识别。
- 数据域未接入时，聚合结果返回 None，由上层标注「暂不可用」，不估算、不填旧值。
- 双轨纪律：无感数据只做正向反馈；底线轨行为事件必须人工确认后才计分。
"""
import random
from datetime import date, timedelta

from tasks.shared import db

# 十四个数据域现状（供 /api/v1/domains/status 展示；与实施方案 2.1 对齐）
DOMAINS = [
    {"id": 1, "name": "学籍与家庭基本信息", "source": "学籍系统/入学登记", "mode": "导入", "status": "已有"},
    {"id": 2, "name": "考勤到课", "source": "智慧班牌/班级考勤终端", "mode": "自动", "status": "已接入"},
    {"id": 3, "name": "课堂参与", "source": "OpenMAIC/青鹿AI", "mode": "自动", "status": "试点已有"},
    {"id": 4, "name": "学业成绩与波动", "source": "教务/考务", "mode": "周期导入", "status": "已接入"},
    {"id": 5, "name": "作业完成与订正", "source": "AI批改", "mode": "自动", "status": "已接入"},
    {"id": 6, "name": "就餐消费", "source": "食堂卡", "mode": "自动", "status": "已接入"},
    {"id": 7, "name": "图书借阅", "source": "图书馆系统", "mode": "自动", "status": "已接入"},
    {"id": 8, "name": "晚寝与宿舍内务", "source": "寝管点验平板", "mode": "顺手记", "status": "已接入"},
    {"id": 9, "name": "请假与出入校", "source": "电子请假单/门卫", "mode": "自动", "status": "已接入"},
    {"id": 10, "name": "校医就诊", "source": "校医室电子台账", "mode": "顺手记", "status": "已接入"},
    {"id": 11, "name": "行为事件（正负两面）", "source": "政教处事件登记", "mode": "事件驱动", "status": "已接入"},
    {"id": 12, "name": "活动与岗位参与", "source": "活动二维码签到", "mode": "顺手记", "status": "已接入"},
    {"id": 13, "name": "心理测查", "source": "MHT/普查量表", "mode": "课内完成", "status": "隔离（教师端不可见）"},
    {"id": 14, "name": "家校沟通", "source": "企业微信", "mode": "自动", "status": "已接入（留痕）"},
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS dom_attendance (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  date TEXT NOT NULL, student_id TEXT NOT NULL, session_no INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL, source TEXT NOT NULL DEFAULT '考勤终端',
  UNIQUE(class_id, date, student_id, session_no)
);
CREATE TABLE IF NOT EXISTS dom_leave (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  student_id TEXT NOT NULL, date_from TEXT NOT NULL, date_to TEXT NOT NULL,
  leave_type TEXT NOT NULL DEFAULT '事假', approved INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL DEFAULT '电子请假单',
  UNIQUE(class_id, student_id, date_from, date_to)
);
CREATE TABLE IF NOT EXISTS dom_dorm (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  date TEXT NOT NULL, student_id TEXT NOT NULL, status TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '寝管点验', UNIQUE(class_id, date, student_id)
);
CREATE TABLE IF NOT EXISTS dom_behavior (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  student_id TEXT NOT NULL, event_date TEXT NOT NULL,
  polarity TEXT NOT NULL DEFAULT 'positive', category TEXT NOT NULL,
  points INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
  fact TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '政教处事件登记',
  confirmed_by TEXT, confirmed_at TEXT
);
CREATE TABLE IF NOT EXISTS dom_meal (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  date TEXT NOT NULL, student_id TEXT NOT NULL, meals INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT '食堂卡', UNIQUE(class_id, date, student_id)
);
CREATE TABLE IF NOT EXISTS dom_library (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  date TEXT NOT NULL, student_id TEXT NOT NULL, action TEXT NOT NULL DEFAULT 'borrow',
  source TEXT NOT NULL DEFAULT '图书馆系统'
);
CREATE TABLE IF NOT EXISTS dom_clinic (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  date TEXT NOT NULL, student_id TEXT NOT NULL, reason_class TEXT NOT NULL DEFAULT '其他',
  source TEXT NOT NULL DEFAULT '校医室台账'
);
CREATE TABLE IF NOT EXISTS dom_activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  date TEXT NOT NULL, student_id TEXT NOT NULL, activity TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '二维码签到'
);
CREATE TABLE IF NOT EXISTS dom_participation (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  date TEXT NOT NULL, student_id TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '',
  events INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT '课堂互动',
  UNIQUE(class_id, date, student_id, subject)
);
CREATE TABLE IF NOT EXISTS dom_homework (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  date TEXT NOT NULL, student_id TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '',
  submitted INTEGER NOT NULL DEFAULT 1, corrected INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'AI批改', UNIQUE(class_id, date, student_id, subject)
);
CREATE TABLE IF NOT EXISTS dom_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, class_id TEXT NOT NULL,
  exam TEXT NOT NULL, student_id TEXT NOT NULL, band TEXT NOT NULL,
  trend TEXT NOT NULL DEFAULT '持平', source TEXT NOT NULL DEFAULT '教务系统',
  UNIQUE(class_id, exam, student_id)
);
"""


def init(seed_class="2607", size=66):
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
    if not has_data(seed_class):
        seed_demo(seed_class, size)


def has_data(class_id):
    row = db.q("SELECT COUNT(*) AS n FROM dom_attendance WHERE class_id=?",
               (str(class_id),), one=True)
    return bool(row and row["n"])


def _week_bounds(day=None):
    d = day or date.today()
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def _day_bounds(day=None):
    d = day or date.today()
    return d, d


def _month_bounds(day=None):
    d = day or date.today()
    start = d.replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1, day=1)
    else:
        next_month = start.replace(month=start.month + 1, day=1)
    end = next_month - timedelta(days=1)
    return start, end


def _terms():
    """学期窗口：Y 年春季（2/20~7/15）与 Y 年冬季（9/1~次年 1/20）。

    年份范围随当前年份自动扩展：2026 年只列 2026春季/2026冬季，
    到 2027 年自动增加 2027春季/2027冬季，以此类推。
    """
    today = date.today()
    out = []
    for y in range(2026, today.year + 1):
        out.append((date(y, 2, 20), date(y, 7, 15)))
        out.append((date(y, 9, 1), date(y + 1, 1, 20)))
    return out


TERMS = _terms()


def _term_bounds(day=None):
    d = day or date.today()
    terms = _terms()
    # 命中任一学期 → 返回该学期完整区间
    for s, e in terms:
        if s <= d <= e:
            return s, e
    # 都没命中（如寒暑假）→ 就近取最近已开始学期；都未开始则回退到第一个
    past = [t for t in terms if t[0] <= d]
    if past:
        return past[-1]
    return terms[0]


def _academic_term_label(s, e):
    """2026-09-01 → 2026冬季；2026-02-20 → 2026春季。"""
    return "%d冬季" % s.year if s.month >= 8 else "%d春季" % s.year


def _period_title(period, start, end):
    """具体周期标题，用于前端展示（区别于"本周/本月"这类相对标签）。"""
    p = (period or "week").lower()
    if p == "day":
        return "%d 年 %d 月 %d 日" % (start.year, start.month, start.day)
    if p == "month":
        return "%d 年 %d 月" % (start.year, start.month)
    if p == "term":
        return _academic_term_label(start, end)
    if start == end:
        return "%d/%d" % (start.month, start.day)
    return "%d/%d – %d/%d" % (start.month, start.day, end.month, end.day)


def _period_label(period, start, end):
    """相对标签：仍落在当前周期用"本周/本月/本学期"，否则用"该周/该月/该学期"。"""
    today = date.today()
    inside = start <= today <= end
    p = (period or "week").lower()
    if p == "day":
        return "当日" if start == today else "该日"
    if p == "month":
        return "本月" if inside else "该月"
    if p == "term":
        return _academic_term_label(start, end)
    return "本周" if inside else "该周"


def period_bounds(period, day=None):
    """统一入口：day / week / month / term → (start, end, label)。默认 week。

    day 为锚点日期（选定周期内的任意一天），缺省今天。
    周 / 月返回完整自然周期（周一到周日、整月），便于横轴稳定；
    学期返回完整学期区间，但当前学期截止到今天，避免大段未来空数据。
    """
    today = date.today()
    p = (period or "week").lower()
    if p == "day":
        s, e = _day_bounds(day)
    elif p == "month":
        s, e = _month_bounds(day)
    elif p == "term":
        s, e = _term_bounds(day)
        if s <= today < e:
            e = today
    else:
        s, e = _week_bounds(day)
    return s, e, _period_label(p, s, e)


def term_options():
    """供前端"学期"下拉使用：学期区间 + 名称（如 2026冬季）+ 是否当前学期。"""
    today = date.today()
    out = []
    for s, e in _terms():
        out.append({
            "start": s.isoformat(),
            "end": e.isoformat(),
            "title": _academic_term_label(s, e),
            "current": s <= today <= e,
        })
    return out


def _uid(prefix):
    return db.uid(prefix)


def _mask(student_id):
    tail = str(student_id)[-2:]
    return "×同学" + tail


def _week_days(start, end):
    out, cur = [], start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


# ---------------------------------------------------------------- 聚合
def attendance_rate(class_id, start, end):
    row = db.q(
        "SELECT SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) AS present, "
        "COUNT(*) AS total FROM dom_attendance "
        "WHERE class_id=? AND date BETWEEN ? AND ?",
        (str(class_id), start.isoformat(), end.isoformat()), one=True)
    if not row or not row["total"]:
        return None, None
    return round(row["present"] * 100.0 / row["total"], 1), int(row["total"])


def leave_count(class_id, start, end):
    rows = db.q(
        "SELECT COUNT(*) AS n FROM dom_leave WHERE class_id=? AND approved=1 "
        "AND NOT (date_to < ? OR date_from > ?)",
        (str(class_id), start.isoformat(), end.isoformat()), one=True)
    return int(rows["n"]) if rows else 0


def dorm_latest(class_id):
    r = db.q("SELECT MAX(date) AS d FROM dom_dorm WHERE class_id=?", (str(class_id),), one=True)
    return r["d"] if r and r["d"] else None


def dorm_anomaly(class_id, day=None):
    d = day or dorm_latest(class_id)
    if not d:
        return None, None
    row = db.q(
        "SELECT SUM(CASE WHEN status IN ('unreturned','missing','late') THEN 1 ELSE 0 END) AS n "
        "FROM dom_dorm WHERE class_id=? AND date=?", (str(class_id), d), one=True)
    return (int(row["n"]) if row and row["n"] is not None else 0), d


def moral_delta(class_id, start, end):
    row = db.q(
        "SELECT SUM(points) AS p FROM dom_behavior WHERE class_id=? AND status='confirmed' "
        "AND event_date BETWEEN ? AND ?",
        (str(class_id), start.isoformat(), end.isoformat()), one=True)
    return (int(row["p"]) if row and row["p"] is not None else 0)


def attention_items(class_id, start, end):
    """例外才打扰：只把命中规则的少数学生列出（蓝/黄级信号）。"""
    days = _week_days(start, end)
    flagged = {}

    def add(sid, mark, action):
        it = flagged.setdefault(sid, {"student_id": sid, "name_masked": _mask(sid),
                                      "marks": [], "actions": []})
        if mark not in it["marks"]:
            it["marks"].append(mark)
        if action not in it["actions"]:
            it["actions"].append(action)

    # 规则 R1：连续 3 日无就餐记录（蓝）
    meal = db.q("SELECT student_id, date, meals FROM dom_meal WHERE class_id=? "
                "AND date BETWEEN ? AND ?", (str(class_id), days[0], days[-1]))
    by_student = {}
    for r in meal:
        by_student.setdefault(r["student_id"], []).append(r)
    for sid, rs in by_student.items():
        if len(rs) >= 3:
            rs.sort(key=lambda x: x["date"])
            gap = 0
            for r in rs:
                gap = gap + 1 if r["meals"] == 0 else 0
                if gap >= 3:
                    add(sid, "就餐规律中断", "核实就餐与生活情况")
                    break
    # 规则 R2：周请假 ≥2 次（蓝）
    for r in db.q("SELECT student_id, COUNT(*) AS n FROM dom_leave WHERE class_id=? AND approved=1 "
                  "AND NOT (date_to < ? OR date_from > ?) GROUP BY student_id",
                  (str(class_id), days[0], days[-1])):
        if r["n"] >= 2:
            add(r["student_id"], "请假频繁", "了解请假原因（不采集事由）")
    # 规则 R3：晚寝连续 3 晚异常（蓝）
    dorm = db.q("SELECT student_id, date, status FROM dom_dorm WHERE class_id=? "
                "AND status IN ('unreturned','missing') AND date BETWEEN ? AND ? "
                "ORDER BY student_id, date", (str(class_id), days[0], days[-1]))
    dmap = {}
    for r in dorm:
        dmap.setdefault(r["student_id"], []).append(r["date"])
    for sid, ds in dmap.items():
        if len(set(ds)) >= 3:
            add(sid, "晚寝连续异常", "核实归寝并联系生活老师")
    # 规则 R5：行为事件周 ≥2 起（橙级信号，仍只提示人工关注）
    for r in db.q("SELECT student_id, COUNT(*) AS n FROM dom_behavior WHERE class_id=? "
                  "AND status='confirmed' AND event_date BETWEEN ? AND ? GROUP BY student_id",
                  (str(class_id), days[0], days[-1])):
        if r["n"] >= 2:
            add(r["student_id"], "行为事件多发", "人工了解情况，不作定性")
    # 规则 R6：作业周提交率 <60%
    for r in db.q("SELECT student_id, SUM(submitted) AS s, COUNT(*) AS n FROM dom_homework "
                  "WHERE class_id=? AND date BETWEEN ? AND ? GROUP BY student_id",
                  (str(class_id), days[0], days[-1])):
        if r["n"] and r["s"] * 1.0 / r["n"] < 0.6:
            add(r["student_id"], "作业欠交", "与任课教师沟通补交")

    items = []
    for it in flagged.values():
        items.append({
            "student_id": it["student_id"], "name_masked": it["name_masked"],
            "mark": "、".join(it["marks"]), "action": "；".join(it["actions"]),
            "status": "待跟进",
        })
    items.sort(key=lambda x: x["student_id"])
    return items


def weekly_numbers(class_id, day=None):
    """周报 4 数字：全部来自数据域聚合；缺域返回 None（上层显示暂不可用）。"""
    start, end = _week_bounds(day)
    att, total = attendance_rate(class_id, start, end)
    anomaly, dorm_day = dorm_anomaly(class_id)
    items = attention_items(class_id, start, end) if has_data(class_id) else None
    if items is None:
        return None
    out = {
        "class_id": str(class_id),
        "week": "%s~%s" % (start.isoformat(), end.isoformat()),
        "attendance_rate": att,
        "attendance_note": ("考勤样本 %d 条（每生每日）" % total) if att is not None else None,
        "attention_count": len(items),
        "moral_delta": moral_delta(class_id, start, end),
        "moral_note": "仅计已人工确认的行为事件（双轨纪律：无感数据只做正向反馈）",
        "dorm_anomaly": anomaly,
        "dorm_note": ("查寝日期 %s（未就绪≠未归）" % dorm_day) if dorm_day else "暂不可用：当日查寝数据未生成",
        "leave_count": leave_count(class_id, start, end),
        "leave_note": None,
        "degraded": att is None or anomaly is None,
        "source": "校内数据域（SQLite）：考勤／晚寝／请假／行为事件／就餐／作业",
    }
    return out


def moral_summary(class_id, start=None, end=None, period=None, anchor=None):
    """班级与学生德育量化：仅已确认事件计分，名册内学生全部返回。

    优先使用显式 start/end；否则按 period + anchor 自动换算（默认本周）。
    anchor 为选定周期内的锚点日期（YYYY-MM-DD），缺省今天。
    最大范围放宽到 180 天（覆盖整学期），超出仍抛 ValueError。
    返回字典含 period / period_label（相对）/ period_title（具体）与可选学期列表。
    """
    label = "本周"
    if period and not start and not end:
        anchor_day = None
        if anchor:
            try:
                anchor_day = date.fromisoformat(str(anchor).strip())
            except ValueError:
                raise ValueError("锚点日期格式应为 YYYY-MM-DD")
        start, end, label = period_bounds(period, anchor_day)
    elif not start and not end:
        start, end = _week_bounds()
    elif not start or not end:
        raise ValueError("开始日期和结束日期必须同时提供")
    if isinstance(start, str):
        start = date.fromisoformat(start)
    if isinstance(end, str):
        end = date.fromisoformat(end)
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")
    days_span = (end - start).days
    if days_span > 180:
        raise ValueError("单次统计范围不能超过 181 天")
    cid = str(class_id)
    first, last = start.isoformat(), end.isoformat()
    confirmed = db.q(
        "SELECT polarity, category, SUM(points) AS p, COUNT(*) AS n FROM dom_behavior "
        "WHERE class_id=? AND status='confirmed' AND event_date BETWEEN ? AND ? "
        "GROUP BY polarity, category ORDER BY p DESC", (cid, first, last))
    events = db.q(
        "SELECT student_id,event_date,category,points FROM dom_behavior "
        "WHERE class_id=? AND status='confirmed' AND event_date BETWEEN ? AND ? "
        "ORDER BY event_date,student_id", (cid, first, last))
    pending = db.q(
        "SELECT * FROM dom_behavior WHERE class_id=? AND status='pending' "
        "ORDER BY ts DESC LIMIT 20", (cid,))
    roster_rows = db.q(
        "SELECT student_id,name FROM students WHERE class_id=? ORDER BY student_id", (cid,))
    students = {}
    for r in roster_rows:
        students[r["student_id"]] = {
            "student_id": r["student_id"], "name": r["name"],
            "positive": 0, "negative": 0, "delta": 0,
            "total_score": 100, "event_count": 0,
        }
    daily = {day: {"date": day, "positive": 0, "negative": 0, "net": 0, "count": 0}
             for day in _week_days(start, end)}
    categories = {"positive": {}, "negative": {}}
    for r in events:
        sid, points = r["student_id"], int(r["points"] or 0)
        day = daily[r["event_date"]]
        day["net"] += points
        day["count"] += 1
        kind = "positive" if points >= 0 else "negative"
        day[kind] += points
        cat = categories[kind].setdefault(r["category"], {
            "category": r["category"], "points": 0, "count": 0})
        cat["points"] += points
        cat["count"] += 1
        if sid in students:
            stu = students[sid]
            stu[kind] += points
            stu["delta"] += points
            stu["total_score"] += points
            stu["event_count"] += 1
    delta = sum(int(r["p"] or 0) for r in confirmed)
    positive_points = sum(d["positive"] for d in daily.values())
    negative_points = sum(d["negative"] for d in daily.values())
    # 周期归一：显式 start/end 传进来时我们不知道 period，按 span 反推标签
    if not period:
        span = days_span
        if span == 0: label = "当日"; period = "day"
        elif span <= 7: label = "本周"; period = "week"
        elif span <= 31: label = "本月"; period = "month"
        else: label = "本学期"; period = "term"
    return {
        "class_id": cid,
        "week": "%s~%s" % (first, last),
        "start": first, "end": last,
        "period": period, "period_label": label,
        "period_title": _period_title(period, start, end),
        "terms": term_options(),
        "base_score": 100,
        "size": len(students),
        "week_delta": delta,
        "positive_points": positive_points,
        "negative_points": negative_points,
        "confirmed_count": sum(d["count"] for d in daily.values()),
        "daily": list(daily.values()),
        "positive_categories": sorted(categories["positive"].values(),
                                      key=lambda x: (-x["points"], x["category"])),
        "negative_categories": sorted(categories["negative"].values(),
                                      key=lambda x: (x["points"], x["category"])),
        "students": list(students.values()),
        "confirmed": [{"polarity": r["polarity"], "category": r["category"],
                       "points": int(r["p"] or 0), "count": int(r["n"])} for r in confirmed],
        "pending": [{"id": r["id"], "student_masked": _mask(r["student_id"]),
                     "polarity": r["polarity"], "category": r["category"],
                     "points": r["points"], "fact": r["fact"], "ts": r["ts"]}
                    for r in pending],
        "rules": "基准 100 分/学期；正向事件 +1~+5，负向事件仅人工确认后 −2~−10；"
                 "无感数据只做正向反馈，监控/门禁/心理数据不进德育分；不公开学生排名",
        "source": "校内数据域（SQLite）：行为事件（政教处登记 → 班主任确认）",
    }


# ---------------------------------------------------------------- 写入
def add_behavior(class_id, student_id, polarity, category, points, fact="", source="政教处事件登记"):
    eid = _uid("be_")
    db.exec_(
        "INSERT INTO dom_behavior(id,ts,class_id,student_id,event_date,polarity,category,"
        "points,status,fact,source) VALUES(?,?,?,?,?,?,?,?, 'pending', ?,?)",
        (eid, db.now(), str(class_id), str(student_id), date.today().isoformat(),
         polarity, category, int(points), fact[:200], source))
    return eid


def confirm_behavior(ctx, event_id, decision):
    row = db.q("SELECT * FROM dom_behavior WHERE id=?", (event_id,), one=True)
    if not row:
        return {"ok": False, "error": "未找到该行为事件"}
    if row["status"] != "pending":
        return {"ok": False, "error": "该事件已处理"}
    status = "confirmed" if decision == "confirm" else "void"
    db.exec_("UPDATE dom_behavior SET status=?, confirmed_by=?, confirmed_at=? WHERE id=?",
             (status, (ctx or {}).get("user_id", "-"), db.now(), event_id))
    db.audit(ctx, "moral.confirm", "ok", event_id,
             "人审点：行为事件确认后计入德育量化" if decision == "confirm" else "事件作废")
    return {"ok": True, "status": status,
            "reply": "已确认计入德育量化" if decision == "confirm" else "已作废，不计分"}


# ---------------------------------------------------------------- 数据域接入（system-to-system）
def _ts(r):
    return r.get("ts") or db.now()


INGEST_SQL = {
    "attendance": (
        "INSERT OR REPLACE INTO dom_attendance"
        "(ts,class_id,date,student_id,session_no,status,source) VALUES(?,?,?,?,?,?,?)",
        lambda cid, r: (_ts(r), cid, r["date"], r["student_id"],
                        int(r.get("session_no", 0)), r.get("status", "present"),
                        r.get("source", "考勤终端"))),
    "leave": (
        "INSERT OR REPLACE INTO dom_leave"
        "(ts,class_id,student_id,date_from,date_to,leave_type,approved,source) "
        "VALUES(?,?,?,?,?,?,?,?)",
        lambda cid, r: (_ts(r), cid, r["student_id"], r["date_from"], r["date_to"],
                        r.get("leave_type", "事假"), int(r.get("approved", 1)),
                        r.get("source", "电子请假单"))),
    "dorm": (
        "INSERT OR REPLACE INTO dom_dorm"
        "(ts,class_id,date,student_id,status,source) VALUES(?,?,?,?,?,?)",
        lambda cid, r: (_ts(r), cid, r["date"], r["student_id"],
                        r.get("status", "returned"), r.get("source", "寝管点验"))),
    "meal": (
        "INSERT OR REPLACE INTO dom_meal"
        "(ts,class_id,date,student_id,meals,source) VALUES(?,?,?,?,?,?)",
        lambda cid, r: (_ts(r), cid, r["date"], r["student_id"],
                        int(r.get("meals", 0)), r.get("source", "食堂卡"))),
    "library": (
        "INSERT INTO dom_library(ts,class_id,date,student_id,action,source) "
        "VALUES(?,?,?,?,?,?)",
        lambda cid, r: (_ts(r), cid, r["date"], r["student_id"],
                        r.get("action", "borrow"), r.get("source", "图书馆系统"))),
    "clinic": (
        "INSERT INTO dom_clinic(ts,class_id,date,student_id,reason_class,source) "
        "VALUES(?,?,?,?,?,?)",
        lambda cid, r: (_ts(r), cid, r["date"], r["student_id"],
                        r.get("reason_class", "其他"), r.get("source", "校医室台账"))),
    "activity": (
        "INSERT INTO dom_activity(ts,class_id,date,student_id,activity,source) "
        "VALUES(?,?,?,?,?,?)",
        lambda cid, r: (_ts(r), cid, r["date"], r["student_id"],
                        r.get("activity", "活动"), r.get("source", "二维码签到"))),
    "participation": (
        "INSERT OR REPLACE INTO dom_participation"
        "(ts,class_id,date,student_id,subject,events,source) VALUES(?,?,?,?,?,?,?)",
        lambda cid, r: (_ts(r), cid, r["date"], r["student_id"],
                        r.get("subject", ""), int(r.get("events", 0)),
                        r.get("source", "课堂互动"))),
    "homework": (
        "INSERT OR REPLACE INTO dom_homework"
        "(ts,class_id,date,student_id,subject,submitted,corrected,source) "
        "VALUES(?,?,?,?,?,?,?,?)",
        lambda cid, r: (_ts(r), cid, r["date"], r["student_id"], r.get("subject", ""),
                        int(r.get("submitted", 1)), int(r.get("corrected", 0)),
                        r.get("source", "AI批改"))),
    "scores": (
        "INSERT OR REPLACE INTO dom_scores"
        "(ts,class_id,exam,student_id,band,trend,source) VALUES(?,?,?,?,?,?,?)",
        lambda cid, r: (_ts(r), cid, r["exam"], r["student_id"], r["band"],
                        r.get("trend", "持平"), r.get("source", "教务系统"))),
}


def ingest(domain, body):
    """批量写入一个数据域；返回实际提交条数（幂等表按唯一键覆盖）。"""
    sql, make = INGEST_SQL[domain]
    cid = str(body.get("class_id") or "2607")
    rows = body.get("records") or []
    stmts = [(sql, make(cid, r)) for r in rows]
    if stmts:
        db.exec_many(stmts)
    return len(stmts)


# ---------------------------------------------------------------- 演示数据（可整体删除）
def seed_demo(class_id="2607", size=66):
    """生成一组与试点班口径一致的演示数据，仅用于校内试用展示。"""
    rnd = random.Random(20261119)
    cid = str(class_id)
    students = ["S%03d" % i for i in range(1, size + 1)]
    start, _ = _week_bounds()
    days = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    flags = students[:6]          # 6 名需关注学生（与试点班口径一致）
    rows_att, rows_dorm, rows_meal, rows_hw = [], [], [], []
    now = db.now()
    absent_plan = {s: set() for s in students}
    for i, s in enumerate(students):
        if i % 11 == 3:
            absent_plan[s].add(days[2])
        if i % 13 == 5:
            absent_plan[s].add(days[4])
    for s in students:
        for d in days:
            st = "absent" if d in absent_plan[s] else "present"
            rows_att.append((now, cid, d, s, 0, st, "考勤终端"))
            if s in flags:
                dorm_status = "unreturned" if d in days[3:] else "returned"
            elif rnd.random() < 0.03:
                dorm_status = "late"
            else:
                dorm_status = "returned"
            rows_dorm.append((now, cid, d, s, dorm_status, "寝管点验"))
            meals = 3 if s not in flags else 2
            rows_meal.append((now, cid, d, s, meals, "食堂卡"))
            sub = 0 if (s in flags and d == days[5]) else 1
            rows_hw.append((now, cid, d, s, "语文", sub, 1 if sub else 0, "AI批改"))
    stmts = []
    for r in rows_att:
        stmts.append(("INSERT OR IGNORE INTO dom_attendance"
                      "(ts,class_id,date,student_id,session_no,status,source) "
                      "VALUES(?,?,?,?,?,?,?)", r))
    for r in rows_dorm:
        stmts.append(("INSERT OR IGNORE INTO dom_dorm"
                      "(ts,class_id,date,student_id,status,source) VALUES(?,?,?,?,?,?)", r))
    for r in rows_meal:
        stmts.append(("INSERT OR IGNORE INTO dom_meal"
                      "(ts,class_id,date,student_id,meals,source) VALUES(?,?,?,?,?,?)", r))
    for r in rows_hw:
        stmts.append(("INSERT OR IGNORE INTO dom_homework"
                      "(ts,class_id,date,student_id,subject,submitted,corrected,source) "
                      "VALUES(?,?,?,?,?,?,?,?)", r))
    # 请假：2 条（与晚寝口径一致，不再冲突）
    stmts.append(("INSERT OR IGNORE INTO dom_leave"
                  "(ts,class_id,student_id,date_from,date_to,leave_type,approved,source) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (now, cid, "S002", days[1], days[1], "病假", 1, "电子请假单")))
    stmts.append(("INSERT OR IGNORE INTO dom_leave"
                  "(ts,class_id,student_id,date_from,date_to,leave_type,approved,source) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (now, cid, "S017", days[2], days[3], "事假", 1, "电子请假单")))
    # 行为事件：8 条已确认正向 +3/条，2 条待确认负向
    cats = ["志愿服务", "社团活动", "岗位服务", "竞赛获奖", "助人行为"]
    for i, s in enumerate(students[10:18]):
        stmts.append(("INSERT INTO dom_behavior"
                      "(id,ts,class_id,student_id,event_date,polarity,category,points,status,"
                      "fact,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (_uid("be_"), now, cid, s, days[i % 6], "positive",
                       cats[i % len(cats)], 3, "confirmed", "政教处登记（演示）", "政教处事件登记")))
    for s, cat, pts in ((students[20], "仪容仪表", -2), (students[31], "课堂纪律", -3)):
        stmts.append(("INSERT INTO dom_behavior"
                      "(id,ts,class_id,student_id,event_date,polarity,category,points,status,"
                      "fact,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (_uid("be_"), now, cid, s, days[-1], "negative", cat, pts,
                       "pending", "待班主任确认，不自动扣分", "政教处事件登记")))
    # 活动签到 / 图书 / 校医 / 课堂参与
    for s in students[:20]:
        stmts.append(("INSERT INTO dom_activity(ts,class_id,date,student_id,activity,source) "
                      "VALUES(?,?,?,?,?,?)", (now, cid, days[2], s, "志愿服务", "二维码签到")))
    for s in students[20:30]:
        stmts.append(("INSERT INTO dom_library(ts,class_id,date,student_id,action,source) "
                      "VALUES(?,?,?,?,?,?)", (now, cid, days[1], s, "borrow", "图书馆系统")))
    for s in students[30:33]:
        stmts.append(("INSERT INTO dom_clinic(ts,class_id,date,student_id,reason_class,source) "
                      "VALUES(?,?,?,?,?,?)", (now, cid, days[3], s, "普通就诊", "校医室台账")))
    db.exec_many(stmts)


def domains_status(class_id="2607"):
    start, end = _week_bounds()
    return {
        "class_id": str(class_id),
        "domains": DOMAINS,
        "connected": [d["id"] for d in DOMAINS if d["status"].startswith("已接入")
                      or d["status"] in ("已有", "试点已有")],
        "isolated": [13],
        "week": "%s~%s" % (start.isoformat(), end.isoformat()),
        "rule": "采集即服务：每个数据域只有一个采集入口、一个权威来源；只采结构与规律，不采内容细节",
    }
