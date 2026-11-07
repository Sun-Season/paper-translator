"""根据原算法的横线、行号和正文起点重建伪代码块。"""
from copy import deepcopy
import re
from paper_translator.legacy.reflow_pdf import source_algorithms

TITLE=re.compile(r"^(?:Algorithm|算法)\s*(\d+)\b",re.I)
STEP=re.compile(r"^\s*(\d+)\s*[:：]\s*")
REF=re.compile(r"(?:\\hfill\s*)?(?:Eq\.?|式|公式)\s*[（(](\d+)[）)]\s*$",re.I)


def source_specs(page):
    result={}
    for item in source_algorithms(page):
        box=item.box
        lines=sorted([(g["rect"].y0,g["width"] or .4) for g in page.get_drawings()
                      if g["type"]=="s" and abs(g["rect"].width-box.width)<4 and
                      box.y0<=g["rect"].y0<=box.y1 and g["rect"].height<1],key=lambda r:r[0])
        if len(lines)!=3:continue
        words=page.get_text("words",clip=box)
        starts={}; refs={}
        for w in words:
            if not re.fullmatch(r"\d+[:：]",w[4]) or w[0]>box.x0+30:continue
            num=int(w[4][:-1])
            row=sorted((v for v in words if v[0]>=w[2] and abs(v[3]-w[3])<3),key=lambda v:v[0])
            if not row:continue
            starts[num]=row[0][0]
            if m:=REF.search(" ".join(v[4] for v in row)):refs[num]=m[1]
        if sorted(starts)!=list(range(1,len(starts)+1)) or not starts:continue
        base=min(starts.values())
        result[item.anchor[4:]]={"box":list(box),"indent":{k:max(0,v-base) for k,v in starts.items()},
                                 "refs":refs,"rules":[w for _,w in lines],"gutter":base-box.x0}
    return result


def match_rows(nodes,origins,specs):
    groups={}
    for i,node in enumerate(nodes):
        m=TITLE.match(node.text_content().strip())
        if not m:continue
        spec=specs.get((origins[i],m[1]))
        if not spec:continue
        rows=[];steps=[]
        for j in range(i+1,len(nodes)):
            if origins[j]!=origins[i]:break
            text=nodes[j].text_content().strip()
            step=STEP.match(text)
            if step:
                k=int(step[1])
                if k!=len(steps)+1:break
                steps.append(k)
            elif not re.match(r"^(?://|▷|▹|Require\b|Ensure\b|Input\b|Output\b|输入|输出|要求|需要|前置条件|后置条件|确保|保证)",text,re.I):
                break
            rows.append(j)
            if len(steps)==len(spec["indent"]):
                groups[i]=(m[1],rows,spec)
                break
    return groups


def typeset(title,nodes,rows,spec,num,inline,anchors):
    thick,middle,bottom=spec["rules"]
    body=[r"\noindent\begin{minipage}{\linewidth}\small\setlength{\parskip}{0pt}\raggedright",
          r"\hypertarget{alg-"+num+r"}{}\hrule height "+f"{thick:g}bp"+r"\vspace{2pt}",
          r"\noindent "+inline(title)+r"\par\vspace{2pt}\hrule height "+f"{middle:g}bp"+r"\vspace{2pt}"]
    for j in rows:
        n=deepcopy(nodes[j])
        text=n.text_content().strip()
        match=STEP.match(text)
        if not match:
            if text.startswith(("//", "▷", "▹")):
                body.append(r"\par\smallskip\noindent\hspace*{"+f"{spec['gutter']:.2f}bp"+r"}\textit{"+inline(n)+r"}\par")
            else:body.append(r"\noindent "+inline(n)+r"\par")
            continue
        k=int(match[1])
        n.text=re.sub(r"^\s*\d+\s*[:：]\s*(?:\\q?quad\s*)?","",n.text or "")
        ref=spec["refs"].get(k)
        if ref:
            if len(n):n[-1].tail=REF.sub("",n[-1].tail or "")
            else:n.text=REF.sub("",n.text)
        gutter=spec["gutter"];indent=spec["indent"][k];reserve=42 if ref else 0
        value=inline(n)
        body.append(r"\noindent\makebox["+f"{gutter:.2f}bp"+r"][r]{"+str(k)+r":\enspace}\hspace*{"+f"{indent:.2f}bp"+
                    r"}\parbox[t]{\dimexpr\linewidth-"+f"{gutter+indent+reserve:.2f}bp"+r"\relax}{\raggedright "+value+"}"+
                    (r"\hfill "+(r"\hyperlink{eq-"+ref+r"}{式（"+ref+"）}" if "eq-"+ref in anchors else "式（"+ref+"）") if ref else "")+r"\par")
    body.append(r"\vspace{2pt}\hrule height "+f"{bottom:g}bp"+r"\hypertarget{alg-end-"+num+r"}{}\end{minipage}")
    return "\n".join(body)


def normalize_algorithm_blocks(markdown):
    """把挤在同一段的编号步骤拆成独立段落，pandoc 才能按行重建算法。"""
    chunks = re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)", markdown)
    for index in range(2, len(chunks), 2):
        blocks = chunks[index].strip().split("\n\n")
        changed = False
        result = []
        for block in blocks:
            lines = block.splitlines()
            if sum(bool(STEP.match(line)) for line in lines) >= 2:
                rebuilt = []
                for line in lines:
                    if STEP.match(line) and rebuilt and rebuilt[-1].strip():
                        rebuilt.append("")
                    rebuilt.append(line)
                block = "\n".join(rebuilt)
                changed = True
            result.append(block)
        if changed:
            chunks[index] = "\n\n" + "\n\n".join(result) + "\n\n"
    return "".join(chunks)
