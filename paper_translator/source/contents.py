"""从原目录识别章节身份，用成品章节标签生成动态目录。"""
import re

_LABEL=re.compile(r'^(?:APPENDIX\s+CONTENTS|TABLE\s+OF\s+CONTENTS|CONTENTS|附录目录|目录)$',re.I)
_ENTRY=re.compile(r'^([A-Z](?:\.\d+)*|\d+(?:\.\d+)*)\s+(.+?)\s+(\d+)\s*$')
_HEADING=re.compile(r'^([A-Z](?:\.\d+)*|\d+(?:\.\d+)*)\s+(.+)$')


def contents_plan(nodes):
    start=next((i for i,n in enumerate(nodes) if _LABEL.fullmatch(n.text_content().strip())),None)
    if start is None:return None
    entries=[];end=None
    for i in range(start+1,len(nodes)):
        text=nodes[i].text_content().strip()
        found=_HEADING.match(" ".join(text.split()))
        if found and found[1] in {x[0] for x in entries} and nodes[i].tag in ('h1','h2','h3','h4','h5','h6'):
            end=i;break
        text=re.sub(r'(?<=\d)\s+(?=(?:[A-Z]|\d+)(?:\.\d+)*\s+[^\s.])','\n',text)
        for part in re.split(r"(?m)(?=^(?:[A-Z]|\d+)(?:\.\d+)*\s+[^\s.])",text):
            match=_ENTRY.match(" ".join(part.split()))
            if match:entries.append((match[1],match[2]))
    if end is None or len(entries)<3:return None
    wanted={key for key,_ in entries};headings={}
    for i in range(end,len(nodes)):
        text=" ".join(nodes[i].text_content().split());match=_HEADING.match(text)
        if match and match[1] in wanted and len(text)<160 and not re.search(r'(?:\.\s*){4}',text):
            if match[1] not in {v['id'] for v in headings.values()}:
                headings[i]={'id':match[1],'title':text,'label':'native-sec-'+match[1].replace('.','-')}
    if wanted-{v['id'] for v in headings.values()}:
        # 无法定位所有章节时不生成部分目录，也不猜测目标。
        return None
    return {'start':start,'end':end,'headings':headings,'entries':entries}


def contents_tex(plan,escape):
    by_id={h['id']:h for h in plan['headings'].values()}
    rows=[]
    for key,_ in plan['entries']:
        h=by_id[key];indent=key.count('.')*1.4
        rows.append(r'\noindent\hspace*{'+f'{indent:.1f}em'+r'}\hyperref['+h['label']+']{'+escape(h['title'])+r'}\nobreak\dotfill\nobreak\pageref{'+h['label']+r'}\par')
    return r'{\small\setlength{\parskip}{3pt}'+ '\n'.join(rows)+'}'
