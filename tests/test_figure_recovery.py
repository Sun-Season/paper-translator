import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pymupdf as pdf

from paper_translator.source.figure_groups import figure_box, restore_placeholder_figures, strip_figure_text, ensure_missing_figures, normalize_figure_html, strip_label_dumps
from paper_translator.render.ruled_algorithm import normalize_algorithm_blocks
from paper_translator.translation.glyphs import strip_pictographs


class FigureRecoveryTest(unittest.TestCase):
    def source(self, root):
        path = root / "source.pdf"
        with pdf.open() as doc:
            page = doc.new_page(width=600, height=800)
            page.insert_text((60, 80), "Body text above the figure at normal size.", fontsize=10)
            page.draw_rect(pdf.Rect(100, 120, 400, 300), color=(0, 0, 0))
            page.insert_text((100, 330), "Figure 2: A test figure caption.", fontsize=10)
            doc.save(path)
        return path

    def test_caption_box_recovers_figure(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); source = self.source(root)
            with pdf.open(source) as doc:
                box = figure_box(doc[0], "2")
            self.assertIsNotNone(box)
            self.assertLess(box.y0, 120)
            self.assertGreater(box.y1, 300)

    def test_placeholder_image_becomes_real_figure(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); source = self.source(root)
            draft = "<!-- 原稿第 1 页 -->\n\n![Figure 2](figure_2)\n\n图 2：测试图。\n\n正文。"
            fixed, records = restore_placeholder_figures(draft, source, root)
            self.assertIn("figures/page-0001-figure-2.png", fixed)
            self.assertNotIn("figure_2", fixed)
            self.assertTrue((root / "figures/page-0001-figure-2.png").is_file())
            self.assertEqual(records[0]["figure"], "2")

    def test_caption_without_image_gets_recovered_figure(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); source = self.source(root)
            draft = "<!-- 原稿第 1 页 -->\n\n图 2：测试图。\n\n正文。"
            fixed, records = restore_placeholder_figures(draft, source, root)
            self.assertIn("![图 2](figures/page-0001-figure-2.png)", fixed)
            self.assertTrue((root / "figures/page-0001-figure-2.png").is_file())
            self.assertEqual(records[0]["figure"], "2")

    def test_missing_caption_leaves_placeholder(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); source = self.source(root)
            draft = "<!-- 原稿第 1 页 -->\n\n![Figure 9](figure_9)\n"
            fixed, records = restore_placeholder_figures(draft, source, root)
            self.assertEqual(records, [])
            self.assertIn("figure_9", fixed)


class FigureTextTest(unittest.TestCase):
    def test_duplicated_figure_text_is_removed_but_title_and_table_kept(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source.pdf"
            with pdf.open() as doc:
                page = doc.new_page(width=600, height=800)
                page.insert_text((60, 40), "A Paper Title", fontsize=16)
                page.draw_rect(pdf.Rect(100, 120, 400, 300), color=(0, 0, 0))
                page.insert_text((110, 200), "Instruction: walk forward past the table and chairs,", fontsize=9)
                page.insert_text((110, 215), "then turn left and stop by the door.", fontsize=9)
                page.insert_text((100, 330), "Figure 1: A test figure caption.", fontsize=10)
                page.insert_text((60, 500), "Body paragraph of the paper.", fontsize=10)
                doc.save(source)
            draft = ("<!-- 原稿第 1 页 -->\n\n# A Paper Title\n\n"
                     "![图 1](figures/x.png)\n\n图 1：测试图。\n\n"
                     "Instruction: walk forward past the table and chairs, then turn left and stop by the door.\n\n正文段落。")
            fixed, removed = strip_figure_text(draft, source)
            self.assertEqual(len(removed), 1)
            self.assertNotIn("Instruction:", fixed)
            self.assertIn("# A Paper Title", fixed)
            self.assertIn("正文段落", fixed)


class FigureHtmlTest(unittest.TestCase):
    def test_html_figure_caption_becomes_plain_caption(self):
        draft = ("<!-- 原稿第 1 页 -->\n\n<figure>\n<figcaption>图 5：报警结果。</figcaption>\n</figure>\n\n正文。")
        fixed = normalize_figure_html(draft)
        self.assertIn("图 5：报警结果。", fixed)
        self.assertNotIn("<figcaption>", fixed)
        self.assertIn("正文。", fixed)


class LabelDumpTest(unittest.TestCase):
    def test_pipe_label_dump_is_removed_but_formula_kept(self):
        draft = ("<!-- 原稿第 1 页 -->\n\n正文。\n\n"
                 "alpha | beta | gamma | delta | one | two | three | four\n\n"
                 "$$a|b|c|d|e|f|g \\frac{1}{2}$$")
        fixed, removed = strip_label_dumps(draft)
        self.assertEqual(len(removed), 1)
        self.assertNotIn("alpha | beta", fixed)
        self.assertIn("\\frac{1}{2}", fixed)


class MissingObjectTest(unittest.TestCase):
    def test_source_figure_absent_from_draft_is_added(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source.pdf"
            with pdf.open() as doc:
                page = doc.new_page(width=600, height=800)
                page.draw_rect(pdf.Rect(100, 120, 400, 300), color=(0, 0, 0))
                page.insert_text((100, 330), "Figure 2: A test figure caption.", fontsize=10)
                doc.save(source)
            draft = "<!-- 原稿第 1 页 -->\n\n图 2 展示了结果。\n\n正文。"
            fixed, added = ensure_missing_figures(draft, source, root)
            self.assertEqual(len(added), 1)
            self.assertIn("![图 2](figures/page-0001-figure-2.png)", fixed)
            self.assertIn("图 2：", fixed)
            self.assertTrue((root / "figures/page-0001-figure-2.png").is_file())

    def test_existing_caption_is_not_duplicated(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source.pdf"
            with pdf.open() as doc:
                page = doc.new_page(width=600, height=800)
                page.draw_rect(pdf.Rect(100, 120, 400, 300), color=(0, 0, 0))
                page.insert_text((100, 330), "Figure 2: A test figure caption.", fontsize=10)
                doc.save(source)
            draft = "<!-- 原稿第 1 页 -->\n\n图 2：已有图。\n"
            fixed, added = ensure_missing_figures(draft, source, root)
            self.assertEqual(added, [])
            self.assertEqual(fixed, draft)

    def test_algorithm_steps_become_separate_paragraphs(self):
        draft = ("<!-- 原稿第 1 页 -->\n\n**算法 1** 测试\n\n1: 第一步\n2: 第二步\n3: 第三步\n")
        fixed = normalize_algorithm_blocks(draft)
        self.assertIn("1: 第一步\n\n2: 第二步\n\n3: 第三步", fixed)


class GlyphTest(unittest.TestCase):
    def test_pictographs_removed_and_dingbats_kept(self):
        text, removed = strip_pictographs("🧑‍🏫 教师；🏫 学校；✓ 通过；✗ 失败")
        self.assertNotIn("🧑", text)
        self.assertNotIn("🏫", text)
        self.assertIn("✓", text)
        self.assertIn("✗", text)
        self.assertIn("教师", text)
        self.assertEqual(set(removed), {"🏫", "🧑", "\u200d"})
