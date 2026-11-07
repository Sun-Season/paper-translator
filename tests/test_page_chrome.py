import unittest

import pymupdf as pdf

from paper_translator.source.page_chrome import chrome_boxes, chrome_text


class PageChromeTest(unittest.TestCase):
    def page(self):
        doc=pdf.open()
        page=doc.new_page(width=600,height=800)
        for y in (200,220,240):
            page.insert_text((60,y),"Body text of the paper at the normal printed size.",fontsize=10)
        page.insert_text((60,770),"Reviewers: please read the reviewer guidelines before writing.",fontsize=5)
        page.insert_text((292,790),"7",fontsize=10)
        return doc,page

    def test_fine_print_footer_and_page_number_are_masked(self):
        doc,page=self.page()
        boxes=chrome_boxes(page)
        covered=lambda y:any(b.y0-1<=y<=b.y1+1 for b in boxes)
        self.assertTrue(covered(770))
        self.assertTrue(covered(790))
        self.assertFalse(covered(200))
        doc.close()

    def test_large_title_in_top_band_is_not_masked(self):
        doc=pdf.open()
        page=doc.new_page(width=600,height=800)
        page.insert_text((60,25),"A Large Paper Title",fontsize=18)
        page.insert_text((60,200),"Body text of the paper at the normal printed size.",fontsize=10)
        boxes=chrome_boxes(page)
        self.assertFalse(any(b.y1<40 and b.y0<20 for b in boxes))
        doc.close()

    def test_chrome_text_drops_masked_lines(self):
        doc,page=self.page()
        boxes=chrome_boxes(page)
        text=chrome_text(page,boxes)
        self.assertIn("Body text",text)
        self.assertNotIn("Reviewers",text)
        doc.close()

    def test_rotated_margin_stamp_is_masked(self):
        doc=pdf.open()
        page=doc.new_page(width=600,height=800)
        page.insert_text((10,300),"arXiv:2511.14759v2",fontsize=8,rotate=90)
        boxes=chrome_boxes(page)
        self.assertTrue(any(b.x1<40 for b in boxes))
        doc.close()
