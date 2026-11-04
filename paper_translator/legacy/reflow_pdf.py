"""从译文重建阅读顺序，重新断行、分页，并嵌回原 PDF 的图和公式。"""

import base64
import html
import io
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf as pdf
from PIL import Image

from paper_translator.source.equation_layout import numbered_equations, outside_equations
from paper_translator.legacy.reading_pdf import CAPTION, NUMBER, REFERENCE, lines, source_figures


@dataclass
class Item:
    page: int
    box: pdf.Rect
    kind: str
    text: str = ""
    anchor: str = ""
    joins: tuple = ()


def inline(block):
    result = ""
    for line in block["lines"]:
        spans = [s for s in line["spans"] if s["text"].strip()]
        if not spans:
            continue
        main = max(spans, key=lambda s: s["size"])
        line_text = ""
        for s in line["spans"]:
            value = html.escape(s["text"].replace("\x00", "").replace("\x03", " "))
            if s["size"] < main["size"] * 0.89 and abs(s["origin"][1]-main["origin"][1]) > main["size"]*.10:
                tag = "sup" if s["origin"][1] < main["origin"][1] else "sub"
                value = f"<{tag}>{value}</{tag}>"
            line_text += value
        if result.endswith("-") and re.match("[a-z]", line_text):
            result = result[:-1]
        elif re.search(r"[a-zA-Z0-9.,;:]$", result) and re.match(
            "[a-zA-Z0-9]", line_text
        ):
            result += " "
        result += line_text
    return result.strip()


def order(items, width):
    # 跨栏标题和插图把双栏页分为上下几段。每段先读左栏，再读右栏。
    mid = width / 2
    wide = sorted(
        (i for i in items if i.box.x0 < width*.4 and i.box.x1 > width*.6),
        key=lambda i: i.box.y0,
    )
    narrow = [i for i in items if i not in wide]
    for separator in [*wide, None]:
        edge = separator.box.y0 if separator else float("inf")
        before = [i for i in narrow if i.box.y0 < edge]
        yield from sorted(before, key=lambda i: (i.box.x0 >= mid, i.box.y0, i.box.x0))
        narrow = [i for i in narrow if i not in before]
        if separator:
            yield separator


def restore_paragraphs(blocks, original, audit):
    """按原稿段落、栏和行距合并翻译后被拆开的文字，保留原始字符顺序。"""
    guides = []
    for b in original.get_text("dict",flags=pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES)["blocks"]:
        text = inline(b)
        if len(text)>65 or CAPTION.match(text):
            guides.append(pdf.Rect(b["bbox"]))
    groups = []
    previous = None
    for block in blocks:
        if not block.get("lines") or not inline(block):
            groups.append(dict(block))
            previous = None
            continue
        r = pdf.Rect(block["bbox"])
        first = pdf.Rect(block["lines"][0]["bbox"])
        point = (first.tl + first.br)*.5
        matches = [k for k,g in enumerate(guides)
                   if (g+(-2,-9,2,5)).contains(point)]
        guide = matches[0] if len(matches)==1 else None
        if guide is not None and previous==guide:
            group=groups[-1]
            last=pdf.Rect(group["lines"][-1]["bbox"])
            gap=first.y0-last.y1
            # 正文和上下标可横向交叠；真正的新段一般有明显段前间距。
            if -max(20,last.height+4)<=gap<=max(3,min(last.height,first.height)*.42):
                before=inline({"lines":[group["lines"][-1]]})
                after=inline({"lines":[block["lines"][0]]})
                group["lines"].extend(block["lines"])
                group["bbox"]=tuple(pdf.Rect(group["bbox"])|r)
                if audit is not None:
                    plain=lambda t: html.unescape(re.sub("<[^>]+>","",t))
                    left,right=plain(before).strip(),plain(after).strip()
                    # 记录文字衔接。纯公式另以矢量裁片保留。
                    if re.search("[一-鿿]",left+right):
                        group.setdefault("joins",[]).append(left[-9:]+right[:9])
                continue
        groups.append({**block,"lines":list(block["lines"])})
        previous=guide
    return groups


def source_algorithms(page):
    """通过题头、同栏横线和连续步骤识别带边框的伪代码。"""
    rules = [pdf.Rect(g["rect"]) for g in page.get_drawings()
             if g["rect"].width > page.rect.width*.18 and g["rect"].height < 2]
    result = []
    for b in page.get_text("blocks"):
        title = re.match(r"^\s*(?:algorithm|算法)\s*(\d+)\b",b[4],re.I)
        if not title:
            continue
        x,y=b[:2]
        top=max((r for r in rules if abs(r.x0-x)<6 and 0<=y-r.y1<12),
                key=lambda r:r.y1,default=None)
        if top is None:
            continue
        for rule in sorted(rules,key=lambda r:r.y0):
            if abs(rule.x0-top.x0)>3 or abs(rule.x1-top.x1)>3 or rule.y0<=b[3]:
                continue
            box=pdf.Rect(top.x0-1,top.y0-1,top.x1+1,rule.y1+1)
            steps=re.findall(r"(?m)^\s*(\d+)\s*[:：]",page.get_textbox(box))
            if len(steps)>=2 and [int(n) for n in steps]==list(range(1,len(steps)+1)):
                result.append(Item(page.number,box,"source-algorithm",anchor="alg-"+title[1]))
                break
    return result


