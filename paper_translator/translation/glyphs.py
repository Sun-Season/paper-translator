"""移除配置字体无法绘制的装饰性 emoji，避免缺字阻断发布。"""
import re

PICTOGRAPHS = re.compile(r"[\U0001F000-\U0001FAFF\u200D\uFE0F]")


def strip_pictographs(markdown):
    """删除 emoji 图符（含变体选择符和零宽连接符），返回文本和实际删除的字符。"""
    removed = PICTOGRAPHS.findall(markdown)
    return PICTOGRAPHS.sub("", markdown), sorted(set(removed))
