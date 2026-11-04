"""压缩译文栏内的段间留白，并为能识别的图和公式建立内部链接。"""

import itertools
import re
from dataclasses import dataclass

import numpy as np
import pymupdf as pdf

FIG = r"(?:fig(?:ure)?s?\.?|图)\s*([A-Z]?\d+(?:\.\d+)*)"
CAPTION = re.compile(r"^\s*" + FIG + r"(?:[ \t]*[:：.．、]|[ \t]*\u3000)", re.IGNORECASE)
REFERENCE = re.compile(
    FIG + r"|(?:eq(?:uation)?\.?|公式|式)\s*[（(]?\s*(\d+(?:\.\d+)*)", re.IGNORECASE
)
NUMBER = re.compile(r"[(（]\s*(\d+(?:\.\d+)*)\s*[)）]\s*$")


@dataclass
class Strip:
    box: pdf.Rect
    shift: float


def mapped(point, strips):
    candidates = [s for s in strips if s.box.x0 <= point.x <= s.box.x1]
    s = min(
        candidates or strips,
        key=lambda s: max(s.box.y0 - point.y, point.y - s.box.y1, 0),
    )
    return pdf.Point(point.x, point.y - s.shift)


def lines(page):
    flags = pdf.TEXTFLAGS_RAWDICT & ~pdf.TEXT_PRESERVE_IMAGES
    for block in page.get_text("rawdict", flags=flags)["blocks"]:
        for line in block.get("lines", []):
            chars = [c for span in line["spans"] for c in span["chars"]]
            if chars:
                yield "".join(c["c"] for c in chars), chars, pdf.Rect(line["bbox"])


def source_figures(source):
    """原稿含 LaTeX 命名目标时，可确定跨栏图的上边缘。"""
    starts = {}
    for name, dest in source.resolve_names().items():
        if name.startswith("figure.") and "to" in dest and dest.get("page", -1) >= 0:
            n = dest["page"]
            pos = pdf.Point(dest["to"]) * source[n].transformation_matrix
            starts.setdefault(n, []).append(pos)
    figures = []
    for page in source:
        regions = {}
        for text, _, box in lines(page):
            m = CAPTION.match(text)
            if not m:
                continue
            candidates = [
                a
                for a in starts.get(page.number, [])
                if a.y < box.y0 and abs(a.x - box.x0) < page.rect.width * 0.12
            ]
            if candidates:
                top = max(candidates, key=lambda a: a.y).y
            else:
                images = [pdf.Rect(im["bbox"]) for im in page.get_image_info()]
                above = [
                    b
                    for b in images
                    if b.y1 <= box.y1
                    and b.y1 >= box.y0 - 35
                    and b.x0 < box.x1
                    and box.x0 < b.x1
                ]
                top = min((b.y0 for b in above), default=box.y0)
            # 单栏短图注的宽度不足以代表图的实际宽度。
            half = page.rect.width / 2
            left = 0 if box.x0 < half else half
            right = page.rect.width if box.x1 > half else half
            regions[m[1]] = pdf.Rect(left, top, right, box.y1)
        figures.append(regions)
    return figures


