from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from paper_translator.harness.job_runtime import Job


class JobRecoveryTest(unittest.TestCase):
    def test_failure_restores_completed_stage(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"source")
            destination = root / "output"
            args = SimpleNamespace(model="test")
            def acquire(stage):
                (stage / "paper.md").write_text("verified draft")
            def fail(stage):
                (stage / "paper.md").write_text("partial edit")
                raise ValueError("service unavailable")
            with self.assertRaises(ValueError):
                with Job(source, destination, args) as job:
                    job.run("translation", acquire)
                    job.run("review", fail)
            self.assertFalse(destination.exists())
            with Job(source, destination, args) as job:
                job.run("translation", lambda _: self.fail("Repeated completed stage"))
                def review(stage):
                    self.assertEqual((stage / "paper.md").read_text(), "verified draft")
                job.run("review", review)
                job.publish()
            self.assertEqual((destination / "paper.md").read_text(), "verified draft")
            self.assertFalse((root / "output.job").exists())

    def test_keep_job_environment_preserves_workspace(self):
        import os
        from unittest.mock import patch
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"source")
            with patch.dict(os.environ, {"PAPER_KEEP_JOB": "1"}):
                with Job(source, root / "out", SimpleNamespace(model="a")) as job:
                    (job.stage / "paper.md").write_text("draft")
                    job.publish()
            self.assertTrue((root / "out.job").exists())

    def test_reject_changed_configuration(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"source")
            with Job(source, root / "out", SimpleNamespace(model="a")):
                pass
            with self.assertRaises(ValueError):
                with Job(source, root / "out", SimpleNamespace(model="b")):
                    pass