def page_items(page, regions, original=None, audit=None):
    blocks = page.get_text(
        "dict", flags=pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES
    )["blocks"]
    algorithms = source_algorithms(original) if original is not None else []
    if algorithms:
        # 译文换行可能略超出原边框，只过滤对应列；保留框后的正文。
        blocks = outside_equations(blocks,[a.box+(-2,-4,2,7) for a in algorithms])
    equations = numbered_equations(original) if original is not None else {}
    if equations:
        blocks = outside_equations(blocks,equations.values())
    if original is not None:
        blocks = restore_paragraphs(blocks,original,audit)
    items = []
    graphics = algorithms + [Item(page.number,r,"source-equation",anchor="eq-"+n) for n,r in equations.items()]
    for key, region in regions.items():
        candidates = [b for b in blocks if (m := CAPTION.match(inline(b))) and m[1] == key
                      and region.x0 <= pdf.Rect(b["bbox"]).x0 < region.x1]
        reason = f"原稿第 {page.number + 1} 页图 {key} 的图注边界无法确认"
        if len(candidates) != 1:
            raise ValueError(reason + "：未找到唯一匹配的译文图注。可用“保留原分页”导出。")
        r = pdf.Rect(region)
        r.y1 = pdf.Rect(candidates[0]["bbox"]).y0
        if r.y1 < r.y0 - 1 or abs(r.y1-region.y1) > max(36, page.rect.height * .07):
            raise ValueError(reason + "：译文图注与原稿位置不符。可用“保留原分页”导出。")
        for b in blocks:
            for line in b["lines"]:
                for span in line["spans"]:
                    box = pdf.Rect(span["bbox"])
                    if (span["text"].strip() and abs(line["dir"][1]) < .1
                        and box.x0 < r.x1 and r.x0 < box.x1
                        and box.y0 + 1 < r.y1 < box.y1 - 1):
                        raise ValueError(reason + "：裁图下边缘穿过文字。可用“保留原分页”导出。")
        if r.height > 5:
            graphics.append(Item(page.number, r, "visual", anchor="fig-" + key))
    # 未编号的照片、框图和表格也作为 PDF 裁片保留。
    extras = [pdf.Rect(im["bbox"]) for im in page.get_image_info()]
    drawings = [
        g
        for g in page.get_drawings()
        if any(c and min(c) < 0.95 for c in (g["color"], g["fill"]))
    ]
    if drawings:
        extras.extend(page.cluster_drawings(drawings=drawings))
    for b in blocks:
        ss = [s for line in b["lines"] for s in line["spans"] if s["text"].strip()]
        if ss and (
            re.fullmatch(r"[,，]?\s*[（(]\d+[)）]", inline(b))
            or all(re.search(r"^(CM|MSBM)|Math|Symbol", s["font"]) for s in ss)
            or all(line["dir"] != (1.0, 0.0) for line in b["lines"])
        ):
            extras.append(pdf.Rect(b["bbox"]))
    merged = []
    for r in extras:
        r = r & page.rect
        if r.is_empty or any(g.box.contains((r.tl + r.br) * 0.5) for g in graphics):
            continue
        # 合并同一公式的多行以及相接的绘图路径。
        remaining = []
        for other in merged:
            if (r + (-4, -6, 4, 6)).intersects(other):
                r |= other
            else:
                remaining.append(other)
        merged = remaining + [r]
    # 合并传递相邻的公式碎片，包括单独提取的右侧编号。
    pending = merged
    merged = []
    while pending:
        r = pending.pop()
        while True:
            neighbors = [b for b in pending if (r + (-5, -7, 5, 7)).intersects(b)]
            if not neighbors:
                break
            for b in neighbors:
                r |= b
                pending.remove(b)
        merged.append(r)
    for r in merged:
        if r.width < 3 or r.height < 2:
            continue
        graphics.append(Item(page.number, r + (-0.35, -0.35, 0.35, 0.35), "visual"))
    for b in blocks:
        r = pdf.Rect(b["bbox"])
        text = inline(b)
        if not text or any(g.box.contains((r.tl + r.br) * 0.5) for g in graphics):
            continue
        m = CAPTION.match(re.sub("<[^>]+>", "", text))
        header = bool(re.match(r"^(?:[IVX]+\.|[A-Z]\.)\s", text) and len(text) < 80)
        kind = (
            "caption"
            if m
            else "heading"
            if header or text in ("致谢", "参考文献", "附录")
            else "p"
        )
        if page.number == 0 and r.y0 < page.rect.height * 0.2:
            sizes = [s["size"] for l in b["lines"] for s in l["spans"]]
            if sizes and max(sizes) >= 15:
                kind = "title"
        items.append(Item(page.number, r, kind, text, joins=tuple(b.get("joins",[]))))
    # 有些独立公式没有绘图轮廓，编号和公式本体可能分属不同文本块。
    for v in graphics:
        if v.anchor:
            continue
        s = page.get_textbox(v.box)
        num = NUMBER.search(s.strip())
        if num and re.search(r"[=∥−ωπ]|[θ∑∫]", s):
            v.anchor = "eq-" + num[1]
        elif re.search(r"[=≈∝]", s) and re.search(r"[θπω∑∫]", s):
            v.anchor = f"display-{page.number + 1}-{round(v.box.y0)}"
    return list(order(items + graphics, page.rect.width))


