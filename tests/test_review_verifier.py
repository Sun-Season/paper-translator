import unittest
from types import SimpleNamespace
from unittest.mock import patch
from paper_translator.harness.review_verifier import verify_review


class ReviewVerifierTest(unittest.TestCase):
    def test_rejected_opinion_is_recorded_and_not_executed(self):
        raw={'findings':[{'observation':'摘要不应该翻译','severity':'major','action':'replace','before':'中文摘要','after':'English abstract'}]}
        verdict=[{'id':0,'verdict':'no_error','reason':'任务要求中文摘要，成品符合要求。'}]
        with patch('paper_translator.cli.request_blocks',return_value=verdict):
            result=verify_review(SimpleNamespace(model='mock'),{'draft':'中文摘要','previous':[],'image_labels':[]},[],raw)
        self.assertEqual(result['findings'],[])
        self.assertEqual(result['rejected_findings'][0]['verification']['verdict'],'no_error')

    def test_uncertainty_remains_blocking(self):
        raw={'findings':[{'observation':'公式疑似缺字','severity':'minor','action':'replace'}]}
        with patch('paper_translator.cli.request_blocks',return_value=[{'id':0,'verdict':'insufficient_evidence','reason':'需要更清晰的公式局部图。'}]):
            result=verify_review(SimpleNamespace(model='mock'),{'draft':'公式','previous':[],'image_labels':[]},[],raw)
        self.assertEqual(result['findings'][0]['severity'],'major')
        self.assertEqual(result['findings'][0]['action'],'review')

    def test_missing_verdict_cannot_pass(self):
        with patch('paper_translator.cli.request_blocks',return_value=[]):
            with self.assertRaises(ValueError):
                verify_review(SimpleNamespace(model='mock'),{'draft':'正文','previous':[],'image_labels':[]},[],{'findings':[{'observation':'问题'}]})

    def test_unrelated_recheck_ids_do_not_create_previous_issues(self):
        verdict=[{'id':0,'verdict':'no_error','reason':'译文准确。'},
                 {'id':'recheck','checks':[{'id':'invented','status':'resolved','evidence':'无关项目'}]}]
        with patch('paper_translator.cli.request_blocks',return_value=verdict):
            result=verify_review(SimpleNamespace(model='mock'),{'draft':'正文','previous':[],'image_labels':[]},[],{'findings':[{'observation':'问题'}]})
        self.assertEqual(result['recheck'],[])
        self.assertEqual(result['findings'],[])

    def test_multiline_evidence_must_exist_in_source_order(self):
        from paper_translator.harness.visual_agent import supported_quote
        self.assertTrue(supported_quote('4 EXPERIMENTS\n4.1 SETUP','4 EXPERIMENTS\n正文\n4.1 SETUP'))
        self.assertFalse(supported_quote('4.1 SETUP\n4 EXPERIMENTS','4 EXPERIMENTS\n4.1 SETUP'))
        self.assertFalse(supported_quote('4 EXPERIMENTS\n5 INVENTED','4 EXPERIMENTS\n4.1 SETUP'))

    def test_partial_verdict_is_retried_with_evidence_and_missing_ids(self):
        good=[{'id':0,'verdict':'no_error','reason':'译文准确。'}]
        with patch('paper_translator.cli.request_blocks',side_effect=[[],good]) as call:
            result=verify_review(SimpleNamespace(model='mock'),{'draft':'正文','previous':[],'image_labels':[]},[],{'findings':[{'observation':'疑点'}]})
        self.assertEqual(result['findings'],[])
        self.assertEqual(call.call_count,2)
        self.assertIn('required_finding_ids',call.call_args.args[1]['messages'][-1]['content'])

    def test_object_destination_supplements_similar_caption_mapping(self):
        from paper_translator.harness.visual_agent import mapped_pages
        class Page:
            def __init__(self,text):self.text=text
            def get_text(self):return self.text
        class Output(list):
            def resolve_names(self):return {'fig-12':{'page':1}}
        output=Output([Page('相同的图注内容'),Page('完全不同的内容')])
        result=mapped_pages(['相同的图注内容'],output,[{'type':'figure','number':'12','page':1}])
        self.assertIn(1,result[0])

    def test_verifier_cannot_reintroduce_unknown_action(self):
        bad=[{'id':0,'verdict':'confirmed_error','repair_safe':True,'reason':'发现错误。','repair':{'action':'随意修改'}}]
        good=[{'id':0,'verdict':'no_error','reason':'重新核对成品后无误。'}]
        with patch('paper_translator.cli.request_blocks',side_effect=[bad,good]) as call:
            result=verify_review(SimpleNamespace(model='mock'),{'draft':'正文','previous':[],'image_labels':[]},[],{'findings':[{'observation':'疑点'}]})
        self.assertEqual(call.call_count,2)
        self.assertEqual(result['findings'],[])

    def test_unsafe_replacement_is_not_executable(self):
        raw={'findings':[{'observation':'条目错误','severity':'major','action':'replace','before':'作者甲','after':'作者乙'}]}
        verdict=[{'id':0,'verdict':'confirmed_error','repair_safe':False,'reason':'建议替换成了其他参考文献，缺少依据。'}]
        with patch('paper_translator.cli.request_blocks',return_value=verdict) as call:
            result=verify_review(SimpleNamespace(model='mock'),{'draft':'作者甲','previous':[],'image_labels':[]},[],raw)
        self.assertEqual(result['findings'][0]['action'],'review')
        self.assertIn('作者乙',call.call_args.args[1]['messages'][1]['content'][0]['text'])

    def test_pdf_hyphenation_quotes_and_ligatures_are_evidence(self):
        from paper_translator.harness.visual_agent import supported_quote
        self.assertTrue(supported_quote("oracle's 35.0% continuations rather than recovery",'oracle’s 35.0% contin-\nuations rather than recovery'))
        self.assertTrue(supported_quote('first findings','ﬁrst ﬁndings'))
        self.assertFalse(supported_quote("oracle's 36.0% continuations",'oracle’s 35.0% contin-\nuations'))
        self.assertFalse(supported_quote('recovery rather than continuations','continuations rather than recovery'))
