import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from paper_translator.cli import request_blocks
from paper_translator.translation.prose_language import check_page, normalized, suspect, translate_gaps


class TranslationRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(model='mock', base_url='https://example.invalid', target='zh')

    def test_invalid_math_escape_is_recovered_without_model_retry(self):
        contents = [r'{"blocks":[{"md":"$\alpha$"}]}', json.dumps({'blocks': [{'md': r'$\alpha$'}]})]
        responses = [io.BytesIO(json.dumps({'choices': [{'message': {'content': s}, 'finish_reason': 'stop'}]}).encode()) for s in contents]
        with patch('urllib.request.urlopen', side_effect=responses) as request, patch('time.sleep'):
            self.assertEqual(request_blocks(self.args, {'messages': []}), [{'md': r'$\alpha$'}])
        self.assertEqual(request.call_count, 1)

    def test_extra_digits_trigger_retry(self):
        responses = [[{'md': '在33D环境中'}], [{'md': '在<KEEP_0>D环境中'}]]
        with patch('paper_translator.cli.request_blocks', side_effect=responses) as request:
            self.assertEqual(translate_gaps(self.args, 'in 3D environment'), '在3D环境中')
        self.assertEqual(request.call_count, 2)

    def test_protected_values_can_follow_chinese_word_order(self):
        with patch('paper_translator.cli.request_blocks', return_value=[{'md': '第<KEEP_1>节给出了<KEEP_0>。'}]):
            self.assertEqual(translate_gaps(self.args, '$x$ is given in Section 3.'), '第3节给出了$x$。')

    def test_literal_template_is_not_untranslated_prose(self):
        self.assertFalse(suspect('指令为 *Walk to the <category> and stop by it.*，保持模板。'))
        self.assertTrue(suspect('This policy is evaluated on the unseen environments with several navigation tasks.'))

    def test_unproven_same_page_duplicate_is_translated_not_deleted(self):
        source = 'The agent follows the route and reaches the target in this environment.'
        replies = [[{'id': 0, 'action': 'duplicate', 'md': '', 'evidence': '没有出现过的译文'}], [{'md': '智能体沿路径行进，并在该环境中到达目标。'}]]
        with tempfile.TemporaryDirectory() as cache, patch.dict(os.environ, {'PAPER_JOB_DIR': cache}), patch('paper_translator.cli.request_blocks', side_effect=replies):
            value, records = check_page(source, 0, [' ' + normalized(source) + ' '], {0: source}, self.args)
        self.assertIn('到达目标', value)
        self.assertEqual(records[0]['action'], 'translate')

    def test_math_percentage_is_escaped_and_unsafe_commands_rejected(self):
        from paper_translator.render.vision_latex import math_tex
        for value in (r'13.1\%', r'a\gets b', r'\lceil x\rceil', r'x^\dagger'):
            self.assertEqual(math_tex(value), value)
        for value in ('13.1%', r'\input{evil}'):
            with self.assertRaises(ValueError):
                math_tex(value)

    def test_malformed_json_is_repaired_without_repeating_visual_review(self):
        bad='{"blocks":[{"md":"text" "id":1}]}'
        good=json.dumps({'blocks':[{'md':'text','id':1}]})
        responses=[io.BytesIO(json.dumps({'choices':[{'message':{'content':v},'finish_reason':'stop'}]}).encode()) for v in (bad,good)]
        args=SimpleNamespace(model='qwen3-vl-plus',base_url='https://example.invalid')
        with patch('urllib.request.urlopen',side_effect=responses) as request,patch('time.sleep'):
            self.assertEqual(request_blocks(args,{'messages':[],'enable_thinking':True}),[{'md':'text','id':1}])
        sent=json.loads(request.call_args.args[0].data)
        self.assertFalse(sent['enable_thinking'])
        self.assertEqual(sent['response_format'],{'type':'json_object'})
        self.assertIn(bad,sent['messages'][-1]['content'])
