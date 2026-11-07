"""移除被重复抄入译稿的页眉，保留正文中的普通重复用语。"""
from collections import Counter
import math
import re

import pymupdf

# 页面四周、明显小于正文的印刷文字（会议模板的审稿人须知、版权行、投稿声明、
# 页码等）不是论文内容；翻译前直接遮挡，避免被当作正文翻译。
TOP_BAND=.05
BOTTOM_BAND=.92
FINE_PRINT=.75


def chrome_boxes(page):
    """返回页眉、页码和细小页脚套话的矩形（单位与页面点一致）。"""
    height=page.rect.height
    lines=[]
    for block in page.get_text("dict",flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        for line in block.get("lines",[]):
            text="".join(s["text"] for s in line["spans"]).strip()
            if not text:continue
            lines.append((pymupdf.Rect(line["bbox"]),
                          max(s["size"] for s in line["spans"]),text))
    if not lines:return []
    weights=Counter()
    for rect,size,text in lines:
        if height*.15<rect.y0<height*.85:
            weights[round(size,1)]+=len(text)
    body_size=weights.most_common(1)[0][0] if weights else sorted(s for _,s,_ in lines)[len(lines)//2]
    boxes=[]
    for rect,size,text in lines:
        header=rect.y1<height*TOP_BAND and size<=body_size*1.05
        footer=rect.y0>height*BOTTOM_BAND and (size<body_size*FINE_PRINT
                                               or re.fullmatch(r"[0-9]{1,4}",text))
        if header or footer:boxes.append(rect)
    return boxes


def chrome_text(page,boxes):
    """按遮挡区域拼出页面文本，供文本层回退时跳过这些套话。"""
    return "\n".join(" ".join(b[4].split()) for b in page.get_text("blocks")
                     if not any(pymupdf.Rect(b[:4]).intersects(box) for box in boxes))


def remove_repeated_headers(markdown, source):
    chunks=re.split(r'(?m)(^<!-- 原稿第 \d+ 页 -->)',markdown)
    with pymupdf.open(source) as doc:
        headers=Counter()
        for page in doc:
            seen=set()
            for b in page.get_text('blocks'):
                value=' '.join(b[4].split())
                if b[3]<page.rect.height*.08 and len(value)>12:
                    seen.add(value)
            headers.update(seen)
        threshold=max(3,math.ceil(len(doc)*.5))
        if not any(n>=threshold for n in headers.values()):
            return markdown,[]
    paragraphs=[part.strip().split('\n\n') for part in chunks[2::2]]
    first=Counter(re.sub(r'\s+','',p[0]) for p in paragraphs if p and len(p[0].strip())<=160)
    repeated={s for s,n in first.items() if n>=threshold and s and not s.startswith(('#','!','|','$'))}
    removed=[]
    for i,parts in enumerate(paragraphs):
        kept=[]
        for part in parts:
            if re.sub(r'\s+','',part) in repeated:
                removed.append({'source_page':i+1,'text':part.strip(),'reason':'重复页首短段且原稿存在重复页眉'})
            else:
                kept.append(part)
        chunks[2*i+2]='\n\n'+'\n\n'.join(kept)+'\n\n'
    return ''.join(chunks),removed
