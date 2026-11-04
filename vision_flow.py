"""依据原页的标题和表号，清理视觉译稿在页界重复的正文。"""
import re

import pymupdf


def overlap(a,b):
    def grams(s):
        s=re.sub(r"[^\w]","",s.lower())
        return {s[i:i+2] for i in range(len(s)-1)}
    x,y=grams(a),grams(b)
    return len(x & y)/max(1,min(len(x),len(y)))


def remove_panel_transcripts(blocks,page):
    """仅合并有原图、匹配图注及图内文字证据的重复转写。"""
    source=page.get_text("blocks")
    images=page.get_image_info()
    for i,block in enumerate(blocks[:-1]):
        if not block.startswith("![") or not (label:=re.match(r"^图\s*(S?\d+)\s",blocks[i+1])):
            continue
        cap=next((b for b in source if re.match(r"^Figure\s+"+label[1]+r"\b",b[4],re.I)),None)
        if not cap:
            continue
        tiles=[im["bbox"] for im in images if im["bbox"][1]<cap[1] and im["bbox"][3]<=cap[1]+2]
        if not tiles:
            continue
        top=min(b[1] for b in tiles)-12
        content="\n".join(b[4] for b in source if b[1]>=top and b[3]<=cap[1])
        labels={"任务":"Task","问题":"Question","答案":"Answer","回答":"Answer"}
        for j in reversed(range(i)):
            text=blocks[j].strip()
            field=re.match(r"^(任务|问题|答案|回答)\s*\d*[:：]",text)
            directions=re.fullmatch(r"(?:(?:前|后|背|左|右)视图\s*){2,}",text)
            literal=re.fullmatch(r"[A-Z][A-Z0-9-]{1,10}",text)
            if ((field and re.search(r"\b"+labels[field[1]]+r"\s*\d*:",content,re.I))
                or (directions and re.search(r"\b(?:Front|Back)\b",content,re.I)
                    and re.search(r"\b(?:Left|Right)\b",content,re.I))
                or (literal and text in content.split())):
                blocks[j]=""
            else:
                break
    blocks[:]=[b for b in blocks if b]


def clean_boundaries(markdown,source):
    chunks=re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)",markdown)
    pages=[chunk.strip().split("\n\n") for chunk in chunks[2::2]]
    if not pages:
        return markdown
    with pymupdf.open(source) as doc:
        if len(doc)!=len(pages):
            raise ValueError("译稿的原页标记与输入论文页数不一致。")
        for i,blocks in enumerate(pages):
            remove_panel_transcripts(blocks,doc[i])
        for i in range(1,len(pages)):
            left,right=pages[i-1],pages[i]
            current=doc[i].get_text()
            prior=doc[i-1].get_text()
            # 当模型提前译出下一页的新章节或表格时，以原稿上的起点为准。
            for j,block in enumerate(left):
                heading=re.match(r"^#+\s+(\d+(?:\.\d+)*)(?=\s|$)",block)
                caption=re.match(r"^(?:表|Table)\s*(\d+)\s",block,re.I)
                anchor=(r"^"+re.escape(heading[1])+r"\s*\n[A-Z]" if heading else
                        r"^Table "+caption[1]+r"\s" if caption else None)
                if anchor and re.search(anchor,current,re.M) and not re.search(anchor,prior,re.M):
                    # 原页中的公式也可能是“数字、换行、大写字母”。要求下一页译稿
                    # 有相同标题，并逐块确认回显；未匹配的文字和图片继续保留。
                    if heading and not any(re.match(r"^#+\s+"+re.escape(heading[1])+r"(?=\s|$)",b) for b in right):
                        continue
                    left[j:]=[b for b in left[j:] if b.startswith("![") or not any(
                        b==other or len(b)>20 and len(other)>20 and overlap(b,other)>.80
                        and sorted(re.findall(r"\d+(?:\.\d+)?",b))==sorted(re.findall(r"\d+(?:\.\d+)?",other))
                        for other in right)]
                    break
            # 页首是原表时，表前连续复现上一页的段落属于上下文回显。
            table=re.search(r"(?m)^(Table|Figure)\s+(S?\d+)\b",current)
            label=("表" if table and table[1]=="Table" else "图")
            caption_start=r"^(?:"+label+"|"+(table[1] if table else "Figure")+r")\s*"+(table[2] if table else "")+r"\s"
            image=next((j for j,b in enumerate(right) if b.startswith("![")),None)
            if table and image and left:
                repeated=[b for b in right[:image] if len(b)>25 and any(
                    overlap(b,x)>.72 and sorted(re.findall(r"\d+(?:\.\d+)?",b))==sorted(re.findall(r"\d+(?:\.\d+)?",x)) for x in left[-10:] if len(x)>25 and not x.startswith("!["))]
                if len(repeated)>=2:
                    retained=[b for b in right[:image] if b not in repeated and not (
                        len(b)<30 and (re.match(r"^(?:表|Table)\s*\d+",b) or
                        b.startswith("#") and any(overlap(b,x)>.8 for x in left if x.startswith("#")))
                        and not re.match(caption_start,b)
                    )]
                    if not any(re.match(caption_start,b) for b in retained+right[image+1:image+2]):
                        title=current[table.start():].splitlines()[0]
                        retained.append(re.sub(r"^(?:Figure|Table)\s+",label+" ",title))
                    right[:image]=retained
            if left and len(left[-1])>=12 and not re.search(r"[。！？.!?]$",left[-1]) and any(
                len(b)>len(left[-1]) and overlap(left[-1],b[:len(left[-1])+12])>.72
                for b in right[:5] if not b.startswith("![")):
                left.pop()
            if left and right and re.search(r"[，、；或的到]$",left[-1]):
                j=next((j for j,b in enumerate(right) if not re.match(
                    r"^(!\[|(?:图|表|Table|Figure)\s*S?\d+\s|\|)",b)),None)
                src_end=re.sub(r"\s*\b"+str(i)+r"\s*$","",prior).rstrip()
                if j is not None and re.search(r"[A-Za-z,]$",src_end) and (
                    re.match(r"^\d+[%％]",right[j]) or left[-1].endswith("，") and re.match(r"^[一-鿿]",right[j]) and not re.match(r"^(?:任务|图|表)\s*\d",right[j])
                ):
                    left[-1]+=right.pop(j)
            # 页首名词补足前页比较级的宾语；下一句的转折同时提供对齐证据。
            if left and left[-1].endswith("减少") and re.search(r"\bfewer\s*\n\d+\s*$",prior):
                gloss={"decisions":"决策次数","steps":"步数","requests":"请求次数","actions":"动作次数"}
                continuation=re.search(r"(?m)^([a-z]+)\. In contrast,",current)
                if continuation and continuation[1] in gloss and any(
                    b.startswith(("相比之下","相较之下")) for b in right[:5]):
                    left[-1]+=gloss[continuation[1]]+"。"
    for k,blocks in enumerate(pages):
        chunks[2*k+2]="\n\n"+"\n\n".join(blocks)+"\n\n"
    return "".join(chunks)
