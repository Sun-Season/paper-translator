"""将视觉译稿的段落、数学和图表交给论文 LaTeX 模板。"""
from pathlib import Path
import re
import json
import shutil
from copy import deepcopy
import tempfile

from lxml import html
import pypandoc
import pymupdf
from PIL import Image
from paper_translator.render.latex_backend import PAPER_PREAMBLE, compile_paper, escape, tex_engine
from paper_translator.translation.vision_flow import clean_boundaries
from paper_translator.render.ruled_algorithm import source_specs, match_rows, typeset
from paper_translator.source.source_header import header_region, draft_header_end, locate_header
from paper_translator.source.source_layout import source_layout, spans_gutter, abstract_columns
from paper_translator.source.equation_layout import numbered_equations
from paper_translator.source.original_tables import original_table_assets

CAP = re.compile(r"^(图|表|Figure|Table)\s*(S?\d+)\s*",re.I)
from paper_translator.config.math_commands import MATH_COMMANDS as SAFE_MATH


REFERENCE = re.compile(r"\[[\d,， –—-]+\]|(?:图|表|公式|式|Fig(?:ure)?\.)\s*(?:（S?\d+）|\(S?\d+\)|S?\d+(?![A-Za-z0-9]|\.\d))")


def math_tex(value):
    value=value.strip()
    if re.search(r"(?<!\\)[%#$]|\x00|\^\^|\\(?:begin|end)\s*\{(?!aligned\}|alignedat\}|gathered\}|matrix\}|pmatrix\}|bmatrix\}|vmatrix\}|Vmatrix\}|cases\}|array\}|smallmatrix\}|split\})",value):
        raise ValueError("公式含不支持的 TeX 语法。")
    if set(re.findall(r"\\([A-Za-z]+)",value))-SAFE_MATH:
        raise ValueError("公式含尚未支持的 LaTeX 命令。")
    depth=0
    for brace in re.findall(r"(?<!\\)[{}]",value):
        depth+=1 if brace=="{" else -1
        if depth<0: break
    if depth: raise ValueError("公式括号不匹配。")
    return value


def normalize_adjacent_math(markdown):
    """保护紧邻数字的行内公式，避免 Markdown 将它解析成普通文字。"""
    return re.sub(r"(?<![\\$])\$([^$\n]+)\$(?=\d)",
                  lambda m: m[0]+" " if re.search(r"[\\^_]",m[1]) else m[0], markdown)


