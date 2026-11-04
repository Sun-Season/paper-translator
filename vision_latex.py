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
from latex_backend import PAPER_PREAMBLE, compile_paper, escape, tex_engine
from vision_flow import clean_boundaries
from ruled_algorithm import source_specs, match_rows, typeset
from source_header import header_region, draft_header_end, locate_header
from source_layout import source_layout, spans_gutter, abstract_columns
from equation_layout import numbered_equations
from original_tables import original_table_assets
from native_tables import table_tex

CAP = re.compile(r"^(图|表|Figure|Table)\s*(S?\d+)\s*",re.I)
SAFE_MATH=set(r"""alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega left right big Big bigg Bigg bigl bigr frac dfrac tfrac sqrt sum prod int iint oint lim limits nolimits in notin cup cap union subset subseteq supset supseteq parallel mid vert Vert lVert rVert lvert rvert langle rangle lbrace rbrace ldots cdots dots vdots ddots pm mp times div cdot circ ast to mapsto rightarrow leftarrow Rightarrow Leftrightarrow le leq ge geq ne neq approx equiv sim simeq propto forall exists infty nabla partial emptyset ell mathcal mathbb mathrm mathbf mathit mathsf mathtt text operatorname log ln exp sin cos tan min max arg det hat widehat bar overline underline tilde widetilde vec dot ddot bigcup bigcap bigoplus oplus otimes quad qquad hspace tag displaystyle textstyle scriptstyle scriptscriptstyle underbrace overbrace binom substack begin end boldsymbol perp lfloor rfloor odot uparrow downarrow""".split())


REFERENCE = re.compile(r"\[[\d,， –—-]+\]|(?:图|表|公式|式|Fig(?:ure)?\.)\s*(?:（S?\d+）|\(S?\d+\)|S?\d+(?![A-Za-z0-9]|\.\d))")


def math_tex(value):
    value=value.strip()
    if re.search(r"[%#$\x00]|\^\^|\\(?:begin|end)\s*\{(?!aligned\}|gathered\}|matrix\}|pmatrix\}|bmatrix\}|cases\})",value):
        raise ValueError("公式含不支持的 TeX 语法。")
    if set(re.findall(r"\\([A-Za-z]+)",value))-SAFE_MATH:
        raise ValueError("公式含尚未支持的 LaTeX 命令。")
    depth=0
    for brace in re.findall(r"(?<!\\)[{}]",value):
        depth+=1 if brace=="{" else -1
        if depth<0: break
    if depth: raise ValueError("公式括号不匹配。")
    return value


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


