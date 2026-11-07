"""用 LaTeX 对已有的论文内容块进行双栏试排。"""
from dataclasses import replace
import html
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pymupdf as pdf

from paper_translator.legacy.reading_pdf import CAPTION, REFERENCE


def tex_engine():
    for binary in ("tectonic", "xelatex"):
        path = shutil.which(binary)
        if path:
            return path
        for folder in ("/opt/homebrew/bin", "/usr/local/bin", "/Library/TeX/texbin"):
            candidate=Path(folder)/binary
            if candidate.is_file() and os.access(candidate,os.X_OK):
                return str(candidate)
    raise ValueError("LaTeX 试排需要 Tectonic 或 XeLaTeX。macOS 可先执行 brew install tectonic。")


def escape(text):
    chars = {"\\":r"\textbackslash{}", "{":r"\{", "}":r"\}", "$":r"\$", "%":r"\%",
             "#":r"\#", "&":r"\&", "_":r"\_", "^":r"\textasciicircum{}", "~":r"\textasciitilde{}"}
    # 正文的数学运算符交给 TeX 数学字体，避免 xeCJK 把它们分配给缺字的宋体。
    for symbol,command in {"∪":"cup","∈":"in","∉":"notin","∑":"sum","∏":"prod","∫":"int",
                           "≈":"approx","≠":"ne","≤":"le","≥":"ge","∝":"propto",
                           "∼":"sim","∇":"nabla","∞":"infty","∥":"Vert","→":"to",
                           "▷":"triangleright","◁":"triangleleft","∗":"ast","−":"mathord{-}","×":"times","∣":"mid"}.items():
        chars[symbol]="\\ensuremath{\\"+command+"}"
    chars["✗"] = r"{\fontspec{Menlo}✗}"
    chars["✓"] = r"{\fontspec{Menlo}✓}"
    return "".join(chars.get(c,c) for c in text if ord(c)>=32 or c in "\n\t")


