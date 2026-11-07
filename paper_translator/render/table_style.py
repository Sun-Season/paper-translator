"""按原稿字形基线和列坐标排数值表，并用 TeX 色块与横线恢复装饰。"""
from bisect import bisect_right
import pymupdf
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
    for b in page.get_text("dict",clip=box,flags=pymupdf.TEXT_MEDIABOX_CLIP)["blocks"]:
        for l in b.get("lines",[]):
            for s in l["spans"]:
                if s["text"].strip():
                    runs.append(s)
    # 同一行中的上下标具有不同基线，不能把每个基线当作独立表行叠加。
    pieces=[[] for _ in edges[:-1]]
    for x,bottom,w,h,color in decorations(page,box):
        pieces[0].append(r"\put("+f"{x-box.x0:.3f},{box.y1-bottom:.3f}"+r"){\color[rgb]{"+rgb(color)+r"}\rule{"+f"{w:.3f}bp"+"}{"+f"{h:.3f}bp"+"}}")
    for s in runs:
        x0,_,x1,_=s['bbox']
        j=bisect_right(cuts,x0+.05)
        scale=(target_edges[j+1]-target_edges[j])/(edges[j+1]-edges[j])
        t=escape(s['text']).replace('↑',r'\ensuremath{\uparrow}').replace('↓',r'\ensuremath{\downarrow}')
        # 字体/颜色命令会吞掉后续空白；显式保留原字形段两端的词间距。
        t=re.sub(r"^ +",lambda m:r"\hspace*{0.25em}"*len(m[0]),t)
        t=re.sub(r" +$",lambda m:r"\hspace*{0.25em}"*len(m[0]),t)
        c=s['color']&0xffffff
        color=rgb([(c>>bit & 255)/255 for bit in (16,8,0)])
        face=(r'\bfseries ' if s['flags']&16 or re.search('Bold|BX',s['font'],re.I) else '')+(r'\itshape ' if s['flags']&2 else '')
        size=f"{s['size']:.3f}bp"
        glyph=r'{\fontsize{'+size+'}{'+size+r'}\selectfont'+face+r'\color[rgb]{'+color+'}'+t+'}'
        xpos=(x0-edges[j])*scale
        pieces[j].append(r'\put('+f"{xpos:.3f},{box.y1-s['origin'][1]:.3f}"+r'){\makebox(0,0)[lb]{\raisebox{0pt}[0pt][0pt]{\resizebox{'+f'{(x1-x0)*scale:.3f}bp'+r'}{\height}{'+glyph+'}}}}')
    cells=[r'\begin{picture}('+f'{b-a:.3f},{box.height:.3f}'+')'+'\n'.join(parts)+r'\end{picture}'
           for a,b,parts in zip(target_edges,target_edges[1:],pieces)]
    return (r'\begingroup\setlength{\tabcolsep}{0pt}\setlength{\unitlength}{1bp}'
            r'\resizebox{\linewidth}{!}{\begin{tabular}{@{}'+'l'*(len(edges)-1)+r'@{}}'
            +' & '.join(cells)+r'\end{tabular}}\endgroup')
