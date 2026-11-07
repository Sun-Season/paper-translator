"""限制单个任务的付费请求；恢复任务不重置已用额度。"""
import fcntl
import json
import os
from pathlib import Path
from paper_translator.harness.job_runtime import atomic_json


def update(action, value=None):
    root=os.environ.get('PAPER_TASK_ROOT')
    if not root:return
    root=Path(root)
    with (root/'request-budget.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=root/'请求用量.json'
        data=json.loads(path.read_text()) if path.exists() else {'calls':0,'prompt_tokens':0,'completion_tokens':0}
        if action=='reserve':
            limit=int(os.environ.get('PAPER_MAX_API_CALLS','150'))
            if data.get('halted'):raise ValueError('模型请求已停止：'+data['halted'])
            if data['calls']>=limit:raise ValueError(f'已达本任务 {limit} 次 API 请求上限，未继续调用。')
            data['calls']+=1;data['limit']=limit
        elif action=='usage':
            for key in ('prompt_tokens','completion_tokens'):
                data[key]+=int((value or {}).get(key,0) or 0)
        elif action=='halt':data['halted']=str(value)
        atomic_json(path,data)
