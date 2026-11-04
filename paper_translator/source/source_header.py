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
    if any(line["bbox"][1] < boundary and re.match(r"^(?:Fig(?:ure)?\.?|Table|图|表)\s*\d", text, re.I)
           for line, text in lines):
        images = [pdf.Rect(im["bbox"]) for im in page.get_image_info() if im["bbox"][1] < boundary]
        if not images:
            return None
        first_image = min(r.y0 for r in images)
        upper = sorted((line["bbox"][1], line["bbox"][3]) for line, text in lines if text and line["bbox"][3] < first_image)
        gaps = [(upper[k][0]-max(y[1] for y in upper[:k]), upper[k][0]) for k in range(1,len(upper))]
        if not gaps:
            return None
        gap, boundary = max(gaps)
        if gap < 10:
            return None
    boxes = [pdf.Rect(line["bbox"]) for line, text in lines if text and line["bbox"][3] <= boundary]
    if not boxes:
        return None
    images = [pdf.Rect(im["bbox"]) for im in page.get_image_info() if im["bbox"][3] <= boundary]
    for drawing in page.get_drawings():
        if drawing["rect"].y1 <= boundary:
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
