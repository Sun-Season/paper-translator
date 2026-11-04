import unittest
import pymupdf as pdf
from source_layout import source_layout, spans_gutter


class SourceLayoutTest(unittest.TestCase):
    def test_mixed_paper_and_ambiguous_page(self):
        with pdf.open() as doc:
            for boxes in [[(45,60,565,420)],[],[(45,60,290,420),(320,60,565,420)]]:
                page=doc.new_page(width=612,height=792)
                for box in boxes:
                    page.insert_textbox(box,"This paragraph describes the results of a scientific experiment. "*18,fontsize=9)
            self.assertEqual(source_layout(doc)[0],[1,1,2])

    def test_column_and_spanning_boxes(self):
        self.assertFalse(spans_gutter(pdf.Rect(48,70,295,130),612))
        self.assertTrue(spans_gutter(pdf.Rect(70,350,540,430),612))
