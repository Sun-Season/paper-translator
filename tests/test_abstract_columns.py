import unittest
import pymupdf
from paper_translator.source.source_layout import abstract_columns


class AbstractColumnsTest(unittest.TestCase):
    def test_abstract_width_independent_of_body(self):
        for width, expected in ((245,2),(510,1)):
            with self.subTest(width=width), pymupdf.open() as doc:
                page=doc.new_page(width=612,height=792)
                page.insert_textbox(pymupdf.Rect(49,100,49+width,400),
                                    "Abstract—"+"This paper describes the method and its results in detail. "*12,
                                    fontsize=10)
                self.assertEqual(abstract_columns(page),expected)
