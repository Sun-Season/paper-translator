import unittest
import pymupdf
from paper_translator.render.native_tables import table_tex
from paper_translator.source.original_tables import table_regions
from paper_translator.translation.vision_flow import remove_panel_transcripts


class LayoutTest(unittest.TestCase):
    def test_panel_fields_need_source_evidence(self):
        with pymupdf.open() as doc:
            p=doc.new_page()
            pix=pymupdf.Pixmap(pymupdf.csRGB,pymupdf.IRect(0,0,10,10),False)
            pix.clear_with(255)
            p.insert_image((40,60,200,145),pixmap=pix)
            for y,t in [(70,"Task: Walk"),(85,"Question: Which way?"),(100,"Front Right MLLM"),(170,"Figure 3 Example")]:
                p.insert_text((40,y),t)
            blocks=["保留这一段。","任务：走到门前。","问题：怎么走？","前视图 右视图","MLLM","![图](figures/example.png)","图3 示意图。","问题：这是正文的问题。"]
            remove_panel_transcripts(blocks,p)
            self.assertEqual(blocks,["保留这一段。","![图](figures/example.png)","图3 示意图。","问题：这是正文的问题。"])

    def test_table_contains_native_cells(self):
        with pymupdf.open() as doc:
            p=doc.new_page()
            p.insert_text((40,55),"Table 6 Results")
            for y in (65,90,145):
                p.draw_line((40,y),(500,y))
            for y,row in [(82,["Method","Score","Cost","Time"]),(111,["First","90","2","3"]),(134,["Next","95","4","5"])]:
                for x,value in zip((42,160,280,400),row):p.insert_text((x,y),value)
            tex=table_tex(p,table_regions(p)["6"])
            cells=tex.split(" & ")
            self.assertEqual(len(cells),4)
            for cell,value in zip(cells,["First","90","2","3"]):
                self.assertIn("}"+value+"}",cell)
            self.assertIn(r"\begin{tabular}",tex)
            self.assertNotIn(r"\includegraphics",tex)
