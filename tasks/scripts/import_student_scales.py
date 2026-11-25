# -*- coding: utf-8 -*-
"""量表种子：从参照包 growth_nav.db 导出启用量表，或从种子 json 导入正式库。

用法（在仓库根目录 pro/ 下执行）：
    python -m tasks.scripts.import_student_scales --write   # 先导出到 data/scales_seed.json 再导入
    python -m tasks.scripts.import_student_scales           # 仅从 json 导入

去重口径：量表按 code+version、题目按 scale_id+item_no，重复执行数量不变。
只导出参照包中 status=1（启用）的量表。
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.shared import db
from tasks.modules.student import student_portal  # noqa: E402

REF_DB = ROOT / "growth-nav-测试包-20261110" / "runtime" / "growth_nav.db"
SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "scales_seed.json"


def _json(value, default):
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def export_seed(source=REF_DB, target=SEED_PATH):
    """从参照包导出 status=1 的量表与题目，写入种子 json。"""
    source = Path(source)
    target = Path(target)
    if not source.exists():
        raise SystemExit("参照包数据库不存在：%s" % source)
    conn = sqlite3.connect(str(source))
    conn.row_factory = sqlite3.Row
    try:
        scales = []
        for row in conn.execute(
                "SELECT * FROM scales WHERE status=1 ORDER BY id"):
            items = []
            for item in conn.execute(
                    "SELECT item_no,stem,options_json,dimension,reverse,option_dims_json "
                    "FROM items WHERE scale_id=? ORDER BY item_no", (int(row["id"]),)):
                items.append({
                    "item_no": int(item["item_no"]),
                    "stem": item["stem"],
                    "options": _json(item["options_json"], []),
                    "dimension": item["dimension"] or "",
                    "reverse": int(item["reverse"] or 0),
                    "option_dims": _json(item["option_dims_json"], None),
                })
            scales.append({
                "code": row["code"],
                "version": row["version"],
                "title": row["title"],
                "item_count": int(row["item_count"] or len(items)),
                "minutes": int(row["minutes"] or 0),
                "dimension_json": _json(row["dimension_json"], {}),
                "status": 1,
                "items": items,
            })
    finally:
        conn.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source": str(source), "exported_at": db.now(), "scales": scales}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def import_seed(seed_path=SEED_PATH):
    """从种子 json 导入正式库，返回导入结果与库内计数。"""
    seed_path = Path(seed_path)
    if not seed_path.exists():
        raise SystemExit("种子文件不存在，请先执行 --write：%s" % seed_path)
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    db.init_db()
    result = student_portal.import_scales(payload.get("scales") or [])
    result["scales_total"] = student_portal.count_scales()
    result["items_total"] = student_portal.count_items()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="学生测评量表导出与导入")
    parser.add_argument("--write", action="store_true", help="先从参照包导出种子 json")
    parser.add_argument("--source", default=str(REF_DB), help="参照包 growth_nav.db 路径")
    parser.add_argument("--seed", default=str(SEED_PATH), help="种子 json 路径")
    args = parser.parse_args(argv)

    if args.write:
        payload = export_seed(args.source, args.seed)
        print("已导出量表 %d 个、题目 %d 道 → %s"
              % (len(payload["scales"]),
                 sum(len(s["items"]) for s in payload["scales"]), args.seed))
    result = import_seed(args.seed)
    print("导入完成：新增量表 %d、更新量表 %d、新增题目 %d、更新题目 %d"
          % (result["scales_added"], result["scales_updated"],
             result["items_added"], result["items_updated"]))
    print("库内启用量表 %d 个、题目 %d 道" % (result["scales_total"], result["items_total"]))
    return result


if __name__ == "__main__":
    main()
