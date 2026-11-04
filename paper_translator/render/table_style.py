"""按原稿字形基线和列坐标排数值表，并用 TeX 色块与横线恢复装饰。"""
from bisect import bisect_right
from statistics import median
import re

from paper_translator.render.latex_backend import escape


def rgb(color):
    return ",".join(f"{v:.4f}" for v in color)


def decorations(page,box):
    parts=[]
    for g in page.get_drawings():
        r=g["rect"]
        if not (box.x0-.5<=r.x0<=r.x1<=box.x1+.5 and box.y0<=r.y0<=r.y1<=box.y1):
            continue
        if g["type"]=="f" and g["fill"] and all(item[0]=="re" for item in g["items"]):
            parts.append((r.x0,r.y1,r.width,r.height,g["fill"]))
        elif g["type"]=="s" and g["color"] and r.height<.2:
            h=g["width"] or .4
            parts.append((r.x0,r.y1+h/2,r.width,h,g["color"]))
    return parts


def numeric_tex(page,box,cuts,column_widths=None):
    edges=[box.x0,*cuts,box.x1]
    target_edges = [box.x0]
    for fraction in column_widths or [(b-a)/box.width for a,b in zip(edges,edges[1:])]:
        target_edges.append(target_edges[-1] + fraction * box.width)
    runs=[]
    for b in page.get_text("dict",clip=box,flags=0)["blocks"]:
        for l in b.get("lines",[]):
            for s in l["spans"]:
                if s["text"].strip():
                    runs.append(s)
    rows=[]
    for s in sorted(runs,key=lambda s:s["origin"][1]):
        if not rows or s["origin"][1]-rows[-1][0]["origin"][1]>.7:
            rows.append([])
        rows[-1].append(s)
    lines=[r"\begingroup\setlength{\tabcolsep}{0pt}\renewcommand{\arraystretch}{0}",
           r"\resizebox{\linewidth}{!}{\begin{tabular}{@{}"+"l"*(len(edges)-1)+r"@{}}"]
    last_y=box.y0
    for i,row in enumerate(rows):
        y=median(s["origin"][1] for s in row)
        fields=[[] for _ in edges[:-1]]
        if i==0:
            for x,bottom,w,h,color in decorations(page,box):
                fields[0].append(r"\rlap{\smash{\hspace*{"+f"{x-box.x0:.3f}bp"+r"}\raisebox{"+f"{y-bottom:.3f}bp"+r"}{\color[rgb]{"+rgb(color)+r"}\rule{"+f"{w:.3f}bp"+"}{"+f"{h:.3f}bp"+"}}}}")
        for s in sorted(row,key=lambda s:s["bbox"][0]):
            x0,_,x1,_=s["bbox"]
            j=bisect_right(cuts,x0+.05)
            scale = (target_edges[j+1]-target_edges[j])/(edges[j+1]-edges[j])
            t=escape(s["text"]).replace("↑",r"\ensuremath{\uparrow}").replace("↓",r"\ensuremath{\downarrow}")
            c=s["color"]&0xffffff
            color=rgb([(c>>bit & 255)/255 for bit in (16,8,0)])
            face=(r"\bfseries " if s["flags"]&16 or re.search("Bold|BX",s["font"],re.I) else "")+(r"\itshape " if s["flags"]&2 else "")
            size=f"{s['size']:.3f}bp"
            glyph=r"{\fontsize{"+size+"}{"+size+r"}\selectfont"+face+r"\color[rgb]{"+color+"}"+t+"}"
            fields[j].append(r"\rlap{\smash{\hspace*{"+f"{(x0-edges[j])*scale:.3f}bp"+r"}\raisebox{"+f"{y-s['origin'][1]:.3f}bp"+r"}{\resizebox{"+f"{(x1-x0)*scale:.3f}bp"+r"}{\height}{"+glyph+"}}}}")
        cells=[r"\makebox["+f"{b-a:.3f}bp"+"][l]{"+''.join(pieces)+"}" for a,b,pieces in zip(target_edges,target_edges[1:],fields)]
        lines.append(r"\rule{0pt}{"+f"{y-last_y:.3f}bp"+"}"+' & '.join(cells)+r"\\")
        last_y=y
    lines.append(r"\rule{0pt}{"+f"{box.y1-last_y:.3f}bp"+r"}\end{tabular}}\endgroup")
    return "\n".join(lines)
