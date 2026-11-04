"""统一排版参数与有界的对象级修改。"""
import json
import math
from pathlib import Path

DEFAULTS = {
    "cjk_font": "Songti SC", "latin_font": "Times New Roman",
    "body_indent_chars": 2, "column_gap_bp": 20,
    "body_alignment": "justify", "columns": "source",
    "preserve_header": True, "preserve_table_rules": True,
    "figure_near_reference": True, "abstract_columns": "source",
    "introduction_gap_bp": 10, "preserve_front_order": True,
    "abstract_label": "Abstract", "abstract_label_style": "bold_italic", "abstract_body_style": "bold",
}


def load_layout(directory):
    path = Path(directory) / "layout.json"
    value = json.loads(path.read_text()) if path.exists() else {}
    if set(value) - {"document", "objects"}:
        raise ValueError("排版配置含未知字段。")
    document = dict(DEFAULTS, **value.get("document", {}))
    if document != DEFAULTS:
        raise ValueError("文档级格式由统一规则固定，模型只能调整对象版式。")
    objects = value.get("objects", {})
    for item in objects.values():
        validate_object(item)
    return {"document": document, "objects": objects}


def validate_object(item):
    if not isinstance(item, dict) or set(item) - {"span", "column_widths"}:
        raise ValueError("对象版式只能包含 span 和 column_widths。")
    if item.get("span", "source") not in ("source", "single", "wide"):
        raise ValueError("对象栏式无效。")
    widths = item.get("column_widths")
    if widths is not None and (not isinstance(widths, list) or not 2 <= len(widths) <= 40 or
            any(type(v) not in (int, float) or not math.isfinite(v) or v < .015 for v in widths) or
            abs(sum(widths) - 1) > .01):
        raise ValueError("表格列宽必须为总和为 1 的正数比例。")


def configure_preamble(preamble, document):
    return (preamble.replace(r"\setmainfont{Times New Roman}", r"\setmainfont{" + document["latin_font"] + "}")
            .replace(r"\setCJKmainfont{Songti SC}", r"\setCJKmainfont{" + document["cjk_font"] + "}")
            .replace(r"\setlength{\columnsep}{20bp}", r"\setlength{\columnsep}{" + str(document["column_gap_bp"]) + "bp}")
            .replace(r"\settowidth{\bodyindent}{正文}", r"\settowidth{\bodyindent}{" + "正" * document["body_indent_chars"] + "}"))
