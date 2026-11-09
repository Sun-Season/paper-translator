"""从正文行估计论文的栏数、版心和各页的分栏方式。"""
from collections import Counter
from statistics import median
import re

import pymupdf


def page_measurements(page):
    width=page.rect.width
    left=[];right=[];full=[]
    # 图注可能通栏，表内的短标签可能左右并列。只统计连续的叙述行。
    for block in page.get_text("dict",flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        rows=block.get("lines",[])
        if len(rows)<2:continue
        first="".join(s["text"] for s in rows[0]["spans"]).strip()
        if re.match(r"^(?:Fig(?:ure)?\.?|Table|图|表)\s*[A-Z]?\d+\s*[:：.]",first,re.I):continue
        for line in rows:
            if abs(line["dir"][1])>.1:continue
            text="".join(s["text"] for s in line["spans"]).strip()
            if len(re.findall(r"[A-Za-z]{2,}",text))<5 and len(re.findall("[一-鿿]",text))<12:continue
            r=pymupdf.Rect(line["bbox"])
            if r.width<width*.22:continue
            if r.x0<width*.39 and r.x1>width*.61:full.append(r)
            elif r.x1<width*.515:left.append(r)
            elif r.x0>width*.485:right.append(r)
    paired=min(len(left),len(right))
    if paired>=3 and paired*2>=len(full):
        return 2,left+right
    if len(full)>=3:return 1,full
    return None,[]


def source_layout(doc):
    observations=[page_measurements(pg) for pg in doc]
    votes=Counter(c for c,_ in observations if c)
    default=votes.most_common(1)[0][0] if votes else 1
    resolved=[]
    for i,(c,_) in enumerate(observations):
        if c is None:
            nearby=[(abs(k-i),k,v) for k,(v,_) in enumerate(observations) if v]
            c=min(nearby)[2] if nearby else default
        resolved.append(c)
    # 用较长的行估计原稿正文左右边距，避免段末短行影响版心宽度。
    margins=[]
    for pg,(c,rows) in zip(doc,observations):
        if not rows:continue
        xs=sorted(r.x0 for r in rows); ends=sorted(r.x1 for r in rows)
        margins.append((xs[len(xs)//10],pg.rect.width-ends[min(len(ends)-1,len(ends)*9//10)]))
    left,right=(map(median,zip(*margins)) if margins else (42,42))
    return resolved,(left,right)


def spans_gutter(box,page_width):
    return box.x0<page_width*.48 and box.x1>page_width*.52


def _page_lines(page):
    lines = []
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        rows = block.get("lines", [])
        if not rows:
            continue
        first = "".join(s["text"] for s in rows[0]["spans"]).strip()
        lines.append((rows, first))
    return lines


def abstract_layout(page, body_columns=1, text_measure=None, left=None, right=None):
    """识别摘要区域及其栏结构。

    返回结构给渲染器使用：栏数、区域坐标、窄版心与居中、版心宽度。
    判断依据是区域内的栏间空白和行首位置分布，而不是单行宽度占页宽的比例。
    """
    page_width = page.rect.width
    left = page_width * .1 if left is None else left
    right = page_width * .1 if right is None else right
    measure = (page_width - left - right) if text_measure is None else text_measure
    blocks = _page_lines(page)
    start = None
    for index, (rows, first) in enumerate(blocks):
        if re.match(r"^(?:Abstract\b|摘\s*要)", first, re.I):
            start = index
            break
    result = {"columns": 1, "box": None, "measure": measure, "narrow": False,
              "centered": False, "left_indent": 0.0, "right_indent": 0.0}
    if start is None:
        return result

    region = []
    for index in range(start, len(blocks)):
        rows, first = blocks[index]
        heading = " ".join("".join(s["text"] for s in row["spans"]) for row in rows[:2]).strip()
        if index > start and re.match(
                r"^(?:\d+[.、．]?\s*[A-Z]|[IVX]+\.?\s+[A-Z]|Introduction\b|引\s*言|绪\s*论)", heading):
            break
        if re.match(r"^(?:Fig(?:ure)?\.?|Table|图|表)\s*[A-Z]?\d+\s*[:：.]", heading, re.I):
            break
        for row in rows:
            if abs(row["dir"][1]) > .1:
                continue
            text = "".join(s["text"] for s in row["spans"]).strip()
            if text:
                region.append(pymupdf.Rect(row["bbox"]))
    if not region:
        return result

    box = pymupdf.Rect(region[0])
    for rect in region[1:]:
        box |= rect

    # 栏间空白：找一条没有任何行横跨的竖直空白带，并确认两侧都有足够行。
    edges = sorted({round(rect.x0, 1) for rect in region} | {round(rect.x1, 1) for rect in region})
    gutter = None
    for start_edge, end_edge in zip(edges, edges[1:]):
        width = end_edge - start_edge
        if width < max(10, measure * .06):
            continue
        middle = (start_edge + end_edge) / 2
        if not (left + measure * .35 <= middle <= left + measure * .65):
            continue
        crossing = sum(1 for rect in region if rect.x0 < middle < rect.x1)
        if crossing:
            continue
        left_rows = [rect for rect in region if rect.x1 <= middle]
        right_rows = [rect for rect in region if rect.x0 >= middle]
        if len(left_rows) >= 3 and len(right_rows) >= 3:
            if gutter is None or width > gutter[0]:
                gutter = (width, middle)
    columns = 2 if gutter else 1

    columns = max(1, min(columns, body_columns or 1))
    left_indent = max(0.0, box.x0 - left)
    right_indent = max(0.0, (page_width - right) - box.x1)
    narrow = columns == 1 and box.width < measure * .82
    centered = narrow and abs(left_indent - right_indent) <= max(6, measure * .08)
    result.update({"columns": columns, "box": [round(v, 2) for v in box],
                   "measure": round(measure, 2), "narrow": narrow, "centered": centered,
                   "left_indent": round(left_indent, 2), "right_indent": round(right_indent, 2)})
    return result


def abstract_columns(page, fallback=1):
    """兼容旧接口：返回摘要区域栏数。"""
    return abstract_layout(page, fallback)["columns"]
