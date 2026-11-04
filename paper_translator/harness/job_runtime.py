"""持久保存任务阶段和失败位置，复用已经完成的阶段。"""
from pathlib import Path
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import time


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.replace(stream.name, path)


class Job:
    def __init__(self, source, destination, args):
        self.destination = destination.resolve()
        self.root = self.destination.with_name(self.destination.name + ".job")
        self.root.mkdir(parents=True, exist_ok=True)
        config = {k: str(v) for k, v in vars(args).items() if k != "out"}
        code = hashlib.sha256()
        for path in sorted(Path(__file__).resolve().parents[1].rglob("*.py")):
            code.update(path.read_bytes())
        self.identity = {"source": hashlib.sha256(source.read_bytes()).hexdigest(),
                         "config": config, "code": code.hexdigest(), "version": 2}
        self.path = self.root / "task.json"
        self.stage = self.root / "result"
        self.state = {"identity": self.identity, "completed": [], "status": "running"}

    def __enter__(self):
        self.lock = (self.root / "lock").open("w")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise ValueError("同一任务正在运行，请等待该进程结束。")
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
            if self.state["identity"] != self.identity:
                self.lock.close()
                raise ValueError("任务参数或工具代码已改变，请使用新的输出目录。")
        self.stage.mkdir(exist_ok=True)
        self.env = {k: os.environ.get(k) for k in ("PAPER_JOB_DIR", "PAPER_PENDING_DIR", "PAPER_TASK_ROOT", "PAPER_PHASE")}
        for key, value in {"PAPER_JOB_DIR": self.root / "cache",
                           "PAPER_PENDING_DIR": self.root / "pending",
                           "PAPER_TASK_ROOT": self.root}.items():
            os.environ[key] = str(value)
        self.save()
        return self

    def save(self):
        self.state["updated_at"] = time.time()
        atomic_json(self.path, self.state)

    def run(self, name, action):
        if name in self.state["completed"]:
            print("恢复已完成阶段：" + name, flush=True)
            return
        completed = self.state["completed"]
        if completed:
            checkpoint = self.root / "checkpoints" / completed[-1]
            shutil.rmtree(self.stage)
            shutil.copytree(checkpoint, self.stage)
        elif self.state.get("status") == "interrupted":
            shutil.rmtree(self.stage)
            self.stage.mkdir()
        self.state.update(status="running", phase=name)
        os.environ["PAPER_PHASE"] = name
        self.save()
        action(self.stage)
        checkpoint = self.root / "checkpoints" / name
        if checkpoint.exists():
            shutil.rmtree(checkpoint)
        shutil.copytree(self.stage, checkpoint)
        completed.append(name)
        self.save()

    def publish(self):
        if not (self.stage / "paper.pdf").exists() and not (self.stage / "paper.md").exists():
            raise ValueError("任务未生成可交付文件。")
        delivery = self.root / "delivery"
        if delivery.exists():
            shutil.rmtree(delivery)
        shutil.copytree(self.stage, delivery)
        delivery.rename(self.destination)
        statuses = []
        for name in ("质量验收.json", "视觉审阅记录.json"):
            path = self.stage / name
            if path.exists():
                statuses.append(json.loads(path.read_text()).get("status"))
        self.state["status"] = "needs_review" if "needs_review" in statuses else "completed"
        self.save()

    def __exit__(self, kind, error, traceback):
        if error:
            self.state.update(status="interrupted", error=str(error))
            self.save()
        for key, value in self.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.lock.close()


def request_event(payload, status, attempt):
    root = os.environ.get("PAPER_TASK_ROOT")
    if not root:
        return
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    atomic_json(Path(root) / "requests" / (identity + ".json"),
                {"request_hash": identity, "phase": os.environ.get("PAPER_PHASE"),
                 "status": status, "attempt": attempt, "model": payload.get("model"),
                 "updated_at": time.time()})
