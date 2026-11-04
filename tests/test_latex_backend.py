import unittest
from paper_translator.render.latex_backend import escape

class LatexBackendTest(unittest.TestCase):
    def test_source_text_cannot_introduce_tex_commands(self):
        self.assertEqual(escape(r'100% & x_1 \input{a}'),r'100\% \& x\_1 \textbackslash{}input\{a\}')
