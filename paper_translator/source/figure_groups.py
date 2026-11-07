"""将同一图注前的多个裁片恢复为原稿中的完整图组。"""
import re
from pathlib import Path
import pymupdf


def restore_groups(markdown, source, directory):
    chunks = re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)", markdown)
    with pymupdf.open(source) as doc:
        for page_index, page in enumerate(doc):
            offset = 2 * page_index + 2
            if offset >= len(chunks):
                break
            blocks = chunks[offset].strip().split("\n\n")
            captions = [b for b in page.get_text("blocks") if re.match(r"^(?:Fig(?:ure)?\.?)\s*\d+", b[4])]
            for index in range(len(blocks)-1, -1, -1):
                match = re.match(r"^(?:图|Figure)\s*(\d+)", blocks[index])
                if not match:
                    continue
                start = index
                while start and blocks[start-1].startswith("!["):
                    start -= 1
                if start>0 and re.match(r"^(?:图|Figure|表|Table)\s*\d+",blocks[start-1]) and (start<2 or not blocks[start-2].startswith("![")):
                    start=index
                end=index+1
                while end<len(blocks) and blocks[end].startswith("!["):
                    end+=1
                if end<len(blocks) and re.match(r"^(?:图|Figure)\s*\d+",blocks[end]):
                    end=index+1
                if index-start+end-index-1 < 2:
                    continue
                cap = next((b for b in captions if re.match(r"^(?:Fig(?:ure)?\.?)\s*"+match[1]+r"\b", b[4])), None)
                if cap is None:
                    continue
                if any(other is not cap and abs(other[1]-cap[1])<4 and (other[2]<=cap[0]+2 or other[0]>=cap[2]-2) for other in captions):
                    continue
                boundary = max([b[3] for b in captions if b[3] < cap[1]] or [0])
                tiles = [pymupdf.Rect(im["bbox"]) for im in page.get_image_info()
                         if im["bbox"][1] >= boundary and im["bbox"][3] <= cap[1]+1]
                tiles += [g["rect"] for g in page.get_drawings()
                          if g["rect"].y0>=boundary and g["rect"].y1<=cap[1]+1
                          and g["rect"].x0>=cap[0]-3 and g["rect"].x1<=cap[2]+3
                          and g["rect"].width>3 and g["rect"].height>2]
                if not tiles:
                    continue
                box = pymupdf.Rect(cap[0], min(r.y0 for r in tiles)-2, cap[2], cap[1]-2)
                name = f"figures/page-{page_index+1:04d}-group-{match[1]}.png"
                path = Path(directory)/name
                path.parent.mkdir(exist_ok=True)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(400/72,400/72), clip=box, alpha=False)
                pix.set_dpi(400,400)
                pix.save(path)
                blocks[start:end] = [f"![图 {match[1]}]({name})",blocks[index]]
            chunks[offset] = "\n\n"+"\n\n".join(blocks)+"\n\n"
    return "".join(chunks)


PLACEHOLDER = re.compile(r"^!\[[^\]]*\]\((?!figures/)[^)]*\)$")
CAPTION = re.compile(r"^\**\s*(?:图|Figure)\s*(\d+)\s*[：:]")
IMAGE = re.compile(r"^!\[[^\]]*\]\(figures/[^)]+\)$")


def figure_box(page, number):
    """由原稿图注向上取图形瓦片，得到图块区域。"""
    captions = []
    for block in page.get_text("blocks"):
        match = re.match(r"^(?:Fig(?:ure)?\.?)\s*(\d+)\b", " ".join(block[4].split()))
        if match:
            captions.append((match.group(1), pymupdf.Rect(block[:4])))
    target = next((rect for value, rect in captions if value == str(number)), None)
    if target is None:
        return None
    from paper_translator.source.original_tables import table_regions
    from paper_translator.source.source_header import header_region
    # 只取同一栏（横向有重叠）的表题和表格作为上边界，另一栏的图注不能截断本图。
    overlap = lambda rect: rect.x1 > target.x0 and rect.x0 < target.x1
    tables = [box for box in table_regions(page).values() if box.y1 <= target.y0 - 1 and overlap(box)]
    above = [rect.y1 for _, rect in captions if rect.y1 <= target.y0 - 1 and overlap(rect)]
    boundary = max(above + [box.y1 for box in tables] or [0])
    head = header_region(page)
    if head is not None and target.y0 > head.y1:
        boundary = max(boundary, head.y1 + 2)
    overlap = lambda box: box[2] > target.x0 and box[0] < target.x1
    tiles = [pymupdf.Rect(item["bbox"]) for item in page.get_image_info()
             if boundary <= item["bbox"][1] and item["bbox"][3] <= target.y0 + 1
             and overlap(item["bbox"])]
    tiles += [item["rect"] for item in page.get_drawings()
              if boundary <= item["rect"].y0 and item["rect"].y1 <= target.y0 + 1
              and overlap(item["rect"]) and item["rect"].width > 2 and item["rect"].height > 2]
    if not tiles:
        return None
    top = min(rect.y0 for rect in tiles) - 2
    left = min(rect.x0 for rect in tiles)
    right = max(rect.x1 for rect in tiles)
    return pymupdf.Rect(left, top, right, target.y0 - 2) & page.rect


