import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import pymupdf
from paper_translator.config.layout_policy import load_layout, validate_object, configure_preamble
from paper_translator.render.latex_backend import PAPER_PREAMBLE
from paper_translator.harness.visual_agent import apply_proposals


class LayoutPolicyTest(unittest.TestCase):
    def test_span_layout_patch_and_source_evidence(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"original.pdf"
            with pymupdf.open() as doc:
                doc.new_page().insert_text((30,50),"Table 1 Model comparisons.")
                doc.save(source)
            (root/"paper.md").write_text("<!-- 原稿第 1 页 -->\n\n表 1 模型比较。")
            (root/"layout-objects.json").write_text(json.dumps({"tab-1":{"source_page":1}}))
            finding=dict(id="one",source_page=1,output_page=1,source_quote="Model comparisons",
                         before="",after="",criterion="跨栏显示",action="layout",
                         object_id="tab-1",layout={"span":"wide"})
            result=apply_proposals(source,root,[finding])
            self.assertTrue(result[0]["applied"])
            config=load_layout(root)
            self.assertEqual(config["objects"]["tab-1"]["span"],"wide")
            self.assertIn(r"\settowidth{\bodyindent}{正正}",configure_preamble(PAPER_PREAMBLE,config["document"]))
            finding["layout"]={"column_widths":[.3,.7]}
            self.assertFalse(apply_proposals(source,root,[finding])[0]["applied"])
            self.assertEqual(load_layout(root),config)

    def test_column_widths_are_not_supported(self):
        with self.assertRaises(ValueError):
            validate_object({"column_widths":[.3,.7]})
