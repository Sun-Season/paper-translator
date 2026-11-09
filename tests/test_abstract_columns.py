import unittest

import pymupdf

from paper_translator.source.source_layout import abstract_columns, abstract_layout

BODY = "This paper describes the method and its results in detail with enough words to fill the line. "


class AbstractLayoutTest(unittest.TestCase):
    def page(self):
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        return doc, page

    def test_narrow_centered_single_column(self):
        doc, page = self.page()
        page.insert_textbox(pymupdf.Rect(143.9, 100, 468.1, 500), "Abstract: " + BODY * 8, fontsize=10)
        layout = abstract_layout(page, body_columns=1, left=108, right=108)
        self.assertEqual(layout["columns"], 1)
        self.assertTrue(layout["narrow"])
        self.assertTrue(layout["centered"])
        doc.close()

    def test_full_width_single_column(self):
        doc, page = self.page()
        page.insert_textbox(pymupdf.Rect(60, 100, 552, 500), "Abstract: " + BODY * 10, fontsize=10)
        layout = abstract_layout(page, body_columns=1, left=60, right=60)
        self.assertEqual(layout["columns"], 1)
        self.assertFalse(layout["narrow"])
        doc.close()

    def test_two_column_abstract(self):
        doc, page = self.page()
        page.insert_textbox(pymupdf.Rect(60, 100, 290, 400), "Abstract: " + BODY * 6, fontsize=10)
        page.insert_textbox(pymupdf.Rect(320, 100, 552, 400), BODY * 6, fontsize=10)
        layout = abstract_layout(page, body_columns=2, left=60, right=60)
        self.assertEqual(layout["columns"], 2)
        self.assertFalse(layout["narrow"])
        doc.close()

    def test_abstract_never_more_columns_than_body(self):
        doc, page = self.page()
        page.insert_textbox(pymupdf.Rect(60, 100, 290, 400), "Abstract: " + BODY * 6, fontsize=10)
        page.insert_textbox(pymupdf.Rect(320, 100, 552, 400), BODY * 6, fontsize=10)
        self.assertEqual(abstract_layout(page, body_columns=1, left=60, right=60)["columns"], 1)
        doc.close()

    def test_legacy_helper_returns_columns(self):
        doc, page = self.page()
        page.insert_textbox(pymupdf.Rect(143.9, 100, 468.1, 500), "Abstract: " + BODY * 8, fontsize=10)
        self.assertEqual(abstract_columns(page), 1)
        doc.close()


if __name__ == "__main__":
    unittest.main()
