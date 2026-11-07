"""保留原稿题头，在最终 PDF 中比对其可见内容。"""
import re

import cv2
import numpy as np
import pymupdf as pdf


def header_region(page):
    lines = [(line, "".join(s["text"] for s in line["spans"]).strip())
             for block in page.get_text("dict", flags=pdf.TEXTFLAGS_TEXT)["blocks"]
             for line in block.get("lines", []) if line["dir"] == (1, 0)]
    boundary = next((line["bbox"][1] for line, text in lines
                     if re.match(r"^(?:Abstract\b|摘\s*要)", text, re.I)), None)
    if page.rotation or boundary is None:
        return None
    caption_before = any(line["bbox"][1] < boundary and re.match(r"^(?:Fig(?:ure)?\.?|Table|图|表)\s*\d", text, re.I)
                         for line, text in lines)
    title_top = 0
    if caption_before:
        candidates=[(line,text) for line,text in lines if text and line["bbox"][1] < boundary
                    and not text.isdigit()]
        sizes=[max(s["size"] for s in line["spans"]) for line,text in candidates]
        if not sizes:
            return None
        largest=max(sizes)
        title=[line for (line,text),size in zip(candidates,sizes) if size>=largest*.9]
        title_top=min(line["bbox"][1] for line in title)
        title_bottom=max(line["bbox"][3] for line in title)
        regions=[pdf.Rect(im["bbox"]) for im in page.get_image_info()
                 if title_bottom < im["bbox"][1] < boundary]
        regions += [g["rect"] for g in page.get_drawings()
                    if title_bottom < g["rect"].y0 < boundary and g["rect"].x0>=min(l["bbox"][0] for l in title)-3 and g["rect"].width>page.rect.width*.15
                    and g["rect"].height>10]
        if not regions:
            return None
        boundary=min(r.y0 for r in regions)
    body_lines=[line for line,text in lines if len(text)>35 and not text.isdigit()]
    body_left=min((line["bbox"][0] for line in body_lines),default=0)
    boxes = [pdf.Rect(line["bbox"]) for line, text in lines if text and not text.isdigit() and line["bbox"][0]>=body_left-3
             and title_top-2<=line["bbox"][1] and line["bbox"][3] <= boundary]
    if not boxes:
        return None
    images = [pdf.Rect(im["bbox"]) for im in page.get_image_info() if title_top-2<=im["bbox"][1] and im["bbox"][3] <= boundary]
    for drawing in page.get_drawings():
        if drawing["rect"].x0>=body_left-3 and title_top-2<=drawing["rect"].y0 and drawing["rect"].y1 <= boundary:
            boxes.append(drawing["rect"])
    box = boxes[0]
    for rect in boxes[1:] + images:
        box |= rect
    return (box + (-2, -2, 2, 2)) & page.rect


def draft_header_end(nodes, origins):
    for i, (node, origin) in enumerate(zip(nodes, origins)):
        if origin:
            break
        if node.tag in ("table", "figure") or node.xpath(".//img"):
            return i if i else None
        if re.match(r"^(?:摘\s*要|Abstract\b)", node.text_content().strip(), re.I):
            return i if i else None
    return None


def locate_header(source, output, box, width):
    def gray(page, scale, clip=None):
        pix = page.get_pixmap(matrix=pdf.Matrix(scale, scale), clip=clip, colorspace=pdf.csGRAY)
        return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    template = gray(source, 1.5 * width / box.width, box)
    target = gray(output, 1.5)
    if any(a > b for a, b in zip(template.shape, target.shape)) or template.std() < 3:
        return 0, (0, 0)
    # 低通处理消除亚像素位置造成的抗锯齿差异。
    template = cv2.GaussianBlur(template, (5, 5), 1)
    target = cv2.GaussianBlur(target, (5, 5), 1)
    _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(target, template, cv2.TM_CCOEFF_NORMED))
    return score, (point[0] / 1.5, point[1] / 1.5)
