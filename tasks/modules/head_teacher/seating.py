# -*- coding: utf-8 -*-
"""班级空间：座位表与寝室表。

- 每个班级每种表各一份布局（seat / dorm），行列可配置。
- 座位以「行 × 列」网格保存；寝室以「每行一间寝室 × 每间若干床位」保存。
- 拖拽排位只改变学生的位置，不影响名册与成长档案。
"""

import json
from math import ceil

from tasks.shared import db
from tasks.modules.head_teacher import roster

KINDS = {"seat": "座位表", "dorm": "寝室表"}
MAX_ROWS = 20
MAX_COLS = 12
MAX_GROUPS = 6
MAX_GROUP_COLS = 6
DEFAULT_SEAT_GROUPS = [2, 2, 2, 2]
ROOM_START = 1101

SCHEMA = """
CREATE TABLE IF NOT EXISTS layout_plans (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  rows INTEGER NOT NULL,
  cols INTEGER NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT,
  UNIQUE(class_id, kind)
);
CREATE TABLE IF NOT EXISTS layout_seats (
  plan_id TEXT NOT NULL,
  row_idx INTEGER NOT NULL,
  col_idx INTEGER NOT NULL,
  student_id TEXT,
  PRIMARY KEY (plan_id, row_idx, col_idx)
);
CREATE INDEX IF NOT EXISTS idx_layout_seats_plan ON layout_seats(plan_id);
CREATE INDEX IF NOT EXISTS idx_layout_seats_student ON layout_seats(plan_id, student_id);
"""


def init():
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()


def _kind(kind):
    kind = str(kind or "seat")
    if kind not in KINDS:
        raise ValueError("未知的表格类型")
    return kind


def _size(class_id, kind, total):
    """座位表默认 4 组 × 2 列；寝室表初始只给 1 间，由班主任逐间新增。"""
    cols = sum(DEFAULT_SEAT_GROUPS)
    if kind == "dorm":
        return 1, 6
    rows = max(1, min(MAX_ROWS, int(ceil(max(total, 1) / float(cols)))))
    return rows, cols


def _parse_groups(value):
    """校验分组列数，例如 [2,4,2]；统一存放在座位表 meta.groups。"""
    if not isinstance(value, (list, tuple)):
        raise ValueError("分组配置格式不正确")
    groups = []
    for item in value:
        try:
            width = int(item)
        except (TypeError, ValueError):
            raise ValueError("分组列数必须是数字")
        if not 1 <= width <= MAX_GROUP_COLS:
            raise ValueError("每组 1—%d 列" % MAX_GROUP_COLS)
        groups.append(width)
    if not groups:
        raise ValueError("请至少设置一个组")
    if len(groups) > MAX_GROUPS:
        raise ValueError("最多 %d 个组" % MAX_GROUPS)
    if sum(groups) > MAX_COLS:
        raise ValueError("座位总列数不能超过 %d 列" % MAX_COLS)
    return groups


def _derive_groups(cols):
    """旧布局没有分组信息时，按常见列数还原分组。"""
    preset = {1: [1], 2: [2], 3: [3], 4: [2, 2], 6: [2, 2, 2], 8: [2, 2, 2, 2]}
    if cols in preset:
        return list(preset[cols])
    groups, left = [], cols
    while left > 0:
        width = min(2, left)
        groups.append(width)
        left -= width
    return groups


def _seat_groups(meta, cols):
    groups = meta.get("groups")
    if isinstance(groups, list) and groups:
        try:
            return _parse_groups(groups)
        except ValueError:
            pass
    return _derive_groups(cols)


def _norm_gender(value):
    v = str(value or "").strip()
    if v in ("男", "boy", "男生", "男寝"):
        return "boy"
    if v in ("女", "girl", "女生", "女寝"):
        return "girl"
    return ""


def _room_meta(rows, start=ROOM_START, names=None, genders=None):
    names = list(names or [])
    genders = list(genders or [])
    rooms, kinds = [], []
    for i in range(rows):
        rooms.append(str(names[i]) if i < len(names) and str(names[i]).strip()
                     else str(int(start) + i))
        kinds.append(_norm_gender(genders[i]) if i < len(genders) else "")
    return {"room_start": int(start), "room_names": rooms, "room_genders": kinds}


