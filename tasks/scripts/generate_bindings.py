# -*- coding: utf-8 -*-
"""生成全校账号 → 职务与班级映射。

用法（在仓库根目录 pro/ 下执行）：
    DB_PATH=/opt/school_pro/runtime/dywork.db python -m tasks.scripts.generate_bindings
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.domain.identity import bindings  # noqa: E402


def main():
    bindings.init()
    result = bindings.generate()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
