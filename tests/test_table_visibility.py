import unittest
import pymupdf as pdf
from paper_translator.render.table_style import numeric_tex


class TableVisibilityTest(unittest.TestCase):
    def test_clipped_source_text_is_not_reintroduced(self):
        with pdf.open() as source,pdf.open() as target:
            page=source.new_page(width=300,height=300)
            page.insert_text((30,50),'HIDDEN')
            page.insert_text((30,180),'VISIBLE')
            out=target.new_page(width=300,height=300)
            out.show_pdf_page(pdf.Rect(0,100,300,300),source,0,clip=pdf.Rect(0,100,300,300))
            # 原 PDF 仍包含裁框外文字；重建只能使用实际可见部分。
            self.assertIn('HIDDEN',out.get_text(flags=0))
            tex=numeric_tex(out,out.rect,[])
            self.assertIn('VISIBLE',tex)
            self.assertNotIn('HIDDEN',tex)
