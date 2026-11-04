"""根据 PDF 字形的位置恢复列与表头，用 LaTeX 单元格重排。"""
import re
from collections import Counter
from bisect import bisect_right
from statistics import median

from paper_translator.render.latex_backend import escape


def table_tex(page,box,language=None,column_widths=None):
    rules=sorted({round(g["rect"].y0,1) for g in page.get_drawings()
                  if g["type"]=="s" and g["rect"].height<1.5
                  and abs(g["rect"].width-box.width)<5 and box.y0<=g["rect"].y0<=box.y1})
    if len(rules)<3:
        raise ValueError("无法确定原表的表头和表体分界。")
    cells=[]
    for b in page.get_text("rawdict",clip=box)["blocks"]:
        for line in b.get("lines",[]):
            chars=[c for s in line["spans"] for c in s["chars"]]
            if not chars:continue
            text="".join(c["c"] for c in chars).strip()
            if text:cells.append((line["bbox"][0],line["bbox"][2],median(c["origin"][1] for c in chars),text,chars))
    rows=[]
    for cell in sorted(cells,key=lambda c:c[2]):
        if not rows or abs(cell[2]-rows[-1][0][2])>2.5:rows.append([])
        rows[-1].append(cell)
    for row in rows:row.sort()
    header=[r for r in rows if r[0][2]<rules[1]]
    data=[r for r in rows if r[0][2]>=rules[1]]
    if not header or not data:raise ValueError("表格缺少可读取的表头或数据行。")
    # 数值表使用数据行估计列边界，避免把跨列表头误认为一列。
    numeric=[r for r in data if sum(bool(re.fullmatch(r"[−–—\d.,%+-]+",c[3])) for c in r)>=2]
    dense=bool(numeric and max(map(len,numeric))>=4 and not any(
        len(c[3].split())>5 for row in numeric for c in row[1:]))
    if dense:
        counts=Counter(len(r) for r in numeric)
        count=max(counts,key=lambda n:(counts[n],n))
        # 合并单元格会减少列数。选择至少两行共同支持的最完整网格。
        count=max([n for n,k in counts.items() if k>=2] or [count])
        samples=[r for r in numeric if len(r)==count]
        cuts=[(max(r[i][1] for r in samples)+min(r[i+1][0] for r in samples))/2 for i in range(count-1)]
    else:
        sample=max(header,key=len)
        count=len(sample)
        cuts=[c[0]-2 for c in sample[1:]]
    if count<2 or cuts!=sorted(cuts):raise ValueError("无法可靠识别表格列。")
    def tex(t):
        return escape(t).replace("↑",r"\ensuremath{\uparrow}").replace("↓",r"\ensuremath{\downarrow}").replace(r"\_",r"\_\allowbreak{}")
    def values(row,heading):
        out=[""]*count
        if heading and len(row)==count:
            return [c[3] for c in row]
        if heading and dense and len(header)==1:
            chars=sorted((c for cell in row for c in cell[4] if c["c"].strip()),key=lambda c:c["bbox"][0])
            gaps=sorted(range(1,len(chars)),key=lambda i:chars[i]["bbox"][0]-chars[i-1]["bbox"][2],reverse=True)
            edges=[0,*sorted(gaps[:count-1]),len(chars)]
            return ["".join(c["c"] for c in chars[a:b]) for a,b in zip(edges,edges[1:])]
        for left,right,y,text,chars in row:
            col=bisect_right(cuts,(left+right)/2 if dense else left+1)
            if heading and dense:
                for token in re.finditer(r"[A-Za-z0-9]+|[^A-Za-z0-9]", "".join(c["c"] for c in chars)):
                    first,last=chars[token.start()],chars[token.end()-1]
                    j=bisect_right(cuts,(first["bbox"][0]+last["bbox"][2])/2)
                    out[j]+=token[0]
            else:out[col]=(out[col]+" "+text).strip()
        return [s.strip() for s in out]
    widths=[box.x0,*cuts,box.x1]
    if column_widths is not None and len(column_widths) != count:
        raise ValueError("指定列宽数量与识别的表格列数不符。")
    if dense:
        from paper_translator.render.table_style import numeric_tex
        return numeric_tex(page,box,cuts,column_widths)
    fractions = column_widths or [(b-a)/box.width for a,b in zip(widths,widths[1:])]
    spec="".join(r"p{\dimexpr "+f"{fraction:.4f}"+r"\linewidth-2\tabcolsep\relax}" for fraction in fractions)
    lines=[r"\begingroup\small\setlength{\tabcolsep}{2pt}\renewcommand{\arraystretch}{1.10}",
           r"\begin{tabular}{@{}"+spec+r"@{}}\hline"]
    logical=[]
    for r in header:
        v=values(r,True)
        if logical and not any(a and b for a,b in zip(logical[-1][1],v)):
            prior=logical[-1][1]
            prior[:]=[a or b for a,b in zip(prior,v)]
        else:
            logical.append((True,v,False))
    last_y=None
    for r in data:
        v=values(r,False)
        sep=last_y is None or any(last_y<y<r[0][2] for y in rules[1:-1])
        line_height=median(c["bbox"][3]-c["bbox"][1] for cell in r for c in cell[4])
        wrapped=last_y is not None and r[0][2]-last_y<=line_height*1.15
        if not dense and logical and not sep and (wrapped or not v[0] or not any(v[1:])) and not logical[-1][0] and any(logical[-1][1][1:]):
            prior=logical[-1][1]
            for j,text in enumerate(v):
                prior[j]=(prior[j]+" "+text).strip()
        else:logical.append((False,v,sep))
        last_y=r[0][2]
    translations=language.resolve(t for _,v,_ in logical for t in v) if language else {}
    fills=[(g["rect"],g["fill"]) for g in page.get_drawings() if g["type"]=="f" and g["fill"] and
           abs(g["rect"].width-box.width)<5 and box.contains(g["rect"])]
    bands=iter(fills)
    for heading,v,sep in logical:
        v=[translations.get(t,t) for t in v]
        if sep:lines.append(r"\hline")
        if not dense and not heading and v[0] and not any(v[1:]):
            band=next(bands,None)
            cell=r"\textbf{"+tex(v[0])+"}"
            if band:
                from paper_translator.render.table_style import rgb
                cell=r"\colorbox[rgb]{"+rgb(band[1])+r"}{\makebox[\dimexpr\linewidth-2\fboxsep-4pt\relax][l]{"+cell+"}}"
            lines.append(r"\multicolumn{"+str(count)+r"}{@{}l@{}}{"+cell+r"}\\")
        else:
            lines.append(" & ".join(r"\textbf{"+tex(t)+"}" if heading else tex(t) for t in v)+r"\\")
    lines.append(r"\hline\end{tabular}"+("}" if dense else "")+r"\endgroup")
    return "\n".join(lines)