def render_latex(source, raw, inline_assets, items, inline_boxes, entries, output, front):
    from paper_translator.legacy.reflow_pdf import CITATIONS
    binary = tex_engine()
    anchors = {it.anchor for it in items if it.anchor}
    with tempfile.TemporaryDirectory(prefix="paper-tex-") as temp:
        root = Path(temp)
        assets = 0
        def graphic(it, width, inline=False):
            nonlocal assets
            assets += 1
            filename = f"asset-{assets}.pdf"
            doc = inline_assets if it.kind=="inline-source" else source if it.kind in ("original-header","source-equation","source-algorithm","source-table") else raw
            with pdf.open() as clip:
                page = clip.new_page(width=it.box.width,height=it.box.height)
                page.show_pdf_page(page.rect,doc,it.page,clip=it.box)
                clip.save(root/filename,garbage=4,deflate=True)
            size = min(width / it.box.width, (540 if width>300 else 270)/it.box.height, 1.09 if inline else 1)
            if it.kind == "panel-page":
                size = min(558/it.box.width,755/it.box.height)
            command=rf"\includegraphics[width={it.box.width*size:.3f}bp]{{{filename}}}"
            return r"\raisebox{-.25\height}{"+command+"}" if inline else command

        def link_text(part, bibliography):
            if bibliography:
                return escape(part)
            pieces=[]
            end=0
            for m in re.finditer(f"(?:{CITATIONS.pattern})|(?:{REFERENCE.pattern})",part,re.I):
                pieces.append(escape(part[end:m.start()]))
                token=m[0]
                if token.startswith("["):
                    pieces.append(re.sub(r"\d+",lambda n:r"\hyperlink{bib-"+n[0]+"}{"+n[0]+"}" if int(n[0]) in entries else n[0],token))
                else:
                    figure=REFERENCE.match(token)
                    key="fig-"+figure[1] if figure[1] else "eq-"+figure[2]
                    pieces.append(r"\hyperlink{"+key+"}{"+escape(token)+"}" if key in anchors else escape(token))
                end=m.end()
            return "".join(pieces)+escape(part[end:])

        notes={it.anchor:it for it in items if it.kind=="footnote"}

        def paragraph(it):
            parts=[]
            for frag in re.split(r"((?:@@m\d+_\d+_\d+@@(?:[ \t]*(?=@@m))?)+|</?(?:sup|sub)>|<fn-\d+-\d+/>)",it.text):
                if frag.startswith("<fn-") and frag[1:-2] in notes:
                    key=frag[1:-2]
                    parts.append(r"\footnote["+key.split("-")[-1]+"]{"+paragraph(notes[key])+"}")
                elif frag in ("<sup>","<sub>"):
                    parts.append(r"\textsuperscript{" if frag=="<sup>" else r"\textsubscript{")
                elif frag in ("</sup>","</sub>"):
                    parts.append("}")
                elif frag.startswith("@@"):
                    pieces=[inline_boxes[k] for k in re.findall(r"@@(m\d+_\d+_\d+)@@",frag)]
                    content=r"\allowbreak{}".join(graphic(v,245,True) for v in pieces)
                    if sum(min(245,v.box.width*1.09) for v in pieces)>120:
                        parts.append(r"\par\nobreak\begingroup\centering "+content+
                                     r"\par\endgroup\nobreak\noindent{}")
                    else:
                        parts.append(r"\allowbreak{}"+content+r"\allowbreak{}")
                else:
                    parts.append(link_text(html.unescape(frag), it.kind=="bib"))
            return "".join(parts)

        body=[]
        columns=False
        skip=set()
        for idx,it in enumerate(items):
            if it.kind == "panel-page":
                if columns:
                    body.append(r"\end{multicols}")
                    columns = False
                body.append(r"\clearpage\noindent\makebox[\linewidth][c]{"+graphic(it,525)+r"}\par")
                continue
            if idx in skip or it.kind=="footnote" or (not it.text and it.kind not in ("visual","source-equation","original-header","source-algorithm","source-table")):
                continue
            visual=it.kind in ("visual","source-equation","original-header","source-algorithm","source-table")
            page_width=raw[it.page].rect.width
            wide=(idx in front or it.kind=="original-header" or
                  (visual and it.box.width>page_width*.64 and it.box.x0<page_width*.4 and it.box.x1>page_width*.6))
            if it.kind=="caption" and idx+1<len(items) and items[idx+1].kind=="source-table":
                continue
            if columns==wide:
                body.append(r"\end{multicols}" if wide else r"\begin{multicols}{2}\raggedcolumns")
                columns=not wide
            dest=r"\hypertarget{"+it.anchor+"}{}" if it.anchor else ""
            if visual:
                if it.anchor.startswith(("fig-", "eq-", "alg-")):
                    kind,num=it.anchor.split("-",1)
                    title={"fig":"图 ","eq":"式 ","alg":"算法 "}[kind]+num
                    dest=r"\pdfbookmark[1]{"+escape(title)+"}{bm-"+it.anchor+"}"+dest
                width=525 if wide else 252
                group=[r"\par\noindent\begin{minipage}{\linewidth}\centering",dest+graphic(it,width)]
                if it.kind=="source-table" and idx and items[idx-1].kind=="caption":
                    group.insert(1,r"{\small\raggedright "+paragraph(items[idx-1])+r"\par}\smallskip")
                if it.anchor.startswith("fig-") and idx+1<len(items):
                    cap=items[idx+1]
                    match=CAPTION.match(html.unescape(re.sub("<[^>]+>","",cap.text)))
                    if match and "fig-"+match[1]==it.anchor:
                        label="图 "+match[1]
                        body_text=re.sub(r"^\s*(?:图|fig(?:ure)?\.?)\s*"+re.escape(match[1])+r"[ \t　:：.．、]*","",cap.text,count=1,flags=re.I)
                        group += [r"\par\vspace{3pt}\hrule height .35pt\vspace{3pt}\raggedright"
                                  r"\fontsize{9}{12}\selectfont\noindent\textbf{"+label+
                                  r"}\enspace "+paragraph(replace(cap,text=body_text))+r"\par\vspace{5pt}"]
                        skip.add(idx+1)
                body.extend(group+[r"\end{minipage}\par\smallskip"])
            elif it.kind in ("heading","title"):
                title=escape(html.unescape(re.sub("<[^>]+>","",it.text)))
                body.append(r"\pdfbookmark[1]{"+title+"}{section-"+str(idx)+"}"+r"\subsection*{"+paragraph(it)+"}")
            elif it.kind in ("caption","author-note"):
                body.append(r"\par\smallskip{\small "+paragraph(it)+r"\par}\medskip")
            elif it.kind=="bib":
                body.append(r"\par\noindent\hangindent=1.7em\hangafter=1 "+dest+paragraph(it)+r"\par")
            else:
                chinese_body = it.kind == "p" and idx not in front and re.search(r"[㐀-鿿]", it.text)
                indent = r"\hspace*{\bodyindent}" if chinese_body else ""
                text = r"\noindent{}"+indent+paragraph(it)+r"\par"
                if it.kind == "p" and idx not in front:
                    text = r"{\rightskip=0pt\parfillskip=0pt plus 1fil "+text+"}"
                body.append(r"\par"+text)
        if columns:body.append(r"\end{multicols}")
        compile_paper(root,output,body,binary)