def strips_for(page, figures):
    """在纯空白处切分。跨栏内容整段移动，不拆图片或公式。"""
    if page.rotation:
        return [Strip(page.rect, 0)]
    pix = page.get_pixmap(colorspace=pdf.csGRAY, alpha=False, annots=False)
    ink = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width) < 248
    h, w = ink.shape
    mid = w // 2
    protected = list(figures.values()) + [
        pdf.Rect(i["bbox"]) for i in page.get_image_info()
    ]
    protected += [
        pdf.Rect(g["rect"])
        for g in page.get_drawings()
        if g["rect"].height > 3
        and any(c and min(c) < 0.97 for c in (g["fill"], g["color"]))
    ]
    protected += [box for _, _, box in lines(page)]
    cross = np.zeros(h, dtype=bool)
    for r in protected:
        r = r & page.rect
        if r.is_empty:
            continue
        y0, y1 = max(0, int(r.y0) - 1), min(h, int(np.ceil(r.y1)) + 1)
        x0, x1 = max(0, int(r.x0)), min(w, int(np.ceil(r.x1)))
        ink[y0:y1, x0:x1] = True
        if x0 < mid < x1:
            cross[y0:y1] = True
    # 合并相邻跨栏行，避免把宽标题或图注切成窄条。
    ii = np.flatnonzero(cross)
    for a, b in itertools.pairwise(ii):
        if b - a <= 14:
            cross[a:b] = True
    edges = [0, *(np.flatnonzero(cross[1:] != cross[:-1]) + 1), h]
    result = []
    prior_saving = 0
    for top, bottom in itertools.pairwise(edges):
        saved_in_band = []
        for x0, x1 in [(0, w)] if cross[top] else [(0, mid), (mid, w)]:
            rows = np.flatnonzero(ink[top:bottom, x0:x1].any(axis=1)) + top
            saved = 0
            start = top
            for a, b in itertools.pairwise(rows):
                if b - a <= 19:
                    continue
                cut = int(a + 5)
                result.append(Strip(pdf.Rect(x0, start, x1, cut), prior_saving + saved))
                saved += int(b - a - 10)
                start = cut + int(b - a - 10)
            result.append(Strip(pdf.Rect(x0, start, x1, bottom), prior_saving + saved))
            # 空栏不应限制下一跨栏区域的位置。
            if len(rows):
                saved_in_band.append(saved)
        prior_saving += min(saved_in_band, default=0)
    return result


