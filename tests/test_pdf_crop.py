import unittest

import pymupdf as pdf

from paper_translator.render.pdf_crop import isolated_pdf_crop


class PdfCropTest(unittest.TestCase):
    def test_reembedded_crop_keeps_visible_text_and_removes_clipped_text(self):
        with pdf.open() as original, pdf.open() as output:
            source = original.new_page(width=320, height=400)
            source.insert_text((75, 58), "Paper title")
            source.insert_text((27, 290), "arXiv margin stamp", rotate=90)
            source.insert_text((75, 170), "Unrelated source paragraph")
            source.draw_line((75, 67), (230, 67))
            box = pdf.Rect(70, 38, 250, 75)

            page = output.new_page(width=320, height=400)
            slot = pdf.Rect(70, 38, 250, 75)
            page.insert_text((75, 170), "Visible translated paragraph")
            with isolated_pdf_crop(original, 0, box) as asset:
                page.show_pdf_page(slot, asset, 0)
            page = output.reload_page(page)
            self.assertEqual(
                source.get_pixmap(clip=box, dpi=144).samples,
                page.get_pixmap(clip=slot, dpi=144).samples,
            )
            self.assertEqual(len(page.search_for("Paper title")), 1)
            self.assertEqual(len(page.search_for("Visible translated paragraph")), 1)
            raw = "".join(chr(c[0]) for span in page.get_texttrace() for c in span["chars"])
            self.assertNotIn("arXiv", raw)
            self.assertNotIn("Unrelated", raw)
