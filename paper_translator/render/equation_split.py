"""按原稿栏宽把过宽的行间公式拆成保持数学结构的对齐多行。"""
import re

RELATIONS = {r"\leq", r"\geq", r"\le", r"\ge", r"\leqslant", r"\geqslant",
             r"\approx", r"\neq", r"\equiv", r"\propto", r"\sim", r"=", r"<", r">"}
BINARY = {"+", "-", r"\pm", r"\mp"}
PUNCTUATION = {","}


def _width_em(latex):
    """粗略估计公式显示宽度（em），用于在断点之间做贪心分行。"""
    text = re.sub(r"\\(?:text|mathrm|mathbf|mathcal|mathbb|hat|widehat|bar|tilde|dot|ddot)\{[^{}]*\}", "x", latex)
    text = re.sub(r"\\[A-Za-z]+", "", text)
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\\(.)", r"\1", text)
    width = 0.0
    for char in text:
        if char.isalpha() or char.isdigit():
            width += 0.55
        elif char in "=<>+":
            width += 0.7
        elif char in ",;:":
            width += 0.3
        elif char in "_^":
            width += 0.0
        else:
            width += 0.5
    return width


def _break_points(latex):
    """只在花括号、\left/\right 和环境之外记录可断点。"""
    depth = 0
    left = 0
    environments = 0
    index = 0
    points = []
    while index < len(latex):
        char = latex[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == "\\":
            match = re.match(r"[A-Za-z]+", latex[index+1:])
            token = "\\" + (match.group(0) if match else latex[index+1:index+2])
            if token == "\\left":
                left += 1
            elif token == "\\right":
                left = max(0, left - 1)
            elif token == "\\begin":
                environments += 1
            elif token == "\\end":
                environments = max(0, environments - 1)
            elif (depth == 0 and left == 0 and environments == 0
                  and token in RELATIONS | BINARY):
                points.append((index, index + len(token)))
            index += len(token)
            continue
        elif depth == 0 and left == 0 and environments == 0 and (char in "=<>" or char in "+-,"):
            points.append((index, index + 1))
        index += 1
    return points


def split_equation(latex, width_em=22.0):
    """在关系符、加减号或逗号处换行；返回 aligned 环境，内容不增不减。"""
    points = _break_points(latex)
    if not points:
        return None
    lines = []
    start = 0
    index = 0
    while index < len(points):
        begin, end = points[index]
        if end <= start:
            index += 1
            continue
        if _width_em(latex[start:end]) <= width_em:
            index += 1
            continue
        fitted = None
        for back in range(index - 1, -1, -1):
            if points[back][1] <= start:
                break
            if _width_em(latex[start:points[back][1]]) <= width_em:
                fitted = points[back][1]
                break
        if fitted and fitted > start:
            lines.append(latex[start:fitted].strip())
            start = fitted
            continue
        lines.append(latex[start:end].strip())
        start = end
        index += 1
    if start < len(latex):
        lines.append(latex[start:].strip())
    lines = [line for line in lines if line]
    if len(lines) < 2:
        return None
    body = ("\n\\\\\n" + "&\\quad ").join(lines)
    return "\\begin{aligned}\n" + body + "\n\\end{aligned}"


def tokens(latex):
    """用于校验拆分没有丢失或改变符号。"""
    value = re.sub(r"\\begin\{aligned\}|\\end\{aligned\}|&|\\\\|\\quad", " ", latex)
    return sorted(re.findall(r"\\[A-Za-z]+|\\[^A-Za-z]|[^\s\\{}]+", value))
