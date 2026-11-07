import unittest
from paper_translator.cli import boundary_hint


class BoundaryHintTest(unittest.TestCase):
    def test_no_contributor_section_after_finished_page(self):
        self.assertEqual(boundary_hint("The policy is robust.","8 Contributions\nCore Contributors"),"")
        self.assertEqual(boundary_hint("across several","References\nA. Author"),"")

    def test_first_sentence_only(self):
        hint=boundary_hint("We evaluated three","models in simulation. This heading and new topic must stay on the new page.")
        self.assertIn("models in simulation.",hint)
        self.assertNotIn("new topic",hint)

    def test_hyphenated_page_break_keeps_hint(self):
        hint=boundary_hint("Starting from the training recipe for a general-\narXiv:2511.14759v2  [cs.LG]  19 Nov 2025\n",
                           "Fig. 2: Some tasks\npurpose VLA and training on diverse data.")
        self.assertIn("general-",hint)
        self.assertIn("mid-word",hint)