PAPER_PREAMBLE=r"""\documentclass[11pt]{article}
\usepackage[paperwidth=648bp,paperheight=842bp,left=42bp,right=42bp,top=36bp,bottom=39bp]{geometry}
\usepackage{fontspec,xeCJK,graphicx,multicol,hyperref}
\setmainfont{Times New Roman}
\setCJKmainfont{Songti SC}
\hypersetup{colorlinks=true,linkcolor=blue}
\setlength{\columnsep}{20bp}\setlength{\parindent}{0pt}
\setlength{\parskip}{3pt plus 1pt}\linespread{1.13}
\setlength{\emergencystretch}{2em}
\newlength{\bodyindent}
\begin{document}\raggedright
\settowidth{\bodyindent}{正文}
"""


def compile_paper(root,output,body,binary,preamble=PAPER_PREAMBLE):
    (root/"paper.tex").write_text(preamble+"\n".join(body)+"\n"+r"\end{document}", encoding="utf8")
    tectonic=Path(binary).name=="tectonic"
    cmd=[binary,"--untrusted","--keep-logs","paper.tex"] if tectonic else [binary,"-no-shell-escape","-halt-on-error","-interaction=nonstopmode","paper.tex"]
    for _ in range(1 if tectonic else 2):
        proc=subprocess.run(cmd,cwd=root,capture_output=True,text=True,errors="replace")
        if proc.returncode:
            raise OSError("LaTeX 编译失败：\n"+(proc.stdout+proc.stderr)[-2200:])
    report=(root/"paper.log").read_text(errors="replace") if (root/"paper.log").is_file() else proc.stderr
    diagnostics=output.parent/"latex"
    diagnostics.mkdir(exist_ok=True)
    for asset in root.iterdir():
        if asset.suffix in {".tex", ".log", ".png", ".pdf"} and asset.name!="paper.pdf":
            shutil.copyfile(asset,diagnostics/asset.name)
    warnings=[line for line in report.splitlines() if "Missing character:" in line or "Overfull " in line]
    (output.parent/"LaTeX版式检查.txt").unlink(missing_ok=True)
    if warnings:
        (output.parent/"LaTeX版式检查.txt").write_text("\n".join(dict.fromkeys(warnings)),encoding="utf8")
    with pdf.open(root/"paper.pdf") as compiled:
        if not len(compiled):raise ValueError("LaTeX 没有生成页面。")
        compiled.save(output,garbage=4,deflate=True,use_objstms=1)
