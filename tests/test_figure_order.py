import unittest
from lxml import html
from paper_translator.render.vision_latex import figure_order


class FigureOrderTest(unittest.TestCase):
    def test_first_body_reference_controls_submission(self):
        root=html.fromstring("<main><h2>1 引言</h2><p>见图 2。</p><h2>后续章节</h2><figure/><p>图2 示意图。</p><p>正文。</p></main>")
        nodes=list(root)
        order=figure_order(nodes,{3:4})
        self.assertEqual(sorted(order),list(range(len(nodes))))
        self.assertLess(order.index(3),order.index(1))
        self.assertLess(order.index(0),order.index(3))

    def test_unreferenced_figure_keeps_original_position(self):
        nodes=list(html.fromstring("<main><p>图 21 说明。</p><figure/><p>图2 测试。</p></main>"))
        self.assertEqual(figure_order(nodes,{1:2}),[0,1,2])
