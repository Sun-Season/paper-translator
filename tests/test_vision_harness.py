import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pymupdf
from vision_harness import repair,source_inventory,verified_export


class HarnessTest(unittest.TestCase):
    def test_header_requires_a_source_boundary_and_matching_render(self):
        from source_header import header_region, draft_header_end, locate_header
        from lxml import html
        nodes = [html.fromstring(tag) for tag in ("<h1>译名</h1>", "<p>署名</p>", "<h2>摘要</h2>")]
        self.assertEqual(draft_header_end(nodes, [0]*3), 2)
        self.assertIsNone(draft_header_end(nodes, [0, 0, 1]))
        with pymupdf.open() as doc:
            source = doc.new_page()
            source.insert_text((72, 80), "A different paper")
            source.insert_text((75, 100), "Authors")
            self.assertIsNone(header_region(source))
            source.insert_text((72, 150), "Abstract")
            box = header_region(source)
            self.assertGreater(locate_header(source, source, box, box.width)[0], .99)
            blank = doc.new_page()
            self.assertLess(locate_header(doc[0], blank, box, box.width)[0], .92)

    def test_split_math_requires_unique_equivalent(self):
        from vision_harness import repair_split_math
        broken = "$\nho = 0.85$"
        good = r"$\rho = 0.85$"
        self.assertEqual(repair_split_math(broken + "；" + good)[0], good + "；" + good)
        self.assertEqual(repair_split_math(broken)[0], broken)

    def test_dimension_is_not_an_equation_reference(self):
        from vision_latex import REFERENCE
        self.assertEqual(REFERENCE.findall("框架式 2D、自回归式 16x；见式 2、公式（12）和图 3。"),
                         ["式 2", "公式（12）", "图 3"])

    def test_source_inventory_excludes_equation_and_discussion(self):
        with pymupdf.open() as d:
            p=d.new_page()
            for i,t in enumerate(["Figure 2: Architecture","Figure 3 shows the model.","3","X"]):
                p.insert_text((50,70+i*20),t)
            self.assertEqual([o["number"] for o in source_inventory(d)],["2"])

    def test_restore_missing_figure_and_remove_only_verified_subtables(self):
        marker="<!-- 原稿第 1 页 -->\n\n"
        raw=marker+"正文段落。\n\n![架构](figures/a.png)\n\n图 2：架构。\n\n后续正文。"
        figure={"type":"figure","page":1,"number":"2","asset":"figures/a.png"}
        table={"type":"table","page":1,"number":"3","parts":["a","b"]}
        issues=[{"source_page":1,"object":"fig-2","code":"missing_object"},
                {"source_page":1,"object":"tab-3","code":"duplicate_parts"}]
        md=marker+"正文段落。\n\n后续正文。\n\n表 3：比较\n\n(a) A\n\n| A |\n\n(b) B\n\n| B |\n\n另一张表\n\n| C |"
        fixed,actions=repair(md,issues,[figure,table],raw)
        self.assertEqual(len(actions),2)
        self.assertIn("图 2：架构。\n\n后续正文",fixed)
        self.assertNotIn("| B |",fixed)
        self.assertIn("| C |",fixed)

    def test_no_progress_keeps_prior_pdf(self):
        import json
        with TemporaryDirectory() as tmp:
            root=Path(tmp);stage=root/"stage";stage.mkdir()
            (stage/"paper.md").write_text("<!-- 原稿第 1 页 -->\n\n"+"正文内容"*40+"\n\n![bad](figures/bad.png)")
            with pymupdf.open() as d:
                d.new_page();d.save(root/"original.pdf")
            def render(run,*args,**kwargs):
                (run/"paper.pdf").write_bytes(run.name.encode())
            issue={"code":"prose_crop","object":"figures/bad.png","source_page":1,"detail":"正文"}
            with patch("vision_latex.render_vision_latex",side_effect=render),patch("vision_harness.audit",return_value=[issue]):
                verified_export(stage,root/"original.pdf",None)
            report=json.loads((stage/"质量验收.json").read_text())
            self.assertEqual(report["status"],"needs_review")
            self.assertEqual(len(report["attempts"]),2)
            self.assertEqual((stage/"paper.pdf").read_bytes(),b"0")

    def test_duplicate_numeric_table_removed_only_on_wrong_source_page(self):
        row1="method180100";row2="method270100"
        table="Table 4: Performance\n\n| Method | Score | Trials |\n|---|---|---|\n| method1 | 80 | 100 |\n| method2 | 70 | 100 |"
        draft="<!-- 原稿第 1 页 -->\n\n"+table+"\n\n保留文字。\n\n<!-- 原稿第 2 页 -->\n\n"+table
        item={"source_page":2,"object":"tab-4","code":"possible_duplicate_table","rows":[row1,row2]}
        objects=[{"type":"table","page":2,"number":"4"}]
        out,actions=repair(draft,[item],objects)
        self.assertEqual(out.count("Table 4: Performance"),1)
        self.assertIn("保留文字。",out)
        self.assertEqual(actions[0]["removed_from_page"],1)
        objects.append({"type":"table","page":1,"number":"4"})
        self.assertEqual(repair(draft,[item],objects),(draft,[]))

    def test_formula_cannot_discard_a_figure(self):
        from vision_flow import clean_boundaries
        with TemporaryDirectory() as tmp:
            file=Path(tmp)/"source.pdf"
            with pymupdf.open() as d:
                d.new_page().insert_text((40,50),"Figure 2: Architecture")
                d.new_page().insert_text((40,50),"3\nX")
                d.save(file)
            draft="<!-- 原稿第 1 页 -->\n\n## 3 模型\n\n![架构](figures/a.png)\n\n图2：架构。\n\n<!-- 原稿第 2 页 -->\n\n正文。"
            self.assertIn("![架构](figures/a.png)",clean_boundaries(draft,file))
