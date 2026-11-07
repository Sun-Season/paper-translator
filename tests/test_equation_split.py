import unittest
from paper_translator.render.equation_split import split_equation, tokens


class EquationSplitTest(unittest.TestCase):
    def test_split_preserves_tokens(self):
        value = r"a = b + c \geq d, e"
        split = split_equation(value, width_em=3)
        self.assertIn("aligned", split)
        self.assertEqual(tokens(value), tokens(split))

    def test_formula_without_break_points_is_not_split(self):
        self.assertIsNone(split_equation(r"\frac{a}{b}"))
