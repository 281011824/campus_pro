# -*- coding: utf-8 -*-
"""只读对比两份 dywork.db 的关键主数据，用于双机一致性审计。

用法：
    python tools/db_audit.py <主库.db> <备库.db>

退出码：0 一致；1 存在差异；2 文件或表缺失。
"""

import json
import sqlite3
import sys

TABLES = ("classes", "students", "head_teacher_pool", "account_bindings")


def _snapshot(path):
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    con.row_factory = sqlite3.Row

    def q(sql, args=()):
        return [dict(r) for r in con.execute(sql, args).fetchall()]

    try:
        data = {
            "class_counts": q(
                "SELECT c.class_id, COALESCE(c.name,'') AS name, COUNT(s.student_id) AS n "
                "FROM classes c LEFT JOIN students s ON s.class_id=c.class_id "
                "GROUP BY c.class_id ORDER BY c.class_id"),
            "classes": q(
                "SELECT class_id, name, grade, major, head_teacher_userid, status "
                "FROM classes ORDER BY class_id"),
            "students_2607": q(
                "SELECT student_id, student_no, name, gender, dorm, bed_no "
                "FROM students WHERE class_id='2607' ORDER BY student_id"),
            "pool": q("SELECT userid FROM head_teacher_pool ORDER BY userid"),
            "bindings": q(
                "SELECT userid, class_ids FROM account_bindings "
                "WHERE portal='headteacher' ORDER BY userid"),
        }
    finally:
        con.close()
    return data


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip())
        return 2
    try:
        a, b = _snapshot(sys.argv[1]), _snapshot(sys.argv[2])
    except sqlite3.Error as exc:
        print("读取数据库失败：%s" % exc)
        return 2

    diffs = []
    for key in ("classes", "class_counts", "students_2607", "pool", "bindings"):
        if a[key] != b[key]:
            diffs.append({"key": key, "primary_rows": len(a[key]), "mirror_rows": len(b[key])})

    report = {
        "identical": not diffs,
        "diffs": diffs,
        "primary": {"class_counts": a["class_counts"], "pool": len(a["pool"])},
        "mirror": {"class_counts": b["class_counts"], "pool": len(b["pool"])},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())
