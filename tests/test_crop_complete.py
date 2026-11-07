import os
from pathlib import Path
import tempfile
import unittest
import pymupdf as pdf
from paper_translator.source.crop_complete import complete_crops


class CropCompleteTest(unittest.TestCase):
    def test_completed_asset_does_not_mutate_hardlinked_input(self):
        with tempfile.TemporaryDirectory() as tmp,pdf.open() as doc:
            root=Path(tmp);(root/'figures').mkdir()
            p=doc.new_page(width=200,height=200)
            p.draw_rect(pdf.Rect(20,60,180,95));p.insert_text((30,110),'axis label')
            original=root/'input.png';p.get_pixmap(clip=pdf.Rect(20,60,180,95)).save(original)
            saved=original.read_bytes();out=root/'figures/crop.png';os.link(original,out)
            changes=complete_crops(doc,root,[{'type':'figure','asset':'figures/crop.png','page':1,'caption_box':[20,120,180,135]}],
                                   [{'path':'figures/crop.png','box':[20,60,180,95]}])
            self.assertEqual(len(changes),1)
            self.assertEqual(original.read_bytes(),saved)
            self.assertNotEqual(out.read_bytes(),saved)
