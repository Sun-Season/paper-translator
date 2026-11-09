"""按表题、横线与原页位置恢复独立表格，保留原 PDF 的字形和线条。"""
import re
import pymupdf


TABLE_CAPTION = re.compile(r"^(?:Table|表)\s*(S?\d+)\b", re.I)


def _overlaps_horizontally(left, right):
    return min(left.x1, right.x1) > max(left.x0, right.x0)


def _table_captions(page, rules):
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        lines = [(pymupdf.Rect(line["bbox"]), "".join(span["text"] for span in line["spans"]).strip())
                 for line in block.get("lines", [])]
        for index, (first, text) in enumerate(lines):
            match = TABLE_CAPTION.match(text)
            if not match:
                continue
            caption = pymupdf.Rect(first)
            # 同一文字块可能合并表题和表体。横线之后的文字不属于表题。
            for line, following in lines[index + 1:]:
                if (TABLE_CAPTION.match(following) or line.y0 <= caption.y0
                        or any(caption.y1 <= rule.y0 <= line.y0 and _overlaps_horizontally(rule, first)
                               for rule in rules)):
                    break
                caption |= line
            yield match[1], caption


def _table_region(page, caption, above, rules, captions):
    nearby = []
    for rule in rules:
        start, end = (rule.y1, caption.y0) if above else (caption.y1, rule.y0)
        if not (0 <= end - start < 24 and _overlaps_horizontally(rule, caption)):
            continue
        if any(box != caption and box.y0 < end and box.y1 > start
               and _overlaps_horizontally(box, rule) for _, box in captions):
            continue
        nearby.append((rule, end - start))
    if not nearby:
        return None
    edge, _ = min(nearby, key=lambda pair: (
        abs(pair[0].x0 + pair[0].x1 - caption.x0 - caption.x1)
        + abs(pair[0].width - caption.width) * .25 + pair[1]))
    others = [box for _, box in captions if box != caption and _overlaps_horizontally(box, edge)]
    if above:
        lower = max((box.y1 for box in others if box.y1 <= edge.y0), default=page.rect.y0)
        upper = edge.y0
    else:
        lower = edge.y0
        upper = min((box.y0 for box in others if box.y0 > edge.y0), default=page.rect.y1)
    aligned = [rule for rule in rules if lower <= rule.y0 <= upper
               and abs(rule.x0 - edge.x0) < 2 and abs(rule.x1 - edge.x1) < 2]
    if len(aligned) < 3:
        return None
    y0 = min(rule.y0 for rule in aligned) - 1
    y1 = max(rule.y1 for rule in aligned) + 1
    if above:
        y1 = min(y1, caption.y0)
    else:
        y0 = max(y0, caption.y1)
    return pymupdf.Rect(edge.x0 - 1, y0, edge.x1 + 1, y1) & page.rect


def _overlap_ratio(left, right):
    overlap = left & right
    smaller = min(left.width * left.height, right.width * right.height)
    if smaller <= 0 or overlap.width <= 0 or overlap.height <= 0:
        return 0
    return overlap.width * overlap.height / smaller


def table_regions(page):
    rules = [drawing["rect"] for drawing in page.get_drawings() if drawing["type"] == "s"
             and drawing["rect"].height < 1.5 and drawing["rect"].width > page.rect.width * .08]
    captions = list(_table_captions(page, rules))
    candidates = [(number,
                   _table_region(page, caption, True, rules, captions),
                   _table_region(page, caption, False, rules, captions))
                  for number, caption in captions]
    # 同一页的表题通常只在表格的一侧。夹在两个表之间的表题上下都能凑出横线组，
    # 这时按本页只在一侧成立的表题样式决定归属，而不是把两个方向都放弃。
    votes = [above is not None for _, above, below in candidates
             if (above is None) != (below is None)]
    balance = sum(votes) * 2 - len(votes)
    style = None if balance == 0 else balance > 0
    regions = []
    for number, above, below in candidates:
        if above is not None and below is not None:
            if style is None:
                continue
            region = above if style else below
        else:
            region = above if above is not None else below
        if region is not None:
            regions.append((number, region))
    # 同号表注（双语原稿、重复表题）只保留第一次出现；不同号且几乎整块重叠说明识别有误，
    # 保留先出现的。同排两栏的表格边缘常有十几点交错，不能当成重复。
    kept = {}
    for number, region in regions:
        if number in kept:
            continue
        if any(_overlap_ratio(region, box) > .25 for other, box in kept.items() if other != number):
            continue
        kept[number] = region
    return kept


def original_table_assets(md,source):
    chunks=re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)",md)
    assets={}
    with pymupdf.open(source) as doc:
        if len(chunks)!=2*len(doc)+1:
            return md,assets
        pages=[v.strip().split("\n\n") for v in chunks[2::2]]
        for i,page in enumerate(doc):
            for num,rect in table_regions(page).items():
                label=re.compile(r"^(?:表|Table)\s*"+re.escape(num)+r"(?=\s|[:：（(])",re.I)
                blocks=pages[i]
                matches=[j for j,b in enumerate(blocks) if label.match(b)]
                if len(matches)>1:
                    matches=[j for j in matches if re.match(r"^(?:表|Table)\s*"+re.escape(num)+r"\s*[:：]",blocks[j],re.I)]
                if len(matches)!=1:continue
                j=matches[0]
                following=[k for k in (j+1,j-1) if 0<=k<len(blocks) and (
                    blocks[k].startswith("|") or re.fullmatch(r"!\[[^\]]*\]\(figures/[^)]+\)",blocks[k]))]
                parts=re.findall(r"(?m)^\(([a-z])\)\s",page.get_textbox(rect))
                end=j+1
                for part in parts:
                    if (end+1>=len(blocks) or not re.match(r"^\("+part+r"\)",blocks[end])
                            or not blocks[end+1].startswith("|")):break
                    end+=2
                else:
                    for k in range(j+1,end):blocks[k]=""
                # 同页多表可能被识别为一张图；各表按各自的原始横线单独裁出。
                for k in following[:1]:
                    blocks[k]=""
                key=f"source-table-{num}.png"
                continuation=key in assets
                if continuation:key=f"source-table-{num}-p{i+1}.png"
                blocks[j]=label.sub("表 "+num,blocks[j],count=1)+"\n\n![原表 "+num+"]("+key+")"
                assets[key]=(i,rect,num)
                if i and not continuation:
                    prior=pages[i-1]
                    if len(prior)>=2 and prior[-1].startswith("|") and label.match(prior[-2]):
                        del prior[-2:]
        for i,blocks in enumerate(pages):
            chunks[2*i+2]="\n\n"+"\n\n".join(filter(None,blocks))+"\n\n"
    return "".join(chunks),assets
