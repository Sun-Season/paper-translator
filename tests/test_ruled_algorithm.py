import unittest
from lxml import html
from ruled_algorithm import match_rows,typeset


class AlgorithmTest(unittest.TestCase):
    def test_block_stops_after_last_step(self):
        nodes=list(html.fromstring(r"<main><h3>Algorithm 1 测试</h3><p>Require: 输入</p><p>1: for</p><p>2: \quad 执行 式（3）</p><p>正文</p></main>"))
        spec={"indent":{1:0,2:14},"rules":[.8,.4,.4],"refs":{2:"3"},"gutter":18}
        num,rows,_=match_rows(nodes,[0]*5,{(0,"1"):spec})[0]
        self.assertEqual(rows,[1,2,3])
        tex=typeset(nodes[0],nodes,rows,spec,num,lambda n:n.text_content(),{"eq-3"})
        self.assertEqual(tex.count(r"\hrule"),3)
        self.assertNotIn(r"\quad",tex)
        self.assertIn(r"\hspace*{14.00bp}",tex)
        self.assertEqual(tex.count("式（3）"),1)
        self.assertIn(r"\hyperlink{eq-3}",tex)
        self.assertNotIn("正文",tex)
