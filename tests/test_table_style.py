import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from paper_translator.translation.table_language import TableLanguage


class CellTranslationTest(unittest.TestCase):
    def test_translate_prose_preserves_numbers_and_reuses_cache(self):
        source="Stop within 0.25 m of the goal."
        with tempfile.TemporaryDirectory() as tmp:
            args=SimpleNamespace(model="qwen3-vl-plus")
            with patch("paper_translator.cli.request_blocks",return_value=[{"id":0,"md":"在距离目标 0.25 米内停止。"}]) as service:
                self.assertIn(source,TableLanguage(tmp,args).resolve([source,"0.25","navigate_pixel"]))
                self.assertIn(source,TableLanguage(tmp,args).resolve([source]))
                self.assertEqual(service.call_count,1)

    def test_changed_threshold_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch("paper_translator.cli.request_blocks",return_value=[{"id":0,"md":"在距离目标 3 米内停止。"}]):
            with self.assertRaises(ValueError):
                TableLanguage(tmp,SimpleNamespace(model="qwen3-vl-plus")).resolve(["Stop within 0.25 m of the goal."])
            self.assertFalse((Path(tmp)/"table-translations.json").exists())
