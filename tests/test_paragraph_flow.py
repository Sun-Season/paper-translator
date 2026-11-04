import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import pymupdf as pdf

from paper_translator.harness.paper_harness import translation_checkpoint
from paper_translator.legacy.reflow_pdf import restore_paragraphs, inline


class ParagraphFlowTest(unittest.TestCase):
    def test_split_lines_stay_in_their_column(self):
        with pdf.open() as source, pdf.open() as raw:
            p=source.new_page()
            sentences="This is a sufficiently long guide paragraph on several lines. "*3
            for left in (35,310):
                p.insert_textbox((left,45,left+220,140),sentences,fontsize=10)
            translated=raw.new_page()
            translated.insert_text((35,58),"First fragment",fontsize=10)
            translated.insert_text((35,71),"then the continuation.",fontsize=10)
            translated.insert_text((310,58),"Other column.",fontsize=10)
            blocks=translated.get_text("dict")["blocks"]
            blocks=[{"bbox":line["bbox"],"lines":[line]} for b in blocks for line in b["lines"]]
            grouped=restore_paragraphs(blocks,p,None)
            self.assertEqual([inline(b) for b in grouped],["First fragment then the continuation.","Other column."])

    def test_checkpoint_reuses_only_matching_input_and_model(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ",{"PAPER_JOB_DIR":temp}):
            src=Path(temp)/"source.pdf"
            with pdf.open() as d:
                d.new_page()
                d.save(src)
            calls=[]
            def execute(work):
                p=work/"result.pdf"
                p.write_bytes(src.read_bytes())
                calls.append(p)
                return p
            for model in ("a","a","b"):
                translation_checkpoint(src,{"service":model},execute)
            self.assertEqual(len(calls),2)
