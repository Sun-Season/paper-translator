import unittest
import pymupdf as pdf
from paper_translator.source.equation_layout import numbered_equations


class EquationLayoutTest(unittest.TestCase):
    def test_aligned_formula_and_number_share_source_crop(self):
        with pdf.open() as doc:
            page=doc.new_page(width=600,height=700)
            for x,y,t in [(40,60,"The display below has two lines."),
                          (65,82,"a = b + c"),(67,95,"+ d"),(282,94,"(2)"),
                          (40,111,"Here the next paragraph begins.")]:
                page.insert_text((x,y),t,fontsize=10)
            box=numbered_equations(page)["2"]
            text=page.get_textbox(box)
            for part in ("a = b + c","+ d","(2)"):
                self.assertIn(part,text)
            self.assertNotIn("paragraph",text)


class InlineMathTest(unittest.TestCase):
    def test_summation_ascii_encoding_never_sent_as_math_text(self):
        from paper_translator.legacy.inline_equations import protected_paragraph
        def span(t,font,x,y):
            return {"text":t,"font":font,"bbox":(x,y,x+6,y+8),"origin":(x,y+6)}
        prose=span("The expected return of a policy is computed by summing the rewards over the trajectory. ","Times",0,10)
        summation=span("P","CMEX10",101,10)
        superscript=span("T","CMMI7",107,8)
        subscript=span("0","CMR7",107,15)
        b={"lines":[{"spans":[prose,summation,superscript]},{"spans":[subscript]}]}
        text,parts=protected_paragraph(b)
        self.assertEqual(text.count("[[M0]]"),1)
        self.assertNotIn("PT",text)
        self.assertEqual(parts[0][1],[summation,superscript,subscript])