def preserve_ruled_tables(items, page):
    captions = [b for b in page.get_text("blocks") if re.match(r"^Table\s+\d+\b", b[4])]
    if not captions:
        return items
    rules = [g["rect"] for g in page.get_drawings() if g["type"] == "s"
             and g["rect"].height < 1.5 and g["rect"].width > page.rect.width*.35]
    for caption in captions:
        cap = pdf.Rect(caption[:4])
        starts = [r for r in rules if -1 <= r.y0-cap.y1 < 25 and abs(r.x0-cap.x0)<8]
        if not starts:
            continue
        first = min(starts,key=lambda r:r.y0)
        bounds = [r for r in rules if r.y0 >= first.y0 and abs(r.x0-first.x0)<2
                  and abs(r.x1-first.x1)<2]
        next_cap = min((b[1] for b in captions if b[1]>cap.y1),default=page.rect.height)
        bounds = [r for r in bounds if r.y1 < next_cap]
        if len(bounds)<3:
            continue
        # 零高度横线取并集时会被 PDF 库忽略，直接从端点构造裁区。
        box = pdf.Rect(first.x0-1,first.y0-1,first.x1+1,max(r.y1 for r in bounds)+1)
        inside = [i for i,it in enumerate(items) if box.contains((it.box.tl+it.box.br)*.5)]
        if inside:
            items = [Item(page.number,box,"source-table") if i==inside[0] else it
                     for i,it in enumerate(items) if i==inside[0] or i not in inside]
        for it in items:
            if it.kind=="p" and it.box.intersects(cap) and re.match(r"^表\s*\d",it.text):
                it.kind="caption"
    return items


def repair_prose(items, source, settings):
    from paper_translator.legacy.inline_equations import TOKEN, translated_template
    pages = {}
    def source_block(it):
        if it.page not in pages:
            pages[it.page] = source[it.page].get_text("dict",flags=pdf.TEXTFLAGS_TEXT)["blocks"]
        matches = [b for b in pages[it.page] if pdf.Rect(b["bbox"]).intersects(it.box)
                   and abs(b["bbox"][0]-it.box.x0)<6 and abs(b["bbox"][1]-it.box.y0)<9
                   and abs(b["bbox"][3]-it.box.y1)<18]
        return matches[0] if len(matches)==1 else None

    def translate(blocks):
        slots = []
        phrases = []
        for block in blocks:
            for line in block["lines"]:
                base = max(line["spans"],key=lambda s:len(s["text"]))
                phrase = ""
                for span in line["spans"]:
                    value = span["text"]
                    if re.search(r"^(?:CMMI|CMSY|CMEX|MSBM)|Math",span["font"]):
                        glyph = html.escape(value.strip())
                        dy = span["origin"][1]-base["origin"][1]
                        if abs(dy)>1 and span["size"] < base["size"]*.9:
                            tag = "sub" if dy>0 else "sup"
                            glyph = f"<{tag}>{glyph}</{tag}>"
                        phrase += f"[[M{len(slots)}]]"
                        slots.append(glyph)
                    else:
                        phrase += value
                phrases.append(phrase.strip())
        translated = translated_template(" ".join(phrases),*settings)
        return TOKEN.sub(lambda m:slots[int(m[1])],html.escape(translated))

    prose = [it for it in items if it.kind in ("p","heading","list-item","bib","caption")]
    previous = None
    for it in prose:
        if it.kind=="caption":
            if re.match(r"^表\s*\d",it.text) and (block:=source_block(it)):
                it.text = translate([block])
            continue
        if it.kind!="p" or "@@" in it.text:
            previous = None
            continue
        if previous and previous.page+1==it.page:
            left,right=source_block(previous),source_block(it)
            if left and right and re.search(r"[A-Za-z]$",inline(left)) and re.match(r"^[a-z]+\b",inline(right)):
                previous.text=translate([left,right])
                it.text=""
                previous=None
                continue
        if re.search(r"[一-鿿]\s*(?:ed|th|ing)\b|\b(?:ed|th)\s*[一-鿿]",it.text) and (block:=source_block(it)):
            it.text=translate([block])
        previous=it


