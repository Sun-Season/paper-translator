from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import pymupdf
from paper_translator.source.original_tables import original_table_assets, table_regions


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


    def test_caption_below_colored_table_in_same_text_block_uses_original_asset(self):
        with TemporaryDirectory() as directory, pymupdf.open() as doc:
            path = Path(directory) / "original.pdf"
            page = doc.new_page()
            page.insert_text((45, 95), "Method  Result\nAlpha  10\nBeta  20\nTable 1: Comparison", fontsize=10)
            block, = page.get_text("dict")["blocks"]
            header, alpha, _, caption = [pymupdf.Rect(line["bbox"]) for line in block["lines"]]
            for y in (header.y0 - 2, header.y1 + .5, caption.y0 - 1):
                page.draw_line((40, y), (185, y))
            highlight = pymupdf.Rect(70, alpha.y0, 101, alpha.y1 - 1)
            page.draw_rect(highlight, color=None, fill=(.85, .94, .83), overlay=False)
            region = table_regions(page)["1"]
            self.assertTrue(region.contains(highlight))
            self.assertNotIn("Comparison", page.get_textbox(region))
            doc.save(path)

            draft = "<!-- 原稿第 1 页 -->\n\n| Method | Result |\n| --- | --- |\n| Alpha | 10 |\n\n表 1：结果比较"
            updated, assets = original_table_assets(draft, path)
            self.assertEqual(set(assets), {"source-table-1.png"})
            self.assertIn("表 1：结果比较", updated)
            self.assertNotIn("| Method", updated)

    def test_nearby_same_width_tables_with_different_caption_positions_are_separate(self):
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((44, 131), "Table 1: First result")
            page.insert_text((44, 151), "Table 2: Second result")
            for top, label in ((60, "first body"), (157, "second body")):
                for offset in (0, 13, 54):
                    page.draw_line((40, top + offset), (330, top + offset))
                page.insert_text((44, top + 30), label)
            regions = table_regions(page)
            self.assertEqual(set(regions), {"1", "2"})
            self.assertEqual(page.get_textbox(regions["1"]).strip(), "first body")
            self.assertEqual(page.get_textbox(regions["2"]).strip(), "second body")

    def test_stacked_tables_with_captions_above_are_both_detected(self):
        # 表题在表上方；表 2 的表题离表 1 底边不足 24pt，两个方向都成立。
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((44, 60), "Table 1: First result")
            for y in (72, 85, 132):
                page.draw_line((40, y), (330, y))
            page.insert_text((44, 110), "first body")
            page.insert_text((44, 146), "Table 2: Second result")
            for y in (172, 185, 232):
                page.draw_line((40, y), (330, y))
            page.insert_text((44, 210), "second body")
            regions = table_regions(page)
            self.assertEqual(set(regions), {"1", "2"})
            self.assertEqual(page.get_textbox(regions["1"]).strip(), "first body")
            self.assertEqual(page.get_textbox(regions["2"]).strip(), "second body")

    def test_stacked_tables_with_captions_below_are_both_detected(self):
        # 表题在表下方；表 1 的表题离表 2 顶边不足 24pt，两个方向都成立。
        with pymupdf.open() as doc:
            page = doc.new_page()
            for top, label in ((60, "first body"), (160, "second body")):
                for y in (top, top + 13, top + 60):
                    page.draw_line((40, y), (330, y))
                page.insert_text((44, top + 30), label)
            page.insert_text((44, 134), "Table 1: First result")
            page.insert_text((44, 234), "Table 2: Second result")
            regions = table_regions(page)
            self.assertEqual(set(regions), {"1", "2"})
            self.assertEqual(page.get_textbox(regions["1"]).strip(), "first body")
            self.assertEqual(page.get_textbox(regions["2"]).strip(), "second body")

    def test_duplicate_caption_numbers_keep_the_first_table(self):
        # 双语原稿会把同一张表的表题写两遍；同号不能把整张表丢掉。
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((44, 60), "Table 1: First result")
            for y in (72, 85, 132):
                page.draw_line((40, y), (330, y))
            page.insert_text((44, 110), "body")
            page.insert_text((44, 146), "Table 1: Same table again")
            regions = table_regions(page)
            self.assertEqual(set(regions), {"1"})
            self.assertEqual(page.get_textbox(regions["1"]).strip(), "body")

    def test_side_by_side_tables_with_slightly_overlapping_borders_are_separate(self):
        # 两栏并排表格的横线常互相探出十几点，不能当成同一张表而丢弃后一张。
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((44, 60), "Table 1: Left")
            page.insert_text((304, 60), "Table 2: Right")
            for x0, x1, label in ((40, 310, "left body"), (300, 560, "right body")):
                for y in (72, 85, 132):
                    page.draw_line((x0, y), (x1, y))
                page.insert_text((44 if x0 == 40 else 304, 110), label)
            regions = table_regions(page)
            self.assertEqual(set(regions), {"1", "2"})
            self.assertIn("left body", page.get_textbox(regions["1"]))
            self.assertIn("right body", page.get_textbox(regions["2"]))
