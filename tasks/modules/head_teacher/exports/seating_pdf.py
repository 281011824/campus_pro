# -*- coding: utf-8 -*-
"""把座位表 / 寝室表渲染成可打印的 A4 横向 PDF。"""

import io
import os
from datetime import datetime
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from tasks.modules.head_teacher import seating

FONT_NAME = "HTWCJK"
_FONT_READY = False

_FONT_CANDIDATES = [
    os.environ.get("SEAT_PDF_FONT") or "",
    "/opt/school_pro/assets/fonts/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]

RED = HexColor("#4A0C0C")
GOLD = HexColor("#C9A84C")
INK = HexColor("#1E1C19")
SUB = HexColor("#6E675C")
MUTED = HexColor("#9A9386")
LINE = HexColor("#E2DACB")
CREAM = HexColor("#FBF7EE")
PAPER = HexColor("#FCFAF5")
BOY = HexColor("#5B7FA6")
GIRL = HexColor("#C4736A")
BOY_BG = HexColor("#EAF2FA")
GIRL_BG = HexColor("#FDF0F2")


def _font():
    global _FONT_READY
    if _FONT_READY:
        return FONT_NAME
    for path in _FONT_CANDIDATES:
        if not path or not Path(path).exists():
            continue
        try:
            if path.lower().endswith(".ttc"):
                pdfmetrics.registerFont(TTFont(FONT_NAME, path, subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont(FONT_NAME, path))
            _FONT_READY = True
            return FONT_NAME
        except Exception:
            continue
    raise RuntimeError("服务器缺少中文字体，无法导出 PDF")


def _text(c, x, y, s, size, color=INK, align="left"):
    c.setFont(FONT_NAME, size)
    c.setFillColor(color)
    if align == "center":
        c.drawCentredString(x, y, s)
    elif align == "right":
        c.drawRightString(x, y, s)
    else:
        c.drawString(x, y, s)


def _fit_size(s, width, size, floor=5.0):
    while size > floor and pdfmetrics.stringWidth(s, FONT_NAME, size) > width:
        size -= 0.5
    return size


def _student(c, x, y, w, h, stu):
    accent = GIRL if stu.get("gender") == "女" else BOY
    c.setFillColor(GIRL_BG if stu.get("gender") == "女" else BOY_BG)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.roundRect(x, y, w, h, 2.5, stroke=1, fill=1)
    c.setFillColor(accent)
    c.rect(x + 0.6, y + 2, 2.4, h - 4, stroke=0, fill=1)
    name = str(stu.get("name") or "")
    sid = str(stu.get("student_id") or "")
    ns = _fit_size(name, w - 10, min(10.5, h * 0.36), 6.0)
    _text(c, x + w / 2 + 1, y + h / 2 - ns * 0.32, name, ns, INK, "center")
    if h >= 24:
        _text(c, x + w / 2 + 1, y + 3.2, sid, min(6.2, h * 0.2), MUTED, "center")


def render(plan, now=None):
    """plan 为 seating.get_plan() 的返回值，返回 PDF 字节。"""
    _font()
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    kind = plan["kind"]
    rows, cols = int(plan["rows"]), int(plan["cols"])
    grid = plan["grid"]
    stats = plan["stats"]
    rooms = (plan.get("meta") or {}).get("room_names") or []

    buf = io.BytesIO()
    portrait = kind == "dorm" or rows >= 14
    width, height = A4 if portrait else landscape(A4)
    c = canvas.Canvas(buf, pagesize=(width, height))
    margin = 30
    title = "%s班%s" % (plan["class_id"], "座位表" if kind == "seat" else "寝室表")

    _text(c, margin, height - 42, title, 17, RED)
    _text(c, width - margin, height - 39, "京山市中等职业技术学校 · 班主任工作台", 8, MUTED, "right")
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.1)
    c.line(margin, height - 52, width - margin, height - 52)

    shape = ("%d 间寝室 × 每间 %d 床" % (rows, cols)) if kind == "dorm" else ("%d 行 × %d 列" % (rows, cols))
    meta = "%s · %s · 已排 %d 人 / 未排 %d 人" % (
        stamp, shape, stats["seated"], stats["unseated"])
    _text(c, margin, height - 66, meta, 8, SUB)

    content_top = height - 80
    foot = margin + 12
    gap = 5.0
    cell_w = (width - 2 * margin - (cols - 1) * gap) / cols

    if kind == "seat":
        bar_h = 19
        c.setFillColor(RED)
        c.roundRect(margin, content_top - bar_h, width - 2 * margin, bar_h, 3, stroke=0, fill=1)
        c.setFont(FONT_NAME, 10)
        c.setFillColor(HexColor("#F3E2AE"))
        c.drawCentredString(width / 2, content_top - bar_h + 6, "讲        台")
        grid_top = content_top - bar_h - 9
        avail = grid_top - foot
        cell_h = min(56.0, (avail - (rows - 1) * gap) / rows)
        _draw_grid(c, grid, margin, grid_top, cell_w, cell_h, gap)
    else:
        avail = content_top - foot
        block_h = (avail - (rows - 1) * gap) / rows
        cell_h = max(13.0, block_h - 12)
        for idx, line in enumerate(grid):
            top = content_top - idx * (block_h + gap)
            room_name = str(rooms[idx]) if idx < len(rooms) else str(1101 + idx)
            filled = sum(1 for cell in line if cell.get("student"))
            parts = seating.room_parts(room_name)
            label = "%s 寝室" % room_name
            if parts:
                label += " · %s号楼%s层%s室" % (parts["building"], parts["floor"], parts["room"])
            _text(c, margin, top - 8.5, label, 9, RED)
            _text(c, width - margin, top - 8.5, "已住 %d / %d" % (filled, len(line)), 7.5, MUTED, "right")
            c.setStrokeColor(LINE)
            c.setLineWidth(0.5)
            c.line(margin, top - 11.5, width - margin, top - 11.5)
            _draw_grid(c, [line], margin, top - 13, cell_w, cell_h, gap,
                       start_row=idx + 1, kind="dorm")

    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(margin, foot - 2, width - margin, foot - 2)
    _text(c, margin, foot - 11, "班主任工作台 · 班级空间 · 拖动排位后导出", 7, MUTED)
    _text(c, width - margin, foot - 11, "第 1 页 / 共 1 页", 7, MUTED, "right")

    c.showPage()
    c.save()
    return buf.getvalue()


def _draw_grid(c, grid, left, top, cell_w, cell_h, gap, start_row=1, kind="seat"):
    for idx, line in enumerate(grid):
        row_no = start_row + idx
        y = top - idx * (cell_h + gap) - cell_h
        for col_no, cell in enumerate(line, 1):
            x = left + (col_no - 1) * (cell_w + gap)
            stu = cell.get("student")
            label = ("%d床" % col_no) if kind == "dorm" else ("%d排%d座" % (row_no, col_no))
            if stu:
                _text(c, x + 4, y + cell_h - 8, label, 6.0, MUTED)
                _student(c, x, y, cell_w, cell_h - 9, stu)
            else:
                c.setFillColor(PAPER)
                c.setStrokeColor(LINE)
                c.setLineWidth(0.5)
                c.setDash(2, 2)
                c.roundRect(x, y, cell_w, cell_h, 2.5, stroke=1, fill=1)
                c.setDash()
                _text(c, x + 4, y + cell_h - 8, label, 6.0, MUTED)
                _text(c, x + cell_w / 2, y + cell_h / 2 - 3, "空位", 6.8, HexColor("#BDB6A8"), "center")
