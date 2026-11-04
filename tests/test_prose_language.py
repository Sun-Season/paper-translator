from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from prose_language import suspect, ownership, normalized, check_page


class ProseCheckTest(TestCase):
    def test_author_list_with_institution_heading(self):
        self.assertFalse(suspect("## Physical Intelligence\nKevin Black, Noah Brown, James Darpinian, Karan Dhabalia"))
        self.assertTrue(suspect("The model uses data, actions, images, and text to learn from the world."))

    def test_numbered_full_name_reference(self):
        self.assertFalse(suspect("[4] Suneel Belkhale, Tianli Ding, and Ted Xiao. Action hierarchies using language, 2024."))
        self.assertTrue(suspect("[4] The model was trained with data from the previous experiments in 2024."))

    def test_keep_intentional_english(self):
        for line in ("GV-Act, SVP, IDM, RoboTwin", "模型采用 RGB-D 与 DeepSeek V4。",
                     "比较了两种方法（Salimans and Ho, 2022; Chen et al., 2025）。",
                     "J. Doe, A. Green. A long paper on the behavior of the robot. 2024.",
                     "运行 `move_to(target)`。", "$$\\text{the output of the model for this task}$$",
                     '示例指令为 “Please move the red block to the corner of the table.”',
                     "| Name | Description of the data used for training the model |"):
            self.assertFalse(suspect(line),line)

    def test_origin_uses_source_not_neighbor_order(self):
        line="The model was pretrained on three distinct stages of real robot data."
        self.assertTrue(suspect(line))
        texts=[" "+normalized(line)+" "," chapter five reports the experiments "]
        self.assertEqual(ownership(line,texts,1),0)
        self.assertEqual(ownership(line,texts*2,2),2)
        self.assertIsNone(ownership("This passage is not found in the original document.",texts,1))

    def test_failed_duplicate_has_no_cache_entry(self):
        line="The model was pretrained on three distinct stages of real robot data."
        texts=[" "+normalized(line)+" "," chapter five reports the experiments "]
        args=SimpleNamespace(model="test",base_url="test")
        with TemporaryDirectory() as tmp,patch.dict("os.environ",{"PAPER_JOB_DIR":tmp}),patch("translate.request_blocks",return_value=[{"id":0,"action":"duplicate","evidence":"凭空编造的中文引文。"}]):
            with self.assertRaises(ValueError):check_page(line,1,texts,{0:"完整译稿。",1:line},args)
            self.assertEqual(list((Path(tmp)/"prose-verdicts").iterdir()),[])
