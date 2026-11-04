"""将同一图注前的多个裁片恢复为原稿中的完整图组。"""
import re
from pathlib import Path
import pymupdf


def restore_groups(markdown, source, directory):
    chunks = re.split(r"(?m)(^<!-- 原稿第 \d+ 页 -->)", markdown)
    with pymupdf.open(source) as doc:
        for page_index, page in enumerate(doc):
            offset = 2 * page_index + 2
            if offset >= len(chunks):
                break
            blocks = chunks[offset].strip().split("\n\n")
            captions = [b for b in page.get_text("blocks") if re.match(r"^(?:Fig(?:ure)?\.?)\s*\d+", b[4])]
            for index in range(len(blocks)-1, -1, -1):
                match = re.match(r"^(?:图|Figure)\s*(\d+)", blocks[index])
                if not match:
                    continue
                start = index
                while start and blocks[start-1].startswith("!["):
                    start -= 1
                if index-start < 2:
                    continue
                cap = next((b for b in captions if re.match(r"^(?:Fig(?:ure)?\.?)\s*"+match[1]+r"\b", b[4])), None)
                if cap is None:
                    continue
                boundary = max([b[3] for b in captions if b[3] < cap[1]] or [0])
                tiles = [pymupdf.Rect(im["bbox"]) for im in page.get_image_info()
                         if im["bbox"][1] >= boundary and im["bbox"][3] <= cap[1]+1]
                if not tiles:
                    continue
                box = pymupdf.Rect(cap[0], min(r.y0 for r in tiles)-2, cap[2], cap[1]-2)
                name = f"figures/page-{page_index+1:04d}-group-{match[1]}.png"
                path = Path(directory)/name
                path.parent.mkdir(exist_ok=True)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(400/72,400/72), clip=box, alpha=False)
                pix.set_dpi(400,400)
                pix.save(path)
                blocks[start:index] = [f"![图 {match[1]}]({name})"]
            chunks[offset] = "\n\n"+"\n\n".join(blocks)+"\n\n"
    return "".join(chunks)
