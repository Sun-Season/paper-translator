import unittest

import pymupdf as pdf

from paper_translator.legacy.reflow_pdf import page_items


class CaptionBoundaryTest(unittest.TestCase):
    def items(self, captions, extra=None):
        with pdf.open() as doc:
            page = doc.new_page()
            for y, text in captions:
                page.insert_text((45, y), text, fontsize=11)
            if extra:
                page.insert_text((320, extra), "axis label", fontsize=9)
            return page_items(page, {"2": pdf.Rect(30, 55, 480, 190)})

    def test_caption_is_separate(self):
        for title in ("Fig. 2: Results", "Figure 2. Results"):
            items = self.items([(185, title)])
            figure = next(i for i in items if i.anchor == "fig-2")
            caption = next(i for i in items if i.kind == "caption")
            self.assertLessEqual(figure.box.y1, caption.box.y0)

    def test_uncertain_crops_stop(self):
        for captions, extra in [
            ([(185, "2 | Results")], None),
            ([(185, "Fig. 2: First"), (215, "Fig. 2: Second")], None),
            ([(450, "Fig. 2: Distant")], None),
            ([(185, "Fig. 2: Results")], 177),
        ]:
            with self.subTest(captions=captions, extra=extra):
                with self.assertRaisesRegex(ValueError, "第 1 页图 2"):
                    self.items(captions, extra)


if __name__ == "__main__":
    unittest.main()