def restore_source_roles(items, original):
    blocks = original.get_text("blocks")
    result = []
    listed = set()
    for b in blocks:
        m = re.match(r"^([1-9]\d*)[.)]\s+", b[4].strip())
        if m:
            listed.add(int(m[1]))
    i = 0
    while i < len(items):
        it = items[i]
        i += 1
        text = it.text.strip()
        if it.kind != "p":
            result.append(it)
            continue
        if (text == str(original.number + 1) and it.box.y0 > .90 * original.rect.height
                and abs((it.box.x0 + it.box.x1)/2 - original.rect.width/2) < 12):
            continue
        if re.match(r"^[†‡*]\s*(?:通讯作者|通信作者|corresponding author)", text, re.I):
            it.kind = "author-note"
        elif re.match(r"^(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\s+\S", text) and any(
            pdf.Rect(b[:4]).intersects(it.box) and len(b[4].strip()) < 110
            and re.match(r"^" + re.escape(text.split()[0]) + r"\s", b[4].strip()) for b in blocks
        ):
            it.kind = "heading"
        cap = re.match(r"^图\s*(\d+)\s+", text)
        if cap:
            guide = next((pdf.Rect(b[:4]) for b in blocks if
                re.match(r"^Figure\s+" + cap[1] + r"\b", b[4].strip(), re.I)
                and pdf.Rect(b[:4]).intersects(it.box)), None)
            if guide:
                while i < len(items) and items[i].kind == "p" and guide.contains((items[i].box.tl+items[i].box.br)*.5):
                    it.text += items[i].text
                    it.box |= items[i].box
                    i += 1
                it.kind = "caption"
                it.text = re.sub(r"^(图\s*\d+)\s+", r"\1：", it.text, count=1)
                if result and result[-1].kind == "visual" and not result[-1].anchor and 0 <= it.box.y0-result[-1].box.y1 < 20:
                    result[-1].anchor = "fig-" + cap[1]
        if it.kind == "p" and 1 in listed and 2 in listed and re.match(r"^1[.)]\s+", text):
            merged = text
            while i < len(items) and items[i].kind == "p" and abs(items[i].box.x0-it.box.x0)<2 and items[i].box.y0-it.box.y1 < 5:
                merged += items[i].text
                it.box |= items[i].box
                i += 1
            starts = list(re.finditer(r"(?<![\d.])([1-9]\d*)[.)]\s+", merged))
            if [int(m[1]) for m in starts] == list(range(1,len(starts)+1)) and len(starts) >= 2 and all(int(m[1]) in listed for m in starts):
                for k,m in enumerate(starts):
                    end = starts[k+1].start() if k+1 < len(starts) else len(merged)
                    result.append(Item(it.page,it.box,"list-item",merged[m.start():end].strip()))
                continue
            it.text = merged
        result.append(it)
    return result


def bibliography(items):
    """按原始编号拆分书目，合并同一条目在不同栏和页上的续文。"""
    entry = None
    active = False
    entries = set()
    result = []
    pattern = re.compile(r"\[(\d{1,3})\]")
    for item in items:
        plain = re.sub("<[^>]+>", "", item.text).strip()
        if re.fullmatch(r"参考文献|references|bibliography", plain, re.I):
            active = True
            result.append(item)
            continue
        if item.kind in ("heading","title") or re.match(r"^(?:附录|appendix\b|supplementary material\b|[A-Z]\s+(?:补充|附加|Additional|Supplementary))", plain, re.I):
            active = False
        if not active or item.kind != "p":
            result.append(item)
            continue
        start = 0
        for match in pattern.finditer(item.text):
            number = int(match[1])
            if number != len(entries)+1:
                continue
            prefix = item.text[start:match.start()].strip()
            if entry and prefix:
                entry.text += " " + prefix
            elif prefix:
                result.append(Item(item.page,item.box,"p",prefix))
            entry = Item(item.page,item.box,"bib",match[0],f"bib-{number}")
            result.append(entry)
            entries.add(number)
            start = match.end()
        if entry:
            entry.text += " " + item.text[start:].strip()
        else:
            result.append(item)
    return result, entries


CITATIONS = re.compile(r"\[\s*[1-9]\d{0,2}(?:\s*[,，;；–—-]\s*[1-9]\d{0,2})*\s*\]")


def cite_links(text, entries):
    def group(match):
        if not all(int(n) in entries for n in re.findall(r"\d+",match[0])):
            return match[0]
        return re.sub(r"\d+",lambda n:f'<a href="#bib-{n[0]}">{n[0]}</a>',match[0])
    return CITATIONS.sub(group,text)


def mixed_columns(sections, css, archive, media, inner, gutter, record_position):
    """先排完图前的正文，再让图与图注共用通栏区域。"""
    stream = io.BytesIO()
    writer = pdf.DocumentWriter(stream)
    device = None
    page_no = -1
    bottom = media.height - 39

    def new_page():
        nonlocal device, page_no
        if device is not None:
            writer.end_page()
        device = writer.begin_page(media)
        page_no += 1
        return 36

    def record(pos):
        record_position(page_no,pos)

    top = new_page()
    for wide, fragments in sections:
        story = pdf.Story(html="".join(fragments), user_css=css, archive=archive)
        if wide:
            area = pdf.Rect(42, top, media.width - 42, bottom)
            more, filled = story.place(area)
            if more:
                top = new_page()
                more, filled = story.place(pdf.Rect(42, top, media.width - 42, bottom))
            if more:
                raise ValueError("跨栏图及图注超出单页可用高度。")
            story.element_positions(record)
            story.draw(device)
            top = filled[3] + 5
            continue
        while True:
            if bottom - top < 40:
                top = new_page()
            available = bottom - top
            # 用同栏宽的长文本框估算剩余正文，末段分到两栏后再放跨栏图。
            more, extent = story.place(pdf.Rect(42, top, 42 + inner, top + 2*available))
            left_height = available if more else min(available, max(36, (extent[3]-top)/2 + 10))
            ends = []
            for col in range(2):
                left = 42 + col*(inner + gutter)
                end = top + left_height if col == 0 else bottom
                more, filled = story.place(pdf.Rect(left, top, left+inner, end))
                story.element_positions(record)
                story.draw(device)
                ends.append(filled[3])
                if not more:
                    break
            if not more:
                top = max(ends) + 5
                break
            top = new_page()
    writer.end_page()
    writer.close()
    return pdf.open("pdf", stream.getvalue())


