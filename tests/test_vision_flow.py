import tempfile
import unittest
from pathlib import Path

import pymupdf
from paper_translator.translation.vision_flow import clean_boundaries


class VisionFlowTest(unittest.TestCase):
    def test_echo_around_table_and_unfinished_sentence(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"paper.pdf"
            with pymupdf.open() as doc:
                doc.new_page().insert_text((40,50),"Table 3 Previous results")
                doc.new_page().insert_text((40,50),"Table 4 Comparison on held-out tasks")
                doc.save(source)
            a="模型在全部四个基准均获得了较高的成功率，在不同场景中也能保持表现。"
            b="在连续多阶段任务中，智能体能够利用多轮交互信息完成最后的目标定位。"
            c="这些结果表明，我们的方法通过主动交互有效解决了目标歧义"
            unique="这项测试还报告了新的消融实验，并说明了接触传感器的安装位置。"
            md=f"<!-- 原稿第 1 页 -->\n\n{a}\n\n{b}\n\n{c}\n\n<!-- 原稿第 2 页 -->\n\n表3 在八个基准上的比较\n\n{a}\n\n{b}\n\n{unique}\n\n![图](figures/test.png)\n\n{c}，使系统能够精确定位。"
            fixed=clean_boundaries(md,source)
            for text in (a,b,c,unique):
                self.assertEqual(fixed.count(text),1)
            self.assertNotIn("表3 在八个",fixed)
