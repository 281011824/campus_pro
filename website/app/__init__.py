"""
@author axiner
@version v1.0.0
@created 2024/07/29 22:22
@abstract app
@description
@history
"""
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
# 单体化后需 import tasks/head_teacher_workbench 业务模块，
# 将项目根目录（/opt/school_pro）加入 sys.path 最前。
_PROJECT_ROOT = APP_DIR.parent.parent  # website/ → 项目根
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