def restore_placeholder_figures(markdown, source, directory):
    """模型把图写成 Markdown 图片链接时，按原稿图注恢复真实图块。"""
    chunks = re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)", markdown)
    restored = []
    with pymupdf.open(source) as doc:
        for page_index, page in enumerate(doc):
            offset = 2 * page_index + 2
            if offset >= len(chunks):
                break
            blocks = chunks[offset].strip().split("\n\n")
            changed = False
            for i, block in enumerate(blocks):
                if not PLACEHOLDER.fullmatch(block.strip()):
                    continue
                number = re.search(r"(\d+)", block)
                if number is None:
                    continue
                box = figure_box(page, number.group(1))
                if box is None:
                    continue
                name = f"figures/page-{page_index+1:04d}-figure-{number.group(1)}.png"
                (Path(directory) / "figures").mkdir(exist_ok=True)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(400 / 72, 400 / 72), clip=box, alpha=False)
                pix.set_dpi(400, 400)
                pix.save(Path(directory) / name)
                blocks[i] = f"![图 {number.group(1)}]({name})"
                changed = True
                restored.append({"source_page": page_index + 1, "figure": number.group(1), "asset": name})
            blocks, added = _fill_missing_figures(blocks, page, directory, page_index)
            restored.extend(added)
            if changed or added:
                chunks[offset] = "\n\n" + "\n\n".join(blocks) + "\n\n"
    return "".join(chunks), restored


def _fill_missing_figures(blocks, page, directory, page_index):
    """图注存在但模型没有输出图块时，按原稿图注位置补图。"""
    captions = [block for block in blocks if CAPTION.match(block.strip())]
    images = [block for block in blocks if IMAGE.match(block.strip())]
    if not captions or len(images) >= len(captions):
        return blocks, []
    result = []
    added = []
    present = len(images)
    for block in blocks:
        match = CAPTION.match(block.strip())
        if match and present < len(captions) and not (result and IMAGE.match(result[-1].strip())):
            number = match.group(1)
            box = figure_box(page, number)
            if box is not None:
                name = f"figures/page-{page_index+1:04d}-figure-{number}.png"
                (Path(directory) / "figures").mkdir(exist_ok=True)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(400 / 72, 400 / 72), clip=box, alpha=False)
                pix.set_dpi(400, 400)
                pix.save(Path(directory) / name)
                result.append(f"![图 {number}]({name})")
                present += 1
                added.append({"source_page": page_index+1, "figure": number, "asset": name})
        result.append(block)
    return result, added


def figure_regions(page):
    """原稿本页所有带图注图块的区域。"""
    boxes = []
    for block in page.get_text("blocks"):
        match = re.match(r"^(?:Fig(?:ure)?\.?)\s*(\d+)\b", " ".join(block[4].split()))
        if match:
            box = figure_box(page, match.group(1))
            if box is not None:
                boxes.append(box)
    return boxes


def _plain(text):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", text.lower())


def _removable(block):
    """标题、表格、图片和没有句读的短行不按图内文字删除。"""
    text = block.strip()
    if text.startswith(("#", "|", "!", "表", "Table", "图", "Figure")):
        return False
    return bool(re.search(r"[.。!?！？]", text))


def strip_figure_text(markdown, source):
    """删除正文中重复转录的图内文字；图块里已经保留原文。"""
    chunks = re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)", markdown)
    removed = []
    with pymupdf.open(source) as doc:
        for i, page in enumerate(doc):
            offset = 2 * i + 2
            if offset >= len(chunks):
                break
            inside = _plain("".join(page.get_textbox(box) for box in figure_regions(page)))
            if len(inside) < 40:
                continue
            blocks = chunks[offset].strip().split("\n\n")
            kept = []
            for block in blocks:
                # 模型有时把图内文字连同自造图片标签一起输出，先去掉标签再判断。
                clean = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", block).strip()
                text = _plain(clean)
                if (_removable(clean) and len(text) >= 60 and text in inside):
                    removed.append({"source_page": i + 1, "text": clean[:80]})
                    continue
                kept.append(block)
            if len(kept) != len(blocks):
                chunks[offset] = "\n\n" + "\n\n".join(kept) + "\n\n"
    return "".join(chunks), removed