def front_matter(items):
    """标记首页题名、署名和摘要；正文标题结束摘要区域。"""
    roles = {}
    state = None
    for idx, item in enumerate(items):
        text = re.sub("<[^>]+>", "", item.text).strip()
        if item.page == 0 and item.kind == "title":
            roles[idx] = "title"
            state = "byline"
        elif item.page == 0 and re.match(r"^(?:摘\s*要|abstract\b)", text, re.I):
            state = "abstract"
            roles[idx] = state
        elif item.kind == "heading" or re.match(
            r"^(?:(?:[IVX]+|\d+)[.、．]?\s*)?(?:引言|绪论|前言|introduction)\s*$", text, re.I
        ):
            break
        elif item.kind == "p" and state and (state == "abstract" or item.page == 0):
            roles[idx] = state
        elif item.kind in ("visual","caption") and state == "byline":
            state = None
        elif item.page > 0 and state != "abstract":
            break
    return roles


def original_header(page, items):
    """识别出独立题头时，用原页裁片替换译文的题名及署名块。"""
    roles = front_matter(items)
    if roles.get(0) != "title" or page.rotation:
        return
    end = 1
    # 公式化题名可能被上游拆成标题和一个小型矢量块。
    while end < len(items) and items[end].page == 0:
        item = items[end]
        if roles.get(end) in ("title", "byline"):
            end += 1
        elif item.kind == "visual" and not item.anchor and item.box.y1 <= items[0].box.y1 + 2:
            end += 1
        elif end > 1 and item.kind == "p" and item.box.y0 < page.rect.height*.3 and not re.match(
                r"^(?:摘\s*要|abstract\b)",item.text,re.I):
            end += 1
        else:
            break
    if end == len(items) or items[end].page != 0:
        return
    limit = items[end].box.y0
    if limit > page.rect.height * .5 or limit < items[0].box.y0:
        return
    boxes = [r for text, _, r in lines(page)
             if text.strip() and r.y0 >= items[0].box.y0-14 and r.y1 <= limit+1]
    if not boxes:
        return
    crop = pdf.Rect(boxes[0])
    for r in boxes[1:]:
        crop |= r
    crop = (crop + (-2,-2,2,2)) & page.rect
    title = re.sub("<[^>]+>", "", items[0].text)
    items[:end] = [Item(0,crop,"original-header",title)]


def bind_footnotes(items, pages):
    """将页底带上标序号的注释绑定到同一原页正文的唯一标记。"""
    for note in items:
        prefix = re.match(r"^\s*<sup>(\d{1,2})</sup>\s*(?=[一-鿿A-Za-z])", note.text)
        if note.kind != "p" or note.box.y0 < pages[note.page].rect.height*.75 or not prefix:
            continue
        number = prefix[1]
        # 句末上标可与公式内部指数区分。保护公式的译文有时把上标展平为数字。
        marker = re.compile(r"(?<=[。.!?！？])\s*(?:<sup>"+number+
                            r"</sup>|"+number+r"(?=\s+[一-鿿A-Za-z]))")
        hits = [(it,m) for it in items if it is not note and it.page==note.page and it.kind=="p"
                for m in marker.finditer(it.text)]
        if len(hits)!=1:
            continue
        it,m=hits[0]
        key=f"fn-{note.page}-{number}"
        it.text=it.text[:m.start()]+f"<{key}/>"+it.text[m.end():].lstrip()
        note.kind="footnote"
        note.anchor=key
        note.text=note.text[prefix.end():]


