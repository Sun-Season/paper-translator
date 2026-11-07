import unittest
import pymupdf
from paper_translator.harness.contents_audit import audit_contents, invalid_page_correction

class ContentsAuditTest(unittest.TestCase):
    def test_displayed_number_must_match_actual_target(self):
        with pymupdf.open() as doc:
            doc.new_page();doc.new_page()
            page=doc[0]
            page.insert_text((50,70),'A Intro');page.insert_text((300,70),'2')
            page.insert_link({'kind':pymupdf.LINK_GOTO,'from':pymupdf.Rect(48,57,100,75),'page':1})
            page.insert_link({'kind':pymupdf.LINK_GOTO,'from':pymupdf.Rect(298,57,310,75),'page':1})
            page=doc.reload_page(page)
            rows=audit_contents(doc,[{'id':'A','title':'A Intro','output_page':2}])
            self.assertEqual(len(rows),1)
            self.assertEqual(audit_contents(doc,[{'id':'A','title':'A Intro','output_page':3}]),[])
            self.assertIsNotNone(invalid_page_correction({'before':'A Intro ..... 2','after':'A Intro ..... 20'},rows))
            self.assertIsNone(invalid_page_correction({'before':'A Intro ..... 2','after':'A Other ..... 20'},rows))
