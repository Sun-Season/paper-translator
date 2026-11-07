import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from paper_translator.harness.review_contract import request_review, render_evidence

class ReviewContractTests(unittest.TestCase):
    def test_empty_reply_is_retried_not_passed(self):
        request=Mock(side_effect=[[], [{'findings': [], 'recheck': []}]])
        payload={'messages': []}
        self.assertEqual(request_review(None,payload,request)['findings'],[])
        self.assertEqual(request.call_count,2)
        self.assertEqual(payload,{'messages': []})
        self.assertIn('blocks',request.call_args.args[1]['messages'][-1]['content'])

    def test_invalid_action_cannot_enter_execution(self):
        bad={'findings':[{'action':'修正文字','severity':'major','observation':'错译','criterion':'核对原文'}],'recheck':[]}
        answer=request_review(None,{'messages':[]},Mock(return_value=[bad]))
        self.assertEqual(answer['findings'],[])
        self.assertEqual(len(answer['rejected_findings']),1)
        self.assertIn('枚举',answer['rejected_findings'][0]['verification']['reason'])

    def test_incomplete_finding_does_not_discard_whole_review(self):
        bad={'findings':[
            {'action':'replace','severity':'major','observation':'缺 after','criterion':'核对'},
            {'action':'review','severity':'minor','observation':'另一条有效意见','criterion':'核对'}],'recheck':[]}
        answer=request_review(None,{'messages':[]},Mock(return_value=[bad]))
        self.assertEqual(len(answer['findings']),1)
        self.assertEqual(answer['findings'][0]['observation'],'另一条有效意见')
        self.assertEqual(len(answer['rejected_findings']),1)

    def test_rendered_toc_uses_actual_destination_not_source_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'目录重建记录.json').write_text(json.dumps({'headings':{'4':{'id':'A','title':'A 方法','label':'native-sec-A'},'5':{'id':'B','title':'B 实验','label':'native-sec-B'}}}))
            document=Mock()
            document.resolve_names.return_value={'native-sec-A':{'page':17}}
            entries=render_evidence(root,document)['contents']['entries']
            self.assertEqual(entries[0]['output_page'],18)
            self.assertIsNone(entries[1]['output_page'])

    def test_absent_manifest_does_not_claim_toc_was_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(render_evidence(Path(tmp),Mock()),{})

    def test_disconnect_retries_same_request(self):
        import http.client
        from types import SimpleNamespace
        from unittest.mock import patch
        from paper_translator.cli import request_blocks
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.read.return_value=json.dumps({'choices':[{'message':{'content':'{"blocks":[]}'},'finish_reason':'stop'}]})
        with patch('paper_translator.cli.urllib.request.urlopen',side_effect=[http.client.RemoteDisconnected('closed'),response]) as call, patch('paper_translator.cli.time.sleep'):
            self.assertEqual(request_blocks(SimpleNamespace(base_url='https://example.invalid/v1',model='mock'),{'messages':[]}),[])
            self.assertEqual(call.call_count,2)
            self.assertEqual(call.call_args_list[0].args[0].data,call.call_args_list[1].args[0].data)

    def test_source_identity_survives_reflow(self):
        from paper_translator.harness.review_contract import source_ownership, labeled_images
        document=Mock()
        document.resolve_names.return_value={'fig-11':{'page':28},'fig-12':{'page':29}}
        objects=[{'type':'figure','number':'11','page':30},{'type':'figure','number':'12','page':31}]
        records=source_ownership(objects,document)
        self.assertEqual([(r['source_page'],r['output_page']) for r in records],[(30,29),(31,30)])
        labels=['主原稿31','相邻原稿30','成品29','成品30']
        images=[{'type':'image_url','image_url':{'url':str(i)}} for i in range(4)]
        pairs=labeled_images({'image_labels':labels},images)
        self.assertEqual([p['text'] for p in pairs[::2]],labels)
        with self.assertRaises(ValueError):
            labeled_images({'image_labels':labels},images[:2])

    def test_image_location_uses_pixels_not_filename_order(self):
        import pymupdf
        from PIL import Image
        from paper_translator.harness.review_contract import image_placements
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'figures').mkdir()
            path=root/'figures/page-0002-03.png'
            Image.new('RGB',(20,10),(50,70,90)).save(path)
            with pymupdf.open() as doc:
                page=doc.new_page();page.insert_image(pymupdf.Rect(100,200,120,210),filename=str(path))
                rows=image_placements(root,doc,2)
                self.assertEqual(rows[0]['output_page'],1)
                self.assertEqual(rows[0]['box'],[100,200,120,210])
                self.assertEqual(image_placements(root,doc,3),[])
