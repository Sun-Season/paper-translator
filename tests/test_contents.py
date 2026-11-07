import unittest
from lxml import html
from paper_translator.source.contents import contents_plan,contents_tex


class ContentsTest(unittest.TestCase):
    def test_page_numbers_follow_output_labels(self):
        nodes=html.fragments_fromstring('<h2>APPENDIX CONTENTS</h2><p>A Intro 16</p><p>A.1 Detail . . . . 16</p><p>B Results 20</p><h2>A 引言</h2><p>A.1 详细内容</p><h2>B 结果</h2>')
        plan=contents_plan(nodes)
        self.assertEqual(plan['end'],4)
        self.assertEqual(set(plan['headings']),{4,5,6})
        tex=contents_tex(plan,lambda s:s)
        self.assertIn(r'\pageref{native-sec-A-1}',tex)
        self.assertIn('A.1 详细内容',tex)
        self.assertNotIn('16',tex)
        self.assertNotIn('20',tex)

    def test_incomplete_section_mapping_is_not_published_as_complete_toc(self):
        nodes=html.fragments_fromstring('<h2>CONTENTS</h2><p>A Intro 16</p><p>B Missing 20</p><p>C Last 21</p><h2>A 引言</h2><h2>C 结果</h2>')
        self.assertIsNone(contents_plan(nodes))

    def test_wrapped_and_merged_entries_keep_all_subsections(self):
        nodes=html.fragments_fromstring('<h2>CONTENTS</h2><p>G Prompts 35</p><p>G.1 Navigation . . .\n. . 35 G.2 Judge . . . 35</p><h2>G 提示</h2><h3>G.1 Navigation\nPolicy</h3><h3>G.2 判断器</h3>')
        plan=contents_plan(nodes)
        self.assertEqual([k for k,_ in plan['entries']],['G','G.1','G.2'])
        self.assertEqual(len(plan['headings']),3)
