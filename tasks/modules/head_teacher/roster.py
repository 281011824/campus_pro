# -*- coding: utf-8 -*-
"""班级学生名册与 Excel 导入导出（学生 / 教师 / 成绩）。

- 名册独立于行为数据，学号与数据域保持一致（S001…）。
- 导出统一为 .xlsx，首行表头，带列宽与表头底色。
- 导入按主键 upsert，返回新增/更新/跳过明细，不因单行错误中断整批。
"""

import io
import random
import sqlite3

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from tasks.domain.identity import accounts
from tasks.shared import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  name TEXT NOT NULL,
  gender TEXT,
  dorm TEXT,
  address TEXT,
  phone TEXT,
  guardian_phone TEXT,
  major TEXT,
  grade TEXT,
  boarding_type TEXT,
  guardian_name TEXT,
  guardian_relation TEXT,
  bed_no TEXT,
  student_no TEXT,
  status TEXT DEFAULT '在读',
  updated_at TEXT,
  PRIMARY KEY (class_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id);
CREATE TABLE IF NOT EXISTS student_records (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  day TEXT,
  title TEXT,
  detail TEXT,
  created_by TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_stu ON student_records(class_id, student_id, kind);
CREATE TABLE IF NOT EXISTS student_transfers (
  id TEXT PRIMARY KEY,
  class_id TEXT,
  student_id TEXT,
  from_class TEXT,
  to_class TEXT,
  operator TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_student_transfers_stu
  ON student_transfers(student_id, created_at);
CREATE TABLE IF NOT EXISTS dorm_changes (
  id TEXT PRIMARY KEY,
  class_id TEXT,
  student_id TEXT,
  from_dorm TEXT,
  from_bed TEXT,
  to_dorm TEXT,
  to_bed TEXT,
  operator TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dorm_changes_stu
  ON dorm_changes(student_id, created_at);
"""

SURNAMES = ["王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
            "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗"]
GIVEN = ["子涵", "雨欣", "浩然", "梓萱", "宇航", "思远", "嘉怡", "俊杰", "欣怡", "天佑",
         "诗涵", "明轩", "梦琪", "子豪", "雨桐", "博文", "静怡", "泽宇", "佳琪", "一鸣"]

HEAD_FILL = PatternFill("solid", fgColor="4A0C0C")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=11, name="微软雅黑")
BODY_FONT = Font(size=10.5, name="微软雅黑")


def init(seed_class="2607", size=66):
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
    _migrate_students()
    ensure_student_no_index()
    if not db.q("SELECT 1 FROM students WHERE class_id=? LIMIT 1", (str(seed_class),), one=True):
        seed(seed_class, size)


def _migrate_students():
    """兼容已有库：补加学生信息扩展列（幂等）。"""
    c = db.connect()
    try:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(students)").fetchall()}
        for name, ddl in (("dorm", "TEXT"), ("address", "TEXT"), ("phone", "TEXT"),
                          ("student_no", "TEXT"), ("major", "TEXT"), ("grade", "TEXT"),
                          ("boarding_type", "TEXT"), ("guardian_name", "TEXT"),
                          ("guardian_relation", "TEXT"), ("bed_no", "TEXT")):
            if name not in cols:
                c.execute("ALTER TABLE students ADD COLUMN %s %s" % (name, ddl))
        c.commit()
    finally:
        c.close()


def ensure_student_no_index():
    """为正式学号 student_no 建唯一索引；历史重复时跳过并返回提示，不抛异常。"""
    try:
        dup = db.q("SELECT student_no FROM students WHERE student_no IS NOT NULL AND student_no<>'' "
                   "GROUP BY student_no HAVING COUNT(*)>1 LIMIT 1", one=True)
    except Exception as exc:
        return {"ready": False, "message": "学号索引检查失败：%s" % exc}
    if dup:
        return {"ready": False,
                "message": "历史数据存在重复学号（如 %s），暂未建立唯一索引，请先修正"
                           % dup["student_no"]}
    try:
        db.exec_("CREATE UNIQUE INDEX IF NOT EXISTS idx_students_student_no "
                 "ON students(student_no) WHERE student_no IS NOT NULL AND student_no<>''")
    except Exception as exc:
        return {"ready": False, "message": "学号唯一索引创建失败：%s" % exc}
    return {"ready": True, "message": ""}


def seed(class_id="2607", size=66):
    rnd = random.Random(2607)
    rows = []
    for i in range(size):
        name = SURNAMES[i % len(SURNAMES)] + GIVEN[(i // len(SURNAMES) + i) % len(GIVEN)]
        rows.append((str(class_id), "S%03d" % (i + 1), name,
                     "男" if i % 2 == 0 else "女",
                     "138%08d" % (10000000 + i * 137),
                     "在读", db.now()))
    db.exec_many([("INSERT OR REPLACE INTO students"
                   "(class_id,student_id,name,gender,guardian_phone,status,updated_at) "
                   "VALUES(?,?,?,?,?,?,?)", r) for r in rows])


def list_students(class_id, keyword=""):
    sql = "SELECT * FROM students WHERE class_id=?"
    args = [str(class_id)]
    if keyword:
        sql += " AND (name LIKE ? OR student_id LIKE ?)"
        args += ["%%%s%%" % keyword, "%%%s%%" % keyword]
    sql += " ORDER BY student_id"
    return [dict(r) for r in db.q(sql, tuple(args))]


# ---------------------------------------------------------------- 寝室床位校验
def _bed_key(value):
    """床位号归一：'2号床' / '02' / '2' 视为同一床位。"""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return str(int(digits)) if digits else str(value or "").strip()


def find_dorm(dorm):
    """按房号或 楼栋+房号 匹配 dorms 字典表；表或记录缺失时返回 None。"""
    name = str(dorm or "").strip()
    if not name:
        return None
    try:
        rec = db.q("SELECT * FROM dorms WHERE room_no=? LIMIT 1", (name,), one=True)
        if rec:
            return dict(rec)
        rec = db.q("SELECT * FROM dorms "
                   "WHERE building||room_no=? OR building||'栋'||room_no=? LIMIT 1",
                   (name, name), one=True)
        return dict(rec) if rec else None
    except Exception:
        # dorms 表尚未建表（如旧库/单测）时只做床位唯一校验
        return None


def validate_dorm_bed(class_id, student_id, dorm, bed_no, gender, exclude_student=True,
                      ignore_student_ids=None):
    """校验寝室床位，返回 True；不合法抛 ValueError。

    - 寝室号与床位号都非空时，全校范围内同一寝室同一床位只能住一人（不限班级）；
    - 寝室号能匹配 dorms 字典表时，校验已住人数不超容量、学生性别与寝室一致；
    - 匹配不到寝室记录时只做床位唯一校验。
    exclude_student=True 时把学生本人排除在占用统计外（编辑自身信息）；
    ignore_student_ids 用于寝室表互换，忽略同一次换出的学生。
    """
    dorm = str(dorm or "").strip()
    bed_no = str(bed_no or "").strip()
    if not dorm:
        return True
    cid, sid = str(class_id or ""), str(student_id or "")
    ignore = {str(x) for x in (ignore_student_ids or ())}

    def skip(row):
        if exclude_student and str(row["class_id"]) == cid and str(row["student_id"]) == sid:
            return True
        return str(row["student_id"]) in ignore

    def rows_of(dorm_value):
        return db.q("SELECT class_id,student_id,name,dorm,bed_no FROM students WHERE dorm=?",
                    (dorm_value,))

    # 1. 全校床号唯一
    if bed_no:
        key = _bed_key(bed_no)
        for row in rows_of(dorm):
            if skip(row) or not str(row.get("bed_no") or "").strip():
                continue
            if _bed_key(row["bed_no"]) == key:
                raise ValueError("床位 %s-%s 已被 %s（%s/%s）占用"
                                 % (dorm, bed_no, row["name"], row["class_id"], row["name"]))

    rec = find_dorm(dorm)
    if not rec:
        return True
    room_no = str(rec.get("room_no") or dorm)
    # 2. 寝室容量（与 dorms.list_for_assignment 同口径：按 students.dorm=room_no 统计）
    occupied = len([row for row in rows_of(room_no) if not skip(row)])
    try:
        capacity = int(rec.get("capacity") or 0)
    except (TypeError, ValueError):
        capacity = 0
    if capacity and occupied >= capacity:
        raise ValueError("寝室已满：%s 已住 %d/%d 人" % (dorm, occupied, capacity))
    # 3. 男/女寝性别（寝室未标注性别时不校验）
    dorm_gender = str(rec.get("gender") or "").strip()
    stu_gender = str(gender or "").strip()
    if dorm_gender and stu_gender and dorm_gender != stu_gender:
        raise ValueError("性别不符：%s 为%s生寝室"
                         % (dorm, "男" if dorm_gender == "男" else "女"))
    return True


def record_dorm_change(class_id, student_id, from_dorm, from_bed, to_dorm, to_bed, operator=""):
    """写一条调宿台账（真实发生寝室或床位变化时调用）。"""
    db.exec_("INSERT INTO dorm_changes(id,class_id,student_id,from_dorm,from_bed,"
             "to_dorm,to_bed,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
             (db.uid("dc_"), str(class_id), str(student_id), str(from_dorm or ""),
              str(from_bed or ""), str(to_dorm or ""), str(to_bed or ""),
              str(operator or ""), db.now()))


def set_dorm_bed(class_id, student_id, dorm, bed_no, operator=""):
    """写入学生寝室/床位并记录调宿台账；返回是否发生实际变化。"""
    student = get_student(class_id, student_id)
    if not student:
        raise ValueError("学生不存在")
    from_dorm = str(student.get("dorm") or "")
    from_bed = str(student.get("bed_no") or "")
    to_dorm = str(dorm or "").strip()
    to_bed = str(bed_no or "").strip()
    if from_dorm == to_dorm and from_bed == to_bed:
        return False
    db.exec_("UPDATE students SET dorm=?,bed_no=?,updated_at=? "
             "WHERE class_id=? AND student_id=?",
             (to_dorm, to_bed, db.now(), str(class_id), str(student_id)))
    record_dorm_change(class_id, student_id, from_dorm, from_bed, to_dorm, to_bed, operator)
    return True


def _workbook(title, headers, rows, widths, notes=None):
    """序列化为 xlsx；notes 为表头前的说明行（如筛选条件、统计口径）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = title
    notes = list(notes or [])
    for note in notes:
        ws.append([note])
    header_row = len(notes) + 1
    ws.append(headers)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for cell in ws[header_row]:
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for r in rows:
        ws.append(list(r))
    for row in ws.iter_rows(min_row=header_row + 1):
        for cell in row:
            cell.font = BODY_FONT
    ws.freeze_panes = "A%d" % (header_row + 1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _read_rows(data):
    wb = load_workbook(io.BytesIO(data), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [str(x).strip() if x is not None else "" for x in rows[0]]
    body = [r for r in rows[1:] if any(c is not None and str(c).strip() for c in r)]
    return headers, body


def _pick(row, idx, *names):
    """按表头别名取单元格文本；缺列或空值返回空串。"""
    for name in names:
        i = idx.get(name, -1)
        if i >= 0:
            text = _cell_text(row, i)
            if text:
                return text
    return ""


def _require_headers(idx, required):
    missing = [h for h in required if h not in idx]
    if missing:
        raise ValueError("缺少必填列：%s" % "、".join(missing))


# ---------------------------------------------------------------- 学生
STU_HEADERS = ["学号", "姓名", "性别", "专业", "年级", "宿舍号", "住宿类型",
               "家长姓名", "家长关系", "家长电话", "床位号", "家庭住址", "学生电话", "状态"]
STU_WIDTHS = [12, 10, 8, 16, 8, 10, 10, 10, 10, 14, 8, 24, 14, 8]
# 管理台跨班导入导出：多一列“班级”
ADMIN_STU_HEADERS = ["学号", "姓名", "性别", "专业", "年级", "班级", "宿舍号", "住宿类型",
                     "家长姓名", "家长关系", "家长电话", "床位号", "家庭住址", "状态", "学生电话"]
ADMIN_STU_WIDTHS = [12, 10, 8, 16, 8, 10, 10, 10, 10, 10, 14, 8, 24, 8, 14]


def export_students(class_id):
    rows = [(s["student_id"], s["name"], s.get("gender"), s.get("major"), s.get("grade"),
             s.get("dorm"), s.get("boarding_type"), s.get("guardian_name"),
             s.get("guardian_relation"), s.get("guardian_phone"), s.get("bed_no"),
             s.get("address"), s.get("phone"), s["status"])
            for s in list_students(class_id)]
    return _workbook("学生名册", STU_HEADERS, rows, STU_WIDTHS)


def import_students(data, class_id):
    headers, body = _read_rows(data)
    idx = {h: i for i, h in enumerate(headers)}
    _require_headers(idx, ("姓名", "性别"))
    added = updated = skipped = 0
    temp_used = set()
    for r in body:
        name = _pick(r, idx, "姓名")
        gender = _pick(r, idx, "性别")
        if not name or not gender:
            skipped += 1
            continue
        sid = _pick(r, idx, "学号")
        old = get_student(class_id, sid) if sid else db.q(
            "SELECT * FROM students WHERE class_id=? AND name=? LIMIT 1",
            (str(class_id), name), one=True)
        if not sid:
            sid = old["student_id"] if old else _temp_student_id(str(class_id), temp_used)
        db.exec_(
            "INSERT INTO students(class_id,student_id,name,gender,major,grade,dorm,"
            "boarding_type,guardian_name,guardian_relation,guardian_phone,bed_no,"
            "address,phone,status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(class_id,student_id) DO UPDATE SET "
            "name=excluded.name,gender=excluded.gender,major=excluded.major,"
            "grade=excluded.grade,dorm=excluded.dorm,boarding_type=excluded.boarding_type,"
            "guardian_name=excluded.guardian_name,guardian_relation=excluded.guardian_relation,"
            "guardian_phone=excluded.guardian_phone,bed_no=excluded.bed_no,"
            "address=excluded.address,phone=excluded.phone,status=excluded.status,"
            "updated_at=excluded.updated_at",
            (str(class_id), sid, name, gender,
             _pick(r, idx, "专业"), _pick(r, idx, "年级"),
             _pick(r, idx, "宿舍号", "寝室"), _pick(r, idx, "住宿类型"),
             _pick(r, idx, "家长姓名", "监护人姓名"),
             _pick(r, idx, "家长关系", "监护人关系"),
             _pick(r, idx, "家长电话", "监护人电话"),
             _pick(r, idx, "床位号", "床位"),
             _pick(r, idx, "家庭住址", "住址"),
             _pick(r, idx, "学生电话", "电话"),
             _pick(r, idx, "状态") or "在读", db.now()))
        if old:
            updated += 1
        else:
            added += 1
    return {"added": added, "updated": updated, "skipped": skipped, "total": len(body)}


# ---------------------------------------------------------------- 教师
TEA_HEADERS = ["登录账号", "姓名", "部门", "职务", "类别", "状态", "企业微信userid", "初始密码"]
TEA_WIDTHS = [14, 10, 18, 16, 12, 8, 18, 14]


def export_teachers():
    rows = db.q("SELECT userid,name,dept,post_name,category,status,wecom_userid "
                "FROM school_accounts ORDER BY userid")
    return _workbook("教师账号", TEA_HEADERS,
                     [(r["userid"], r["name"], r["dept"], r["post_name"],
                       r["category"], r["status"], r["wecom_userid"], "") for r in rows],
                     TEA_WIDTHS)


def import_teachers(data):
    accounts.init()
    headers, body = _read_rows(data)
    idx = {h: i for i, h in enumerate(headers)}
    if "登录账号" not in idx or "姓名" not in idx:
        raise ValueError("缺少必填列：登录账号、姓名")
    added = updated = skipped = 0
    for r in body:
        uid = str(r[idx["登录账号"]]).strip() if r[idx["登录账号"]] else ""
        name = str(r[idx["姓名"]]).strip() if r[idx["姓名"]] else ""
        if not uid or not name:
            skipped += 1
            continue
        pwd = ""
        if "初始密码" in idx and r[idx["初始密码"]]:
            pwd = str(r[idx["初始密码"]])
        old = accounts.get(uid)
        if old:
            digest = accounts.sha256_hex(pwd) if pwd else old["password_sha256"]
            updated += 1
        else:
            if not pwd:
                skipped += 1
                continue
            digest = accounts.sha256_hex(pwd)
            added += 1
        accounts.import_records([{
            "userid": uid, "name": name,
            "password_sha256": digest,
            "wecom_userid": str(r[idx.get("企业微信userid", -1)] or "") if "企业微信userid" in idx else "",
            "dept": str(r[idx.get("部门", -1)] or "") if "部门" in idx else "",
            "post_name": str(r[idx.get("职务", -1)] or "") if "职务" in idx else "",
            "category": str(r[idx.get("类别", -1)] or "") if "类别" in idx else "",
            "status": str(r[idx.get("状态", -1)] or "本校") if "状态" in idx else "本校",
        }])
    return {"added": added, "updated": updated, "skipped": skipped, "total": len(body)}


# ---------------------------------------------------------------- 成绩
SCORE_HEADERS = ["学号", "考试", "等第", "趋势"]
SCORE_WIDTHS = [12, 20, 10, 10]


def export_scores(class_id):
    rows = db.q("SELECT student_id,exam,band,trend FROM dom_scores WHERE class_id=? "
                "ORDER BY exam,student_id", (str(class_id),))
    return _workbook("成绩", SCORE_HEADERS,
                     [(r["student_id"], r["exam"], r["band"], r["trend"]) for r in rows],
                     SCORE_WIDTHS)


def import_scores(data, class_id):
    headers, body = _read_rows(data)
    idx = {h: i for i, h in enumerate(headers)}
    if "学号" not in idx or "考试" not in idx or "等第" not in idx:
        raise ValueError("缺少必填列：学号、考试、等第")
    added = updated = skipped = 0
    for r in body:
        sid = str(r[idx["学号"]]).strip() if r[idx["学号"]] else ""
        exam = str(r[idx["考试"]]).strip() if r[idx["考试"]] else ""
        band = str(r[idx["等第"]]).strip() if r[idx["等第"]] else ""
        if not sid or not exam or not band:
            skipped += 1
            continue
        exists = db.q("SELECT 1 FROM dom_scores WHERE class_id=? AND exam=? AND student_id=?",
                      (str(class_id), exam, sid), one=True)
        db.exec_(
            "INSERT INTO dom_scores(ts,class_id,exam,student_id,band,trend,source) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(class_id,exam,student_id) DO UPDATE SET "
            "band=excluded.band,trend=excluded.trend,ts=excluded.ts",
            (db.now(), str(class_id), exam, sid, band,
             str(r[idx.get("趋势", -1)] or "持平") if "趋势" in idx else "持平", "成绩导入"))
        if exists:
            updated += 1
        else:
            added += 1
    return {"added": added, "updated": updated, "skipped": skipped, "total": len(body)}


def score_summary(class_id, exam=None):
    row = db.q("SELECT exam FROM dom_scores WHERE class_id=? ORDER BY ts DESC LIMIT 1",
               (str(class_id),), one=True) if not exam else {"exam": exam}
    if not row:
        return None
    exam = row["exam"]
    dist = {r["band"]: r["n"] for r in db.q(
        "SELECT band,COUNT(*) AS n FROM dom_scores WHERE class_id=? AND exam=? GROUP BY band",
        (str(class_id), exam))}
    trend = {r["trend"]: r["n"] for r in db.q(
        "SELECT trend,COUNT(*) AS n FROM dom_scores WHERE class_id=? AND exam=? GROUP BY trend",
        (str(class_id), exam))}
    return {"exam": exam, "distribution": dist, "trend": trend,
            "total": sum(dist.values())}


# ---------------------------------------------------------------- 成长档案记录
RECORD_KINDS = ("特长", "兴趣", "奖惩", "家访")


def add_record(class_id, student_id, kind, title, detail="", day="", created_by=""):
    if kind not in RECORD_KINDS:
        raise ValueError("记录类型不合法")
    rid = db.uid("sr_")
    db.exec_("INSERT INTO student_records(id,class_id,student_id,kind,day,title,detail,"
             "created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
             (rid, str(class_id), str(student_id), kind, day or "",
              str(title or ""), str(detail or ""), str(created_by or ""), db.now()))
    return {"id": rid}


def list_records(class_id, student_id):
    rows = db.q("SELECT * FROM student_records WHERE class_id=? AND student_id=? "
                "ORDER BY kind, day DESC, created_at DESC", (str(class_id), str(student_id)))
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 演示数据
SPECIALTIES = ["篮球", "书法", "声乐", "数控车削", "电子装配", "舞蹈", "绘画", "田径",
               "计算机维修", "烹饪", "礼仪", "摄影"]
INTERESTS = ["阅读", "篮球", "动漫设计", "音乐", "摄影", "编程", "书法", "羽毛球",
             "手工制作", "志愿服务", "短视频剪辑", "足球"]
AWARDS = ["校级三好学生", "技能竞赛三等奖", "文明学生", "优秀班干部", "进步之星"]
VISIT_WAYS = ["电话沟通", "入户家访", "校内面谈"]


def seed_scores(class_id="2607", exam="2026 秋季期中"):
    students = list_students(class_id)
    if not students:
        return 0
    if db.q("SELECT 1 FROM dom_scores WHERE class_id=? AND exam=? LIMIT 1",
            (str(class_id), exam), one=True):
        return 0
    bands = ["A"] * 8 + ["B"] * 22 + ["C"] * 26 + ["D"] * 10
    trends = ["上升", "持平", "下降"]
    rows = []
    for i, s in enumerate(students):
        band = bands[i % len(bands)]
        trend = trends[i % 3]
        rows.append((db.now(), str(class_id), exam, s["student_id"], band, trend, "演示数据"))
    db.exec_many([("INSERT OR REPLACE INTO dom_scores"
                   "(ts,class_id,exam,student_id,band,trend,source) VALUES(?,?,?,?,?,?,?)", r)
                  for r in rows])
    return len(rows)


def seed_records(class_id="2607"):
    students = list_students(class_id)
    if not students or db.q("SELECT 1 FROM student_records WHERE class_id=? LIMIT 1",
                            (str(class_id),), one=True):
        return 0
    rows = []
    for i, s in enumerate(students):
        sid = s["student_id"]
        rows.append((db.uid("sr_"), str(class_id), sid, "特长", "",
                     SPECIALTIES[i % len(SPECIALTIES)], "校级社团在册", "演示数据", db.now()))
        rows.append((db.uid("sr_"), str(class_id), sid, "兴趣", "",
                     INTERESTS[(i * 3) % len(INTERESTS)], "兴趣小组参与", "演示数据", db.now()))
        if i % 7 == 0:
            rows.append((db.uid("sr_"), str(class_id), sid, "奖惩", "2026-10-18",
                         "校级三好学生", "2025—2026 学年评选", "演示数据", db.now()))
        if i % 9 == 0:
            rows.append((db.uid("sr_"), str(class_id), sid, "家访", "2026-10-25",
                         VISIT_WAYS[i % len(VISIT_WAYS)], "了解近期家庭与作息情况", "演示数据", db.now()))
    db.exec_many([("INSERT OR REPLACE INTO student_records"
                   "(id,class_id,student_id,kind,day,title,detail,created_by,created_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?)", r) for r in rows])
    return len(rows)


def seed_demo(class_id="2607"):
    return {"scores": seed_scores(class_id), "records": seed_records(class_id)}

def template(kind):
    if kind == "students":
        return _workbook("学生名册", STU_HEADERS,
                         [("S001", "示例学生", "男", "电子商务", "2026", "1401", "住校",
                           "张三", "父亲", "13800000000", "1号床", "示例地址",
                           "13900000000", "在读")], STU_WIDTHS)
    if kind == "admin_students":
        return _workbook("学生名册", ADMIN_STU_HEADERS,
                         [("S001", "示例学生", "男", "电子商务", "2026", "2607", "1401", "住校",
                           "张三", "父亲", "13800000000", "1号床", "示例地址", "在读",
                           "13900000000")], ADMIN_STU_WIDTHS)
    if kind == "teachers":
        return _workbook("教师账号", TEA_HEADERS,
                         [("JS0001", "示例教师", "教务处", "教师", "教师", "本校", "13800000000", "")],
                         TEA_WIDTHS)
    if kind == "scores":
        return _workbook("成绩", SCORE_HEADERS,
                         [("S001", "2026 秋季期中", "B", "上升")], SCORE_WIDTHS)
    raise ValueError("未知模板类型：" + kind)


def export(kind, class_id="2607"):
    if kind == "students":
        return export_students(class_id)
    if kind == "admin_students":
        return admin_export_students()
    if kind == "teachers":
        return export_teachers()
    if kind == "scores":
        return export_scores(class_id)
    raise ValueError("未知导出类型：" + kind)


def import_file(kind, data, class_id="2607"):
    if kind == "students":
        return import_students(data, class_id)
    if kind == "admin_students":
        return admin_import_students(data)
    if kind == "teachers":
        return import_teachers(data)
    if kind == "scores":
        return import_scores(data, class_id)
    raise ValueError("未知导入类型：" + kind)


# ---------------------------------------------------------------- 政教处：名单上传与学号编排
DEYU_STU_HEADERS = ["班级", "姓名", "性别", "学号(可空)", "专业", "年级", "宿舍号",
                    "住宿类型", "家长姓名", "家长关系", "家长电话", "床位号", "家庭住址", "状态"]
DEYU_STU_WIDTHS = [10, 10, 6, 16, 16, 8, 8, 10, 10, 10, 14, 8, 24, 8]

# 政教处名单可覆盖的学生信息列（不含姓名/性别/学号等主键与身份字段）
_DEYU_FIELD_ALIASES = (
    ("major", ("专业",)),
    ("grade", ("年级",)),
    ("dorm", ("宿舍号", "寝室")),
    ("boarding_type", ("住宿类型", "住宿方式")),
    ("guardian_name", ("家长姓名", "监护人姓名")),
    ("guardian_relation", ("家长关系", "监护人关系")),
    ("guardian_phone", ("家长电话", "监护人电话")),
    ("bed_no", ("床位号", "床位")),
    ("address", ("家庭住址", "住址")),
    ("phone", ("学生电话", "电话")),
    ("status", ("状态",)),
)


def deyu_student_template():
    """政教处名单导入模板：班级、姓名、性别、学号(可空) 及学生信息扩展列。"""
    return _workbook("学生名单", DEYU_STU_HEADERS,
                     [("2607", "示例学生", "男", "", "电子商务", "2026", "1401", "住校",
                       "张三", "父亲", "13800000000", "1号床", "示例地址", "在读")],
                     DEYU_STU_WIDTHS)


def _cell_text(row, idx):
    if idx < 0 or idx >= len(row):
        return ""
    value = row[idx]
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _deyu_find(headers):
    idx = {h: i for i, h in enumerate(headers)}

    def find(*names):
        for name in names:
            if name in idx:
                return idx[name]
        return -1
    return find


def _temp_student_id(class_id, used):
    seq = 1
    while True:
        sid = "T%s%03d" % (class_id, seq)
        if sid not in used and not db.q(
                "SELECT 1 FROM students WHERE class_id=? AND student_id=?",
                (class_id, sid), one=True):
            used.add(sid)
            return sid
        seq += 1


def _deyu_import_row(class_id, name, gender, student_no, values, temp_used, overwrite=False):
    """写入单行合法数据，返回 (student_id, action)。

    action：added / updated / conflict。overwrite=False 时，命中已有学生（按学号或同班同名）
    不写入、返回 conflict；overwrite=True 时用非空的新值覆盖旧数据。
    学号被其他班级占用、学号唯一索引冲突时抛 ValueError。
    """
    owner = None
    if student_no:
        owner = db.q("SELECT * FROM students WHERE student_no=?", (student_no,), one=True)
        if owner and str(owner["class_id"]) != class_id:
            raise ValueError("学号 %s 已被其他班级占用" % student_no)
    if owner is None:
        owner = db.q("SELECT * FROM students WHERE class_id=? AND name=? LIMIT 1",
                     (class_id, name), one=True)
    if owner:
        if not overwrite:
            return owner["student_id"], "conflict"
        merged = dict(owner)
        for key, _aliases in _DEYU_FIELD_ALIASES:
            if values.get(key):
                merged[key] = values[key]
        merged["name"] = name
        merged["gender"] = gender or merged.get("gender") or ""
        if student_no:
            merged["student_no"] = student_no
        # 政教处名单覆盖：先校验寝室床位/容量/性别，不合法则该行记 error 且不写库
        validate_dorm_bed(class_id, owner["student_id"], merged.get("dorm"),
                          merged.get("bed_no"), merged.get("gender"))
        try:
            db.exec_(
                "UPDATE students SET name=?,gender=?,major=?,grade=?,dorm=?,"
                "boarding_type=?,guardian_name=?,guardian_relation=?,guardian_phone=?,"
                "bed_no=?,address=?,phone=?,status=?,student_no=?,updated_at=? "
                "WHERE class_id=? AND student_id=?",
                (merged["name"], merged["gender"], merged.get("major") or "",
                 merged.get("grade") or "", merged.get("dorm") or "",
                 merged.get("boarding_type") or "", merged.get("guardian_name") or "",
                 merged.get("guardian_relation") or "", merged.get("guardian_phone") or "",
                 merged.get("bed_no") or "", merged.get("address") or "",
                 merged.get("phone") or "", merged.get("status") or "在读",
                 merged.get("student_no") or "", db.now(),
                 class_id, owner["student_id"]))
        except sqlite3.IntegrityError as exc:
            raise ValueError("学号冲突：%s" % exc)
        return owner["student_id"], "updated"
    sid = _temp_student_id(class_id, temp_used)
    # 政教处名单导入：新增行同样校验寝室床位/容量/性别
    validate_dorm_bed(class_id, sid, values.get("dorm"), values.get("bed_no"), gender)
    try:
        db.exec_(
            "INSERT INTO students(class_id,student_id,name,gender,major,grade,dorm,"
            "boarding_type,guardian_name,guardian_relation,guardian_phone,bed_no,"
            "address,phone,status,updated_at,student_no) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (class_id, sid, name, gender or "", values.get("major") or "",
             values.get("grade") or "", values.get("dorm") or "",
             values.get("boarding_type") or "", values.get("guardian_name") or "",
             values.get("guardian_relation") or "", values.get("guardian_phone") or "",
             values.get("bed_no") or "", values.get("address") or "",
             values.get("phone") or "", values.get("status") or "在读",
             db.now(), student_no or None))
    except sqlite3.IntegrityError as exc:
        raise ValueError("学号冲突：%s" % exc)
    return sid, "added"


def deyu_import_students(data, overwrite=False):
    """解析名单 xlsx：逐行校验并写入，返回成功/冲突/错误行明细；非法行不写入。

    overwrite=False 时，与库内已有学生命中的行记为 conflict 并保留旧数据，
    由前端弹窗确认后再以 overwrite=True 重传同一文件覆盖。

    强校验（errors）：姓名/性别缺失、文件内学号重复、学号被库中其他学生占用；
    同班同名保持冲突逻辑（不计 errors）。目标班级不存在时整单 ValueError。
    """
    from tasks.domain.identity import classes as class_dict

    headers, body = _read_rows(data)
    idx = {h: i for i, h in enumerate(headers)}
    _require_headers(idx, ("班级", "姓名", "性别"))
    find = _deyu_find(headers)
    ci, ni, gi = find("班级"), find("姓名"), find("性别")
    si = find("学号(可空)", "学号（可空）", "学号")
    field_idx = {key: find(*aliases) for key, aliases in _DEYU_FIELD_ALIASES}
    index_state = ensure_student_no_index()

    # 目标班级必须存在：任一数据行班级缺失对应记录时整单拒绝（不写入任何行）
    for pos, raw in enumerate(body):
        class_id = _cell_text(raw, ci)
        if class_id and not class_dict.get(class_id):
            raise ValueError("第 %d 行班级不存在：%s" % (pos + 2, class_id))

    rows, seen, seen_no, temp_used = [], set(), set(), set()
    ok_count = added = updated = 0
    conflicts, errors = [], []

    def fail(row_no, class_id, name, student_no, reason):
        rows.append({"row": row_no, "class_id": class_id,
                     "name": name, "student_no": student_no, "status": "error",
                     "message": reason})
        errors.append({"row": row_no, "student_no": student_no,
                       "name": name, "reason": reason})

    for pos, raw in enumerate(body):
        row_no = pos + 2
        class_id = _cell_text(raw, ci)
        name = _cell_text(raw, ni)
        gender = _cell_text(raw, gi)
        student_no = _cell_text(raw, si)
        values = {key: _cell_text(raw, i) for key, i in field_idx.items() if i >= 0}
        if not class_id:
            fail(row_no, class_id, name, student_no, "班级不能为空")
            continue
        if not name:
            fail(row_no, class_id, name, student_no, "姓名不能为空")
            continue
        if not gender:
            fail(row_no, class_id, name, student_no, "性别不能为空")
            continue
        if (class_id, name) in seen:
            fail(row_no, class_id, name, student_no, "文件内同一班级姓名重复")
            continue
        if student_no:
            if student_no in seen_no:
                fail(row_no, class_id, name, student_no,
                     "文件内学号重复：%s" % student_no)
                continue
            owner = db.q("SELECT class_id,student_id,name FROM students WHERE student_no=?",
                         (student_no,), one=True)
            if owner and not (str(owner["class_id"]) == class_id
                              and str(owner["name"]) == name):
                fail(row_no, class_id, name, student_no,
                     "学号 %s 已被其他学生占用（%s/%s）"
                     % (student_no, owner["class_id"], owner["student_id"]))
                continue
            seen_no.add(student_no)
        seen.add((class_id, name))
        try:
            sid, action = _deyu_import_row(class_id, name, gender, student_no,
                                           values, temp_used, overwrite)
        except ValueError as exc:
            fail(row_no, class_id, name, student_no, str(exc))
            continue
        if action == "conflict":
            rows.append({"row": row_no, "class_id": class_id, "name": name,
                         "student_no": student_no, "student_id": sid,
                         "status": "conflict",
                         "message": "与已有学生冲突，已保留旧数据"})
            conflicts.append({"row": row_no, "class_id": class_id, "student_id": sid,
                              "student_no": student_no, "name": name})
            continue
        if action == "updated":
            updated += 1
        else:
            added += 1
        ok_count += 1
        rows.append({"row": row_no, "class_id": class_id, "name": name,
                     "student_no": student_no, "student_id": sid, "status": "ok",
                     "message": "已更新" if action == "updated" else (
                         "已导入并写入学号" if student_no else "已导入（待编学号）")})
    return {"ok_count": ok_count, "conflict_count": len(conflicts),
            "failed_count": len(errors), "total": len(body),
            "added": added, "updated": updated, "skipped": len(errors),
            "rows": rows, "conflicts": conflicts, "errors": errors,
            "index": index_state}


def _class_prefix(class_id, cls):
    """按 年级(2 位) + 班号(2 位) 生成前缀；年级缺失时取自 class_id 前两位。"""
    cdigits = "".join(ch for ch in str(cls.get("class_id") or class_id) if ch.isdigit())
    gdigits = "".join(ch for ch in str(cls.get("grade") or "") if ch.isdigit())
    if not gdigits and len(cdigits) >= 4:
        gdigits = cdigits[:2]
    grade = gdigits[-2:] if len(gdigits) >= 2 else gdigits
    cno = cdigits[-2:] if len(cdigits) >= 2 else cdigits
    return grade, cno


def numbering_preview(class_id, prefix="", width=2):
    """学号编排预览：不落库；已有学号默认跳过，与库中重复标记 conflict。"""
    from tasks.domain.identity import classes as class_dict

    cid = str(class_id or "").strip()
    if not cid:
        raise ValueError("请先选择班级")
    cls = class_dict.get(cid)
    if not cls:
        raise ValueError("班级不存在")
    try:
        width = int(width or 2)
    except (TypeError, ValueError):
        raise ValueError("序号位数必须为数字")
    if width < 1 or width > 6:
        raise ValueError("序号位数需为 1~6")
    prefix = str(prefix or "").strip()
    grade, cno = _class_prefix(cid, cls)
    if not prefix:
        prefix = grade + cno
    if not prefix:
        raise ValueError("无法自动生成学号前缀，请手动填写")

    used = {r["student_no"]: r for r in db.q(
        "SELECT class_id,student_id,student_no FROM students "
        "WHERE student_no IS NOT NULL AND student_no<>''")}
    items, seq, conflict_count = [], 0, 0
    for stu in list_students(cid):
        existing = str(stu.get("student_no") or "").strip()
        if existing:
            items.append({"student_id": stu["student_id"], "name": stu["name"],
                          "student_no": existing, "conflict": False, "skipped": True})
            continue
        seq += 1
        number = prefix + str(seq).zfill(width)
        owner = used.get(number)
        conflict = bool(owner and not (
            str(owner["class_id"]) == cid
            and str(owner["student_id"]) == str(stu["student_id"])))
        if conflict:
            conflict_count += 1
        items.append({"student_id": stu["student_id"], "name": stu["name"],
                      "student_no": number, "conflict": conflict, "skipped": False})
    return {"class_id": cid, "rule": "%s + 序号(%d 位)" % (prefix, width),
            "prefix": prefix, "width": width, "items": items,
            "conflict_count": conflict_count, "index": ensure_student_no_index()}


def numbering_apply(class_id, items):
    """事务内写入学号：跳过已有值，冲突整单回滚；返回更新条数。"""
    cid = str(class_id or "").strip()
    if not cid:
        raise ValueError("请先选择班级")
    if not db.q("SELECT 1 FROM classes WHERE class_id=?", (cid,), one=True):
        raise ValueError("班级不存在")
    if not isinstance(items, list) or not items:
        raise ValueError("没有可应用的学号")
    index_state = ensure_student_no_index()

    plan, seen_sid, seen_no, skipped = [], set(), set(), 0
    for pos, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("第 %d 项格式错误" % (pos + 1))
        sid = str(item.get("student_id") or "").strip()
        number = str(item.get("student_no") or "").strip()
        if not sid or not number:
            raise ValueError("第 %d 项缺少学生或学号" % (pos + 1))
        if sid in seen_sid:
            raise ValueError("学生 %s 重复提交" % sid)
        seen_sid.add(sid)
        stu = db.q("SELECT student_id,student_no FROM students WHERE class_id=? AND student_id=?",
                   (cid, sid), one=True)
        if not stu:
            raise ValueError("学生不存在：%s" % sid)
        if str(stu.get("student_no") or "").strip():
            skipped += 1
            continue
        if number in seen_no:
            raise ValueError("学号重复：%s" % number)
        seen_no.add(number)
        if db.q("SELECT 1 FROM students WHERE student_no=?", (number,), one=True):
            raise ValueError("学号 %s 已被占用" % number)
        plan.append((sid, number))
    if not plan:
        return {"updated": 0, "skipped": skipped, "index": index_state}

    c = db.connect()
    c.isolation_level = None
    updated = 0
    try:
        c.execute("BEGIN IMMEDIATE")
        for sid, number in plan:
            cur = c.execute(
                "UPDATE students SET student_no=?,updated_at=? WHERE class_id=? AND student_id=? "
                "AND (student_no IS NULL OR student_no='')",
                (number, db.now(), cid, sid))
            updated += cur.rowcount
        c.commit()
    except sqlite3.IntegrityError as exc:
        c.rollback()
        raise ValueError("学号冲突，已整单回滚：%s" % exc)
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    return {"updated": updated, "skipped": skipped, "index": index_state}


# ---------------------------------------------------------------- 管理台：跨班学生管理
def get_student(class_id, student_id):
    row = db.q("SELECT * FROM students WHERE class_id=? AND student_id=?",
               (str(class_id), str(student_id)), one=True)
    return dict(row) if row else None


def count_all_students():
    row = db.q("SELECT COUNT(*) AS n FROM students", one=True)
    return int(row["n"]) if row else 0


def list_all_students(keyword="", class_id="", page=1, size=50):
    where, args = [], []
    keyword = str(keyword or "").strip()
    if keyword:
        where.append("(student_id LIKE ? OR name LIKE ? OR COALESCE(student_no,'') LIKE ?)")
        args += ["%%%s%%" % keyword] * 3
    class_id = str(class_id or "").strip()
    if class_id:
        where.append("class_id=?")
        args.append(class_id)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.q("SELECT COUNT(*) AS n FROM students" + where_sql, tuple(args), one=True)["n"]
    page = max(1, int(page or 1))
    size = max(1, min(500, int(size or 50)))
    sql = ("SELECT * FROM students" + where_sql +
           " ORDER BY class_id, student_id LIMIT ? OFFSET ?")
    args += [size, (page - 1) * size]
    items = [dict(r) for r in db.q(sql, tuple(args))]
    return {"items": items, "total": total, "page": page, "size": size}


def create_student(class_id, student_id, name, gender="", dorm="", address="",
                   phone="", guardian_phone="", status="在读", major="", grade="",
                   boarding_type="", guardian_name="", guardian_relation="", bed_no="",
                   student_no=""):
    class_id = str(class_id or "").strip()
    student_id = str(student_id or "").strip()
    name = str(name or "").strip()
    gender = str(gender or "").strip()
    student_no = str(student_no or "").strip()
    if not class_id or not name or not gender:
        raise ValueError("班级、姓名、性别不能为空")
    if not student_id:
        student_id = _temp_student_id(class_id, set())
    if get_student(class_id, student_id):
        raise ValueError("该班级下已存在相同学号")
    if student_no and db.q("SELECT 1 FROM students WHERE student_no=?", (student_no,), one=True):
        raise ValueError("学号 %s 已存在" % student_no)
    # 统一入口：政教处/管理台新增都先校验寝室床位
    validate_dorm_bed(class_id, student_id, dorm, bed_no, gender)
    try:
        db.exec_(
            "INSERT INTO students(class_id,student_id,name,gender,major,grade,dorm,"
            "boarding_type,guardian_name,guardian_relation,guardian_phone,bed_no,"
            "address,phone,status,updated_at,student_no) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (class_id, student_id, name, gender, str(major or ""), str(grade or ""),
             str(dorm or ""), str(boarding_type or ""), str(guardian_name or ""),
             str(guardian_relation or ""), str(guardian_phone or ""), str(bed_no or ""),
             str(address or ""), str(phone or ""), str(status or "在读"), db.now(),
             student_no or None))
    except sqlite3.IntegrityError as exc:
        raise ValueError("学号冲突：%s" % exc)
    return get_student(class_id, student_id)


def update_student(class_id, student_id, new_class_id=None, new_student_id=None, **fields):
    """编辑学生；若传入 new_class_id / new_student_id 则视为调班/改学号（删旧行后插新行）。

    路径参数 class_id/student_id 定位原记录；目标班级/学号通过显式参数传入，
    避免与同名路径参数冲突（否则调用方 **body 会触发“multiple values”）。
    """
    old = get_student(class_id, student_id)
    if not old:
        raise ValueError("学生不存在")
    new_class = (str(new_class_id).strip() if new_class_id is not None
                 and str(new_class_id).strip() else str(old["class_id"]))
    new_sid = (str(new_student_id).strip() if new_student_id is not None
               and str(new_student_id).strip() else str(old["student_id"]))
    changed_key = (new_class != str(old["class_id"])) or (new_sid != str(old["student_id"]))
    if changed_key and get_student(new_class, new_sid):
        raise ValueError("目标班级下已存在相同学号")
    merged = dict(old)
    allowed = ("name", "gender", "major", "grade", "dorm", "boarding_type",
               "guardian_name", "guardian_relation", "guardian_phone", "bed_no",
               "address", "phone", "status")
    for k, v in fields.items():
        if k in allowed and v is not None:
            merged[k] = str(v)
    if new_class_id is not None:
        merged["class_id"] = new_class
    if new_student_id is not None:
        merged["student_id"] = new_sid
    if not str(merged.get("name") or "").strip():
        raise ValueError("姓名不能为空")
    if not str(merged.get("gender") or "").strip():
        raise ValueError("性别不能为空")
    # 编辑学生：以合并后的寝室/床位/性别重新校验，排除本人占位
    validate_dorm_bed(old["class_id"], old["student_id"], merged.get("dorm"),
                      merged.get("bed_no"), merged.get("gender"))
    merged["updated_at"] = db.now()
    db.exec_("DELETE FROM students WHERE class_id=? AND student_id=?",
             (str(old["class_id"]), str(old["student_id"])))
    db.exec_(
        "INSERT INTO students(class_id,student_id,name,gender,major,grade,dorm,"
        "boarding_type,guardian_name,guardian_relation,guardian_phone,bed_no,"
        "address,phone,status,student_no,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (merged["class_id"], merged["student_id"], merged["name"],
         merged.get("gender") or "", merged.get("major") or "", merged.get("grade") or "",
         merged.get("dorm") or "", merged.get("boarding_type") or "",
         merged.get("guardian_name") or "", merged.get("guardian_relation") or "",
         merged.get("guardian_phone") or "", merged.get("bed_no") or "",
         merged.get("address") or "", merged.get("phone") or "",
         merged.get("status") or "在读", merged.get("student_no") or "",
         merged["updated_at"]))
    return get_student(merged["class_id"], merged["student_id"])


def delete_student(class_id, student_id):
    if not get_student(class_id, student_id):
        raise ValueError("学生不存在")
    db.exec_("DELETE FROM students WHERE class_id=? AND student_id=?",
             (str(class_id), str(student_id)))
    db.exec_("DELETE FROM student_accounts WHERE class_id=? AND student_id=?",
             (str(class_id), str(student_id)))
    return True


def delete_students(class_id, student_ids):
    """批量删除本班学生；逐条执行，返回删除与未找到数量。"""
    cid = str(class_id)
    deleted = missing = 0
    for sid in student_ids or []:
        sid = str(sid or "").strip()
        if not sid:
            continue
        if get_student(cid, sid):
            delete_student(cid, sid)
            deleted += 1
        else:
            missing += 1
    return {"deleted": deleted, "missing": missing}


def transfer_students(student_refs, target_class_id, operator=""):
    """批量转班：逐人更新 students.class_id、迁移学生账号、记录转班台账。

    - 学生账号整行迁移（删除旧班级行、写入新班级行），保留密码摘要与启用状态；
    - dom_* 历史表按原班级保留，用于历史追溯，不做改写；
    - 任一条校验失败即整单拒绝（写库前完成全部校验），返回 moved 与目标班级。
    """
    from tasks.domain.identity import classes as class_dict

    target = str(target_class_id or "").strip()
    if not target:
        raise ValueError("请先选择目标班级")
    if not class_dict.get(target):
        raise ValueError("目标班级不存在：%s" % target)
    if not isinstance(student_refs, list) or not student_refs:
        raise ValueError("请先选择要转班的学生")

    plan, seen, problems = [], set(), []
    for pos, ref in enumerate(student_refs):
        if not isinstance(ref, dict):
            problems.append("第 %d 项格式错误" % (pos + 1))
            continue
        cid = str(ref.get("class_id") or "").strip()
        sid = str(ref.get("student_id") or "").strip()
        if not cid or not sid:
            problems.append("第 %d 项缺少班级或学号" % (pos + 1))
            continue
        if (cid, sid) in seen:
            problems.append("学生重复提交：%s/%s" % (cid, sid))
            continue
        seen.add((cid, sid))
        stu = get_student(cid, sid)
        if not stu:
            problems.append("学生不存在：%s/%s" % (cid, sid))
            continue
        if cid == target:
            problems.append("%s 已在目标班级" % (stu.get("name") or sid))
            continue
        if get_student(target, sid):
            problems.append("目标班级已存在学号 %s" % sid)
            continue
        plan.append((cid, sid, stu.get("name") or ""))
    if problems:
        raise ValueError("；".join(problems))

    now = db.now()
    c = db.connect()
    c.isolation_level = None
    moved = 0
    try:
        c.execute("BEGIN IMMEDIATE")
        for cid, sid, _name in plan:
            c.execute("UPDATE students SET class_id=?,updated_at=? "
                      "WHERE class_id=? AND student_id=?",
                      (target, now, cid, sid))
            acc = c.execute(
                "SELECT password_sha256,status FROM student_accounts "
                "WHERE class_id=? AND student_id=?", (cid, sid)).fetchone()
            if acc is not None:
                c.execute("DELETE FROM student_accounts WHERE class_id=? AND student_id=?",
                          (cid, sid))
                c.execute("INSERT OR REPLACE INTO student_accounts"
                          "(class_id,student_id,password_sha256,status,updated_at) "
                          "VALUES(?,?,?,?,?)",
                          (target, sid, acc["password_sha256"], acc["status"], now))
            c.execute("INSERT INTO student_transfers"
                      "(id,class_id,student_id,from_class,to_class,operator,created_at) "
                      "VALUES(?,?,?,?,?,?,?)",
                      (db.uid("tr_"), target, sid, cid, target,
                       str(operator or ""), now))
            moved += 1
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    return {"moved": moved, "target_class_id": target,
            "students": [{"class_id": target, "student_id": sid, "name": name}
                         for _cid, sid, name in plan]}


def admin_export_students():
    rows = db.q("SELECT * FROM students ORDER BY class_id, student_id")
    data = [(r["student_id"], r["name"], r.get("gender"), r.get("major"), r.get("grade"),
             r["class_id"], r.get("dorm"), r.get("boarding_type"), r.get("guardian_name"),
             r.get("guardian_relation"), r.get("guardian_phone"), r.get("bed_no"),
             r.get("address"), r["status"], r.get("phone")) for r in rows]
    return _workbook("学生名册", ADMIN_STU_HEADERS, data, ADMIN_STU_WIDTHS)


def admin_import_students(data):
    headers, body = _read_rows(data)
    idx = {h: i for i, h in enumerate(headers)}
    _require_headers(idx, ("姓名", "性别", "班级"))
    added = updated = skipped = 0
    temp_used = set()
    for r in body:
        class_id = _pick(r, idx, "班级")
        name = _pick(r, idx, "姓名")
        gender = _pick(r, idx, "性别")
        if not class_id or not name or not gender:
            skipped += 1
            continue
        sid = _pick(r, idx, "学号")
        old = get_student(class_id, sid) if sid else db.q(
            "SELECT * FROM students WHERE class_id=? AND name=? LIMIT 1",
            (class_id, name), one=True)
        if not sid:
            sid = old["student_id"] if old else _temp_student_id(class_id, temp_used)
        # 管理台跨班导入：逐行校验寝室床位（同 dorm+bed 全校唯一、容量、性别）
        validate_dorm_bed(class_id, sid, _pick(r, idx, "宿舍号", "寝室"),
                          _pick(r, idx, "床位号", "床位"), gender)
        db.exec_(
            "INSERT INTO students(class_id,student_id,name,gender,major,grade,dorm,"
            "boarding_type,guardian_name,guardian_relation,guardian_phone,bed_no,"
            "address,phone,status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(class_id,student_id) DO UPDATE SET "
            "name=excluded.name,gender=excluded.gender,major=excluded.major,"
            "grade=excluded.grade,dorm=excluded.dorm,boarding_type=excluded.boarding_type,"
            "guardian_name=excluded.guardian_name,guardian_relation=excluded.guardian_relation,"
            "guardian_phone=excluded.guardian_phone,bed_no=excluded.bed_no,"
            "address=excluded.address,phone=excluded.phone,status=excluded.status,"
            "updated_at=excluded.updated_at",
            (class_id, sid, name, gender,
             _pick(r, idx, "专业"), _pick(r, idx, "年级"),
             _pick(r, idx, "宿舍号", "寝室"), _pick(r, idx, "住宿类型"),
             _pick(r, idx, "家长姓名", "监护人姓名"),
             _pick(r, idx, "家长关系", "监护人关系"),
             _pick(r, idx, "家长电话", "监护人电话"),
             _pick(r, idx, "床位号", "床位"),
             _pick(r, idx, "家庭住址", "住址"),
             _pick(r, idx, "学生电话", "电话"),
             _pick(r, idx, "状态") or "在读", db.now()))
        if old:
            updated += 1
        else:
            added += 1
    return {"added": added, "updated": updated, "skipped": skipped, "total": len(body)}