def repaginate(original, translated, output, *, columns=1, audit=None, formula_audit=None, inline_settings=None, backend="mupdf"):
    if columns not in (1, 2):
        raise ValueError("跨页重排支持一栏或两栏。")
    with pdf.open(original) as source, pdf.open(translated) as raw, pdf.open() as inline_assets:
        if len(source) != len(raw):
            raise ValueError("译文与原稿页数不一致，无法匹配图文。")
        # arXiv 版本戳是页边元数据；它的纵向范围有时与首图重叠。
        first = raw[0]
        stamps = []
        for b in first.get_text("dict", flags=pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES)["blocks"]:
            for line in b["lines"]:
                r = pdf.Rect(line["bbox"])
                text = "".join(s["text"] for s in line["spans"])
                if (abs(line["dir"][1]) > .9 and re.search(r"arXiv:\s*\d{4}\.\d+",text,re.I)
                    and (r.x1 < first.rect.width*.1 or r.x0 > first.rect.width*.9)):
                    stamps.append(r)
        for r in stamps:
            first.add_redact_annot(r,fill=None)
        if stamps:
            first.apply_redactions(images=0,graphics=0)
        figures = source_figures(source)
        items = []
        inline_boxes = {}
        for page in raw:
            group = page_items(page, figures[page.number], source[page.number], audit)
            group = preserve_ruled_tables(group,source[page.number])
            group = restore_source_roles(group,source[page.number])
            if inline_settings:
                from paper_translator.legacy.inline_equations import protect_inline_items
                inline_boxes.update(protect_inline_items(source[page.number],group,inline_settings,Item,inline_assets))
            items.extend(group)
        original_header(source[0],items)
        # 数字书目以原文为准，避免翻译模型改写编号、作者拼写和 DOI。
        start = next((i for i,item in enumerate(items) if re.fullmatch(
            r"参考文献|references|bibliography",re.sub("<[^>]+>","",item.text).strip(),re.I)), None)
        if start is not None:
            end = next((i for i in range(start+1,len(items)) if re.match(
                r"^(?:附录|appendix\b|supplementary material\b|[A-Z]\s+(?:补充|附加|Additional|Supplementary))",re.sub("<[^>]+>","",items[i].text),re.I)),len(items))
            original_items = []
            last = items[end].page if end < len(items) else len(source)-1
            for i in range(items[start].page,last+1):
                original_items.extend(page_items(source[i],figures[i]))
            originals, numbers = bibliography(original_items)
            if numbers and any(re.match(r"^\s*\[1\]",item.text) for item in items[start+1:end]):
                items[start+1:end] = [item for item in originals if item.kind=="bib"]
        if backend == "latex" and start is not None:
            panel_pages = {it.page for it in items if it.kind == "heading" and
                           re.match(r"^[A-Z](?:\.\d+)?\s", it.text) and
                           it.box.y0 < raw[it.page].rect.height*.15 and
                           len(raw[it.page].get_image_info()) >= 6 and it.page > items[start].page}
            kept = []
            for it in items:
                if it.page not in panel_pages:
                    kept.append(it)
                elif not kept or kept[-1].page != it.page:
                    page = raw[it.page]
                    kept.append(Item(it.page,page.rect,"panel-page"))
            items = kept
        items, entries = bibliography(items)
        entries.update(int(item.anchor.split("-")[1]) for item in items if item.kind=="bib")
        if backend=="latex":
            bind_footnotes(items,raw)
            if inline_settings:
                repair_prose(items,source,inline_settings)
        # 源页的栏尾常落在句中。把跨栏、跨页续句接回同一段。
        previous = None
        for item in items:
            if item.kind in ("visual", "caption","source-equation","footnote"):
                continue
            if (
                previous
                and previous.kind == "p"
                and item.kind == "p"
                and (
                    re.search("[，、；,]$", previous.text)
                    or (
                        (previous.page != item.page or
                         previous.box.x1 <= raw[item.page].rect.width/2 <= item.box.x0)
                        and re.search(r"[一-鿿]$", previous.text.rstrip())
                        and re.match(r"[一-鿿A-Za-z]",item.text)
                    )
                )
            ):
                if audit is not None:
                    left=html.unescape(re.sub("<[^>]+>","",previous.text)).strip()
                    right=html.unescape(re.sub("<[^>]+>","",item.text)).strip()
                    previous.joins += (left[-9:]+right[:9],)
                previous.text += item.text
                previous.joins += item.joins
                item.text = ""
            else:
                previous = item
        if backend=="latex":
            from paper_translator.render.latex_backend import render_latex
            render_latex(source,raw,inline_assets,items,inline_boxes,entries,output,front_matter(items))
            return
        blank = io.BytesIO()
        Image.new("RGB", (1, 1), "white").save(blank, "PNG")
        uri = "data:image/png;base64," + base64.b64encode(blank.getvalue()).decode()
        width, height = (648, 842) if columns == 2 else (540, 720)
        gutter = 20
        inner = (width - 84 - (columns - 1) * gutter) / columns
        visuals = []
        body = []
        sections = []
        span = False
        figure_number = ""

        mentioned = {m[1] for i in items if i.kind == "p" for m in REFERENCE.finditer(i.text) if m[1]}
        def return_label(key):
            return f' <a style="font-size:8pt" href="#back-{key}">返回正文</a>'
        headings = {}
        front = front_matter(items) if columns == 2 else {}
        for idx, item in enumerate(items):
            wide_visual = (columns == 2 and item.kind == "visual"
                           and item.box.x0 < raw[item.page].rect.width * .4
                           and item.box.x1 > raw[item.page].rect.width * .6
                           and item.box.width > raw[item.page].rect.width * .64)
            if item.kind == "original-header":
                wide_visual = columns == 2
            companion = (span and figure_number and re.match(
                rf"^图\s*{re.escape(figure_number)}(?![\d.])|^Fig(?:ure)?\.?(?:\s+){re.escape(figure_number)}(?![\d.])",
                item.text,re.IGNORECASE))
            is_wide = bool(wide_visual or companion or idx in front)
            if span != is_wide or wide_visual or (idx in front and idx - 1 not in front):
                if body:
                    sections.append((span,body))
                body = []
            span = is_wide
            if wide_visual:
                figure_number = item.anchor.removeprefix("fig-") if item.anchor.startswith("fig-") else ""
            if item.kind in ("visual","original-header","source-equation","source-algorithm"):
                scale = min(
                    (width - 84 if wide_visual else inner) / item.box.width, (0.78 if wide_visual else 0.39) * height / item.box.height, 1.20
                )
                if item.kind in ("original-header","source-equation"):
                    scale = min(scale, 1.0)
                if item.anchor.startswith(("eq-", "display-")):
                    scale = min(scale, 1.25)
                w, h = item.box.width * scale, item.box.height * scale
                body.append(
                    f'<div class="visual"><img src="{uri}" style="width:{w:.3f}pt;height:{h:.3f}pt"/></div>'
                )
                if item.anchor.startswith(("eq-","display-")):
                    body.append('<div class="visual">'+return_label(item.anchor)+'</div>')
                visuals.append(item)
            elif item.text:
                if audit is not None:
                    audit.extend((item.page,j) for j in item.joins)
                tag = {"heading": "h2", "title": "h1"}.get(item.kind, "p")
                if tag != "p" or item.kind == "caption":
                    headings[f"b{idx}"] = re.sub("<[^>]+>", "", item.text)
                block_id = item.anchor if item.kind == "bib" else f"b{idx}"
                content = item.text if item.kind == "bib" else cite_links(item.text, entries)
                if inline_boxes:
                    def math_slot(match):
                        v=inline_boxes[match[1]]
                        visuals.append(v)
                        scale=min(1.1,inner/v.box.width)
                        return (f'<img src="{uri}" style="width:{v.box.width*scale:.3f}pt;'
                                f'height:{v.box.height*scale:.3f}pt;vertical-align:middle"/>')
                    content=re.sub(r"@@(m\d+_\d+_\d+)@@",math_slot,content)
                cap = CAPTION.match(item.text)
                if cap and cap[1] in mentioned:
                    content += return_label("fig-"+cap[1])
                body.append(
                    f'<{tag} class="{front.get(idx, item.kind)}" id="{block_id}">{content}</{tag}>'
                )
        css = """body{margin:0;font-family:sans-serif;font-size:11pt;line-height:1.45}
.bib{margin:0 0 7pt;padding-left:20pt;text-indent:-20pt}a{color:#20557c;text-decoration:underline}p{margin:0 0 6pt} h1{font-size:19pt;margin:5pt 0 10pt} h2{font-size:13pt;color:#24435a;margin:8pt 0 3pt}
.visual{text-align:center;margin:4pt 0}.caption{font-size:9pt;color:#253849;margin:2pt 0 9pt}"""
        if columns == 2:
            css += ".title,.byline{text-align:center}.byline{font-size:9pt;margin-bottom:3pt}.abstract{margin:6pt 0 9pt}"
        font = Path("/Library/Fonts/Arial Unicode.ttf")
        archive = None
        if font.is_file():
            archive = pdf.Archive(str(font.parent))
            css += "@font-face{font-family:article;src:url('Arial Unicode.ttf')}body{font-family:article,sans-serif}"
        if body:
            sections.append((span,body))
        marks = {}

        bib_targets = {}
        citations = []
        back_labels = []
        def record_position(n,pos):
            if not pos.open_close & 1:
                return
            rect = pdf.Rect(pos.rect)
            if pos.href and pos.href.startswith("#back-") and not rect.is_empty:
                back_labels.append((n,rect,pos.href[6:]))
            if pos.id in headings:
                marks.setdefault(pos.id,(n,rect.tl))
            if pos.id and pos.id.startswith("bib-"):
                bib_targets.setdefault(pos.id,(n,rect))
            if pos.href and pos.href.startswith("#bib-") and not rect.is_empty:
                citations.append((n,rect,pos.href[1:]))

        media = pdf.Rect(0, 0, width, height)
        def next_column(index, _filled):
            column = index % columns
            left = 42 + column * (inner + gutter)
            area = pdf.Rect(left, 36, left + inner, height - 39)
            return media if column == 0 else None, area, None

        if any(wide for wide,_ in sections):
            laid_out = mixed_columns(sections, css, archive, media, inner, gutter, record_position)
        else:
            story = pdf.Story(html="".join(body), user_css=css, archive=archive)
            stream = io.BytesIO()
            writer = pdf.DocumentWriter(stream)
            story.write(writer,next_column,lambda pos: record_position(pos.page_num-1,pos))
            writer.close()
            laid_out = pdf.open("pdf",stream.getvalue())
        with laid_out as doc:
            slots = [
                (p.number, pdf.Rect(im["bbox"]))
                for p in doc
                for im in p.get_image_info()
            ]
            if len(slots) != len(visuals):
                raise ValueError("图文块数量与重排结果不一致。")
            targets = {}
            for (n, r), v in zip(slots, visuals):
                origin = source if v.kind in ("original-header","source-equation","source-algorithm","inline-source") else raw
                if v.kind=="inline-source": origin=inline_assets
                doc[n].show_pdf_page(r, origin, v.page, clip=v.box)
                if v.kind == "inline-source" and formula_audit is not None:
                    formula_audit.append(("inline",v.page,v.box,n,r))
                if v.kind == "source-equation" and formula_audit is not None:
                    formula_audit.append((v.anchor[3:],v.page,v.box,n,r))
                if v.kind == "original-header":
                    transform = v.box.torect(r)
                    for link in source[v.page].get_links():
                        if link["kind"] == pdf.LINK_URI and v.box.intersects(link["from"]):
                            doc[n].insert_link({"kind":pdf.LINK_URI, "from":(link["from"] & v.box)*transform,
                                                "uri":link["uri"]})
                    headings["original-header"] = v.text
                    marks = {"original-header":(n,r.tl), **marks}
                if v.anchor:
                    targets[v.anchor] = (n, r)

            def fit_destination(target):
                k, rect = target
                page = doc[k]
                rect = rect & page.rect
                native = rect * ~page.transformation_matrix
                coords = " ".join(f"{x:.3f}" for x in native)
                return f"[{page.xref} 0 R /FitR {coords}]"

            def jump(n, r, target):
                k, box = target
                page = doc[n]
                page.insert_link({"kind": pdf.LINK_GOTO, "from": r, "page": k, "to": box.tl})
                xref = page.annot_xrefs()[-1][0]
                doc.xref_set_key(xref, "A/D", fit_destination(target))

            for n,rect,key in citations:
                dest,box=bib_targets[key]
                # 目标窗口从条目首行开始，给作者和标题留出阅读空间。
                area = pdf.Rect(box.x0-6,box.y0-6,box.x1+6,box.y0+115)
                jump(n,rect,(dest,area))
            print(f"参考文献：{len(bib_targets)} 条；正文引用链接：{len(citations)} 处。")
            views = {}
            for key,(n,r) in targets.items():
                area = r + (-6,-8,6,10)
                if key.startswith("fig-"):
                    number = key.split("-",1)[1]
                    for block in doc[n].get_text("blocks"):
                        box = pdf.Rect(block[:4])
                        if (r.y1-2 <= box.y0 <= r.y1+24 and box.x0 < r.x1 and r.x0 < box.x1
                            and re.match(rf"^\s*(?:图|Fig(?:ure)?\.?)\s*{re.escape(number)}(?![\d.])",block[4],re.I)):
                            area |= box + (-4,-4,4,6)
                else:
                    area += (-12,-34,12,34)
                views[key] = (n,area & doc[n].rect)
            refs = {}
            for p in doc:
                for t, chars, box in lines(p):
                    for m in REFERENCE.finditer(t):
                        key = ("fig-" + m[1]) if m[1] else ("eq-" + m[2])
                        if key not in targets:
                            continue
                        r = pdf.Rect(chars[m.start()]["bbox"]) | pdf.Rect(
                            chars[m.end() - 1]["bbox"]
                        )
                        jump(p.number, r, views[key])
                        p.draw_line((r.x0,r.y1-1),(r.x1,r.y1-1),color=(.14,.38,.56),width=.45)
                        if not CAPTION.match(t):
                            refs.setdefault(key, (p.number, r))
                p.insert_text(
                    (width / 2 - 5, height - 15),
                    str(p.number + 1),
                    fontsize=8,
                    color=(0.35, 0.4, 0.43),
                )
            for key, (n, box) in targets.items():
                if key.startswith(("eq-", "display-")):
                    cues = [
                        r
                        for text, _, r in lines(doc[n])
                        if box.y0 - 65 < r.y1 <= box.y0 and r.x0 < box.x1 and box.x0 < r.x1
                        and re.search(r"[一-鿿]{2,}|[A-Za-z]{4}", text)
                    ]
                    if cues:
                        cue = max(cues, key=lambda r: r.y1)
                        jump(n, cue, views[key])
                        refs.setdefault(key, (n, cue))
            for n,rect,key in back_labels:
                if key in refs:
                    k,cue=refs[key]
                    left=42 if cue.x0<width/2 or columns==1 else width/2+gutter/2
                    jump(n,rect,(k,pdf.Rect(left-5,cue.y0-28,left+inner+5,cue.y1+52)))
            toc = []
            for key, (n, pt) in marks.items():
                text = headings[key]
                if not CAPTION.match(text):
                    toc.append(
                        [1, text, n + 1, {"kind": pdf.LINK_GOTO, "page": n, "to": pt}]
                    )
            if targets:
                toc.append([1, "图与公式", 1])
                for key, (n, r) in targets.items():
                    kind, num = key.split("-", 1)
                    title = {"fig": "图 ", "eq": "式 ", "display": "未编号公式 ", "alg":"算法 "}[kind]
                    toc.append(
                        [
                            2,
                            title + (num if kind != "display" else ""),
                            n + 1,
                            {"kind": pdf.LINK_GOTO, "page": n, "to": r.tl},
                        ]
                    )
            if toc:
                doc.set_toc(toc)
                if targets:
                    for xref, key in zip(doc.get_outline_xrefs()[-len(targets):], targets):
                        doc.xref_set_key(xref, "A", f"<< /S /GoTo /D {fit_destination(views[key])} >>")
            doc.set_metadata(raw.metadata)
            if inline_settings and formula_audit is not None:
                from paper_translator.source.equation_layout import verify_equations
                inline_expected=[a for a in formula_audit if a[0]=="inline"]
                verify_equations(inline_assets,doc,inline_expected)
            doc.subset_fonts()
            doc.save(output, garbage=4, deflate=True)
            print(f"跨页重排完成：{len(raw)} 个原页重排为 {len(doc)} 页。")