def room_parts(name):
    """四位寝室号：第一位楼栋、第二位楼层、后两位寝室。"""
    s = str(name or "").strip()
    if len(s) == 4 and s.isdigit():
        return {"building": s[0], "floor": s[1], "room": s[2:]}
    return {}


def _bed_no(value):
    """从“2号床”“02”等文本提取床序号，用于按床位排列。"""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else 9999


def _default_meta(kind, rows):
    return _room_meta(rows) if kind == "dorm" else {"groups": list(DEFAULT_SEAT_GROUPS)}


def _parse_meta(raw):
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _plan(class_id, kind):
    return db.q("SELECT * FROM layout_plans WHERE class_id=? AND kind=?",
                (str(class_id), kind), one=True)


def _students(class_id):
    return roster.list_students(class_id)


def _seat_map(plan_id):
    seats = {}
    for row in db.q("SELECT row_idx,col_idx,student_id FROM layout_seats WHERE plan_id=?",
                    (plan_id,)):
        if row["student_id"]:
            seats[(int(row["row_idx"]), int(row["col_idx"]))] = row["student_id"]
    return seats


def _write_seats(plan_id, seats):
    db.exec_many([("DELETE FROM layout_seats WHERE plan_id=?", (plan_id,))] +
                 [("INSERT OR REPLACE INTO layout_seats(plan_id,row_idx,col_idx,student_id) "
                   "VALUES(?,?,?,?)", (plan_id, r, c, sid))
                  for (r, c), sid in seats.items()])