CAPTION_SOURCE = re.compile(r"^(?:Fig(?:ure)?\.?)\s*(\d+)\s*[:：]")


def source_captions(page):
    result = []
    for block in page.get_text("blocks"):
        text = " ".join(block[4].split())
        match = CAPTION_SOURCE.match(text)
        if match:
            result.append((match.group(1), text))
    return result


def _translate_caption(args, text):
    from paper_translator.cli import request_blocks
    payload = {"model": args.model, "messages": [
        {"role": "system", "content": "Translate this figure caption into Chinese. Keep the figure number, panel labels, numbers, citations and LaTeX commands. Return JSON with blocks containing one md string."},
        {"role": "user", "content": text}]}
    blocks = request_blocks(args, payload)
    value = blocks[0].get("md", "").strip() if blocks else ""
    return value or text


def ensure_missing_figures(markdown, source, directory, args=None):
    """原稿有图注、译稿完全没有这张图和图注时，补图并翻译图注。"""
    chunks = re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)", markdown)
    added = []
    with pymupdf.open(source) as doc:
        for i, page in enumerate(doc):
            offset = 2 * i + 2
            if offset >= len(chunks):
                break
            blocks = chunks[offset].strip().split("\n\n")
            text = "\n".join(blocks)
            changed = False
            for number, caption in source_captions(page):
                if re.search(rf"(?:图|Figure)\s*{number}\s*[：:]", text):
                    continue
                if any(f"-figure-{number}.png" in block for block in blocks):
                    continue
                box = figure_box(page, number)
                if box is None:
                    continue
                name = f"figures/page-{i+1:04d}-figure-{number}.png"
                (Path(directory) / "figures").mkdir(exist_ok=True)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(400 / 72, 400 / 72), clip=box, alpha=False)
                pix.set_dpi(400, 400)
                pix.save(Path(directory) / name)
                label = _translate_caption(args, caption) if args is not None and getattr(args, "model", None) else caption
                block = f"![图 {number}]({name})\n\n图 {number}：{label}"
                position = next((k for k, b in enumerate(blocks) if re.search(rf"图\s*{number}\b", b)), len(blocks))
                blocks.insert(position, block)
                text = "\n".join(blocks)
                added.append({"source_page": i + 1, "figure": number, "asset": name})
                changed = True
            if changed:
                chunks[offset] = "\n\n" + "\n\n".join(blocks) + "\n\n"
    return "".join(chunks), added


HTML_FIGURE = re.compile(r"<figure>\s*<figcaption>(.*?)</figcaption>\s*</figure>", re.S | re.I)


def normalize_figure_html(markdown):
    """把模型输出的 <figure><figcaption>…</figcaption></figure> 还原成普通图注段落。"""
    return HTML_FIGURE.sub(lambda match: match.group(1).strip(), markdown)


def dedupe_figure_blocks(markdown):
    """同一页里完全重复的图注或图块只保留第一份（模型偶尔重复输出）。"""
    chunks = re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)", markdown)
    for index in range(2, len(chunks), 2):
        blocks = chunks[index].strip().split("\n\n")
        seen = set()
        kept = []
        for block in blocks:
            text = block.strip()
            if text.startswith("![") or CAPTION.match(text) or CAPTION_SOURCE.match(text):
                key = " ".join(text.split())
                if key in seen:
                    continue
                seen.add(key)
            kept.append(block)
        if len(kept) != len(blocks):
            chunks[index] = "\n\n" + "\n\n".join(kept) + "\n\n"
    return "".join(chunks)


def strip_label_dumps(markdown):
    """删除整段转录的图内标签（大量竖线分隔的短标签），图块里已经保留原图。"""
    chunks = re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)", markdown)
    removed = []
    for index in range(2, len(chunks), 2):
        blocks = chunks[index].strip().split("\n\n")
        kept = []
        for block in blocks:
            text = block.strip()
            body = text
            if text.startswith("```"):
                body = re.sub(r"^```[^\n]*\n?", "", text)
                body = re.sub(r"\n?```$", "", body).strip()
            pipes = body.count("|")
            cjk = len(re.findall(r"[\u4e00-\u9fff]", body))
            words = re.findall(r"[A-Za-z]{2,}", body)
            is_table = bool(re.search(r"(?m)^\|.*\|$", body)) or "---" in body
            is_math = bool(re.search(r"[\\$]", body)) or body.startswith("$$")
            if (pipes >= 5 and not is_table and not is_math and cjk == 0 and len(words) >= 8
                    and len(body) < 1200 and not re.search(r"[。！？]", body)):
                removed.append({"page": index // 2, "text": body[:60]})
                continue
            kept.append(block)
        if len(kept) != len(blocks):
            chunks[index] = "\n\n" + "\n\n".join(kept) + "\n\n"
    return "".join(chunks), removed
