"""按表题、横线与原页位置恢复独立表格，保留原 PDF 的字形和线条。"""
import re
import pymupdf


def table_regions(page):
    blocks=page.get_text("blocks")
    captions=[]
    rules=[g["rect"] for g in page.get_drawings() if g["type"]=="s"
           and g["rect"].height<1.5 and g["rect"].width>page.rect.width*.22]
    for b in blocks:
        m=re.match(r"^(?:Table|表)\s*(S?\d+)\b",b[4],re.I)
        if not m:
            continue
        cap=pymupdf.Rect(b[:4])
        starts=[r for r in rules if 0<=r.y0-cap.y1<24
                and min(r.x1,cap.x1)>max(r.x0,cap.x0)]
        if starts:
            captions.append((m[1],cap,min(starts,key=lambda r:r.y0)))
    result={}
    for num,cap,first in captions:
        limit=min((c.y0 for _,c,_ in captions if c.y0>first.y0 and c.x0<first.x1 and c.x1>first.x0),default=page.rect.height)
        aligned=sorted((r for r in rules if first.y0<=r.y0<limit and abs(r.x0-first.x0)<2
                        and abs(r.x1-first.x1)<2),key=lambda r:r.y0)
        if len(aligned)>=3:
            result[num]=pymupdf.Rect(first.x0-1,first.y0-1,first.x1+1,aligned[-1].y1+1)&page.rect
    return result


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
