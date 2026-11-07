"""向审阅提供实际渲染证据，并恢复不完整的模型回复。"""
import copy
import json
import re

ACTIONS = {'replace', 'insert_after', 'recrop', 'layout', 'review'}

def render_evidence(run, document):
    path = run / '目录重建记录.json'
    if not path.exists():
        return {}
    plan = json.loads(path.read_text())
    names = document.resolve_names()
    entries = []
    for heading in plan.get('headings', {}).values():
        target = names.get(heading['label'], {})
        page = target.get('page')
        entries.append(dict(heading, output_page=page + 1 if isinstance(page, int) and page >= 0 else None))
    return {'contents': {'entries': entries, 'rule':
        '目录由 LaTeX 根据实际章节重建。draft 中目录的旧标题、页码不是成品；只对照成品图片和实际目标页判断，目标未知时不得推断正确。'}}

def _finding_problem(finding, index):
    """返回单条意见的字段问题；字段完整时返回 None。"""
    if not isinstance(finding, dict):
        return f'findings[{index}] 必须为对象。'
    if finding.get('action') not in ACTIONS or finding.get('severity') not in ('major', 'minor'):
        return f'findings[{index}] 的 action 或 severity 不在约定枚举中。'
    for key in ('observation', 'criterion'):
        if not isinstance(finding.get(key), str) or not finding[key].strip():
            return f'findings[{index}] 缺少 {key}。'
    if finding['action'] in ('replace', 'insert_after'):
        for key in ('before', 'after', 'source_quote'):
            if not isinstance(finding.get(key), str) or not finding[key].strip():
                return f'findings[{index}] 的修改缺少 {key}。'
    return None


def validate_answer(blocks):
    """校验审阅结构；单条意见字段不完整时跳过该条，不丢弃整组审阅。"""
    if not isinstance(blocks, list) or len(blocks) != 1 or not isinstance(blocks[0], dict):
        raise ValueError('blocks 必须恰含一个审阅对象。')
    answer = blocks[0]
    if not isinstance(answer.get('findings'), list) or not isinstance(answer.get('recheck'), list):
        raise ValueError('审阅必须包含 findings 和 recheck 数组。')
    accepted = []
    rejected = list(answer.get('rejected_findings') or [])
    for i, finding in enumerate(answer['findings']):
        problem = _finding_problem(finding, i)
        if problem:
            record = dict(finding) if isinstance(finding, dict) else {'observation': str(finding)}
            record['verification'] = {'verdict': 'insufficient_evidence',
                                      'reason': problem + ' 该条无法执行，已跳过。'}
            rejected.append(record)
        else:
            accepted.append(finding)
    if len(accepted) != len(answer['findings']):
        answer = dict(answer, findings=accepted, rejected_findings=rejected)
    return answer

def request_review(args, payload, request):
    payload = copy.deepcopy(payload)
    for attempt in range(3):
        blocks = request(args, payload)
        try:
            return validate_answer(blocks)
        except ValueError as error:
            if attempt == 2:
                raise
            payload['messages'].extend([
                {'role': 'assistant', 'content': json.dumps({'blocks': blocks}, ensure_ascii=False)},
                {'role': 'user', 'content': str(error) + ' 请根据原始证据完整重答，不得只返回缺项；无法安全执行时使用 review 并说明原因。'}])


def source_ownership(objects, document):
    """对象归属来自原稿清单，目标页来自成品；两者不能互相替代。"""
    names = document.resolve_names()
    result = []
    for obj in objects:
        prefix = {'figure': 'fig-', 'table': 'tab-', 'algorithm': 'alg-'}.get(obj['type'])
        if prefix is None:
            continue
        key = prefix + obj['number']
        page = names.get(key, {}).get('page')
        result.append({'object_id': key, 'source_page': obj['page'],
                       'output_page': page + 1 if isinstance(page, int) and page >= 0 else None})
    return result


def labeled_images(context, images):
    labels = context.get('image_labels')
    if labels is None:
        labels = [f"【原稿】英文原论文第 {context.get('source_page')} 页"] + [
            f"【成品】中文导出第 {p} 页" for p in context.get('output_pages', [])]
    if len(labels) != len(images):
        raise ValueError('图像数量与身份标签不一致。')
    result = []
    for label, img in zip(labels, images):
        result.extend([{'type': 'text', 'text': label}, img])
    return result


def image_placement_map(run, document):
    """一次扫描得到 原页 -> 实际嵌入位置，供整轮审阅复用。"""
    import pymupdf
    assets = {}
    for path in (run/'figures').glob('page-*.png'):
        match = re.match(r'page-(\d+)-', path.name)
        if match is None:
            continue
        entry = assets.setdefault(pymupdf.Pixmap(str(path)).digest,
                                  {'source_page': int(match[1]), 'names': []})
        entry['names'].append('figures/'+path.name)
    result = {}
    for page in document:
        for item in page.get_image_info(hashes=True):
            entry = assets.get(item['digest'])
            if entry is None:
                continue
            result.setdefault(entry['source_page'], []).append(
                {'assets': entry['names'], 'output_page': page.number+1, 'box': list(item['bbox'])})
    return result


def image_placements(run, document, source_page):
    """按解码像素摘要定位实际嵌入的图块，不用文字相似度猜位置。"""
    return image_placement_map(run, document).get(source_page, [])