def figure_order(nodes,captions):
    """整图连同图注提前入队，让双栏浮动图尽量贴近首次正文引用。"""
    queue={}
    moved=set()
    last_slot=0
    caption_indices=set(captions.values())
    for idx,cap in sorted(captions.items()):
        match=CAP.match(nodes[cap].text_content())
        if match[1].lower() not in ("图","figure"):
            continue
        pattern=re.compile(r"(?:图\s*|Fig(?:ure)?\.?\s+)"+re.escape(match[2])+r"(?![\d.]*\d)",re.I)
        first=next((j for j,n in enumerate(nodes) if j not in caption_indices and
                    n.tag=="p" and pattern.search(n.text_content())),None)
        slot=idx
        if first is not None:
            # 双栏通栏图一般在提交后的下一页页首放置；预留约一栏正文。
            slot=min(first,(idx+first)//2)
            length=0
            while slot>last_slot+1 and length<550 and nodes[slot-1].tag=="p" and slot-1 not in caption_indices:
                slot-=1
                length+=len(nodes[slot].text_content())
        slot=max(slot,last_slot)
        last_slot=slot
        if slot!=idx:
            queue.setdefault(slot,[]).append(idx)
            moved.add(idx)
    order=[]
    for i in range(len(nodes)):
        order.extend(queue.get(i,[]))
        if i not in moved:
            order.append(i)
    return order


def duplicate_of_header(text,header):
    """译稿里的标题/作者段落在原稿题头图里已经存在时返回 True。"""
    if not header or not text:return False
    from difflib import SequenceMatcher
    a="".join(re.findall(r"[a-z0-9]+",text.lower()))
    b="".join(re.findall(r"[a-z0-9]+",header.lower()))
    if len(a)<12 or not b:return False
    return a in b or SequenceMatcher(None,a,b).ratio()>=.9


def merge_split_display(markdown):
    """模型偶尔把一条多行公式拆成相邻两个 $$ 块；带编号时合并为 aligned。"""
    pattern = re.compile(r"\$\$(.*?)\$\$\s*\$\$(.*?)\$\$", re.S)

    def merge(match):
        first, second = match.group(1).strip(), match.group(2).strip()
        tag = re.search(r"\\tag\{(\d+)\}\s*$", first)
        tail = re.sub(r"\\tag\{\d+\}\s*$", "", first).rstrip() if tag else first
        if not tag or not re.search(r"(?:\\geq|\\leq|\\ge|\\le|=)\s*$", tail):
            return match.group(0)
        body = "\\begin{aligned}\n" + tail + "\n&\\quad " + second + "\n\\end{aligned}"
        return "$$" + body + " \\tag{" + tag.group(1) + "}$$"

    return pattern.sub(merge, markdown)


def protect_emphasis(markdown):
    """转义加粗片段内部的星号，公式里的 * 保持原样。"""
    def escape(match):
        parts = re.split(r"(\$[^$]+\$|\\\(.*?\\\))", match.group(1))
        text = "".join(part if (part.startswith("$") and part.endswith("$"))
                       or (part.startswith(r"\(") and part.endswith(r"\)"))
                       else part.replace("*", r"\*") for part in parts)
        return "**" + text + "**"
    return re.sub(r"\*\*([^\n]+?)\*\*", escape, markdown)


def source_heading_prefixes(source):
    """原稿中的章节编号（IV.、A.、4.）集合。"""
    prefixes = set()
    with pymupdf.open(source) as doc:
        for page in doc:
            for line in page.get_text().splitlines():
                text = " ".join(line.split())
                match = re.match(r"^((?:[IVXLC]+|\d+|[A-Z])(?:\.\d+)*\.)\s+[A-Z][^\n]{2,90}$", text)
                if match:
                    prefixes.add(match[1])
    return prefixes


def number_headings(markdown, prefixes):
    """按原稿编号样式把短标题行标成 Markdown 标题，避免被当成有序列表。"""
    if not prefixes:
        return markdown
    lines = []
    for line in markdown.splitlines():
        text = line.strip()
        match = re.match(r"^((?:[IVXLC]+|\d+|[A-Z])(?:\.\d+)*\.)\s+\S", text)
        if (match and match[1] in prefixes and len(text) <= 90
                and not re.search(r"[。！？；]", text)
                and not text.startswith(("#", "-", ">", "|", "!"))):
            lines.append("### " + text)
        else:
            lines.append(line)
    return "\n".join(lines)


def render_vision_latex(directory,source=None,args=None,*,prepared_draft=False,crop_boxes=None,equation_splits=None):
    from paper_translator.translation.vision_pdf import source_links
    directory=Path(directory)
    from paper_translator.config.layout_policy import load_layout, configure_preamble
    layout = load_layout(directory)
    object_layout = layout["objects"]
    manifest = {}
    (directory/"原表保留记录.json").unlink(missing_ok=True)
    (directory/"layout.json").write_text(json.dumps(layout, ensure_ascii=False, indent=2))
    md=(directory/"paper.md").read_text()
    md=re.sub(r"\\cite(?:p|t)?\{([\d,\s]+)\}", lambda m:"["+re.sub(r"\s+","",m[1])+"]", md)
    if source:
        from paper_translator.source.page_chrome import remove_repeated_headers
        md,removed_headers=remove_repeated_headers(md,source)
        (directory/"页眉清理记录.json").write_text(json.dumps(removed_headers,ensure_ascii=False,indent=2))
        from paper_translator.source.figure_groups import restore_groups
        md = restore_groups(md, source, directory)
    source_tables={}
    if source:
        if not prepared_draft:
            md=clean_boundaries(source_links(md,source),source)
        (directory/"paper.md").write_text(md)
        md,source_tables=original_table_assets(md,source)
    # 单图原页的图注有时被图内对话隔开；只在原稿编号唯一时重新配对。
    if source:
        chunks=re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)",md)
        with pymupdf.open(source) as doc:
            for page in doc:
                j=2*page.number+2
                if j>=len(chunks):
                    break
                labels=re.findall(r"(?m)^Figure\s+(S?\d+)\b",page.get_text())
                blocks=chunks[j].strip().split("\n\n")
                images=[k for k,b in enumerate(blocks) if b.startswith("![")]
                if len(images)==len(labels)==1:
                    caps=[k for k,b in enumerate(blocks) if re.match(r"^(?:Figure|图)\s*"+labels[0]+r"\s",b)]
                    if len(caps)==1 and caps[0]>images[0]+1:
                        blocks.insert(images[0]+1,blocks.pop(caps[0]))
                        chunks[j]="\n\n"+"\n\n".join(blocks)+"\n\n"
        md="".join(chunks)
    md=re.sub(r"(?m)^<!-- 原稿第 (\d+) 页 -->$",r"\n\nPAPERPAGEBOUNDARY\1\n\n",md)
    md=re.sub(r"(?m)^#+\s+(\d+\.\d+)[ \t]*\n+(?!#)([^\n。！？$]{1,28})$",r"### \1 \2",md)
    md=re.sub(r"(?m)^(A(?:\.\d+)?)\s+([^\n。！？$]{1,55})$",r"### \1 \2",md)
    # 模型偶尔把行内公式写成双反斜杠（\\(…\\)），先归一化再转换。
    md=md.replace("\\\\(", "\\(").replace("\\\\)", "\\)")
    md=md.replace("\\\\[", "\\[").replace("\\\\]", "\\]")
    md=re.sub(r"\\\[(.*?)\\\]",lambda m:"$$"+m[1]+"$$",md,flags=re.S)
    md=re.sub(r"\\\((.*?)\\\)",lambda m:"$"+m[1].strip()+"$",md,flags=re.S)
    md=re.sub(r"\$\$(.*?)\$\$",lambda m:"\n\n$$"+m[1]+"$$\n\n",md,flags=re.S)
    md=re.sub(r"\\eqno\s*\{?\((\d+)\)\}?",r"\\tag{\1}",md)
    md=re.sub(r"\\hfill\s+Eq\.\s*\((\d+)\)",r"　式（\1）",md)
    md=md.replace("<br>"," / ").replace("<br/>"," / ")
    md=re.sub(r"(?m)^(参考文献|References)\s*$",r"## \1",md)
    md=protect_emphasis(md)
    if source:
        md=number_headings(md,source_heading_prefixes(source))
    root=html.fragment_fromstring(pypandoc.convert_text(normalize_adjacent_math(md),"html5",format="markdown-raw_html-raw_tex",extra_args=["--mathjax","--wrap=none"]),create_parent="main")
    page_index=0
    nodes=[];origins=[]
    for node in root:
        marker=re.fullmatch(r"PAPERPAGEBOUNDARY(\d+)",node.text_content().strip())
        if marker:
            page_index=int(marker[1])-1
        else:
            nodes.append(node);origins.append(page_index)
    captions={}
    source_caps={}
    if source:
        with pymupdf.open(source) as original:
            for pg in original:
                source_caps[pg.number]=[(m[1],pymupdf.Rect(b[:4])) for b in pg.get_text("blocks")
                    if (m:=re.match(r"^Figure\s+(S?\d+)\b",b[4]))]
    for i,n in enumerate(nodes):
        if n.tag not in ("table","figure"):continue
        image=n.find(".//img")
        filename=image.get("src") if image is not None else None
        number=source_tables[filename][2] if filename in source_tables else None
        kind="table" if n.tag=="table" or filename in source_tables else "figure"
        if not number and filename in (crop_boxes or {}):
            box=crop_boxes[filename]
            candidates=[]
            for num,rect in source_caps.get(origins[i],[]):
                gap=rect.y0-box.y1
                if -18<=gap<75 and min(rect.x1,box.x1)>max(rect.x0,box.x0):
                    candidates.append((abs(gap),num))
            if candidates:number=min(candidates)[1]
        if number:
            matches=[j for j,node in enumerate(nodes) if origins[j]==origins[i] and node.tag=="p"
                and (m:=CAP.match(node.text_content())) and m[2]==number
                and ((m[1].lower() in ("表","table"))==(kind=="table"))]
            if len(matches)==1 and matches[0] not in captions.values():
                captions[i]=matches[0]
                continue
        for j in ((i-1,i+1) if kind=="table" else (i+1,i-1)):
            if 0<=j<len(nodes) and nodes[j].tag=="p" and (m:=CAP.match(nodes[j].text_content())) and j not in captions.values():
                if (m[1].lower() in ("表","table"))!=(kind=="table"):continue
                captions[i]=j
                break
    anchors=set()
    def cap_id(match):
        return ("fig-" if match[1].lower() in ("图","figure") else "tab-")+match[2]
    for k in captions.values():anchors.add(cap_id(CAP.match(nodes[k].text_content())))
    for n in nodes:
        b=re.match(r"^\[(\d+)\]\s",n.text_content())
        if b:anchors.add("bib-"+b[1])
    anchors.update("eq-"+k for k in re.findall(r"\\tag\{(\d+)\}",md))
    def printable(text):
        # 纯文本里偶尔仍带 $…$ 或 \(…\)；先按公式切分，避免把公式转义成普通字符。
        out=[]
        for part in re.split(r"(\\\(.*?\\\)|\$[^$]+\$)",text):
            if part.startswith(r"\(") and part.endswith(r"\)") and len(part)>4:
                try:out.append(r"\("+math_tex(part[2:-2])+r"\)");continue
                except ValueError:pass
            elif part.startswith("$") and part.endswith("$") and len(part)>2:
                try:out.append(r"\("+math_tex(part[1:-1])+r"\)");continue
                except ValueError:pass
            pieces=re.split(r"(https?://[^\s一-鿿，。；]+)",part)
            for k,piece in enumerate(pieces):
                if k%2:
                    pieces[k]="".join(escape(c)+(r"\allowbreak{}" if c in "/._-?&=" else "") for c in piece)
                else:
                    pieces[k]=escape(piece)
            chunk="".join(pieces)
            # DOI 在斜杠和点后给出断点，避免长 DOI 把整行顶出边界。
            chunk=re.sub(r"(10\.\d{4,9}/)([0-9A-Za-z.]+)",
                         lambda m:m.group(1)+r"\allowbreak{}"+m.group(2).replace(".",r".\allowbreak{}"),chunk)
            out.append(chunk)
        return "".join(out)
    def linked(text):
        def sub(m):
            t=m[0]
            def link(key,v):return r"\hyperlink{"+key+"}{"+v+"}" if key in anchors else v
            if t.startswith("["):return re.sub(r"\d+",lambda d:link("bib-"+d[0],d[0]),t)
            return link({"图":"fig-","F":"fig-","表":"tab-"}.get(t[0],"eq-")+re.search(r"S?\d+",t)[0],t)
        return REFERENCE.sub(sub,printable(text))
    def inline(n,links=True):
        encode=linked if links else printable
        t=encode(n.text or "")
        for child in n:
            tag=child.tag
            if tag=="span" and "math" in child.get("class","").split():
                val=math_tex(child.text_content()[2:-2])
                # 长行内公式在等号/逗号/斜杠处给出断点，避免整块公式超出栏宽。
                val=re.sub(r"([=,/])", r"\1\\allowbreak{}", val)
                t+=r"\("+val+r"\)"
            else:
                v=inline(child,links and tag!="a")
                if tag in ("strong","em","sup","sub"):
                    cmd={"strong":"textbf","em":"textit","sup":"textsuperscript","sub":"textsubscript"}[tag]
                    v="\\"+cmd+"{"+v+"}"
                if tag=="a" and re.fullmatch(r"https?://[^\s{}\\%#]+",child.get("href","")):
                    v=r"\href{"+child.get("href").replace("_",r"\_")+"}{"+v+"}"
                if tag=="code":v=v.replace(r"\_",r"\_\allowbreak{}")
                t+=v
            t+=encode(child.tail or "")
        # 行内公式和 DOI 本身不可断行；给出断点，避免整行越界。
        t=t.replace(r"\(", r"\allowbreak\(")
        return re.sub(r"(10\.\d{4,9}/)",r"\1\\allowbreak{}",t)
    abstract_count=1
    widths=[];columns=[];eq_boxes={};alg_specs={};preamble=configure_preamble(PAPER_PREAMBLE, layout["document"])
    if source:
        with pymupdf.open(source) as original:
            widths=[pg.rect.width for pg in original]
            columns,(left,right)=source_layout(original)
            abstract_count=abstract_columns(original[0],columns[0])
            override=getattr(args,"layout",None)
            if override in ("reflow","reflow-two"):
                columns=[1 if override=="reflow" else 2]*len(columns)
            paper=original[0].rect
            preamble=preamble.replace("paperwidth=648bp,paperheight=842bp,left=42bp,right=42bp",
                f"paperwidth={paper.width:.2f}bp,paperheight={paper.height:.2f}bp,left={left:.2f}bp,right={right:.2f}bp")
            for pg in original:
                alg_specs.update({(pg.number,n):spec for n,spec in source_specs(pg).items()})
                if columns[pg.number]==2:
                    for num,box in numbered_equations(pg).items():
                        eq_boxes[pg.number,num]=box
            (directory/"原稿栏式.json").write_text(json.dumps({"原页栏数":columns,"左边距_bp":left,"右边距_bp":right},ensure_ascii=False,indent=2))
    with tempfile.TemporaryDirectory(prefix="vision-tex-") as tmp:
        work=Path(tmp)
        if source_tables:
            # 表格按原稿矢量整块还原：表内文字保留原文，只翻译表题和表注。
            with pymupdf.open(source) as original:
                for filename,(page,box,_) in source_tables.items():
                    asset_name=Path(filename).stem+"-original.pdf"
                    (directory/"tables").mkdir(exist_ok=True)
                    with pymupdf.open() as asset:
                        target=asset.new_page(width=box.width,height=box.height)
                        target.show_pdf_page(target.rect,original,page,clip=box)
                        asset.save(work/asset_name)
                    shutil.copyfile(work/asset_name,directory/"tables"/asset_name)
                    tex=r"\includegraphics[width=\linewidth,height=.82\textheight,keepaspectratio]{"+asset_name+"}"
                    report=directory/"原表保留记录.json"
                    records=json.loads(report.read_text()) if report.exists() else {}
                    records[filename]={"source_page":page+1,"table":source_tables[filename][2],
                                       "mode":"original_vector","translated_cells":False}
                    report.write_text(json.dumps(records,ensure_ascii=False,indent=2))
                    print(f"表 {source_tables[filename][2]} 按原稿矢量还原，表内文字保留原文。",flush=True)
                    tablefile=Path(filename).with_suffix(".tex")
                    (work/tablefile).write_text(tex)
                    (directory/"tables").mkdir(exist_ok=True)
                    (directory/"tables"/tablefile).write_text(tex)
        if source:
            from paper_translator.harness.vision_harness import source_inventory
            with pymupdf.open(source) as original:
                for obj in source_inventory(original):
                    anchors.add({"figure":"fig-","table":"tab-","algorithm":"alg-"}.get(obj["type"],"")+str(obj["number"]))
            anchors.update("grid-"+Path(name).stem.replace("source-table-","grid-") for name in source_tables)
        body=[]
        equations={}
        header_end = draft_header_end(nodes, origins) if source else None
        if source:
            with pymupdf.open(source) as original:
                box = header_region(original[0])
                header_text=""
                if box and header_end:
                    with pymupdf.open(source) as original_text:
                        header_text=" ".join(original_text[0].get_text(clip=box).split())
                    header_width = min(box.width, widths[0] - left - right)
                    with pymupdf.open() as asset:
                        page = asset.new_page(width=box.width, height=box.height)
                        page.show_pdf_page(page.rect, original, 0, clip=box)
                        asset.save(work/"source-header.pdf")
                    body.append(r"\par\noindent\hspace*{"+f"{max(0,box.x0-left):.3f}bp"+
                                r"}\includegraphics[width="+f"{header_width:.3f}bp"+r"]{source-header.pdf}\par")
                else:
                    header_end = None
        figure_captions={};figure_groups={};figure_members=set()
        if source:
            with pymupdf.open(source) as original:
                for j,caption_index in captions.items():
                    if nodes[j].tag!='figure':continue
                    match=CAP.match(nodes[caption_index].text_content())
                    if not match or not cap_id(match).startswith('fig-'):continue
                    number=cap_id(match)[4:]
                    source_cap=next((b for b in original[origins[j]].get_text('blocks')
                                     if re.match(r'^(?:Figure|Fig\.?)\s*'+re.escape(number)+r'\b',b[4])),None)
                    if source_cap:figure_captions[j]=pymupdf.Rect(source_cap[:4])
            unused_figures=set(figure_captions)
            for j in sorted(figure_captions):
                if j not in unused_figures:continue
                rect=figure_captions[j]
                group=sorted([k for k in unused_figures if origins[k]==origins[j] and abs(figure_captions[k].y0-rect.y0)<4],key=lambda k:figure_captions[k].x0)
                if len(group)>1 and all(figure_captions[a].x1<figure_captions[b].x0 for a,b in zip(group,group[1:])):
                    figure_groups[min(group)]=group
                    figure_members.update(set(group)-{min(group)})
                    unused_figures.difference_update(group)
        def copy_figure(j,filename):
            src=nodes[j].find('.//img').get('src')
            shutil.copyfile(directory/src,work/filename)
        sibling_groups={};sibling_members=set()
        table_nodes={n.find(".//img").get("src"):i for i,n in enumerate(nodes)
                     if n.tag=="figure" and n.find(".//img") is not None and n.find(".//img").get("src") in source_tables}
        unused=set(table_nodes)
        for filename in sorted(table_nodes,key=lambda f:table_nodes[f]):
            if filename not in unused:continue
            pg,rect,_=source_tables[filename]
            group=sorted([f for f in unused if source_tables[f][0]==pg and abs(source_tables[f][1].y0-rect.y0)<3],
                         key=lambda f:source_tables[f][1].x0)
            if len(group)>1 and all(source_tables[a][1].x1<source_tables[b][1].x0 for a,b in zip(group,group[1:])):
                indices=[table_nodes[f] for f in group]
                leader=min(indices)
                if all(j in captions for j in indices):
                    sibling_groups[leader]=group
                    sibling_members.update(set(indices)-{leader})
                    unused.difference_update(group)
        from paper_translator.source.contents import contents_plan,contents_tex
        (directory/'目录重建记录.json').unlink(missing_ok=True)
        toc=contents_plan(nodes)
        if toc:
            (directory/'目录重建记录.json').write_text(json.dumps(toc,ensure_ascii=False,indent=2))
        in_columns=False
        started=False
        in_abstract=False
        emitted=set()
        def dest(key):
            anchors.add(key)
            if key in emitted:return ""
            emitted.add(key)
            return r"\hypertarget{"+key+"}{}"
        algorithms=match_rows(nodes,origins,alg_specs)
        algorithm_rows={j for _,rows,_ in algorithms.values() for j in rows}
        order=figure_order(nodes,captions) if layout["document"]["figure_near_reference"] else list(range(len(nodes)))
        if columns:
            # 浮动对象可在同一版式区段内靠近引用，不能跨越切栏边界。
            regions=[0]
            for j in range(1,len(columns)):
                regions.append(regions[-1]+int(columns[j]!=columns[j-1]))
            order.sort(key=lambda k:regions[origins[k]])
        front_end = next((k for k,n in enumerate(nodes) if origins[k]==0 and n.tag in ("h1","h2","h3") and re.match(r"^(?:(?:1|I)[.、．]?\s|引言|绪论|Introduction)", n.text_content().strip(), re.I)), 0)
        if layout["document"]["preserve_front_order"] and front_end:
            order = list(range(front_end)) + [k for k in order if k >= front_end]
        for i in order:
            if header_end and i < header_end:continue
            if header_text and origins[i]==0 and duplicate_of_header(nodes[i].text_content(),header_text):continue
            if toc and toc['start']<i<toc['end']:continue
            n=nodes[i]
            if i in captions.values() or i in algorithm_rows or i in sibling_members or i in figure_members:continue
            t=n.text_content().strip()
            is_introduction=bool(re.match(r"^(?:(?:1|I)[.、．]?\s|引言|绪论|Introduction)",t,re.I)) and n.tag in ("h1","h2","h3")
            abstract_label = origins[i]==0 and re.match(r"^(?:摘要|Abstract\b)",t,re.I)
            if abstract_label:
                in_abstract=True
            if is_introduction:
                in_abstract=False

            if n.tag in ("h1","h2","h3","h4","h5","h6"):
                if i and (re.match(r"^(?:(?:1|I)[.、．]?\s|引言|绪论|Introduction)",t,re.I) or (i>0 and re.match(r"^\d+[.\s]",t))):
                    started=True
            if origins[i]>0:started=True
            dual=(in_abstract and abstract_count==2) or (started and bool(columns) and columns[origins[i]]==2)
            wide=n.tag in ("figure","table")
            width=None
            if n.tag=="figure":
                img=n.find(".//img")
                if img is None:raise ValueError("图块缺少图片。")
                original_table=img.get("src") in source_tables
                if original_table:
                    filename=img.get("src")
                    width=source_tables[filename][1].width
                    wide=spans_gutter(source_tables[filename][1],widths[source_tables[filename][0]])
                else:
                    path=(directory/img.get("src","")).resolve()
                    if path.parent!=(directory/"figures").resolve() or not path.is_file():raise ValueError("图块路径无效。")
                    with Image.open(path) as im:
                        wide=im.width/im.height>1.15
                        match=re.fullmatch(r"page-(\d+)-\d+\.png",path.name)
                        if match and 0<int(match[1])<=len(widths):
                            dpi=im.info.get("dpi",(400,400))[0]
                            wide=im.width*72/dpi > widths[int(match[1])-1]*.6
                            width=im.width*72/dpi
                    original_box=(crop_boxes or {}).get(img.get("src"))
                    if original_box and widths:
                        width=original_box.width
                        wide=spans_gutter(original_box,widths[origins[i]])
            if i in sibling_groups:
                boxes=[source_tables[f][1] for f in sibling_groups[i]]
                group_box=pymupdf.Rect(boxes[0])
                for rectangle in boxes[1:]:group_box|=rectangle
                width=group_box.width
                wide=spans_gutter(group_box,widths[origins[i]])
            if i in figure_groups:
                wide=True
            object_id = cap_id(CAP.match(nodes[captions[i]].text_content())) if i in captions else None
            if i in algorithms:
                object_id = "alg-" + algorithms[i][0]
                wide = spans_gutter(pymupdf.Rect(algorithms[i][2]["box"]), widths[origins[i]])
            if object_id:
                setting = object_layout.get(object_id, {})
                if setting.get("span") in ("single", "wide"):
                    wide = setting["span"] == "wide"
                manifest[object_id] = {"source_page": origins[i]+1, "span": "wide" if wide else "single",
                                       "column_widths": setting.get("column_widths")}
            if dual!=in_columns:
                if dual and origins[i]==0:
                    body.insert(0,r"\twocolumn[{")
                    body.append(r"}]\raggedbottom")
                else:
                    body.append(r"\twocolumn" if dual else r"\onecolumn")
                in_columns=dual
            def place_graphic(content):
                if started:
                    kind="table" if original_table else "figure"
                    env=kind+"*" if wide and dual else kind
                    spec="[!tp]" if wide and dual else "[!htbp]"
                    content="\\begin{"+env+"}"+spec+content+"\\end{"+env+"}"
                body.append("{\\par"+content+"\\par}")
            if i in algorithms:
                num,rows,spec=algorithms[i]
                wide=dual and wide
                env="figure*" if wide else "figure"
                block=typeset(n,nodes,rows,spec,num,inline,anchors)
                body.append("\\begin{"+env+"}[!htbp]"+block+"\\end{"+env+"}")
            elif n.tag in ("figure","table"):
                cap=""
                if i in captions:
                    cn=nodes[captions[i]]
                    m=CAP.match(cn.text_content())
                    desc=deepcopy(cn)
                    if desc.text and CAP.match(desc.text):
                        desc.text=CAP.sub("",desc.text,count=1)
                        caption_text=inline(desc)
                    else:
                        rest=cn.text_content()[m.end():]
                        # 图注前缀被加粗时 text 在子节点里，这里按文本重建并保留行内公式。
                        caption_text="".join(
                            (r"\("+math_tex(part[2:-2])+r"\)") if part.startswith(r"\(") and part.endswith(r"\)")
                            else linked(part)
                            for part in re.split(r"(\\\(.*?\\\))",rest))
                    cap=(dest(cap_id(m))+r"{\raggedright\fontsize{9}{12}\selectfont\noindent\textbf{"
                         +escape(m[0].strip())+r"}\enspace "+caption_text+r"\par}")
                if n.tag=="figure":
                    if original_table and i in sibling_groups:
                        cells=[]
                        available=(widths[origins[i]]-left-right)/(2 if dual and not wide else 1)
                        ratio=min(1,available/group_box.width)
                        for sibling in sibling_groups[i]:
                            page,rectangle,num=source_tables[sibling]
                            j=table_nodes[sibling]
                            caption=deepcopy(nodes[captions[j]])
                            value=inline(caption)
                            cell_width=rectangle.width*ratio
                            grid=Path(sibling).stem.replace("source-table-","grid-")
                            manifest["tab-"+num]={"source_page":page+1,"span":"wide" if wide else "single",
                                                  "column_widths":object_layout.get("tab-"+num,{}).get("column_widths")}
                            cell_cap=cap if j==i else dest("tab-"+num)+r"{\raggedright\fontsize{9}{12}\selectfont\noindent "+value+r"\par}"
                            cells.append(r"\begin{minipage}[t]{"+f"{cell_width:.3f}bp"+r"}\vspace{0pt}"+
                                cell_cap+r"\smallskip"+dest(grid)+r"\input{"+Path(sibling).with_suffix(".tex").name+r"}\end{minipage}")
                        place_graphic(r"\noindent "+r"\hfill".join(cells)+r"\par")
                        continue
                    if original_table:
                        num=source_tables[filename][2]
                        grid=Path(filename).stem.replace("source-table-","grid-")
                        cap=cap.replace(r"\textbf{表 "+num+"}",r"\hyperlink{"+grid+r"}{\textbf{表 "+num+"}}",1)
                        table_width=(f"{min(width,(widths[origins[i]]-left-right)/(2 if dual and not wide else 1)):.2f}bp" if widths else r"\linewidth")
                        place_graphic(r"\centering\begin{minipage}{"+table_width+"}"+cap+
                                    r"\vspace{3pt}\centering"+dest(grid)+r"\par\nobreak"+
                                    r"\input{"+Path(filename).with_suffix(".tex").name+
                                    r"}\end{minipage}\par\smallskip")
                        continue
                    if i in figure_groups:
                        cells=[]
                        group=figure_groups[i]
                        combined=pymupdf.Rect(figure_captions[group[0]])
                        for j in group[1:]:combined|=figure_captions[j]
                        available=widths[origins[i]]-left-right
                        ratio=min(1,available/combined.width)
                        for j in group:
                            image=nodes[j].find('.//img')
                            asset=f'figure-{j}.png';copy_figure(j,asset)
                            cn=deepcopy(nodes[captions[j]]);m=CAP.match(cn.text_content());key=cap_id(m)
                            cell_cap=cap if j==i else dest(key)+r'{\raggedright\fontsize{9}{12}\selectfont\noindent '+inline(cn)+r'\par}'
                            cell_width=figure_captions[j].width*ratio
                            manifest[key]={'source_page':origins[j]+1,'span':'wide','column_widths':None}
                            cells.append(r'\begin{minipage}[t]{'+f'{cell_width:.3f}bp'+r'}\vspace{0pt}\centering\includegraphics[width=\linewidth,height=.40\textheight,keepaspectratio]{'+asset+r'}\par\smallskip'+cell_cap+r'\end{minipage}')
                        place_graphic(r'\centering '+r'\hfill'.join(cells)+r'\par')
                        continue
                    filename=f"figure-{i}.png";copy_figure(i,filename)
                    graphic_width=r"\linewidth"
                    if width and widths:
                        available=widths[origins[i]]-left-right
                        if dual and not wide:available=(available-20)/2
                        graphic_width=f"{min(max(width,figure_captions[i].width) if i in figure_captions else width,available):.2f}bp"
                    place_graphic(r"\centering\begin{minipage}{"+graphic_width+r"}\centering\includegraphics[width=\linewidth,height=.69\textheight,keepaspectratio]{"+filename+r"}\par\vspace{3pt}\hrule\vspace{3pt}"+cap+r"\end{minipage}\par\smallskip")
                else:
                    if dual and wide: body.append(r"\onecolumn")
                    rows=n.xpath(".//tr"); count=max(len(r) for r in rows)
                    fractions = object_layout.get(object_id, {}).get("column_widths") or [1/count]*count
                    if len(fractions) != count: raise ValueError("表格列宽数量与 Markdown 表格不符。")
                    spec = "".join(r"p{\dimexpr "+str(v)+r"\linewidth-6pt\relax}" for v in fractions)
                    table_env = "tabular" if dual and not wide else "longtable"
                    body.append(r"\par "+cap+r"\nobreak{\small\setlength{\tabcolsep}{3pt}\begin{"+table_env+r"}{@{}"+spec+r"@{}}\hline")
                    for r in rows:
                        body.append(" & ".join(inline(c) for c in r)+r"\\")
                        if r[0].tag=="th":body.append(r"\hline"+(r"\endhead" if table_env=="longtable" else ""))
                    body.append(r"\hline\end{"+table_env+"}}")
                    if dual: body.append(r"\twocolumn")
            elif in_abstract and (n.tag == "p" or abstract_label):
                content = deepcopy(n)
                if abstract_label:
                    prefix = re.match(r"^\s*(?:摘要|Abstract\b)\s*[—–:：-]*\s*", content.text_content(), re.I)
                    remaining = prefix.end()
                    for segment in content.xpath(".//text()"):
                        if not remaining:
                            break
                        value = str(segment)
                        removed = min(remaining, len(value))
                        if segment.is_text:
                            segment.getparent().text = value[removed:]
                        else:
                            segment.getparent().tail = value[removed:]
                        remaining -= removed
                label = r"\textbf{\textit{" + escape(layout["document"]["abstract_label"]) + r"}}—" if abstract_label else ""
                value = inline(content)
                if layout["document"]["abstract_body_style"] == "bold":
                    value = r"\textbf{" + value + "}"
                body.append(r"\par\noindent " + label + value + r"\par")
            elif (n.tag.startswith("h") and n.tag[1:].isdigit()) or (toc and i in toc['headings']):
                if i==0:body.append(r"{\centering\LARGE\bfseries "+inline(n)+r"\par}\medskip")
                else:
                    if is_introduction:
                        body.append(r"\par\addvspace{"+str(layout["document"]["introduction_gap_bp"])+r"bp}")
                    body.append(r"\pdfbookmark[1]{"+escape(t)+"}{sec-"+str(i)+r"}\subsection*{"+inline(n)+"}")
                if toc and i in toc['headings']:
                    body.append(r'\hypertarget{'+toc['headings'][i]['label']+r'}{}\label{'+toc['headings'][i]['label']+'}')
                if toc and i==toc['start']:
                    body.append(contents_tex(toc,escape))
            elif n.tag in ("ol","ul"):
                env="enumerate" if n.tag=="ol" else "itemize"
                body.append("\\begin{"+env+"}")
                if env == "enumerate":
                    start = int(n.get("start", "1"))
                    body.append(r"\setcounter{enumi}{"+str(start-1)+"}")
                body.extend([*(r"\item "+inline(c) for c in n),"\\end{"+env+"}"])
            elif len(n)==1 and "display" in n[0].get("class","").split():
                val=math_tex(n[0].text_content()[2:-2])
                from paper_translator.render.equation_split import _width_em
                tag=(re.search(r"\\tag\{(\d+)\}",val)
                     or re.search(r"\\quad\s*\((\d+)\)\s*$",val))
                if tag:
                    val=val[:tag.start()]+val[tag.end():]
                if r"\\" in val and r"\begin" not in val: val=r"\begin{gathered}"+val+r"\end{gathered}"
                key=tag[1] if tag else "u"+str(len(equations))
                equations[key]=val
                inner=(equation_splits or {}).get(key,val)
                measure=(r"\setbox\eqbox\hbox{$\displaystyle "+inner+r"$}"
                         r"\typeout{EQWIDTH:"+key+r":\the\wd\eqbox:\the\linewidth}")
                if tag:
                    equation=(dest("eq-"+tag[1])+measure+r"\["+inner+r"\tag{"+tag[1]+r"}\]")
                else:
                    # 无编号公式没有原稿框可对照，仍用等比缩小兜底。
                    equation=r"\par{\centering\fitmath{"+inner+r"}{}\par}"
                rect=eq_boxes.get((origins[i],tag[1])) if tag else None
                limit=((widths[origins[i]]-left-right)/2-8) if dual else (widths[origins[i]]-left-right-8)
                if tag and rect is not None and _width_em(val)*10.95>limit:
                    # 排不进栏宽时保留原稿公式（矢量、原始换行/对齐和编号），不缩小字号。
                    asset_name="eq-"+tag[1]+"-original.pdf"
                    with pymupdf.open(source) as original, pymupdf.open() as asset:
                        page=original[origins[i]]
                        target=asset.new_page(width=rect.width,height=rect.height)
                        target.show_pdf_page(target.rect,original,page.number,clip=rect)
                        asset.save(work/asset_name)
                    (directory/"figures").mkdir(exist_ok=True)
                    shutil.copyfile(work/asset_name,directory/"figures"/asset_name)
                    wide=dual and spans_gutter(rect,widths[origins[i]])
                    figure=r"\includegraphics[width=\linewidth,height=.9\textheight,keepaspectratio]{"+asset_name+"}"
                    if wide:
                        equation=r"\hypertarget{eq-"+tag[1]+r"}{}\begin{figure*}[!tp]"+figure+r"\end{figure*}"
                    else:
                        equation=r"\hypertarget{eq-"+tag[1]+r"}{}\par{\centering "+figure+r"\par}"
                    body.append(equation); continue
                if dual and rect is not None and spans_gutter(rect,widths[origins[i]]):
                    equation=r"\begin{figure*}[!tp]"+equation+r"\end{figure*}"
                body.append(equation)
            elif t:
                foot=re.match(r"^([¹²³⁴⁵⁶⁷⁸⁹⁰]+)\s*",t)
                if foot:
                    number="".join(str("¹²³⁴⁵⁶⁷⁸⁹⁰".index(c)+1) for c in foot[1])
                    desc=deepcopy(n)
                    if desc.text:desc.text=desc.text[foot.end():]
                    body.append(r"\footnotetext["+number+"]{"+inline(desc)+r"}")
                    continue
                bib=re.match(r"^\[(\d+)\]\s",t)
                if bib:body.append(r"\par\noindent\raggedright\hangindent=1.7em "+dest("bib-"+bib[1])+inline(n,False)+r"\par")
                elif started and n.tag=="p" and re.search(r"[一-鿿]",t) and not t.startswith(("†","‡")):
                    body.append(r"{\leftskip=0pt\rightskip=0pt\parfillskip=0pt plus 1fil\noindent\hspace*{\bodyindent}"+inline(n)+r"\par}")
                else:body.append(r"\par\noindent "+inline(n)+r"\par")

        extra=r"""\usepackage{amsmath,amsfonts,amssymb,longtable}
\raggedbottom
\renewcommand{\dblfloatpagefraction}{.80}
\renewcommand{\floatpagefraction}{.80}
\renewcommand{\dbltopfraction}{.94}
\renewcommand{\topfraction}{.92}
\renewcommand{\textfraction}{.07}
\setcounter{dbltopnumber}{3}
\newsavebox{\eqbox}
\newcommand{\fitmath}[2]{\sbox{\eqbox}{$\displaystyle #1$#2}\ifdim\wd\eqbox>\linewidth\typeout{EQSCALE:\the\wd\eqbox:\the\linewidth}\resizebox{\linewidth}{!}{\usebox{\eqbox}}\else\usebox{\eqbox}\fi}
"""
        (directory/"layout-objects.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        (directory/"equations.json").write_text(json.dumps(equations,ensure_ascii=False,indent=2))
        compile_paper(work,directory/"paper.pdf",body,tex_engine(),preamble.replace(r"\begin{document}",extra+r"\begin{document}"))

        if source:
            report = {"verified": False, "reason": "无法可靠分隔原稿或译稿的题头与摘要"}
            if header_end:
                with pymupdf.open(source) as original, pymupdf.open(directory/"paper.pdf") as output:
                    score, (x, y) = locate_header(original[0], output[0], box, header_width)
                    scale = header_width / box.width
                    printed_box = pymupdf.Rect(x-2, y-2, x+header_width+2, y+box.height*scale+2)
                    source_text = "".join(original[0].get_text(clip=box).split())
                    printed_text = "".join(output[0].get_text(clip=printed_box).split())
                    report = {"verified": score >= .92 and source_text == printed_text,
                              "similarity": score, "text_matches": source_text == printed_text,
                              "source_box": list(box)}
                    if report["verified"]:
                        for link in original[0].get_links():
                            rect = link["from"]
                            if box.contains(rect) and link.get("uri", "").startswith(("https://", "http://")):
                                target = pymupdf.Rect(x+(rect.x0-box.x0)*scale, y+(rect.y0-box.y0)*scale,
                                                      x+(rect.x1-box.x0)*scale, y+(rect.y1-box.y0)*scale)
                                output[0].insert_link({"kind":pymupdf.LINK_URI, "from":target, "uri":link["uri"]})
                        if output.is_dirty:output.saveIncr()
            (directory/"题头检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
