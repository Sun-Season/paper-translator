from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import pymupdf
from visual_agent import apply_proposals,mapped_pages


class AgentReviewTest(unittest.TestCase):
    def test_mapping_includes_all_pages(self):
        with pymupdf.open() as doc:
            for i in range(5):
                doc.new_page().insert_text((40,55),f"Different content on unique page number {i}.")
            mapped=mapped_pages(["unique page number 0","unique page number 4"],doc)
            self.assertEqual(set().union(*map(set,mapped)),set(range(5)))

    def test_unsupported_and_invented_number_leave_draft_intact(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"paper-original.pdf"
            with pymupdf.open() as d:
                d.new_page().insert_text((40,60),"The score is 30.");d.save(source)
            text="<!-- 原稿第 1 页 -->\n\n分数为30。"
            (root/"paper.md").write_text(text)
            base=dict(id="a",source_page=1,output_page=1,criterion="数值一致",before="分数为30。",after="分数为80。",source_quote="The score is 30.")
            edits=apply_proposals(source,root,[dict(base,action="replace"),dict(base,action="run_shell")])
            self.assertFalse(any(e['applied'] for e in edits))
            self.assertEqual((root/"paper.md").read_text(),text)

    def test_collect_rendered_feedback_and_publish_only_reviewed_candidate(self):
        import json,hashlib
        from types import SimpleNamespace
        from unittest.mock import patch
        from visual_agent import visual_export
        with TemporaryDirectory() as tmp:
            root=Path(tmp);stage=root/"stage";stage.mkdir();source=root/"source.pdf"
            with pymupdf.open() as d:
                d.new_page().insert_text((40,60),"The robot did not move.");d.save(source)
            (stage/"paper.md").write_text("<!-- 原稿第 1 页 -->\n\n机器人移动了。")
            def render(run,src,args):
                (run/"质量验收.json").write_text('{"remaining":[]}')
                with pymupdf.open() as doc:
                    doc.new_page().insert_text((40,60),"render "+run.name);doc.save(run/"paper.pdf")
            calls=[]
            def review(src,run,args,prior):
                self.assertTrue((run/"paper.pdf").is_file())
                calls.append(run.name)
                if prior:
                    self.assertIn("机器人没有移动。",(run/"paper.md").read_text())
                    findings=[];checks=[{"id":prior[0]["id"],"status":"resolved","evidence":"否定词已恢复"}]
                else:
                    findings=[dict(action="replace",source_page=1,source_quote="did not move",output_page=1,
                                   observation="漏译否定",proposal="恢复否定",criterion="语义一致",before="机器人移动了。",
                                   after="机器人没有移动。",severity="major")];checks=[]
                return [dict(source_page=1,output_pages=[1],findings=findings,recheck=checks)]
            with patch("vision_harness.verified_export",side_effect=render),patch("visual_agent.review_round",side_effect=review):
                visual_export(stage,source,SimpleNamespace(model="test"))
            log=json.loads((stage/"视觉审阅记录.json").read_text())
            self.assertEqual((calls,log["selected_round"],log["status"]),(["0","1"],2,"passed"))
            self.assertEqual(log["rounds"][1]["pdf_sha256"],hashlib.sha256((stage/"paper.pdf").read_bytes()).hexdigest())
