import unittest
from paper_translator.harness.visual_agent import locate_quote

class QuoteLocationTest(unittest.TestCase):
    def test_pdf_line_wrap_can_be_located_without_changing_math(self):
        text='前文。原稿中的 $x_t$\n表示当前状态。后文。'
        self.assertEqual(locate_quote(text,'原稿中的 $x_t$ 表示当前状态。'),('原稿中的 $x_t$\n表示当前状态。',None))
    def test_duplicates_are_rejected(self):
        self.assertIsNone(locate_quote('当前状态。当前 状态。','当前\n状态。')[0])
    def test_symbol_or_content_change_is_not_fuzzy_matched(self):
        self.assertIsNone(locate_quote('$x_t$ 表示状态','$x_1$ 表示状态')[0])
        self.assertIsNone(locate_quote('不是全部','是全部内容')[0])

class AdjacentMathTest(unittest.TestCase):
    def test_formula_before_number_is_parsed_as_math(self):
        import pypandoc
        from paper_translator.render.vision_latex import normalize_adjacent_math
        text=r"标记 $^\dagger$360 个"
        output=pypandoc.convert_text(normalize_adjacent_math(text),"html5",
                                    format="markdown-raw_html-raw_tex",extra_args=["--mathjax"])
        self.assertIn('class="math inline"',output)
        self.assertIn('360',output)

    def test_currency_and_ordinary_math_unchanged(self):
        from paper_translator.render.vision_latex import normalize_adjacent_math
        text=r"价格 $5$20；公式 $x_t$ 结束"
        self.assertEqual(normalize_adjacent_math(text),text)

class EvidenceBoundaryTest(unittest.TestCase):
    def test_line_end_hyphen_can_be_a_compound_or_word_break(self):
        from paper_translator.harness.visual_agent import supported_quote
        self.assertTrue(supported_quote('current-frame-only by 27.4', 'current-\nframe-only by 27.4'))
        self.assertTrue(supported_quote('navigation succeeds', 'navi-\ngation succeeds'))
        self.assertFalse(supported_quote('current-frame-only by 28.4', 'current-\nframe-only by 27.4'))

    def test_neighbor_owner_requires_exact_source_and_draft(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import pymupdf
        from paper_translator.harness.visual_agent import apply_proposals
        with TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.pdf'
            with pymupdf.open() as doc:
                doc.new_page().insert_text((40,40),'Different statement')
                doc.new_page().insert_text((40,40),'three of four policies')
                doc.save(source)
            (root/'paper.md').write_text('<!-- 原稿第 1 页 -->\n其他内容。\n<!-- 原稿第 2 页 -->\n四种策略显著。')
            finding=dict(id='test',source_page=1,source_quote='three of four policies',
                         before='四种策略显著。',after='四种策略中的三种显著。',action='replace',criterion='数量准确',output_page=2)
            result=apply_proposals(source,root,[finding])[0]
            self.assertTrue(result['applied'])
            self.assertEqual(result['source_page'],2)
            self.assertEqual(result['reported_source_page'],1)

class StructuralRepairTest(unittest.TestCase):
    def test_comment_paragraph_keeps_algorithm_identity(self):
        from lxml import html
        from paper_translator.render.ruled_algorithm import match_rows
        nodes=[html.fromstring(s) for s in ['<p>Algorithm 1 Example</p>', '<p>1: Update</p>', '<p>▷ first alarm</p>', '<p>2: Return</p>']]
        spec={'indent':{1:0,2:0}}
        groups=match_rows(nodes,[0]*4,{(0,'1'):spec})
        self.assertEqual(groups[0][1],[1,2,3])

    def test_empty_set_variant_is_supported(self):
        from paper_translator.render.vision_latex import math_tex
        self.assertEqual(math_tex(r'H_t^{(\varnothing)}'),r'H_t^{(\varnothing)}')
