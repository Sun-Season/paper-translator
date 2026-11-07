"""统计参考文献区是否被翻译成中文，作为交付前的提示。

参考文献条目按学术惯例保留原文；本模块只报告，不改写正文。
"""
import re

CJK=re.compile(r"[\u3400-\u9fff]")
HEADING=re.compile(r"(?mi)^\s*(?:#{1,4}\s*|\*\*\s*)?(?:\d+(?:\.\d+)*\s*)?(?:参考文献|references)\s*(?:\*\*)?\s*$")


def reference_section(markdown):
    """返回参考文献正文；没有该章节或章节为空时返回空串。"""
    headings=list(HEADING.finditer(markdown))
    if not headings:return ""
    body=markdown[headings[-1].end():]
    # 附录或正文的章节标题表示参考文献区结束。
    stop=re.search(r"(?m)^#{1,2}\s+\S",body)
    return body[:stop.start()] if stop else body


def reference_blocks(markdown):
    section=reference_section(markdown)
    if not section.strip():return []
    blocks=[]
    for block in re.split(r"\n\s*\n",section):
        block=re.sub(r"(?m)^<!--.*?-->$","",block).strip()
        if block:blocks.append(block)
    return blocks


def audit_references(markdown):
    blocks=reference_blocks(markdown)
    translated=[{"index":index+1,"text":block[:120]}
                for index,block in enumerate(blocks) if CJK.search(block)]
    return {"entries":len(blocks),"translated":len(translated),
            "samples":translated[:5],"status":"needs_review" if translated else "passed"}
