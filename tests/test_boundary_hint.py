import unittest
from translate import boundary_hint


class BoundaryHintTest(unittest.TestCase):
    def test_no_contributor_section_after_finished_page(self):
        self.assertEqual(boundary_hint("The policy is robust.","8 Contributions\nCore Contributors"),"")
        self.assertEqual(boundary_hint("across several","References\nA. Author"),"")

    def test_first_sentence_only(self):
        hint=boundary_hint("We evaluated three","models in simulation. This heading and new topic must stay on the new page.")
        self.assertIn("models in simulation.",hint)
        self.assertNotIn("new topic",hint)
