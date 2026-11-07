import tempfile,unittest
from unittest.mock import patch
from pathlib import Path
import json
from paper_translator.harness.request_budget import update

class BudgetTest(unittest.TestCase):
    def test_resume_does_not_reset_budget(self):
        with tempfile.TemporaryDirectory() as root,patch.dict('os.environ',{'PAPER_TASK_ROOT':root,'PAPER_MAX_API_CALLS':'2'}):
            update('reserve');update('reserve')
            with self.assertRaises(ValueError):update('reserve')
            update('usage',{'prompt_tokens':10,'completion_tokens':4})
            self.assertEqual(json.loads((Path(root)/'请求用量.json').read_text())['calls'],2)

    def test_permission_error_stops_subsequent_calls(self):
        with tempfile.TemporaryDirectory() as root,patch.dict('os.environ',{'PAPER_TASK_ROOT':root}):
            update('reserve');update('halt','HTTP 402')
            with self.assertRaisesRegex(ValueError,'402'):update('reserve')
