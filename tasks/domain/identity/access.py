# -*- coding: utf-8 -*-
"""班级数据访问范围：只有本班班主任可以查看本班学生信息。"""

from tasks.domain.identity import org
from tasks.shared import db


def headteacher_classes(user_id):
    """当前用户担任班主任的班级（通讯录职务与账号映射合并后的结果）。"""
    classes = set()
    for p in org.posts_of(user_id):
        if p.get("portal") == "headteacher":
            classes.update(db.loads(p.get("class_ids"), []))
    return classes


def can_view_class(user_id, class_id):
    return str(class_id) in headteacher_classes(user_id)