def _ensure_plan(class_id, kind):
    existing = _plan(class_id, kind)
    if existing:
        # 旧座位表补上默认分组（4 组 × 2 列），学生已排的 row/col 保持不变
        if kind == "seat":
            meta = _parse_meta(existing["meta"])
            if not isinstance(meta.get("groups"), list) or not meta.get("groups"):
                meta["groups"] = list(DEFAULT_SEAT_GROUPS)
                db.exec_(
                    "UPDATE layout_plans SET cols=?,meta=?,updated_at=? WHERE id=?",
                    (sum(DEFAULT_SEAT_GROUPS), json.dumps(meta, ensure_ascii=False),
                     db.now(), existing["id"]))
                existing = _plan(class_id, kind)
        return existing
    students = _students(class_id)
    rows, cols = _size(class_id, kind, len(students))
    plan_id = db.uid("ly_")
    meta = _default_meta(kind, rows)
    # 初始为空位：学生全部在右侧未分配区，由班主任拖拽落位
    db.exec_(
        "INSERT INTO layout_plans(id,class_id,kind,rows,cols,meta,updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (plan_id, str(class_id), kind, rows, cols, json.dumps(meta, ensure_ascii=False), db.now()))
    return _plan(class_id, kind)


def rebuild_dorm_from_roster(class_id, force=False):
    """按 students.dorm / bed_no 重建班级寝室表。

    名单上传或新增学生后调用；roster_synced 标记避免每次打开重复重建，
    force=True 用于名单覆盖后强制刷新。返回最新的布局行。
    """
    plan = _ensure_plan(str(class_id), "dorm")
    meta = _parse_meta(plan["meta"])
    if not force and meta.get("roster_synced"):
        return plan
    rooms, order = {}, []
    for stu in _students(class_id):
        name = str(stu.get("dorm") or "").strip()
        if not name:
            continue
        if name not in rooms:
            rooms[name] = []
            order.append(name)
        rooms[name].append(stu)
    if not rooms:
        return plan
    order.sort(key=lambda n: (0, int(n)) if n.isdigit() else (1, n))
    order = order[:MAX_ROWS]
    cols = max(6, max(len(rooms[n]) for n in order))
    cols = min(MAX_COLS, cols)
    seats = {}
    for r, name in enumerate(order, 1):
        members = sorted(rooms[name], key=lambda s: (_bed_no(s.get("bed_no")),
                                                     str(s.get("name") or "")))
        for c, stu in enumerate(members[:cols], 1):
            seats[(r, c)] = stu["student_id"]
    genders = []
    for name in order:
        kinds = {_norm_gender(s.get("gender")) for s in rooms[name]}
        kinds.discard("")
        genders.append(kinds.pop() if len(kinds) == 1 else ("mixed" if len(kinds) > 1 else ""))
    fresh = _room_meta(len(order), meta.get("room_start") or ROOM_START, order, genders)
    fresh["roster_synced"] = True
    _write_seats(plan["id"], seats)
    db.exec_("UPDATE layout_plans SET rows=?,cols=?,meta=?,updated_at=? WHERE id=?",
             (len(order), cols, json.dumps(fresh, ensure_ascii=False), db.now(), plan["id"]))
    return _plan(class_id, "dorm")


def get_plan(class_id, kind):
    kind = _kind(kind)
    plan = _ensure_plan(str(class_id), kind)
    if kind == "dorm" and not _parse_meta(plan["meta"]).get("roster_synced"):
        plan = rebuild_dorm_from_roster(class_id, force=True) or plan
    rows, cols = int(plan["rows"]), int(plan["cols"])
    students = _students(class_id)
    by_id = {s["student_id"]: s for s in students}
    seats = _seat_map(plan["id"])
    grid = []
    for r in range(1, rows + 1):
        line = []
        for c in range(1, cols + 1):
            sid = seats.get((r, c))
            stu = by_id.get(sid) if sid else None
            line.append({"row": r, "col": c, "student": stu})
        grid.append(line)
    taken = {sid for sid in seats.values() if sid in by_id}
    pool = [s for s in students if s["student_id"] not in taken]
    meta = _parse_meta(plan["meta"])
    if kind == "dorm":
        meta = _room_meta(rows, meta.get("room_start") or ROOM_START,
                          meta.get("room_names"), meta.get("room_genders"))
    else:
        meta = {"groups": _seat_groups(meta, cols)}
    return {
        "class_id": str(class_id),
        "kind": kind,
        "kind_name": KINDS[kind],
        "rows": rows,
        "cols": cols,
        "grid": grid,
        "pool": pool,
        "meta": meta,
        "updated_at": plan["updated_at"],
        "stats": {
            "total": len(students),
            "seated": len(taken),
            "unseated": len(pool),
            "capacity": rows * cols,
            "empty": rows * cols - len(taken),
        },
    }


def save_layout(class_id, kind, rows, cols, meta=None):
    kind = _kind(kind)
    plan = _ensure_plan(str(class_id), kind)
    old = _parse_meta(plan["meta"])
    given = dict(meta) if isinstance(meta, dict) else {}
    if kind == "seat":
        if given.get("groups"):
            groups = _parse_groups(given["groups"])
            cols = sum(groups)
        else:
            try:
                cols = int(cols)
            except (TypeError, ValueError):
                raise ValueError("列数必须是数字")
            groups = _derive_groups(cols)
        meta = {"groups": groups}
    else:
        meta = given or old
    try:
        rows = int(rows)
    except (TypeError, ValueError):
        raise ValueError("行数必须是数字")
    if not (1 <= rows <= MAX_ROWS and 1 <= cols <= MAX_COLS):
        raise ValueError("行数 1—%d，列数 1—%d" % (MAX_ROWS, MAX_COLS))
    if kind == "dorm":
        start = int(meta.get("room_start") or old.get("room_start") or ROOM_START)
        if "room_names" in meta:
            names = meta.get("room_names") or []
        else:
            names = old.get("room_names") or []
        if "room_genders" in meta:
            genders = meta.get("room_genders") or []
        else:
            genders = old.get("room_genders") or []
        meta = _room_meta(rows, start, names, genders)
        if any(not (len(n) == 4 and n.isdigit()) for n in meta["room_names"]):
            raise ValueError("寝室号需为四位数字，例如 1401")
    db.exec_many([
        ("UPDATE layout_plans SET rows=?,cols=?,meta=?,updated_at=? WHERE id=?",
         (rows, cols, json.dumps(meta, ensure_ascii=False), db.now(), plan["id"])),
        ("DELETE FROM layout_seats WHERE plan_id=? AND (row_idx>? OR col_idx>?)",
         (plan["id"], rows, cols)),
    ])
    return get_plan(class_id, kind)


def assign(class_id, kind, row, col, student_id, operator=""):
    kind = _kind(kind)
    plan = _ensure_plan(str(class_id), kind)
    try:
        row, col = int(row), int(col)
    except (TypeError, ValueError):
        raise ValueError("座位位置不正确")
    rows, cols = int(plan["rows"]), int(plan["cols"])
    if not (1 <= row <= rows and 1 <= col <= cols):
        raise ValueError("座位超出当前行列范围")
    student_id = str(student_id or "").strip()
    if not student_id:
        raise ValueError("请选择学生")
    if not db.q("SELECT 1 FROM students WHERE class_id=? AND student_id=?",
                (str(class_id), student_id), one=True):
        raise ValueError("该学生不在本班名册")
    seats = _seat_map(plan["id"])
    if seats.get((row, col)) == student_id:
        return get_plan(class_id, kind)
    old_seat = next((pos for pos, sid in seats.items() if sid == student_id), None)
    occupant = seats.get((row, col))
    statements = [("DELETE FROM layout_seats WHERE plan_id=? AND student_id=?",
                   (plan["id"], student_id))]
    if occupant and occupant != student_id:
        statements.append(("DELETE FROM layout_seats WHERE plan_id=? AND student_id=?",
                           (plan["id"], occupant)))
    statements.append(("INSERT OR REPLACE INTO layout_seats(plan_id,row_idx,col_idx,student_id) "
                       "VALUES(?,?,?,?)", (plan["id"], row, col, student_id)))
    if occupant and occupant != student_id and old_seat:
        statements.append(("INSERT OR REPLACE INTO layout_seats(plan_id,row_idx,col_idx,student_id) "
                           "VALUES(?,?,?,?)", (plan["id"], old_seat[0], old_seat[1], occupant)))
    dorm_moves = []
    if kind == "dorm":
        by_id = {s["student_id"]: s for s in _students(class_id)}
        meta = _parse_meta(plan["meta"])
        rooms = _room_meta(rows, meta.get("room_start") or ROOM_START,
                           meta.get("room_names"), meta.get("room_genders"))
        names = rooms["room_names"]
        target_room = names[row - 1] if row - 1 < len(names) else str(row)
        target_bed = "%d号床" % col
        # 目标床位若已有人则是两人互换，校验时忽略被换出的同学
        ignore = [occupant] if occupant and occupant != student_id else []
        roster.validate_dorm_bed(class_id, student_id, target_room, target_bed,
                                 (by_id.get(student_id) or {}).get("gender"),
                                 True, ignore)
        dorm_moves.append((student_id, target_room, target_bed))
        if occupant and occupant != student_id and old_seat:
            old_room = names[old_seat[0] - 1] if old_seat[0] - 1 < len(names) else str(old_seat[0])
            dorm_moves.append((occupant, old_room, "%d号床" % old_seat[1]))
        final = dict(seats)
        if old_seat:
            final.pop(old_seat, None)
        final.pop((row, col), None)
        final[(row, col)] = student_id
        if occupant and occupant != student_id and old_seat:
            final[old_seat] = occupant
        genders = list(meta.get("room_genders") or [])
        while len(genders) < rows:
            genders.append("")
        for r in range(1, rows + 1):
            present = [(by_id.get(sid) or {}).get("gender") for (rr, _cc), sid in final.items()
                       if rr == r and by_id.get(sid)]
            kinds = {"girl" if g == "女" else "boy" for g in present}
            fixed = _norm_gender(genders[r - 1])
            if fixed and kinds and fixed not in kinds:
                raise ValueError("该寝室是%s寝室" % ("男生" if fixed == "boy" else "女生"))
            if len(kinds) > 1:
                raise ValueError("同一寝室不能安排男女生混住")
            if not fixed and kinds:
                genders[r - 1] = list(kinds)[0]
        meta["room_genders"] = genders
        # 已由班主任手工落位，避免下次打开时被名单重建覆盖
        meta["roster_synced"] = True
        statements.append(("UPDATE layout_plans SET meta=? WHERE id=?",
                           (json.dumps(meta, ensure_ascii=False), plan["id"])))
    db.exec_many(statements)
    db.exec_("UPDATE layout_plans SET updated_at=? WHERE id=?", (db.now(), plan["id"]))
    # 寝室表落位后回写学生主数据，并记录调宿台账
    for sid, room_name, bed_label in dorm_moves:
        roster.set_dorm_bed(class_id, sid, room_name, bed_label, operator)
    return get_plan(class_id, kind)


def unassign(class_id, kind, student_id, operator=""):
    kind = _kind(kind)
    plan = _ensure_plan(str(class_id), kind)
    sid = str(student_id or "")
    seats = _seat_map(plan["id"])
    was_seated = sid in seats.values()
    db.exec_("DELETE FROM layout_seats WHERE plan_id=? AND student_id=?",
             (plan["id"], sid))
    if kind == "dorm":
        # 移回待排区：同步清空学生寝室/床位并记录台帐
        if was_seated:
            roster.set_dorm_bed(class_id, sid, "", "", operator)
        meta = _parse_meta(plan["meta"])
        meta["roster_synced"] = True
        db.exec_("UPDATE layout_plans SET meta=?,updated_at=? WHERE id=?",
                 (json.dumps(meta, ensure_ascii=False), db.now(), plan["id"]))
    else:
        db.exec_("UPDATE layout_plans SET updated_at=? WHERE id=?", (db.now(), plan["id"]))
    return get_plan(class_id, kind)


def room_gender(line):
    """根据一间寝室内学生性别推断：boy / girl / mixed / empty。"""
    boys = girls = 0
    for cell in line:
        stu = cell.get("student")
        if not stu:
            continue
        if stu.get("gender") == "女":
            girls += 1
        else:
            boys += 1
    if boys and girls:
        return "mixed"
    if girls:
        return "girl"
    if boys:
        return "boy"
    return "empty"


def add_room(class_id, room_name, gender):
    """在寝室表末尾新增一间寝室，房号与男/女寝属性由班主任填写。"""
    plan = _ensure_plan(str(class_id), "dorm")
    name = str(room_name or "").strip()
    if not (len(name) == 4 and name.isdigit()):
        raise ValueError("寝室号需为四位数字，例如 1401")
    kind = _norm_gender(gender)
    if not kind:
        raise ValueError("请选择男生寝室或女生寝室")
    rows, cols = int(plan["rows"]), int(plan["cols"])
    if rows >= MAX_ROWS:
        raise ValueError("最多 %d 间寝室" % MAX_ROWS)
    meta = _parse_meta(plan["meta"])
    names = _room_meta(rows, meta.get("room_start") or ROOM_START,
                       meta.get("room_names"), meta.get("room_genders"))
    if name in names["room_names"]:
        raise ValueError("寝室号已存在")
    names["room_names"].append(name)
    names["room_genders"].append(kind)
    return save_layout(class_id, "dorm", rows + 1, cols, names)


def update_room(class_id, room_name, gender):
    """修改寝室类型；寝室号不可修改。"""
    plan = _ensure_plan(str(class_id), "dorm")
    meta = _parse_meta(plan["meta"])
    rows = int(plan["rows"])
    meta = _room_meta(rows, meta.get("room_start") or ROOM_START,
                      meta.get("room_names"), meta.get("room_genders"))
    name = str(room_name or "").strip()
    if name not in meta["room_names"]:
        raise ValueError("寝室不存在")
    idx = meta["room_names"].index(name)
    kind = _norm_gender(gender)
    if not kind:
        raise ValueError("请选择男生寝室或女生寝室")
    seats = _seat_map(plan["id"])
    by_id = {s["student_id"]: s.get("gender") for s in _students(class_id)}
    present = ["girl" if by_id.get(sid) == "女" else "boy"
               for (r, _c), sid in seats.items() if r == idx + 1 and by_id.get(sid)]
    if present and any(g != kind for g in present):
        raise ValueError("寝室内已有%s生，不能改为%s寝室" % (
            "男" if present[0] == "boy" else "女", "男生" if kind == "boy" else "女生"))
    meta["room_genders"][idx] = kind
    db.exec_("UPDATE layout_plans SET meta=?,updated_at=? WHERE id=?",
             (json.dumps(meta, ensure_ascii=False), db.now(), plan["id"]))
    return get_plan(class_id, "dorm")


def delete_room(class_id, room_name):
    """删除寝室，寝室内学生自动回到未分配区。"""
    plan = _ensure_plan(str(class_id), "dorm")
    meta = _parse_meta(plan["meta"])
    rows = int(plan["rows"])
    if rows <= 1:
        raise ValueError("至少保留一间寝室")
    meta = _room_meta(rows, meta.get("room_start") or ROOM_START,
                      meta.get("room_names"), meta.get("room_genders"))
    name = str(room_name or "").strip()
    if name not in meta["room_names"]:
        raise ValueError("寝室不存在")
    idx = meta["room_names"].index(name) + 1
    meta["room_names"].pop(idx - 1)
    meta["room_genders"].pop(idx - 1)
    # 寝室内学生回到未分配区：同步清空其寝室/床位，避免名单重建时复活已删寝室
    for (row_idx, _col), sid in _seat_map(plan["id"]).items():
        if row_idx == idx:
            roster.set_dorm_bed(class_id, sid, "", "")
    meta["roster_synced"] = True
    db.exec_many([
        ("DELETE FROM layout_seats WHERE plan_id=? AND row_idx=?", (plan["id"], idx)),
        ("UPDATE layout_seats SET row_idx=row_idx-1 WHERE plan_id=? AND row_idx>?",
         (plan["id"], idx)),
        ("UPDATE layout_plans SET rows=?,meta=?,updated_at=? WHERE id=?",
         (rows - 1, json.dumps(meta, ensure_ascii=False), db.now(), plan["id"])),
    ])
    return get_plan(class_id, "dorm")


def auto_arrange(class_id, kind):
    kind = _kind(kind)
    plan = _ensure_plan(str(class_id), kind)
    rows, cols = int(plan["rows"]), int(plan["cols"])
    students = _students(class_id)
    seats = {}
    if kind == "dorm":
        meta = _parse_meta(plan["meta"])
        genders = list(meta.get("room_genders") or [])
        while len(genders) < rows:
            genders.append("")
        boys = [s["student_id"] for s in students if s.get("gender") != "女"]
        girls = [s["student_id"] for s in students if s.get("gender") == "女"]
        for r in range(1, rows + 1):
            g = _norm_gender(genders[r - 1])
            if not g:
                g = "boy" if boys else "girl"
                genders[r - 1] = g
            pool = boys if g == "boy" else girls
            for c in range(1, cols + 1):
                if not pool:
                    break
                seats[(r, c)] = pool.pop(0)
        _write_seats(plan["id"], seats)
        meta["room_genders"] = genders
        db.exec_many([
            ("UPDATE layout_plans SET meta=?,updated_at=? WHERE id=?",
             (json.dumps(meta, ensure_ascii=False), db.now(), plan["id"])),
        ])
        return get_plan(class_id, kind)
    for i, stu in enumerate(students):
        if i >= rows * cols:
            break
        seats[(i // cols + 1, i % cols + 1)] = stu["student_id"]
    _write_seats(plan["id"], seats)
    db.exec_("UPDATE layout_plans SET updated_at=? WHERE id=?", (db.now(), plan["id"]))
    return get_plan(class_id, kind)


def clear(class_id, kind, operator=""):
    kind = _kind(kind)
    plan = _ensure_plan(str(class_id), kind)
    if kind == "dorm":
        # 清空寝室表：座位上学生同步清空寝室/床位并记录调宿台账
        for sid in set(_seat_map(plan["id"]).values()):
            roster.set_dorm_bed(class_id, sid, "", "", operator)
        meta = _parse_meta(plan["meta"])
        meta["roster_synced"] = True
        db.exec_many([
            ("DELETE FROM layout_seats WHERE plan_id=?", (plan["id"],)),
            ("UPDATE layout_plans SET meta=?,updated_at=? WHERE id=?",
             (json.dumps(meta, ensure_ascii=False), db.now(), plan["id"])),
        ])
        return get_plan(class_id, kind)
    db.exec_("DELETE FROM layout_seats WHERE plan_id=?", (plan["id"],))
    db.exec_("UPDATE layout_plans SET updated_at=? WHERE id=?", (db.now(), plan["id"]))
    return get_plan(class_id, kind)
