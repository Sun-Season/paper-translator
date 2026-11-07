"""修复模型 JSON 字符串中的未转义 LaTeX，不猜测缺失字段或括号。"""
import json
import re
from paper_translator.config.math_commands import MATH_COMMANDS

_LATEX = {'frac','beta','begin','bar','big','bigl','bigr','boldsymbol','binom',
          'text','textbf','textit','textrm','textnormal','times','theta','tau','tag','top','to',
          'right','rangle','rho','ref','rm','rightarrow','nu','nabla','neq','not','neg','newcommand',
          'underline','underbrace','upsilon','usepackage','varepsilon','varnothing','vec'} | MATH_COMMANDS


def decode_model_json(raw):
    result=[];inside=False;i=0
    while i<len(raw):
        c=raw[i]
        if c=='"':
            inside=not inside;result.append(c);i+=1;continue
        if inside and c=='\\' and i+1<len(raw):
            nxt=raw[i+1]
            if nxt in '\\"/':
                result.extend((c,nxt));i+=2;continue
            word=re.match(r'[A-Za-z]+',raw[i+1:])
            valid_unicode=nxt=='u' and re.match(r'[0-9a-fA-F]{4}',raw[i+2:i+6])
            if (word and word[0] in _LATEX) or (nxt not in 'bfnrtu') or (nxt=='u' and not valid_unicode):
                result.append('\\\\');i+=1;continue
            result.extend((c,nxt));i+=2;continue
        if inside and ord(c)<32:
            result.append(json.dumps(c)[1:-1])
        else:result.append(c)
        i+=1
    return json.loads(''.join(result))