def reading_pdf(original, translated, output):
    with pdf.open(original) as source, pdf.open(translated) as raw, pdf.open() as doc:
        if len(source) != len(raw):
            raise ValueError("原稿和译文页数不同。")
        figures = source_figures(source)
        maps, targets, mentions, old_links = [], {}, [], []
        for n, page in enumerate(raw):
            out = doc.new_page(width=page.rect.width, height=page.rect.height)
            strips = strips_for(page, figures[n])
            maps.append(strips)
            for s in strips:
                if not s.box.is_empty and page.get_contents():
                    out.show_pdf_page(
                        s.box + (0, -s.shift, 0, -s.shift), raw, n, clip=s.box
                    )
            old_links.append(page.get_links())
            page_lines = list(lines(page))
            local_equations = 0
            for text, chars, box in page_lines:
                cap = CAPTION.match(text)
                number = NUMBER.search(text)
                if cap:
                    name = ("fig", cap[1])
                    top = figures[n].get(cap[1], box).y0
                    targets.setdefault(
                        name, (n, pdf.Point(box.x0, min(top, box.y0)), box)
                    )
                elif number and (
                    not text[: number.start()].strip()
                    or re.search(r"[=∑∣‖∥∫√]", text[: number.start()])
                ):
                    name = ("eq", number[1])
                    targets.setdefault(name, (n, box.tl, box))
                elif (
                    re.search(r"[=≈∝]", text)
                    and len(text) > 6
                    and not re.search(r"[+−*/=]\s*$", text)
                    and not re.search(r"[一-鿿]|[a-zA-Z]{4,}", text)
                    and not any(r.intersects(box) for r in figures[n].values())
                    and not any(
                        abs((b.y0 + b.y1 - box.y0 - box.y1) / 2) < 7
                        and (0 <= box.x0 - b.x1 < 18 or 0 <= b.x0 - box.x1 < 18)
                        and re.search(r"[一-鿿]|[a-zA-Z]{3,}", t)
                        for t, _, b in page_lines
                    )
                ):
                    local_equations += 1
                    name = ("display", f"{n + 1}·{local_equations}")
                    targets[name] = (n, box.tl, box)
                for m in REFERENCE.finditer(text):
                    if cap and m.start() < cap.end():
                        continue
                    key = ("fig", m[1]) if m[1] else ("eq", m[2])
                    r = pdf.Rect(chars[m.start()]["bbox"])
                    for c in chars[m.start() + 1 : m.end()]:
                        r |= pdf.Rect(c["bbox"])
                    mentions.append((key, n, r))
            for name, (pg, _, r) in list(targets.items()):
                if pg != n or name[0] == "fig" or r is None:
                    continue
                candidates = [
                    (t, b)
                    for t, _, b in page_lines
                    if r.y0 - 85 < b.y1 <= r.y0 + 1
                    and b.x0 < r.x1
                    and r.x0 < b.x1
                    and re.search(r"[一-鿿]{2,}|[a-zA-Z]{4,}", t)
                ]
                if candidates:
                    _, cue = max(candidates, key=lambda item: item[1].y1)
                    mentions.append((name, n, cue))
            # 图号在译文被换行或改写时，仍能从原稿图注定位。
            for k, r in figures[n].items():
                targets.setdefault(
                    ("fig", k), (n, pdf.Point(max(24, r.x0), r.y0), None)
                )

        def new_rect(n, r):
            p = mapped((r.tl + r.br) * 0.5, maps[n])
            return r + (0, p.y - r.y0 - r.height / 2, 0, p.y - r.y0 - r.height / 2)

        def goto(n, r, k, point):
            doc[n].insert_link(
                {"kind": pdf.LINK_GOTO, "from": r, "page": k, "to": point}
            )

        backs = {}
        for name, n, r in mentions:
            if name not in targets:
                continue
            k, p, _ = targets[name]
            dst = mapped(p, maps[k])
            dst.y = max(0, dst.y - 5)
            r = new_rect(n, r)
            doc[n].draw_line(
                (r.x0, r.y1 - 1), (r.x1, r.y1 - 1), color=(0.18, 0.43, 0.6), width=0.35
            )
            goto(n, r, k, dst)
            backs.setdefault(name, (n, r.tl))
        for name, (n, p, r) in targets.items():
            if name in backs and r is not None:
                goto(n, new_rect(n, r), *backs[name])
        for n, links in enumerate(old_links):
            for l in links:
                r = new_rect(n, l["from"])
                if l["kind"] == pdf.LINK_URI and l.get("uri"):
                    doc[n].insert_link(
                        {"kind": pdf.LINK_URI, "from": r, "uri": l["uri"]}
                    )
                elif (
                    l["kind"] == pdf.LINK_NAMED
                    and 0 <= l.get("page", -1) < len(doc)
                    and isinstance(l.get("to"), pdf.Point)
                ):
                    dest_page = l["page"]
                    dest_point = l["to"] * raw[dest_page].transformation_matrix
                    goto(n, r, dest_page, mapped(dest_point, maps[dest_page]))
                elif l["kind"] == pdf.LINK_GOTO and 0 <= l["page"] < len(doc):
                    goto(n, r, l["page"], mapped(l["to"], maps[l["page"]]))

        def label(key):
            kind, number = key
            if kind == "display":
                return "未编号公式 " + number
            return ("图 " if kind == "fig" else "式 ") + number

        # 页脚只占用已确认的空白区域。满版页仍可使用目录导航。
        for n, page in enumerate(doc):
            local = [(key, p) for key, (pg, p, _) in targets.items() if pg == n]
            if not local or page.rotation:
                continue
            width, height = page.rect.width, page.rect.height
            band = pdf.Rect(24, height - 23, width - 24, height - 4)
            pix = page.get_pixmap(clip=band, colorspace=pdf.csGRAY, alpha=False)
            if not pix.samples or min(pix.samples) < 240:
                continue
            x = 28
            for key, p in local:
                text = label(key)
                w = pdf.get_text_length(text, fontname="china-s", fontsize=8)
                if x + w > width - 24:
                    break
                page.insert_text(
                    (x, height - 10),
                    text,
                    fontname="china-s",
                    fontsize=8,
                    color=(0.08, 0.32, 0.53),
                )
                goto(
                    n,
                    pdf.Rect(x, height - 19, x + w, height - 7),
                    n,
                    mapped(p, maps[n]),
                )
                x += w + 14
        toc = raw.get_toc() or source.get_toc()
        if targets:
            toc.append([1, "图与公式", 1])
            for (kind, key), (n, p, _) in sorted(
                targets.items(), key=lambda t: (t[1][0], t[1][1].y)
            ):
                toc.append(
                    [
                        2,
                        label((kind, key)),
                        n + 1,
                        {"kind": pdf.LINK_GOTO, "page": n, "to": mapped(p, maps[n])},
                    ]
                )
        if toc:
            doc.set_toc(toc)
        doc.set_metadata(raw.metadata)
        doc.save(output, garbage=4, deflate=True)
        print(
            f"排版完成：{len(doc)} 页，{len(targets)} 个图／公式目标，"
            f"{sum(k in targets for k, _, _ in mentions)} 处正文跳转。"
        )
