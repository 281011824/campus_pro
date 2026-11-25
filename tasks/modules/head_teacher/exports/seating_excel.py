# -*- coding: utf-8 -*-
"""把座位表 / 寝室表导出为 Excel。

- 座位表：按行列网格，男生浅蓝、女生淡粉。
- 寝室表：每间寝室 6 人为一个单元，外框按男寝蓝色 / 女寝粉色区分。
"""

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from tasks.modules.head_teacher import seating

INK = "FF1E1C19"
SUB = "FF6E675C"
MUTED = "FF9A9386"
RED = "FF4A0C0C"
GOLD_BG = "FFF7F2E7"
EMPTY_BG = "FFFCFAF5"
BOY_BG = "FFEAF2FA"
GIRL_BG = "FFFDF0F2"
MIX_BG = "FFFFF7E6"
BOY_LINE = "FF5B7FA6"
GIRL_LINE = "FFC4736A"
MIX_LINE = "FFC9A84C"
EMPTY_LINE = "FFBDB6A8"
THIN = "FFDCD3C1"

_GENDER_TEXT = {"boy": "男寝", "girl": "女寝", "mixed": "混合", "empty": "空寝"}
_GENDER_FILL = {"boy": BOY_BG, "girl": GIRL_BG, "mixed": MIX_BG, "empty": "FFF4F1EA"}
_GENDER_LINE = {"boy": BOY_LINE, "girl": GIRL_LINE, "mixed": MIX_LINE, "empty": EMPTY_LINE}


def _fill(color):
    return PatternFill("solid", fgColor=color)


def _side(color, style="thin"):
    return Side(style=style, color=color)


def _header(c, text, width, row=1):
    c.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(width, 1))
    cell = c.cell(row=row, column=1, value=text)
    cell.font = Font(name="Microsoft YaHei", size=16, bold=True, color=RED)
    cell.alignment = Alignment(horizontal="left", vertical="center")
    c.row_dimensions[row].height = 26


def _sub(c, text, width, row=2):
    c.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(width, 1))
    cell = c.cell(row=row, column=1, value=text)
    cell.font = Font(name="Microsoft YaHei", size=9, color=SUB)
    cell.alignment = Alignment(horizontal="left", vertical="center")


def _student_cell(cell, stu, line_color=THIN, thick=False):
    if not stu:
        cell.value = "空位"
        cell.font = Font(name="Microsoft YaHei", size=9, color=MUTED)
        cell.fill = _fill(EMPTY_BG)
        style = "thin"
        color = line_color
    else:
        cell.value = "%s\n%s" % (stu.get("name") or "", stu.get("student_id") or "")
        cell.font = Font(name="Microsoft YaHei", size=10.5, color=INK, bold=True)
        cell.fill = _fill(GIRL_BG if stu.get("gender") == "女" else BOY_BG)
        style = "medium" if thick else "thin"
        color = line_color
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = Border(left=_side(color, style), right=_side(color, style),
                         top=_side(color, style), bottom=_side(color, style))


