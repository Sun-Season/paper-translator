import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pymupdf as pdf
from paper_translator.harness.layout_audit import layout_issues
from paper_translator.harness.job_runtime import Job
from paper_translator.harness.visual_agent import visual_export
from paper_translator.source.original_tables import table_regions


class LayoutGateTest(unittest.TestCase):
    def test_real_paint_outside_page_is_detected_without_tex_log(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            with pdf.open() as doc:
                p=doc.new_page(width=200,height=200)
                p.draw_rect(pdf.Rect(50,190,90,225),fill=(0,0,0))
                doc.save(root/'paper.pdf')
            self.assertIn('paint_outside_page',[i['code'] for i in layout_issues(root)])

    def test_tex_overflow_is_blocking_even_inside_paper_margins(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            with pdf.open() as doc:
                doc.new_page().insert_text((50,50),'Valid page')
                doc.save(root/'paper.pdf')
            self.assertEqual(layout_issues(root),[])
            (root/'LaTeX版式检查.txt').write_text(r'Overfull \hbox (12.0pt too wide) in paragraph')
            self.assertEqual(layout_issues(root)[0]['code'],'latex_overflow')

    def test_publish_rechecks_geometry(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.pdf';source.write_bytes(b'source')
            with self.assertRaisesRegex(ValueError,'阻止发布'):
                with Job(source,root/'output',SimpleNamespace()) as job:
                    with pdf.open() as doc:
                        p=doc.new_page(width=200,height=200);p.draw_rect(pdf.Rect(50,190,90,225),fill=(0,0,0));doc.save(job.stage/'paper.pdf')
                    job.publish()
            self.assertFalse((root/'output').exists())

    def test_narrow_side_by_side_tables_are_identified(self):
        with pdf.open() as doc:
            p=doc.new_page(width=600,height=800)
            for number,x in enumerate((100,240,380),1):
                p.insert_text((x,80),f'Table {number}: Results',fontsize=9)
                for y in (90,105,140):p.draw_line((x,y),(x+110,y))
            self.assertEqual(set(table_regions(p)),{'1','2','3'})

    def test_stalled_second_round_does_not_end_repair_loop(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'stage';stage.mkdir();source=root/'source.pdf'
            with pdf.open() as doc:
                doc.new_page().insert_text((40,60),'The original statement.');doc.save(source)
            (stage/'paper.md').write_text('<!-- 原稿第 1 页 -->\n\n译文。')
            finding=dict(action='replace',source_page=1,source_quote='original statement',output_page=1,observation='可核对的问题',
                         proposal='修改',criterion='修复',before='译文。',after='修正译文。',severity='major')
            calls=[]
            def render(run,src,args):
                (run/'质量验收.json').write_text('{"remaining":[]}')
                with pdf.open() as doc:
                    doc.new_page().insert_text((40,60),'Rendered candidate');doc.save(run/'paper.pdf')
            def review(src,run,args,prior):
                calls.append(run.name)
                if len(calls)==3:
                    return [dict(source_page=1,output_pages=[1],findings=[],recheck=[dict(id=x['id'],status='resolved',evidence='已核实') for x in prior])]
                return [dict(source_page=1,output_pages=[1],findings=[dict(finding)],recheck=[])]
            def edits(src,run,prior):
                return [dict(id=x['id'],applied=False,reason='上一候选没有改善验收结果，已回退；请基于当前 PDF 提出其他方案。') for x in prior]
            with patch('paper_translator.harness.vision_harness.verified_export',side_effect=render),patch('paper_translator.harness.visual_agent.review_round',side_effect=review),patch('paper_translator.harness.visual_agent.apply_proposals',side_effect=edits):
                visual_export(stage,source,SimpleNamespace(model='mock',max_review_rounds=3))
            self.assertEqual(len(calls),3)
            self.assertEqual(json.loads((stage/'视觉审阅记录.json').read_text())['status'],'passed')

    def test_interrupted_review_restores_same_pdf_without_rendering_again(self):
        import os
        with TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'stage';stage.mkdir();source=root/'source.pdf';source.write_bytes(b'source')
            (stage/'paper.md').write_text('<!-- 原稿第 1 页 -->\n译文')
            rendered=[]
            def render(run,src,args):
                rendered.append(1)
                (run/'paper.pdf').write_bytes(b'exact-candidate')
                (run/'质量验收.json').write_text('{"remaining":[]}')
            fail=[dict(source_page=1,output_pages=[1],error='temporary response failure',findings=[],recheck=[])]
            good=[dict(source_page=1,output_pages=[1],findings=[],recheck=[])]
            with patch.dict(os.environ,{'PAPER_TASK_ROOT':str(root/'job')}),patch('paper_translator.harness.vision_harness.verified_export',side_effect=render),patch('paper_translator.harness.visual_agent.review_round',side_effect=[fail,good]):
                args=SimpleNamespace(model='mock',max_review_rounds=2)
                with self.assertRaisesRegex(ValueError,'任务已保留'):visual_export(stage,source,args)
                visual_export(stage,source,args)
            self.assertEqual(len(rendered),1)
            self.assertEqual((stage/'paper.pdf').read_bytes(),b'exact-candidate')

    def test_resolving_one_issue_cannot_accept_more_blockers(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'stage';stage.mkdir();source=root/'source.pdf';source.write_bytes(b'source')
            (stage/'paper.md').write_text('<!-- 原稿第 1 页 -->\n译文')
            def render(run,src,args):
                (run/'paper.pdf').write_bytes(b'same-pdf')
                (run/'质量验收.json').write_text('{"remaining":[]}')
            finding=dict(source_page=1,output_page=1,severity='major',action='review',source_quote='source',before='',after='',observation='问题一',proposal='复核',criterion='核实')
            calls=[]
            def review(src,run,args,prior):
                calls.append(1)
                if len(calls)==1:return [dict(source_page=1,findings=[dict(finding)],recheck=[])]
                return [dict(source_page=1,findings=[dict(finding,observation='新问题二'),dict(finding,source_quote='different',observation='新问题三')],recheck=[dict(id=x['id'],status='resolved',evidence='旧问题消失') for x in prior])]
            with patch('paper_translator.harness.vision_harness.verified_export',side_effect=render),patch('paper_translator.harness.visual_agent.review_round',side_effect=review),patch('paper_translator.harness.visual_agent.apply_proposals',return_value=[]):
                with self.assertRaisesRegex(ValueError,'预算已用完'):visual_export(stage,source,SimpleNamespace(model='mock',max_review_rounds=2))
            report=json.loads((stage/'视觉审阅记录.json').read_text())
            self.assertEqual(report['selected_round'],1)
            self.assertFalse(report['rounds'][1]['accepted'])
