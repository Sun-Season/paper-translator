import unittest
import pymupdf
from paper_translator.source.original_tables import table_regions


class OriginalTableTest(unittest.TestCase):
    def test_each_caption_gets_its_own_table_body(self):
        with pymupdf.open() as doc:
            page=doc.new_page()
            for number,top in ((6,80),(7,215)):
                page.insert_text((40,top),f"Table {number} Performance comparison")
                for y in (top+12,top+28,top+90):
                    page.draw_line((40,y),(520,y))
                page.insert_text((45,top+55),f"sample {number}")
            regions=table_regions(page)
            self.assertEqual(set(regions),{"6","7"})
            for number in ("6","7"):
                self.assertEqual(page.get_textbox(regions[number]).strip(),"sample "+number)
