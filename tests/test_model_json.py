import unittest
from paper_translator.harness.model_json import decode_model_json


class ModelJsonTest(unittest.TestCase):
    def test_unescaped_math_does_not_become_control_characters(self):
        self.assertEqual(decode_model_json(r'{"value":"$\frac{a}{b}+\theta+\alpha$"}')['value'],r'$\frac{a}{b}+\theta+\alpha$')

    def test_valid_json_escapes_are_preserved(self):
        self.assertEqual(decode_model_json(r'{"value":"line\nnext\tword \\frac \u03b1"}')['value'],'line\nnext\tword \\frac α')

    def test_missing_structure_is_not_invented(self):
        with self.assertRaises(ValueError):decode_model_json('{"value":"test"')
