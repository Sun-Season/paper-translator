"""从原稿建立清单，核对实际导出的 PDF，仅重试能定位的问题。"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

import cv2
import numpy as np
import pymupdf as pdf
from PIL import Image

from paper_translator.source.original_tables import table_regions
from paper_translator.render.ruled_algorithm import source_specs

LABEL=re.compile(r"^(Fig(?:ure)?\.?|Table|图|表)\s*(S?\d+(?:\.\d+)*)(?=\s*[:：、]|[.．]\s+\S|\s*$|\s+(?-i:[A-Z]))",re.I)


def source_inventory(doc):
    objects=[]
    for page in doc:
        captions={}
        for b in page.get_text("dict",flags=pdf.TEXTFLAGS_TEXT)["blocks"]:
            for line in b.get("lines",[]):
                text="".join(s["text"] for s in line["spans"]).strip()
                m=LABEL.match(text)
                if m:
                    if not text[m.end():].strip() and not (page.get_images() or page.get_drawings()):
                        continue
                    kind="table" if m[1].lower() in ("table","表") else "figure"
                    captions.setdefault((kind,m[2]),line["bbox"])
        for num,spec in source_specs(page).items():
            objects.append({"type":"algorithm","number":num,"page":page.number+1,
                            "steps":list(spec["indent"]),"refs":list(spec["refs"].values()),"box":spec["box"]})
        tables=table_regions(page)
        for n,box in tables.items():
            captions.setdefault(("table",n),list(box))
        for (kind,n),caption in captions.items():
            item={"type":kind,"number":n,"page":page.number+1,"caption_box":list(caption)}
            if kind=="table" and n in tables:
                box=tables[n]
                item["box"]=list(box)
                item["grid"]="grid-"+n+(f"-p{page.number+1}" if any(o.get("grid")=="grid-"+n for o in objects) else "")
                item["parts"]=re.findall(r"(?m)^\(([a-z])\)\s",page.get_textbox(box))
            objects.append(item)
    return objects


def raster_inventory(doc,directory,draft,objects):
    """把裁片逆向定位到原页；使用最终 PDF 的图像摘要核对实际绘制。"""
    crops=[]
    pages=re.split(r"(?m)^<!-- 原稿第 \d+ 页 -->",draft)[1:]
    for i,text in enumerate(pages):
        if i>=len(doc):break
        page=doc[i]
        paths=re.findall(r"!\[[^\]]*\]\((figures/[^)]+)\)",text)
        if not paths:continue
        pix=page.get_pixmap(matrix=pdf.Matrix(.75,.75),colorspace=pdf.csGRAY)
        gray=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width)
        graphics=[pdf.Rect(a["bbox"]) for a in page.get_image_info()]
        graphics.extend(g["rect"] for g in page.get_drawings() if g["rect"].get_area()>20)
        blocks=page.get_text("blocks")
        for name in dict.fromkeys(paths):
            path=(directory/name).resolve()
            if path.parent!=(directory/"figures").resolve() or not path.is_file():continue
            with Image.open(path) as im:
                digest=hashlib.md5(im.convert("RGB").tobytes()).hexdigest()
                dpi=im.info.get("dpi",(400,400))[0]
                w,h=[round(k*54/dpi) for k in im.size]
                record={"page":i+1,"path":name,"digest":digest}
                crops.append(record)
                if not (5<=w<=pix.width and 5<=h<=pix.height):continue
                template=np.array(im.convert("L").resize((w,h),Image.Resampling.LANCZOS))
            if template.std()<5:continue
            _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED))
            if score<.68:continue
            rect=pdf.Rect(x/.75,y/.75,(x+w)/.75,(y+h)/.75)
            record.update(box=list(rect),score=round(score,3))
            if (not any(rect.intersects(g) for g in graphics)
                and sum(len(b[4].split()) for b in blocks if rect.intersects(pdf.Rect(b[:4])))>=70
                and not any(o["page"]==i+1 and "box" in o and rect.intersects(pdf.Rect(o["box"])) for o in objects)):
                record["prose_crop"]=True
        for obj in (o for o in objects if o["type"]=="figure" and o["page"]==i+1):
            cap=pdf.Rect(obj["caption_box"])
            options=[]
            for crop in crops:
                if crop["page"]!=i+1 or "box" not in crop or crop.get("prose_crop"):continue
                box=pdf.Rect(crop["box"])
                gap=cap.y0-box.y1
                if -18<=gap<75 and min(cap.x1,box.x1)>max(cap.x0,box.x0):
                    options.append((abs(gap),crop["path"],crop))
            if options:
                c=min(options)[2]
                obj.update(asset=c["path"],digest=c["digest"])
    return crops


def row_strings(page,box=None):
    words=sorted(page.get_text("words",clip=box),key=lambda w:((w[1]+w[3])/2,w[0]))
    rows=[]
    for w in words:
        y=(w[1]+w[3])/2
        if not rows or y-rows[-1][0]>3:rows.append((y,[]))
        rows[-1][1].append(w)
    return ["".join(w[4] for w in sorted(row,key=lambda w:w[0])) for _,row in rows]


def audit(source,directory,objects,crops):
    from paper_translator.harness.layout_audit import layout_issues
    issues=layout_issues(directory)
    def issue(code,p,object_id,detail):
        issues.append({"code":code,"source_page":p,"object":object_id,"detail":detail})
    with pdf.open(directory/"paper.pdf") as out:
        header_check = directory/"题头检查.json"
        if not header_check.is_file() or not json.loads(header_check.read_text()).get("verified"):
            issue("source_header_unverified",1,"header","未能验证首页题头与原稿一致")
        names=out.resolve_names()
        draws=[Counter(im["digest"].hex() for im in pg.get_image_info(hashes=True)) for pg in out]
        rows=[r for pg in out for r in row_strings(pg)]
        for c in crops:
            if c.get("prose_crop") and any(h[c["digest"]] for h in draws):
                issue("prose_crop",c["page"],c["path"],"成品绘制了与原页连续正文匹配的裁片")
        for obj in objects:
            kind,n,p=obj["type"],obj["number"],obj["page"]
            anchor={"figure":"fig-","table":"tab-","algorithm":"alg-"}[kind]+n
            dest=names.get(anchor,{})
            target=dest.get("page",-1)
            if not 0<=target<len(out):
                issue("missing_object",p,anchor,"成品缺少可定位的对象")
                continue
            if kind=="algorithm":
                end=names.get("alg-end-"+n,{})
                pg=out[target]
                if end.get("page")!=target:
                    issue("split_algorithm",p,anchor,"算法首尾没有落在同一页")
                    continue
                start_pt=pdf.Point(dest["to"])*pg.transformation_matrix
                end_pt=pdf.Point(end["to"])*pg.transformation_matrix
                rules=sorted([g["rect"] for g in pg.get_drawings() if start_pt.y-6<=g["rect"].y0<=end_pt.y+6
                              and abs(g["rect"].x0-start_pt.x)<4 and g["rect"].height<1
                              and g["rect"].width>pg.rect.width*.18],key=lambda r:r.y0)
                # 上下两条横线必须贴合算法首尾；中间可有一条或更多（相邻表格可能共享横线）。
                if len(rules)<3 or abs(rules[0].y0-start_pt.y)>6 or abs(rules[-1].y0-end_pt.y)>6:
                    issue("algorithm_rules",p,anchor,"算法区域未核实三条横线")
                    continue
                box=pdf.Rect(rules[0].x0-1,start_pt.y-2,rules[0].x1+1,end_pt.y+2)
                # 只取可见文本块；get_textbox 会把嵌入表格里的原始英文层也算进来。
                text="\n".join(b[4] for b in pg.get_text("blocks")
                               if box.intersects(pdf.Rect(b[:4])) and b[1]>=box.y0-4)
                steps=[int(k) for k in re.findall(r"(?m)^\s*(\d+)[:：]",text)]
                if steps!=obj["steps"] or r"\quad" in text:
                    issue("algorithm_steps",p,anchor,"行号不连续或出现未排版的缩进指令")
                targets=[link.get("nameddest") for link in pg.get_links() if box.intersects(link["from"])]
                if any("eq-"+v in names and "eq-"+v not in targets for v in obj["refs"]):
                    issue("algorithm_ref",p,anchor,"算法内公式引用缺少跳转")
            elif kind=="figure":
                digest=obj.get("digest")
                if not digest:
                    issue("unverified_figure",p,anchor,"无法把译稿裁片可靠配准到原图")
                elif draws[target][digest]!=1 or sum(h[digest] for h in draws)!=1:
                    issue("figure_ink",p,anchor,"原图裁片没有在目标页恰好绘制一次")
            elif "box" in obj:
                # 多个独立数值行在成品中重复，才能判定整组子表被重复绘制。
                box=pdf.Rect(obj["box"])
                grid=names.get(obj["grid"],{})
                grid_page=grid.get("page",-1)
                if 0<=grid_page<len(out):
                    pg=out[grid_page]
                    top=(pdf.Point(grid["to"])*pg.transformation_matrix).y
                    clip=pdf.Rect(0,max(0,top-5),pg.rect.width,min(pg.rect.height,top+max(80,box.height*1.8)))
                    printed=re.sub(r"\s+","",pg.get_textbox(clip))
                    tokens=set(re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{2,}\b|\b\d+(?:\.\d+)?\b",source[p-1].get_textbox(box)))
                    if len([v for v in tokens if v in printed])<min(3,len(tokens)) or not printed:
                        issue("unverified_table",p,anchor,"表体落点未匹配到原表内容")
                elif not any(h.get(c["digest"]) for c in crops if c["page"]==p and "box" in c
                             and (box & pdf.Rect(c["box"])).get_area()>.65*box.get_area() for h in [draws[target]]):
                    issue("unverified_table",p,anchor,"未确认原生表体或同位置的原表裁片")
                src=row_strings(source[p-1],box)
                signatures=Counter(r for r in src if re.match(r"[A-Za-z]",r) and len(re.findall(r"\d",r))>=7)
                if signatures:
                    repeats=[r for r,nrows in signatures.items() if sum(s.count(r) for s in rows)>nrows]
                    if len(repeats)>=2:
                        issue("duplicate_parts" if obj.get("parts") else "possible_duplicate_table",p,anchor,"成品重复数值行："+", ".join(repeats[:3]))
                        issues[-1]["rows"]=repeats
                if obj.get("parts"):
                    for part in obj["parts"]:
                        if not (0<=grid_page<len(out) and "("+part+")" in printed):
                            issue("missing_part",p,anchor,f"无法验证子表 ({part})")
            else:
                issue("unverified_table",p,anchor,"原表边界未可靠识别，需核对表体")
        for pg in out:
            raw = pg.get_text()
            if re.search(r"\\cite(?:p|t)?\s*\{", raw):
                issue("unrendered_citation", None, f"pdf-{pg.number+1}", "引用命令被印为正文")
            text=re.sub(r"\s+","",raw)
            if len(text)<14 and not pg.get_image_info() and not pg.get_drawings():
                issue("sparse_page",None,f"pdf-{pg.number+1}","页面只有少量文字，无图表")
        for pg in out:
            for link in pg.get_links():
                name=link.get("nameddest","")
                if name.startswith(("tab-","fig-","eq-","bib-")) and link.get("page",-1)!=names.get(name,{}).get("page",-2):
                    issue("invalid_link",None,name,f"译文第 {pg.number+1} 页链接目标无效")
    return issues


def repair(draft,issues,objects,original_draft=None):
    chunks=re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)",draft)
    original_chunks=re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)",original_draft or draft)
    actions=[]
    for item in issues:
        if item["code"]=="missing_glyph":
            # 字体没有字形时直接删除该字符，避免逐轮重试仍无法出页。
            match=re.search(r"There is no (.+?) \(U\+([0-9A-Fa-f]{4,6})\)",item.get("detail",""))
            if match:
                char=chr(int(match.group(2),16))
                if any(char in chunk for chunk in chunks):
                    chunks=[chunk.replace(char,"") for chunk in chunks]
                    actions.append(item)
            continue
        p=item["source_page"]
        if not p or 2*p>=len(chunks):continue
        text=chunks[2*p]
        if item["code"]=="prose_crop":
            if len(re.findall(r"[一-鿿]",text))<30:
                continue
            text=re.sub(r"!\[[^\]]*\]\("+re.escape(item["object"])+r"\)","",text)
        elif item["code"] in ("missing_object","figure_ink") and item["object"].startswith("fig-"):
            num=item["object"][4:]
            obj=next(o for o in objects if o["type"]=="figure" and o["page"]==p and o["number"]==num)
            if not obj.get("asset"):
                continue
            raw=original_chunks[2*p].strip().split("\n\n")
            cap_pattern=re.compile(r"^(?:图|Figure)\s*"+re.escape(num)+r"(?=[：:.\s])",re.I)
            cap=[b for b in raw if cap_pattern.match(b)]
            image=[b for b in raw if b.startswith("![") and "("+obj["asset"]+")" in b]
            if len(cap)!=1 or len(image)!=1:
                continue
            blocks=text.strip().split("\n\n")
            slot=next((k for k,b in enumerate(blocks) if b in (cap[0],image[0])),None)
            if slot is None:
                # 从未清理的译稿定位相邻保留段落，恢复图与图注。
                following=raw[raw.index(cap[0])+1:]
                slot=next((blocks.index(b) for b in following if b in blocks),len(blocks))
            blocks=[b for b in blocks if b not in (cap[0],image[0])]
            blocks[slot:slot]=[image[0],cap[0]]
            text="\n\n"+"\n\n".join(blocks)+"\n\n"
        elif item["code"]=="possible_duplicate_table":
            num=item["object"][4:]
            owners={o["page"] for o in objects if o["type"]=="table" and o["number"]==num}
            for j in (p-1,p+1):
                if j in owners or j<1 or 2*j>=len(chunks):continue
                blocks=chunks[2*j].strip().split("\n\n")
                for k,b in enumerate(blocks[:-1]):
                    if not re.match(r"^(?:表|Table)\s*"+re.escape(num)+r"\s*[:：]",b,re.I) or not blocks[k+1].startswith("|"):
                        continue
                    rows={re.sub(r"[|*\s`]+","",r) for r in blocks[k+1].splitlines()}
                    if len(rows.intersection(item.get("rows",[])))>=2:
                        del blocks[k:k+2]
                        chunks[2*j]="\n\n"+"\n\n".join(blocks)+"\n\n"
                        actions.append({**item,"removed_from_page":j})
                        break
        elif item["code"]=="duplicate_parts":
            obj=next(o for o in objects if o["page"]==p and "tab-"+o["number"]==item["object"])
            blocks=text.strip().split("\n\n")
            for i,b in enumerate(blocks):
                if not re.match(r"^(?:表|Table)\s*"+obj["number"]+r"\s*[:：]",b):continue
                j=i+1
                for part in obj["parts"]:
                    if (j+1>=len(blocks) or not re.match(r"^\("+part+r"\)\s*",blocks[j])
                        or not blocks[j+1].lstrip().startswith("|")):break
                    j+=2
                else:
                    del blocks[i+1:j]
                    text="\n\n"+"\n\n".join(blocks)+"\n\n"
                break
        if text!=chunks[2*p]:
            chunks[2*p]=text
            actions.append(item)
    return "".join(chunks),actions


def repair_split_math(draft):
    """用同一译稿中的完整公式核对被控制字符截断的命令。"""
    intact = re.findall(r"(?<![\\$])\$(\\[a-zA-Z]+[^$\n\r]*)\$(?!\$)", draft)
    records = []
    pattern = r"(?<![\\$])\$[\r\n\t]([a-zA-Z]+)([^$\r\n]*)\$(?!\$)"
    def restore(match):
        candidates = {value for value in intact
                      if value[1:2] in ("r", "n", "t") and value[2:] == match[1] + match[2]}
        fixed = "$" + candidates.pop() + "$" if len(candidates) == 1 else match[0]
        page = draft.count("<!-- 原稿第 ", 0, match.start())
        records.append({"source_page": page, "before": match[0], "after": fixed})
        return fixed
    return re.sub(pattern, restore, draft), records


def strip_unresolved_images(draft):
    """删除模型自造的图片链接，只保留确实存在于 figures/ 的裁片。"""
    def replace(match):
        target=match.group(1).strip()
        if target.startswith("figures/"):return match.group(0)
        return ""
    return re.sub(r"!\[[^\]]*\]\(([^)]+)\)",replace,draft)


def verified_export(directory,source,args):
    from paper_translator.render.vision_latex import render_vision_latex
    from paper_translator.translation.prose_language import check_draft, inspect_page, normalized, source_pages
    path=directory/"paper.md"
    if args is not None:
        from paper_translator.translation.headings import translate_headings
        translate_headings(path,args)
    logpath=directory/"正文语言检查.json"
    log=json.loads(logpath.read_text()) if logpath.is_file() else []
    log.extend(check_draft(path,source,args) if args is not None else [])
    logpath.write_text(json.dumps(log,ensure_ascii=False,indent=2))
    refs=source_pages(source)
    draft, math_records = repair_split_math(path.read_text())
    from paper_translator.source.figure_groups import restore_placeholder_figures, restore_groups, normalize_figure_html
    draft = normalize_figure_html(draft)
    draft, restored_figures = restore_placeholder_figures(draft, source, directory)
    draft = strip_unresolved_images(draft)
    from paper_translator.source.figure_groups import strip_figure_text, ensure_missing_figures
    draft, removed_figure_text = strip_figure_text(draft, source)
    from paper_translator.render.ruled_algorithm import normalize_algorithm_blocks
    draft = normalize_algorithm_blocks(draft)
    draft, ensured_figures = ensure_missing_figures(draft, source, directory, args)
    from paper_translator.translation.glyphs import strip_pictographs
    draft, removed_glyphs = strip_pictographs(draft)
    draft = restore_groups(draft, source, directory)
    original_draft=draft
    with pdf.open(source) as original,tempfile.TemporaryDirectory(dir=directory.parent) as temp:
        objects=source_inventory(original)
        crops=raster_inventory(original,directory,draft,objects)
        from paper_translator.source.crop_complete import complete_crops
        completed=complete_crops(original,directory,objects,crops)
        crop_report=directory/'图块边界补全.json'
        if completed or not crop_report.exists():
            crop_report.write_text(json.dumps(completed,ensure_ascii=False,indent=2))
        if completed:
            objects=source_inventory(original)
            crops=raster_inventory(original,directory,draft,objects)
        report={"inline_math":math_records,"source_inventory":objects,"attempts":[],"scope":"中文正文语言、英文段落的原页归属、识别到的编号图表、图像绘制、表体与子表、内部链接、异常稀疏页。未逐句校对翻译语义。"}
        best=None
        previous=None
        for count in range(3):
            run=Path(temp)/str(count)
            run.mkdir()
            (run/"paper.md").write_text(draft)
            if (directory/"figures").is_dir():
                shutil.copytree(directory/"figures",run/"figures",copy_function=os.link)
            config = directory/"layout.json"
            if config.exists(): shutil.copyfile(config, run/"layout.json")
            try:
                render_vision_latex(run,source,args,prepared_draft=count>0,
                                    crop_boxes={c["path"]:pdf.Rect(c["box"]) for c in crops if "box" in c})
                issues=audit(original,run,objects,crops)
                for record in math_records:
                    if record["before"] == record["after"]:
                        issues.append({"code":"split_inline_math","object":record["before"],"source_page":record["source_page"],"detail":"缺少唯一的完整公式可供核对"})
                if args and args.target.lower().startswith("zh"):
                    kept={(r["page"],r["source"]) for r in log if r["action"]=="keep"}
                    pages=re.split(r"(?m)^<!-- 原稿第 \d+ 页 -->",(run/"paper.md").read_text())[1:]
                    for i,text in enumerate(pages):
                        for j,b,owner in inspect_page(text,i,refs):
                            if (i+1,b) not in kept:
                                issues.append({"code":"unchecked_english","object":f"paragraph-{j}","source_page":i+1,"detail":b[:100]})
                    with pdf.open(run/"paper.pdf") as output:
                        printed=[normalized(pg.get_text()) for pg in output]
                    for k,record in enumerate(log):
                        words=normalized(record["source"]).split()
                        if record["action"] not in ("translate","duplicate") or len(words)<14:
                            continue
                        sample=" ".join(words[:14])
                        if any(sample in pg for pg in printed):
                            issues.append({"code":"printed_english","object":f"prose-{k}","source_page":record["page"],"detail":sample})

            except (ValueError,OSError) as error:
                if best is None:raise
                report["attempts"].append({"attempt":count+1,"error":str(error)})
                break
            entry={"attempt":count+1,"issues":issues}
            report["attempts"].append(entry)
            keys={(i["code"],i["source_page"],i["object"]) for i in issues}
            if previous is not None and not keys<previous:
                break
            best=run
            report.update(selected_attempt=count+1,status="needs_review" if issues else "passed",remaining=issues)
            previous=keys
            if not issues or count==2:break
            draft,actions=repair((run/"paper.md").read_text(),issues,objects,original_draft)
            if not actions:break
            entry["repairs"]=actions
        for path in best.iterdir():
            if path.name=="figures":continue
            if path.is_dir():shutil.copytree(path,directory/path.name,dirs_exist_ok=True)
            else:shutil.copyfile(path,directory/path.name)
        report["advisories"]=[name for name in ("LaTeX版式检查.txt","表格待译说明.txt") if (best/name).is_file()]
        from paper_translator.harness.reference_audit import audit_references
        report["references"]=audit_references((best/"paper.md").read_text())
        (directory/"参考文献检查.json").write_text(json.dumps(report["references"],ensure_ascii=False,indent=2))
        if restored_figures:report["placeholder_figures"]=restored_figures
        if removed_figure_text:report["figure_text_removed"]=removed_figure_text
        if ensured_figures:report["ensured_figures"]=ensured_figures
        if removed_glyphs:report["glyphs_removed"]=removed_glyphs
        (directory/"质量验收.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
        if report["references"]["translated"]:
            print(f"参考文献：{report['references']['translated']}/{report['references']['entries']} 条仍为中文，需重新翻译该区域。",flush=True)
        if report["remaining"]:
            (directory/"待复核.txt").write_text("\n".join(f"{i['object']}（原页 {i['source_page']}） {i['detail']}" for i in report["remaining"]))
        print("成品验收："+("已通过对象检查" if report["status"]=="passed" else "仍需复核，详见待复核.txt"),flush=True)
