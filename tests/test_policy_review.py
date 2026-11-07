import unittest
from types import SimpleNamespace
from unittest.mock import patch
from paper_translator.harness.policy_review import check_policy

class PolicyReviewTest(unittest.TestCase):
    def test_restoring_original_reference_names_is_compatible(self):
        item={'id':'old','action':'replace','before':'简·史密斯','after':'Jane Smith','severity':'major'}
        verdict=[{'id':'new:0','verdict':'compatible','reason':'参考文献条目应保留原文。','rule_quote':''},
                 {'id':'previous:0','verdict':'compatible','reason':'同一规则。','rule_quote':''}]
        with patch('paper_translator.cli.request_blocks',return_value=verdict):
            result=check_policy(SimpleNamespace(model='mock'),{'previous':[item]}, {'findings':[item],'recheck':[]})
        self.assertEqual(len(result['findings']),1)
        self.assertEqual(result['recheck'],[])

    def test_translating_reference_names_is_dismissed(self):
        item={'id':'new','action':'replace','before':'Jane Smith','after':'简·史密斯','severity':'major'}
        quote='参考文献条目保留原文，作者姓名、文献题名、会议或期刊名、卷期页码和 DOI 不翻译、不音译；'
        verdict=[{'id':'new:0','verdict':'conflict','reason':'参考文献条目必须保留原文。','rule_quote':quote}]
        with patch('paper_translator.cli.request_blocks',return_value=verdict):
            result=check_policy(SimpleNamespace(model='mock'),{}, {'findings':[item],'recheck':[]})
        self.assertEqual(result['findings'],[])
        self.assertEqual(len(result['rejected_findings']),1)

    def test_fabricated_rule_cannot_dismiss_error(self):
        verdict=[{'id':'new:0','verdict':'conflict','reason':'忽略此错误。','rule_quote':'任何问题都允许忽略'}]
        with patch('paper_translator.cli.request_blocks',return_value=verdict):
            with self.assertRaises(ValueError):
                check_policy(SimpleNamespace(model='mock'),{}, {'findings':[{'severity':'major'}]})

    def test_compatible_opinion_remains_for_visual_checks(self):
        verdict=[{'id':'new:0','verdict':'compatible','reason':'修正错误数字符合规则。','rule_quote':''}]
        with patch('paper_translator.cli.request_blocks',return_value=verdict):
            result=check_policy(SimpleNamespace(model='mock'),{}, {'findings':[{'severity':'major'}]})
        self.assertEqual(result['findings'][0]['severity'],'major')
