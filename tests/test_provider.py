import unittest
from unittest.mock import patch
from paper_translator.config.provider import api_key

class ProviderTest(unittest.TestCase):
    def test_deepseek_uses_its_own_key(self):
        with patch.dict('os.environ',{'DEEPSEEK_API_KEY':'deepseek-test','OPENAI_API_KEY':'other-test'}):
            self.assertEqual(api_key('https://api.deepseek.com/v1'),'deepseek-test')
            self.assertEqual(api_key('https://other.example/v1'),'other-test')

    def test_deepseek_does_not_fall_back_to_other_provider_key(self):
        with patch.dict('os.environ',{'OPENAI_API_KEY':'other-test'},clear=True),patch('paper_translator.config.provider.dotenv_values',return_value={}):
            self.assertIsNone(api_key('https://api.deepseek.com'))

    def test_truncation_retries_with_larger_output_limit(self):
        import io,json
        from types import SimpleNamespace
        from paper_translator.cli import request_blocks
        first=io.StringIO(json.dumps({'choices':[{'finish_reason':'length','message':{'content':''}}]}))
        second=io.StringIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"blocks":[]}'}}]}))
        with patch('paper_translator.config.provider.api_key',return_value='test'),patch('paper_translator.cli.urllib.request.urlopen',side_effect=[first,second]) as call:
            self.assertEqual(request_blocks(SimpleNamespace(base_url='https://api.deepseek.com',model='deepseek-flash'),{'model':'deepseek-flash','messages':[]}),[])
        self.assertEqual(call.call_count,2)
        limits=[json.loads(c.args[0].data)['max_tokens'] for c in call.call_args_list]
        self.assertEqual(limits,[8192,16384])
        sent=json.loads(call.call_args_list[0].args[0].data)
        self.assertEqual(sent['thinking'],{'type':'disabled'})
        self.assertEqual(sent['response_format'],{'type':'json_object'})

    def test_repeated_truncation_stops_instead_of_looping(self):
        import io,json
        from types import SimpleNamespace
        from paper_translator.cli import request_blocks
        body=json.dumps({'choices':[{'finish_reason':'length','message':{'content':''}}]})
        with patch('paper_translator.config.provider.api_key',return_value='test'),patch('paper_translator.cli.urllib.request.urlopen',side_effect=[io.StringIO(body),io.StringIO(body)]) as call:
            with self.assertRaises(RuntimeError):
                request_blocks(SimpleNamespace(base_url='https://api.deepseek.com',model='deepseek-flash'),{'model':'deepseek-flash','messages':[]})
        self.assertEqual(call.call_count,2)
