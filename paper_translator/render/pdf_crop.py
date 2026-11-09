"""生成不携带框外文字的 PDF 矢量裁片。"""

from contextlib import contextmanager

import pymupdf as pdf


class CropIsolationError(ValueError):
    """无法在保留画面的同时隔离裁区的文本层。"""


def _has_outside_text(page):
    bounds = page.rect + (-.05, -.05, .05, .05)
    for span in page.get_texttrace():
        for code, _, _, bbox in span["chars"]:
            rect = pdf.Rect(bbox)
            if not rect.is_empty and not bounds.intersects(rect) and chr(code).strip():
                return True
    return False


def _show_crop(asset, source, number, box):
    page = asset.new_page(width=box.width, height=box.height)
    if source[number].get_contents():
        page.show_pdf_page(page.rect, source, number, clip=box)
    return page


def _remove_surrounding_text(page, box, padding):
    outer = page.rect
    x0, y0, x1, y1 = (box + (-padding, -padding, padding, padding)) & outer
    for rect in (
        pdf.Rect(outer.x0, outer.y0, x0, outer.y1),
        pdf.Rect(x1, outer.y0, outer.x1, outer.y1),
        pdf.Rect(x0, outer.y0, x1, y0),
        pdf.Rect(x0, y1, x1, outer.y1),
    ):
        if not rect.is_empty:
            page.add_redact_annot(rect, fill=False, cross_out=False)
    page.apply_redactions(images=pdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pdf.PDF_REDACT_LINE_ART_NONE)


@contextmanager
def isolated_pdf_crop(source, number, box):
    """保留框内矢量和文字；用字形坐标与裁区像素分别检查选择和画面。"""
    box = pdf.Rect(box) & source[number].rect
    if box.is_empty:
        raise CropIsolationError(f"原稿第 {number+1} 页的矢量裁区为空。")

    with pdf.open() as reference:
        original = _show_crop(reference, source, number, box)
        if not _has_outside_text(original):
            yield reference
            return
        expected = original.get_pixmap(dpi=144).samples

    # 先贴边清理。若碰到字形度量框，再留一点余量，仍须通过同样的检查。
    for padding in (0, 2):
        with pdf.open() as cleaned, pdf.open() as asset:
            cleaned.insert_pdf(source, from_page=number, to_page=number, links=False, annots=False)
            _remove_surrounding_text(cleaned[0], box, padding)
            page = _show_crop(asset, cleaned, 0, box)
            if not _has_outside_text(page) and page.get_pixmap(dpi=144).samples == expected:
                yield asset
                return

    raise CropIsolationError(f"原稿第 {number+1} 页的矢量裁片无法同时保留原画面并移除框外文字。")
