import unittest
import pymupdf as pdf
from reflow_pdf import Item,bind_footnotes

class FootnoteTest(unittest.TestCase):
    def test_note_is_bound_to_sentence_not_formula_exponent(self):
        with pdf.open() as doc:
            doc.new_page()
            body=Item(0,pdf.Rect(30,45,270,110),"p","公式 x<sup>1</sup>。<sup>1</sup>奖励函数")
            note=Item(0,pdf.Rect(30,760,270,780),"p","<sup>1</sup>为简单起见。")
            bind_footnotes([body,note],doc)
            self.assertEqual(body.text,"公式 x<sup>1</sup>。<fn-0-1/>奖励函数")
            self.assertEqual((note.kind,note.text),("footnote","为简单起见。"))
