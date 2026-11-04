"""每篇论文的排版执行器：重排、验收、交付或回退至原分页译文。"""
import re
import json
import shutil
import unicodedata
from pathlib import Path

import pymupdf as pdf


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC",text) if c.isalnum())


def run_layout(source, checkpoint, destination, columns, inline_settings=None, backend="mupdf"):
    from reflow_pdf import repaginate

    output = destination / "paper.pdf"
    log = {"layout_engine":backend,"input": source.name, "stages": ["translation_available", "reflow"]}
    paragraphs = []
    formulas = []
    try:
        repaginate(source, checkpoint, output, columns=columns, audit=paragraphs, formula_audit=formulas, inline_settings=inline_settings,backend=backend)
        log["stages"].append("verify")
        from equation_layout import verify_equations
        verify_equations(source,output,[a for a in formulas if a[0]!="inline"])
        with pdf.open(output) as doc:
            # 先核对导出的阅读流，避免只验证准备写入的 HTML。
            # 重排文本先写入页面，图像、公式等 PDF 裁片随后以 Form XObject 覆盖。
            # 验收时只读正文图层，避免把稍后绘制的图内文字插入跨页句子。
            chunks = []
            for page in doc:
                for xref in page.get_contents():
                    data = doc.xref_stream(xref)
                    if re.fullmatch(rb"\s*q\s+/fzFrm\d+\s+Do\s+Q\s*",data):
                        doc.update_stream(xref,b"")
                chunks.append(page.get_text(clip=pdf.Rect(0,0,page.rect.width,page.rect.height-26)))
            text = normalized("".join(chunks))
            if backend=="latex":
                log.update(compiled_pages=len(doc),bookmarks=len(doc.get_toc()),
                           links=sum(len(p.get_links()) for p in doc))
            failures = []
            for page, content in paragraphs:
                fragment = normalized(content)
                if not fragment:
                    continue
                # 换页可能插入页码；在页内检查相邻文本块拼接处。
                if fragment not in text:
                    failures.append(page+1)
            if failures:
                raise ValueError(f"重排后无法核实文本衔接，涉及原稿页 {sorted(set(failures))}。")
        log.update(status="ready", verified_joins=len(paragraphs), verified_numbered_equations=[n for n,*_ in formulas if n!="inline"], verified_inline_fragments=sum(n=="inline" for n,*_ in formulas))
        shutil.copyfile(checkpoint,destination / "原分页译文.pdf")
    except ValueError as error:
        shutil.copyfile(checkpoint, output)
        note=f"已保留原分页译文。重排未通过验收：{error}\n"
        (destination/"版式说明.txt").write_text(note,encoding="utf8")
        log.update(status="original_layout_fallback",reason=str(error))
        print(note)
    log["stages"].append("deliver")
    (destination/"任务报告.json").write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding="utf8")


def translation_checkpoint(source, settings, execute):
    """同一原稿与翻译配置共用一个任务目录，成功落盘后才可复用。"""
    import fcntl
    import hashlib
    import os
    import tempfile
    from importlib.metadata import version

    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    config = dict(settings, engine=version("pdf2zh-next"), source_sha256=digest.hexdigest())
    job_id = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    root = Path(os.getenv("PAPER_JOB_DIR") or Path.home()/"Library"/"Caches"/"paper-translator"/"jobs")
    job = root/job_id
    job.mkdir(parents=True, exist_ok=True, mode=0o700)
    saved = job/"translated.pdf"
    def record(stage, **fields):
        with (job/"events.jsonl").open("a", encoding="utf8") as log:
            log.write(json.dumps({"stage":stage,**fields},ensure_ascii=False)+"\n")
    with (job/"lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if saved.exists():
            record("reuse_translation")
            return saved
        record("translate")
        try:
            with tempfile.TemporaryDirectory(dir=job) as work:
                candidate=execute(Path(work))
                with pdf.open(source) as original, pdf.open(candidate) as translated:
                    if len(original)!=len(translated):
                        raise ValueError("原稿与译文页数不一致。")
                candidate.replace(saved)
        except Exception as error:
            record("failed",error_type=type(error).__name__)
            raise
        record("translation_committed")
        return saved
