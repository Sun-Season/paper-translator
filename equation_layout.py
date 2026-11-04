"""从原稿识别有编号的独立公式，保留同一公式的所有行和编号。"""
import re
import pymupdf as pdf


def numbered_equations(page):
    blocks = page.get_text("dict", flags=pdf.TEXTFLAGS_TEXT)["blocks"]
    rows = [(pdf.Rect(line["bbox"]), line["spans"]) for b in blocks for line in b["lines"]]
    text = lambda spans: "".join(s["text"] for s in spans).strip()
    result = {}
    mid = page.rect.width / 2
    for label, spans in rows:
        number = re.fullmatch(r"[（(](\d+(?:\.\d+)*)[)）]", text(spans))
        if not number:
            continue
        # 右对齐的公式编号；避开列表序号和正文内括号。
        side = 0 if label.x0 < mid else mid
        if label.x1-side < mid*.73:
            continue
        crosses_gutter = any(b.x0 < mid-4 and b.x1 > mid+4
                             and abs(b.y0-label.y0)<max(6,label.height)
                             and (re.search(r"[=∑∫≈]",text(ss)) or any("Math" in s["font"] or "CMMI" in s["font"] for s in ss))
                             for b,ss in rows)
        if crosses_gutter or any(b.x0 < mid*.65 and b.x1 > mid*1.4 and abs(b.y0-label.y0)<95
               and any(re.search(r"[a-z]{4}",s["text"]) for s in ss) for b,ss in rows):
            side = 0
            width = page.rect.width
        else:
            width = mid
        column = [(b,ss) for b,ss in rows if side <= b.x0 < side+width]
        left = min(b.x0 for b,_ in column)
        def prose(b,ss):
            ordinary = " ".join(s["text"] for s in ss
                                if not re.search(r"^(CM|MSBM)|Math|Symbol",s["font"]))
            ordinary=re.sub(r"\b(?:ref|fail|log|exp|min|max|sin|cos|arg|flow|SPO|KL)\b","",ordinary)
            return (b.x0 < left+22 and re.search(r"[A-Za-z]{3,}|[一-鿿]{2,}",ordinary)
                    or len(ordinary.strip())>32)
        limits = [b for b,ss in column if prose(b,ss)]
        top = max((b.y1 for b in limits if b.y1<=label.y0), default=0)
        end = min((b.y0 for b in limits if b.y0>=label.y1-2), default=page.rect.height)
        band = [(b,ss) for b,ss in column if top < (b.y0+b.y1)/2 < end]
        if not any(re.search(r"[=≥≤∝∑∇πϕθω]|Math|CMMI|CMSY",s["font"]+s["text"])
                   for _,ss in band for s in ss):
            continue
        labels = [b for b,ss in band if re.fullmatch(r"[（(]\d+(?:\.\d+)*[)）]",text(ss))]
        if len(labels)!=1:
            continue
        rect=pdf.Rect(label)
        for b,_ in band:
            rect |= b
        result[number[1]]=(rect+(-1,-1,1,1)) & page.rect
    return result


def outside_equations(blocks, regions):
    """在恢复文字段落之前剔除已经由原稿裁片承担的公式行。"""
    kept=[]
    for block in blocks:
        lines=[]
        for line in block["lines"]:
            b=pdf.Rect(line["bbox"])
            if not any(r.contains((b.tl+b.br)*.5) for r in regions):
                lines.append(line)
        if lines:
            r=pdf.Rect(lines[0]["bbox"])
            for line in lines[1:]:
                r |= pdf.Rect(line["bbox"])
            kept.append({**block,"lines":lines,"bbox":tuple(r)})
    return kept


def verify_equations(original, output, placements):
    """以相同分辨率渲染原稿裁区和成品落点，检查印刷墨迹是否一致。"""
    import numpy as np
    from contextlib import nullcontext
    with (nullcontext(original) if isinstance(original,pdf.Document) else pdf.open(original)) as src, (nullcontext(output) if isinstance(output,pdf.Document) else pdf.open(output)) as dest:
        for number,source_page,clip,target_page,slot in placements:
            samples=[]
            with pdf.open() as views:
                for doc,n,region in ((src,source_page,clip),(dest,target_page,slot)):
                    p=views.new_page(width=clip.width,height=clip.height)
                    p.show_pdf_page(p.rect,doc,n,clip=region)
                    bitmap=p.get_pixmap(matrix=pdf.Matrix(2,2),colorspace=pdf.csGRAY)
                    samples.append(255-np.frombuffer(bitmap.samples,dtype=np.uint8).astype(float))
            expected,actual=samples
            error=np.abs(expected-actual).sum()/max(expected.sum(),1)
            if expected.sum()==0 or error>.08:
                raise ValueError(f"原稿第 {source_page+1} 页式 ({number}) 的渲染校验失败（墨迹差异 {error:.1%}）。")
