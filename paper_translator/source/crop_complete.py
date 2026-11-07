"""在资产登记前，补全图块与图注之间的坐标轴标签或图例。"""
from pathlib import Path
import pymupdf as pdf


def complete_crops(source,directory,objects,crops):
    by_path={c['path']:c for c in crops if 'box' in c}
    changes=[]
    for obj in objects:
        if obj['type']!='figure' or obj.get('asset') not in by_path:continue
        crop=by_path[obj['asset']];box=pdf.Rect(crop['box']);caption=pdf.Rect(obj['caption_box'])
        gap=caption.y0-box.y1
        overlap=max(0,min(box.x1,caption.x1)-max(box.x0,caption.x0))
        if not(3<gap<45 and overlap>=box.width*.8):continue
        complete=pdf.Rect(box.x0,box.y0,box.x1,caption.y0-2)
        pix=source[obj['page']-1].get_pixmap(matrix=pdf.Matrix(400/72,400/72),clip=complete,alpha=False)
        pix.set_dpi(400,400)
        path=Path(directory)/crop['path'];temporary=path.with_name(path.stem+'.complete.png')
        pix.save(temporary)
        temporary.replace(path)  # 断开硬链接，不改输入缓存。
        changes.append({'source_page':obj['page'],'asset':crop['path'],'before':list(box),'after':list(complete)})
    return changes
