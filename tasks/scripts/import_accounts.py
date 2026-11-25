# -*- coding: utf-8 -*-
"""导入教师账号到 SQLite。

用法（在仓库根目录 pro/ 下执行）：
    python -m tasks.scripts.import_accounts /tmp/accounts.json
JSON 结构：[{userid,name,password_sha256,wecom_userid,dept,post_name,category,status}, ...]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.domain.identity import accounts  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("usage: python -m tasks.scripts.import_accounts <accounts.json>")
        return 2
    accounts.init()
    with open(sys.argv[1], encoding="utf-8") as fh:
        records = json.load(fh)
    n = accounts.import_records(records)
    print(json.dumps({"imported": n, **accounts.stats()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
