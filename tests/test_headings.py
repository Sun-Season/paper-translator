from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest
from paper_translator.translation.headings import translate_headings


class HeadingTest(unittest.TestCase):
    def test_body_titles_translate_but_source_header_stays(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'paper.md';p.write_text('<!-- 原稿第 1 页 -->\n# Original Paper Title\n## Anonymous Authors\n摘要 正文\n## 1 INTRODUCTION\n<!-- 原稿第 2 页 -->\n## 4 EXPERIMENTS\n')
            with patch('paper_translator.cli.request_blocks',return_value=[{'id':0,'translation':'引言'},{'id':1,'translation':'实验'}]):
                translate_headings(p,SimpleNamespace(model='mock',target='zh'))
            t=p.read_text();self.assertIn('# Original Paper Title',t);self.assertIn('## Anonymous Authors',t)
            self.assertIn('## 1 引言',t);self.assertIn('## 4 实验',t)

    def test_title_translation_cannot_change_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'paper.md';old='<!-- 原稿第 2 页 -->\n## 3D Evaluation\n';p.write_text(old)
            with patch('paper_translator.cli.request_blocks',return_value=[{'id':0,'translation':'2D 评估'}]):
                with self.assertRaises(ValueError):translate_headings(p,SimpleNamespace(model='mock',target='zh'))
            self.assertEqual(p.read_text(),old)

    def test_contents_label_keeps_structural_role_after_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'paper.md';p.write_text('<!-- 原稿第 2 页 -->\n## APPENDIX CONTENTS\n')
            with patch('paper_translator.cli.request_blocks',return_value=[{'id':0,'translation':'附录内容'}]):
                translate_headings(p,SimpleNamespace(model='mock',target='zh'))
            self.assertIn('## 附录目录',p.read_text())

    def test_plain_numbered_heading_is_translated_without_changing_toc(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'paper.md';p.write_text('<!-- 原稿第 2 页 -->\nC.4 Calibration . . . 22\nC.4  CALIBRATION\n正常正文。\n')
            with patch('paper_translator.cli.request_blocks',return_value=[{'id':0,'translation':'校准'}]):
                translate_headings(p,SimpleNamespace(model='mock',target='zh'))
            self.assertIn('C.4  校准',p.read_text())
            self.assertIn('C.4 Calibration . . . 22',p.read_text())

    def test_bold_plain_appendix_heading_is_translated(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'paper.md';p.write_text('<!-- 原稿第 2 页 -->\nF  **QUALITATIVE EXAMPLES**\n')
            with patch('paper_translator.cli.request_blocks',return_value=[{'id':0,'translation':'**定性示例**'}]):
                translate_headings(p,SimpleNamespace(model='mock',target='zh'))
            self.assertIn('F  **定性示例**',p.read_text())
