"""将编译越界和实际出页绘制作为发布前的阻断问题。"""
from pathlib import Path
import re

import numpy as np
import pymupdf as pdf


def layout_issues(directory):
    directory=Path(directory)
    issues=[]
    warning=directory/'LaTeX版式检查.txt'
    if warning.exists():
        for line in warning.read_text().splitlines():
            match=re.search(r'Overfull \\([hv])box \(([\d.]+)pt too',line)
            if 'Missing character:' in line or (match and float(match[2])>1):
                issues.append({'code':'latex_overflow' if match else 'missing_glyph',
                    'source_page':None,'object':'latex','detail':line,'severity':'major'})
    # 扩大可渲染画布，观察原纸张之外实际绘制的墨迹；尊重 PDF 内部裁剪路径。
    with pdf.open(directory/'paper.pdf') as doc:
        if (directory/'目录重建记录.json').exists():
            from paper_translator.harness.review_contract import render_evidence
            from paper_translator.harness.contents_audit import audit_contents
            entries=render_evidence(directory,doc).get('contents',{}).get('entries',[])
            verified=audit_contents(doc,entries)
            missing={e['id'] for e in entries}-{e['id'] for e in verified}
            if missing:
                issues.append({'code':'contents_target_unverified','source_page':None,'object':'contents',
                               'detail':'目录显示页码与实际目标尚未验证：'+', '.join(sorted(missing)),'severity':'major'})
        for page in doc:
            if page.rotation:
                issues.append({'code':'unsupported_geometry','source_page':None,'object':f'pdf-{page.number+1}',
                               'detail':'输出页面旋转，无法验证边界','severity':'major'})
                continue
            original=page.mediabox
            margin=24
            page.set_mediabox(original+(-margin,-margin,margin,margin))
            pix=page.get_pixmap(matrix=pdf.Matrix(1,1),colorspace=pdf.csGRAY,alpha=False)
            ink=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width)<180
            bands=[ink[:margin-1,:],ink[-margin+1:,:],ink[:,:margin-1],ink[:,-margin+1:]]
            if sum(int(b.sum()) for b in bands)>3:
                issues.append({'code':'paint_outside_page','source_page':None,'object':f'pdf-{page.number+1}',
                               'detail':'扩大画布后发现纸张之外仍有文字或图形','severity':'major'})
    return issues