def render_vision_latex(directory,source=None,args=None,*,prepared_draft=False,crop_boxes=None):
    from vision_pdf import source_links
    directory=Path(directory)
    from layout_policy import load_layout, configure_preamble
    layout = load_layout(directory)
    object_layout = layout["objects"]
    manifest = {}
    (directory/"layout.json").write_text(json.dumps(layout, ensure_ascii=False, indent=2))
    md=(directory/"paper.md").read_text()
    md=re.sub(r"\\cite(?:p|t)?\{([\d,\s]+)\}", lambda m:"["+re.sub(r"\s+","",m[1])+"]", md)
    if source:
        from figure_groups import restore_groups
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
    md=re.sub(r"\\\[(.*?)\\\]",lambda m:"$$"+m[1]+"$$",md,flags=re.S)
    md=re.sub(r"\\\((.*?)\\\)",lambda m:"$"+m[1].strip()+"$",md,flags=re.S)
    md=re.sub(r"\$\$(.*?)\$\$",lambda m:"\n\n$$"+m[1]+"$$\n\n",md,flags=re.S)
    md=re.sub(r"\\eqno\s*\{?\((\d+)\)\}?",r"\\tag{\1}",md)
    md=re.sub(r"\\hfill\s+Eq\.\s*\((\d+)\)",r"　式（\1）",md)
    md=md.replace("<br>"," / ").replace("<br/>"," / ")
    root=html.fragment_fromstring(pypandoc.convert_text(md,"html5",format="markdown-raw_html-raw_tex",extra_args=["--mathjax","--wrap=none"]),create_parent="main")
    page_index=0
    nodes=[];origins=[]
    for node in root:
        marker=re.fullmatch(r"PAPERPAGEBOUNDARY(\d+)",node.text_content().strip())
        if marker:
            page_index=int(marker[1])-1
        else:
            nodes.append(node);origins.append(page_index)
    captions={}
    for i,n in enumerate(nodes):
        if n.tag not in ("table","figure"):continue
        image=n.find(".//img")
        original=image is not None and image.get("src") in source_tables
        for j in ((i-1,i+1) if n.tag=="table" or original else (i+1,i-1)):
            if 0<=j<len(nodes) and nodes[j].tag=="p" and CAP.match(nodes[j].text_content()) and j not in captions.values():
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
        parts=re.split(r"(https?://[^\s一-鿿，。；]+)",text)
        for k,part in enumerate(parts):
            if k%2:
                parts[k]="".join(escape(c)+(r"\allowbreak{}" if c in "/._-?&=" else "") for c in part)
            else:
                parts[k]=escape(part)
        return "".join(parts)
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
        return t
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
            from table_language import TableLanguage
            language=TableLanguage(directory,args)
            with pymupdf.open(source) as original:
                for filename,(page,box,_) in source_tables.items():
                    tex=table_tex(original[page],box,language,object_layout.get("tab-"+source_tables[filename][2], {}).get("column_widths"))
                    tablefile=Path(filename).with_suffix(".tex")
                    (work/tablefile).write_text(tex)
                    (directory/"tables").mkdir(exist_ok=True)
                    (directory/"tables"/tablefile).write_text(tex)
        body=[]
        header_end = draft_header_end(nodes, origins) if source else None
        if source:
            with pymupdf.open(source) as original:
                box = header_region(original[0])
                if box and header_end:
                    header_width = min(box.width, widths[0] - left - right)
                    with pymupdf.open() as asset:
                        page = asset.new_page(width=box.width, height=box.height)
                        page.show_pdf_page(page.rect, original, 0, clip=box)
                        asset.save(work/"source-header.pdf")
                    body.append(r"\par\noindent\makebox[\linewidth][c]{\includegraphics[width="
                                + f"{header_width:.3f}bp" + r"]{source-header.pdf}}\par")
                else:
                    header_end = None
        in_columns=False
        started=False
        in_abstract=False
        emitted=set()
        def dest(key):
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
            n=nodes[i]
            if i in captions.values() or i in algorithm_rows:continue
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
                body.append(content)
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
                        caption_text=linked(cn.text_content()[m.end():])
                    cap=(dest(cap_id(m))+r"{\raggedright\fontsize{9}{12}\selectfont\noindent\textbf{"
                         +escape(m[0].strip())+r"}\enspace "+caption_text+r"\par}")
                if n.tag=="figure":
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
                    filename=f"figure-{i}.png";shutil.copyfile(path,work/filename)
                    graphic_width=r"\linewidth"
                    if width and widths:
                        available=widths[origins[i]]-left-right
                        if dual and not wide:available=(available-20)/2
                        graphic_width=f"{min(width,available):.2f}bp"
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
            elif n.tag.startswith("h") and n.tag[1:].isdigit():
                if i==0:body.append(r"{\centering\LARGE\bfseries "+inline(n)+r"\par}\medskip")
                else:
                    if is_introduction:
                        body.append(r"\par\addvspace{"+str(layout["document"]["introduction_gap_bp"])+r"bp}")
                    body.append(r"\pdfbookmark[1]{"+escape(t)+"}{sec-"+str(i)+r"}\subsection*{"+inline(n)+"}")
            elif n.tag in ("ol","ul"):
                env="enumerate" if n.tag=="ol" else "itemize"
                body.append("\\begin{"+env+"}")
                if env == "enumerate":
                    start = int(n.get("start", "1"))
                    body.append(r"\setcounter{enumi}{"+str(start-1)+"}")
                body.extend([*(r"\item "+inline(c) for c in n),"\\end{"+env+"}"])
            elif len(n)==1 and "display" in n[0].get("class","").split():
                val=math_tex(n[0].text_content()[2:-2])
                tag=re.search(r"\\tag\{(\d+)\}",val)
                num=""
                if tag:
                    num=dest("eq-"+tag[1])+r"\quad("+tag[1]+")"
                    val=val[:tag.start()]+val[tag.end():]
                if r"\\" in val and r"\begin" not in val: val=r"\begin{gathered}"+val+r"\end{gathered}"
                equation=r"\par{\centering\fitmath{"+val+"}{"+num+r"}\par}"
                rect=eq_boxes.get((origins[i],tag[1])) if tag else None
                if dual and rect is not None and spans_gutter(rect,widths[origins[i]]):
                    equation=r"\begin{figure*}[!tp]"+equation+r"\end{figure*}"
                body.append(equation)
            elif t:
                bib=re.match(r"^\[(\d+)\]\s",t)
                if bib:body.append(r"\par\noindent\hangindent=1.7em "+dest("bib-"+bib[1])+inline(n,False)+r"\par")
                elif started and n.tag=="p" and re.search(r"[一-鿿]",t) and not t.startswith(("†","‡")):
                    body.append(r"{\rightskip=0pt\parfillskip=0pt plus 1fil\noindent\hspace*{\bodyindent}"+inline(n)+r"\par}")
                else:body.append(r"\par\noindent "+inline(n)+r"\par")

        extra=r"""\usepackage{amsmath,amsfonts,longtable}
\renewcommand{\dblfloatpagefraction}{.80}
\renewcommand{\floatpagefraction}{.80}
\renewcommand{\dbltopfraction}{.94}
\renewcommand{\topfraction}{.92}
\renewcommand{\textfraction}{.07}
\setcounter{dbltopnumber}{3}
\newsavebox{\eqbox}
\newcommand{\fitmath}[2]{\sbox{\eqbox}{$\displaystyle #1$#2}\ifdim\wd\eqbox>\linewidth\resizebox{\linewidth}{!}{\usebox{\eqbox}}\else\usebox{\eqbox}\fi}
"""
        (directory/"layout-objects.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
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
