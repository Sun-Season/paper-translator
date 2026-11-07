import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from paper_translator.harness.reference_audit import audit_references
from paper_translator.harness.visual_agent import gate_findings, ineffective, visual_export


def finding(**changes):
    base=dict(source_page=1,output_page=1,severity='major',action='replace',source_quote='source',
              before='译文',after='修正译文',observation='问题',proposal='修改',criterion='一致')
    base.update(changes)
    return base


class GateFindingTest(unittest.TestCase):
    def test_minor_is_advisory_and_unfixable_major_blocks(self):
        minor=finding(severity='minor')
        stale=finding(execution={'applied':False,'reason':'本原页译稿中找不到修改片段'})
        real=finding()
        blockers,advisories=gate_findings([minor,stale,real])
        self.assertEqual([f['gate'] for f in advisories],['advisory'])
        self.assertEqual([f['gate'] for f in blockers],['unfixable','evidence_insufficient'])

    def test_round_level_failure_still_blocks(self):
        stalled=finding(execution={'applied':False,'reason':'上一候选没有改善验收结果，已回退；请基于当前 PDF 提出其他方案。'})
        blockers,advisories=gate_findings([stalled])
        self.assertEqual([f['gate'] for f in blockers],['still_problematic'])
        self.assertEqual(advisories,[])

    def test_review_action_still_blocks(self):
        blockers,advisories=gate_findings([finding(action='review')])
        self.assertEqual(len(blockers),1)
        self.assertEqual(advisories,[])

    def test_ineffective_rejects_noop_and_empty_replacement(self):
        self.assertIn('相同',ineffective(finding(before='译文',after='译文')))
        self.assertIn('为空',ineffective(finding(after='')))
        self.assertIsNone(ineffective(finding()))


class PublishWithBlockingTest(unittest.TestCase):
    def test_unfixable_major_blocks_publication(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'stage';stage.mkdir();source=root/'source.pdf'
            source.write_bytes(b'source')
            (stage/'paper.md').write_text('<!-- 原稿第 1 页 -->\n译文')
            def render(run,src,args):
                (run/'paper.pdf').write_bytes(b'pdf')
                (run/'质量验收.json').write_text('{"remaining":[]}')
            def review(src,run,args,prior):
                return [dict(source_page=1,findings=[finding()],recheck=[])]
            def edits(src,run,prior):
                return [dict(id=x['id'],applied=False,reason='本原页译稿中找不到修改片段') for x in prior]
            with patch('paper_translator.harness.vision_harness.verified_export',side_effect=render),\
                 patch('paper_translator.harness.visual_agent.review_round',side_effect=review),\
                 patch('paper_translator.harness.visual_agent.apply_proposals',side_effect=edits):
                with self.assertRaises(ValueError):
                    visual_export(stage,source,SimpleNamespace(model='mock',max_review_rounds=2))
            log=json.loads((stage/'视觉审阅记录.json').read_text())
            self.assertEqual(log['status'],'needs_review')
            self.assertEqual(log['advisories'],[])
            self.assertEqual(len(log['blocking']),1)
            self.assertEqual(log['blocking'][0]['gate'],'unfixable')
            self.assertEqual(log['categories']['unfixable'],1)


class ReferenceAuditTest(unittest.TestCase):
    def test_translated_entries_are_counted(self):
        markdown=("# 正文\n\n内容。\n\n## 参考文献\n\n"
                  "Jiazhao Zhang, Kunyu Wang. Uni-NaVid. 2026.\n\n"
                  "洪一聪、王尊。弥合离散与连续环境学习之间的鸿沟。CVPR，2022。\n")
        report=audit_references(markdown)
        self.assertEqual((report['entries'],report['translated']),(2,1))
        self.assertEqual(report['status'],'needs_review')

    def test_english_references_pass(self):
        markdown="## References\n\nJiazhao Zhang, Kunyu Wang. Uni-NaVid. 2026.\n"
        self.assertEqual(audit_references(markdown)['status'],'passed')

    def test_bold_heading_ends_at_appendix(self):
        markdown=("**REFERENCES**\n\nJiazhao Zhang. Uni-NaVid. 2026.\n\n"
                  "## A 相关工作\n\n这里是附录正文，不属于参考文献。\n")
        report=audit_references(markdown)
        self.assertEqual((report['entries'],report['translated']),(1,0))

    def test_copy_asset_same_file_is_noop(self):
        from paper_translator.harness.visual_agent import _copy_asset
        with TemporaryDirectory() as folder:
            path = Path(folder) / "figure-1.png"
            path.write_bytes(b"png")
            self.assertEqual(_copy_asset(path, path), path)
