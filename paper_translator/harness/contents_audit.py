"""直接核对成品目录文字、显示页码、链接和正文目标。"""
import re


def compact(text):
    return re.sub(r'\s+','',text)


def audit_contents(document, entries):
    rows=[]
    for page in document:
        links=[]
        for link in page.get_links():
            if not isinstance(link.get('page'),int) or link['page']<0:continue
            box=link['from']
            text=page.get_text(clip=box+(-1,-2,1,2)).strip()
            links.append((text,link,box))
        for entry in entries:
            for text,link,box in links:
                if compact(text)!=compact(entry['title']):continue
                target=entry.get('output_page')
                numbers=[(s,l,b) for s,l,b in links if s.isdigit() and b.x0>box.x1 and abs(b.y0-box.y0)<5]
                valid=[(s,l,b) for s,l,b in numbers if int(s)==target and l['page']+1==target and link['page']+1==target]
                if len(valid)==1:
                    rows.append(dict(entry,contents_page=page.number+1,printed_page=int(valid[0][0]),status='verified'))
    # 一项只有一个可核验的目录位置，重复或缺失都不当作通过。
    return [row for row in rows if sum(x['id']==row['id'] for x in rows)==1]


def invalid_page_correction(finding, verified):
    """只有目录行的纯页码修改与成品证据冲突时，才撤销该修改意见。"""
    pattern=r'^([A-Z](?:\.\d+)*|\d+(?:\.\d+)*)\s+(.+?)[.．·…]{2,}\s*(\d+)\s*$'
    before=re.match(pattern,finding.get('before','').strip())
    after=re.match(pattern,finding.get('after','').strip())
    if not before or not after or before[1]!=after[1] or compact(before[2])!=compact(after[2]):return None
    entry=next((r for r in verified if r['id']==before[1] and compact(r['title'])==compact(before[1]+' '+before[2])),None)
    if entry is None or int(after[3])==entry['printed_page']:return None
    return f"成品目录 {entry['id']} 的显示页码和两处链接均指向实际正文第 {entry['printed_page']} 页；建议改成 {after[3]} 将破坏跳转一致性。"
