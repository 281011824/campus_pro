# -*- coding: utf-8 -*-
"""生成演示数据：一次考试（等第/趋势）与成长档案记录。

用法（在仓库根目录 pro/ 下执行）：
    DB_PATH=/opt/school_pro/runtime/dywork.db python -m tasks.scripts.seed_demo
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.modules.head_teacher import roster  # noqa: E402


def main():
    roster.init()
    result = roster.seed_demo("2607")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
