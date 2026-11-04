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


def abstract_columns(page, fallback=1):
    """根据摘要叙述行的实际宽度识别栏式。"""
    blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
    active = False
    for block in blocks:
        rows = block.get("lines", [])
        text = " ".join(s["text"] for row in rows for s in row["spans"])
        if re.match(r"^(?:Abstract\b|摘\s*要)", text.strip(), re.I):
            active = True
        if not active:
            continue
        widths = [row["bbox"][2]-row["bbox"][0] for row in rows
                  if len("".join(s["text"] for s in row["spans"])) > 30]
        if widths:
            return 1 if median(widths) > page.rect.width * .6 else 2
    return fallback