def _sheet_seat(ws, plan, stamp):
    rows, cols = plan["rows"], plan["cols"]
    line_rows = sum(1 for line in plan["grid"] if any(x["student"] for x in line))
    _header(ws, "%s班座位表" % plan["class_id"], cols + 1)
    _sub(ws, "%s · %d 行 × %d 列 · 已排 %d 人 / 未排 %d 人" %
         (stamp, rows, cols, plan["stats"]["seated"], plan["stats"]["unseated"]), cols + 1)
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=cols + 1)
    bar = ws.cell(row=3, column=1, value="讲        台")
    bar.fill = _fill("FF4A0C0C")
    bar.font = Font(name="Microsoft YaHei", size=11, bold=True, color="FFF3E2AE")
    bar.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[3].height = 22

    for col in range(2, cols + 2):
        h = ws.cell(row=4, column=col, value="%d列" % (col - 1))
        h.font = Font(name="Microsoft YaHei", size=9, color=SUB)
        h.fill = _fill(GOLD_BG)
        h.alignment = Alignment(horizontal="center", vertical="center")
    ws.cell(row=4, column=1, value="").fill = _fill(GOLD_BG)

    for r, line in enumerate(plan["grid"], 1):
        row = 4 + r
        tag = ws.cell(row=row, column=1, value="%d排" % r)
        tag.font = Font(name="Microsoft YaHei", size=8, color=MUTED)
        tag.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[row].height = 34
        for c, cell in enumerate(line, 2):
            _student_cell(ws.cell(row=row, column=c), cell["student"])

    note_row = 5 + rows
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=cols + 1)
    note = ws.cell(row=note_row, column=1,
                   value="图例：男生浅蓝 / 女生淡粉　·　班主任工作台 · 班级空间　·　共 %d 排有学生" % line_rows)
    note.font = Font(name="Microsoft YaHei", size=8, color=MUTED)
    ws.column_dimensions["A"].width = 7
    for c in range(2, cols + 2):
        ws.column_dimensions[get_column_letter(c)].width = 14
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def _sheet_dorm(ws, plan, stamp):
    rows, cols = plan["rows"], plan["cols"]
    rooms = (plan.get("meta") or {}).get("room_names") or []
    fixed = (plan.get("meta") or {}).get("room_genders") or []
    _header(ws, "%s班寝室表" % plan["class_id"], cols)
    _sub(ws, "%s · %d 间寝室 × 每间 %d 床 · 已住 %d 人" %
         (stamp, rows, cols, plan["stats"]["seated"]), cols)

    for i, line in enumerate(plan["grid"]):
        gender = (fixed[i] if i < len(fixed) and fixed[i] else "") or seating.room_gender(line)
        filled = sum(1 for x in line if x["student"])
        top = 4 + i * 3
        head = 4 + i * 3
        last = top + 1
        for c in range(1, cols + 1):
            cell = ws.cell(row=head, column=c)
            cell.fill = _fill(_GENDER_FILL[gender])
            cell.border = Border(
                left=_side(_GENDER_LINE[gender], "medium" if c == 1 else "thin"),
                right=_side(_GENDER_LINE[gender], "medium" if c == cols else "thin"),
                top=_side(_GENDER_LINE[gender], "medium"),
                bottom=_side(_GENDER_LINE[gender], "thin"))
        ws.merge_cells(start_row=head, start_column=1, end_row=head, end_column=cols)
        title_text = "%s 寝室" % (rooms[i] if i < len(rooms) else (1101 + i))
        parts = seating.room_parts(rooms[i] if i < len(rooms) else '')
        if parts:
            title_text += "（%s号楼 %s层 %s室）" % (parts["building"], parts["floor"], parts["room"])
        title = ws.cell(row=head, column=1,
                        value="%s　·　%s　·　已住 %d / %d" % (
                            title_text, _GENDER_TEXT[gender], filled, len(line)))
        title.font = Font(name="Microsoft YaHei", size=11, bold=True,
                          color=_GENDER_LINE[gender])
        title.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[head].height = 21

        for c, cell in enumerate(line, 1):
            target = ws.cell(row=last, column=c)
            _student_cell(target, cell["student"], _GENDER_LINE[gender])
            edge = _side(_GENDER_LINE[gender], "medium")
            target.border = Border(
                left=edge if c == 1 else _side(THIN),
                right=edge if c == cols else _side(THIN),
                top=_side(_GENDER_LINE[gender], "medium"),
                bottom=edge)
        ws.row_dimensions[last].height = 36
        ws.row_dimensions[top + 2].height = 6

    note_row = 4 + rows * 3
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=cols)
    note = ws.cell(row=note_row, column=1,
                   value="图例：男生浅蓝 / 女生淡粉；男寝外框蓝色、女寝外框粉色　·　班主任工作台")
    note.font = Font(name="Microsoft YaHei", size=8, color=MUTED)
    for c in range(1, cols + 1):
        ws.column_dimensions[get_column_letter(c)].width = 14
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def render(plan, now=None):
    """plan 为 seating.get_plan() 的返回值，返回 xlsx 字节。"""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    wb = Workbook()
    ws = wb.active
    if plan["kind"] == "dorm":
        ws.title = "寝室表"
        _sheet_dorm(ws, plan, stamp)
    else:
        ws.title = "座位表"
        _sheet_seat(ws, plan, stamp)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
