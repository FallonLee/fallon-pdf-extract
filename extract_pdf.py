# -*- coding: utf-8 -*-
"""
fallon-pdf-extract - PDF -> 结构化 Markdown 提取脚本
用法:
  单文件: python extract_pdf.py <pdf_path> [--outdir OUT] [--pages "222-393"] [--chapters "8-17"] [--title "自定义标题"] [--lang en|zh]
  批量:   python extract_pdf.py --batch <dir> [--outdir OUT] [--lang en|zh]   (处理目录下所有 *.pdf)

功能:
  - TOC 定位章节边界 (--chapters 或 --pages 指定范围)
  - 字号分级识别标题层级 (章/节/小节/次小节)
  - 相对页面边距过滤页眉页脚 (自适应 A4/Letter)
  - 多栏布局检测 (双栏/多栏按栏序 + 栏内 y 序重组)
  - find_tables 提取表格, 支持合并单元格(to_markdown), 过滤 Abstract/图形乱码伪表
  - 断词连字符复原, ligature 规范化, 分数/特殊字符映射
  - 跨页段落/列表合并, 连续空行折叠
  - 脚注(页底小字)区分, 作者行启发式识别
"""
import argparse
import glob
import re
import sys
import os
from collections import Counter
import pymupdf  # PyMuPDF

# ---------- 文本清洗 ----------
LIG = [("\ufb01", "fi"), ("\ufb02", "fl"), ("\ufb00", "ff"),
       ("\ufb03", "ffi"), ("\ufb04", "ffl")]

def clean(s):
    for a, b in LIG:
        s = s.replace(a, b)
    # 分数 (¼ ½ ¾ ⅓ ⅔) 与特殊字符保持原样, 不做任何映射 (避免被误转成 '=')
    s = s.replace("\x01", "\u00d7").replace("\x02", "\u00d7")
    # 注意: 软连字符 \xad 不在此时删除, 留待 dehyphen 在换行拼接阶段处理,
    # 否则换行处的软连字符被提前抹掉, 词会被错误地用空格接成 'electron ics'.
    return s

def norm(s):
    return re.sub(r"\s+", " ", s).strip()

def dehyphen(parts, lang="en"):
    """Join lines. en: drop line-break hyphen before lowercase; keep em/en dash."""
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not out:
            out = p
        elif lang == "en" and out.endswith("\u00ad"):
            out = out[:-1] + p  # 换行处软连字符 -> 直接拼接 (electron\xad + ics)
        elif lang == "en" and out.endswith("-") and p[:1].islower():
            out = out[:-1] + p
        elif out.endswith("\u2014") or out.endswith("\u2013"):
            out = out + p
        else:
            out += " " + p
    return out

# ---------- 编号子节标题识别 ----------
# 识别行首编号子节: 1.3 Title / 1.3.1 Title (至少含一个小数点, 即 chapter.section 两级以上).
# 排除纯章号(无小数点, 如 "1 Introduction")与单级编号列表(如 "1. First").
# 仅用于与正文同字号的子节标题(本书子节与正文同字号, 字号探测无法区分).
NUM_HEAD_RE = re.compile(r"^(\d+\.)+\d+\s+(\S)")


def numbered_heading_level(text, maxlen=140):
    """返回 Markdown 标题层级(int, 3=###) 或 None.
    - 行首须为 chapter.section[.subsection...] 形式 (至少两级, 含小数点)
    - 整行长度受限, 排除 TOC 多栏拼接的长块
    - 编号后首字符须大写, 过滤 '2.5 million' 之类句首小数
    """
    t = text.strip()
    if not t or len(t) > maxlen:
        return None
    m = NUM_HEAD_RE.match(t)
    if not m:
        return None
    numpart = re.match(r"^(\d+\.)+\d+", t).group(0)
    after = t[len(numpart):].strip()
    if not after or not (after[0].isupper()):
        return None
    dots = numpart.count(".")  # 1.3 -> 1 ; 1.3.1 -> 2
    level = 2 + dots  # h2=章, 故 1.3 -> h3, 1.3.1 -> h4
    return min(level, 5)


# ---------- 伪表格过滤 ----------
def is_pseudo_table(tbl):
    """True if table is an Abstract/Keywords label box or garbled figure overlay."""
    try:
        rows = tbl.extract()
    except Exception:
        return True
    cells = " ".join((c or "").strip() for r in rows for c in r if c and c.strip())
    cells = norm(cells)
    if cells in ("Abstract", "Keywords", "") or (len(cells) < 12 and cells.startswith("Abstract")):
        return True
    tokens = [t for t in cells.replace("\n", " ").split() if len(t) > 1]
    if not tokens:
        return True
    garbage = 0
    for t in tokens:
        m = re.match(r"^([A-Za-z]+)(\d+)([A-Za-z]+)$", t)
        if m and m.group(1) and m.group(3):
            garbage += 1
        elif any(ch.isdigit() for ch in t) and any(ch.isalpha() for ch in t) \
                and not re.match(r"^[A-Za-z]*\d+$", t):
            garbage += 1
    return garbage / len(tokens) > 0.3

def in_table(x0, y0, x1, y1, tables):
    for tb in tables:
        r = tb.bbox
        if x0 >= r[0] - 2 and y0 >= r[1] - 2 and x1 <= r[2] + 2 and y1 <= r[3] + 2:
            return True
    return False

def table_to_md(tbl):
    # 优先用 PyMuPDF 内置 to_markdown (处理合并单元格), 回退手写
    try:
        md = tbl.to_markdown()
        if md and "|" in md:
            return md.strip()
    except Exception:
        pass
    rows = tbl.extract()
    if not rows:
        return None
    ncols = max(len(r) for r in rows)
    def cell(t):
        return norm(clean((t or "").replace("\n", " "))).replace("|", "\\|")
    hdr = rows[0]
    out = ["| " + " | ".join(cell(c) for c in hdr) + " |", "|" + "---|" * ncols]
    for r in rows[1:]:
        cells = [cell(c) for c in r]
        if len(cells) < ncols:
            cells += [""] * (ncols - len(cells))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)

def reconstruct_table_md(page, bbox, header_expand=30, row_tol=8):
    """无边框/纯文本对齐表格的兜底重建: 在表格 bbox 内按 x/y 聚类文本 span 还原网格.
    PyMuPDF find_tables 对无竖线表格常误判空列/错位, 此时用本函数.
    header_expand: 向上扩展以捕获表头行(表头常在 bbox 上方)."""
    x0, y0, x1, y1 = bbox
    y0e = y0 - header_expand
    try:
        d = page.get_text("dict")
    except Exception:
        return None
    spans = []
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                sx0, sy0, sx1, sy1 = s["bbox"]
                cx, cy = (sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0
                if x0 - 6 <= cx <= x1 + 6 and y0e - 6 <= cy <= y1 + 6:
                    spans.append((cx, cy, s["text"]))
    if len(spans) < 2:
        return None
    # 聚类 y -> 行
    spans.sort(key=lambda t: (round(t[1], 1), t[0]))
    rows, cur = [], []
    for c in spans:
        if not cur or abs(c[1] - cur[-1][1]) <= row_tol:
            cur.append(c)
        else:
            rows.append(cur)
            cur = [c]
    if cur:
        rows.append(cur)
    # 聚类 x -> 列(自适应阈值)
    xs = sorted(set(round(c[0], 1) for c in spans))
    span = (xs[-1] - xs[0]) if len(xs) > 1 else 0
    col_tol = max(30, 0.15 * span) if span > 0 else 30
    cols, cc = [], [xs[0]]
    for x in xs[1:]:
        if x - cc[-1] <= col_tol:
            cc.append(x)
        else:
            cols.append(sum(cc) / len(cc))
            cc = [x]
    cols.append(sum(cc) / len(cc))
    if len(cols) < 2:
        return None
    # 构建网格
    grid = []
    for r in rows:
        row = [""] * len(cols)
        for cx, cy, txt in r:
            ci = min(range(len(cols)), key=lambda i: abs(cols[i] - cx))
            row[ci] = (row[ci] + " " + txt).strip()
        grid.append(row)
    if len(grid) < 2:
        return None
    # 剔除 caption 行(Table X.X 标题, 可能跨整宽落入首行)
    grid = [r for r in grid if not (len(r) >= 1 and re.match(r"^Table\s*\d", r[0].strip()))]
    if len(grid) < 2:
        return None
    ncol = max(len(r) for r in grid)
    def cell(t):
        return t.replace("|", "\\|")
    out = []
    for ri, row in enumerate(grid):
        cells = [cell(row[i]) if i < len(row) else "" for i in range(ncol)]
        out.append("| " + " | ".join(cells) + " |")
        if ri == 0:
            out.append("|" + "---|" * ncol)
    return "\n".join(out)


def drop_empty_columns(md):
    """删除表格中全部为空的列(Phantom 列), 含 ColN 占位空列. 分隔行自动重建."""
    rows = [r for r in md.splitlines() if r.strip().startswith("|")]
    if len(rows) < 2:
        return md
    def parse(r):
        return [c.strip() for c in r.strip().strip("|").split("|")]
    parsed = [parse(r) for r in rows]
    ncol = max(len(p) for p in parsed)
    parsed = [[(p[i] if i < len(p) else "") for i in range(ncol)] for p in parsed]
    sep_re = re.compile(r"^\|[-: |]+\|$")
    data = [p for r, p in zip(rows, parsed) if not sep_re.match(r.strip())]
    if not data:
        return md
    keep = [i for i in range(ncol)
            if any(parsed_cell and not re.match(r"^Col\d+$", parsed_cell.strip())
                   for parsed_cell in (row[i] for row in data))]
    if len(keep) == ncol:
        return md
    out = []
    for r, p in zip(rows, parsed):
        if sep_re.match(r.strip()):
            out.append("|" + "---|" * len(keep))
        else:
            out.append("| " + " | ".join(p[i] for i in keep) + " |")
    return "\n".join(out)


def table_is_bad(md):
    """PyMuPDF 表格是否需兜底重建: 含 ColN 空列占位 或 数据行列数不一致."""
    if not md:
        return True
    if re.search(r"\bCol\d+\b", md):
        return True
    rows = [r for r in md.splitlines() if r.strip().startswith("|")]
    data = [r for r in rows if not re.match(r"^\|[-: |]+\|$", r.strip())]
    if len(data) < 2:
        return False
    counts = [r.count("|") for r in data]
    if len(set(counts)) > 1:
        return True
    return False


# ---------- 章节号解析 (兼容多种 TOC 格式) ----------
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
         "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13,
         "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20}

def parse_chapter_label(title):
    """返回 (章号int, 去号标题) 或 None"""
    t = title.strip()
    # "Chapter 8 ..." / "CHAPTER 8 ..."
    m = re.match(r"^(?:chapter|ch)\.?\s+(\d{1,3})\s*[.:]?\s*(.*)$", t, re.I)
    if m:
        return int(m.group(1)), (m.group(2) or "").strip()
    # "§ 8 ..." / "Sec. 8 ..."
    m = re.match(r"^(?:§|sec\.?|section)\s*(\d{1,3})\s*[.:]?\s*(.*)$", t, re.I)
    if m:
        return int(m.group(1)), (m.group(2) or "").strip()
    # 罗马数字 "VIII. ..."
    m = re.match(r"^([IVX]{1,5})\s*[.:]\s*(.*)$", t)
    if m and m.group(1) in ROMAN:
        return ROMAN[m.group(1)], (m.group(2) or "").strip()
    # "8. Title" / "8: Title" / "8 Title"
    m = re.match(r"^(\d{1,3})\s*([.:]|\s)\s*(.*)$", t)
    if m:
        return int(m.group(1)), (m.group(3) or "").strip()
    return None

# ---------- 图片提取 (存原图 + 图注) ----------
CAP_RE = re.compile(r"^(Figure|Fig\.?|Illustrations?|Illust\.?|Plate|Diagram|Map|Chart)\s*[\d\.]+", re.I)

def _save_image(doc, page, xref, info, rect, images_dir, fname, rel_prefix=""):
    """提取图片为文件, 返回相对路径(xxx.ext 或 <rel_prefix>/xxx.ext)或 None.
    优先 extract_image(无损原图); 失败或原始格式不可存时回退 get_pixmap(clip) 渲染区域."""
    try:
        img = doc.extract_image(xref)
    except Exception:
        img = None
    ext = (img.get("ext") if img else None) or "png"
    data = img.get("image") if img else None
    if not data or ext not in ("png", "jpg", "jpeg", "bmp", "gif"):
        try:
            clip = pymupdf.Rect(*rect)
            pix = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(2, 2))
            ext, data = "png", pix.tobytes("png")
        except Exception:
            return None
    if ext == "jpeg":
        ext = "jpg"
    rel = f"{fname}.{ext}" if not rel_prefix else f"{rel_prefix}/{fname}.{ext}"
    with open(os.path.join(images_dir, f"{fname}.{ext}"), "wb") as f:
        f.write(data)
    return rel

def _find_caption(page, x0, y0, x1, y1):
    """在图片下方寻找图注文本(匹配 CAP_RE, 取最近者)."""
    try:
        d = page.get_text("dict")
    except Exception:
        return None
    best, best_dist = None, 1e9
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        bx0, by0, bx1, by1 = b["bbox"]
        if by0 < y1 - 2:
            continue
        if min(bx1, x1) - max(bx0, x0) < 0.3 * (x1 - x0):
            continue  # x 重叠不足
        txt = norm(clean("".join(s["text"] for l in b["lines"] for s in l["spans"])))
        if not CAP_RE.match(txt):
            continue
        dist = by0 - y1
        if dist < best_dist:
            best_dist, best = dist, txt
    return best

# ---------- 多栏单元构建 ----------
def build_units(page, tabs):
    """返回按阅读顺序(text/table)排列的单元列表: (kind, cx, cy, payload)"""
    d = page.get_text("dict")
    width = page.rect.width
    height = page.rect.height
    raw = []
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        lines = b["lines"]
        if not lines:
            continue
        xs = [(l["bbox"][0] + l["bbox"][2]) / 2 for l in lines]
        cx = sum(xs) / len(xs)
        cy = b["bbox"][1]
        # 文本块中心落在某表格 bbox 内 -> 跳过(表格单独处理)
        if any(t.bbox[0] <= cx <= t.bbox[2] and t.bbox[1] <= cy <= t.bbox[3] for t in tabs):
            continue
        raw.append(("text", cx, cy, b))
    for tb in tabs:
        r = tb.bbox
        raw.append(("table", (r[0] + r[2]) / 2, r[1], tb))
    if not raw:
        return raw
    # 1D 聚类分栏: 相邻单元中心 x 差 > 0.18*width 视为新栏
    order = sorted(range(len(raw)), key=lambda i: raw[i][1])
    cols, cur = [], [order[0]]
    for i in order[1:]:
        if raw[i][1] - raw[cur[-1]][1] > 0.18 * width:
            cols.append(cur)
            cur = [i]
        else:
            cur.append(i)
    cols.append(cur)
    col_x = [sum(raw[i][1] for i in c) / len(c) for c in cols]
    cols_sorted = [c for _, c in sorted(zip(col_x, cols))]
    ordered = []
    for c in cols_sorted:
        c.sort(key=lambda i: raw[i][2])  # 栏内按 y
        ordered.extend(c)
    return [raw[i] for i in ordered]

# ---------- 单文件处理 ----------
def process_single(pdf_path, args, batch=False):
    """提取单个 PDF 为结构化 Markdown.
    batch=True 表示批量调用: 忽略 --title (改用 PDF 元数据标题), 图片目录按文件名隔离以防覆盖."""
    # 列表/段落收集辅助 (供下方 flush 复用, 避免在内层循环重复定义)
    items = cur_kind = cur = None
    def flush():
        nonlocal cur_kind, cur, items
        if cur_kind is not None:
            items.append((cur_kind, cur))
        cur_kind, cur = None, []

    doc = pymupdf.open(pdf_path)

    # ---- 1. 确定页面范围 ----
    toc_titles = {}
    ch_starts = {}
    if args.chapters:
        toc = doc.get_toc()
        for lvl, title, page in toc:
            if lvl > 2:
                continue
            parsed = parse_chapter_label(title)
            if not parsed:
                continue
            n, tlabel = parsed
            if n not in ch_starts or page < ch_starts[n]:
                ch_starts[n] = page - 1
            if n not in toc_titles:
                toc_titles[n] = tlabel or title
        a, b = map(int, args.chapters.split("-"))
        if a in ch_starts:
            start = ch_starts[a]
            end = min(ch_starts.get(b + 1, doc.page_count + 1) - 1, doc.page_count - 1)
            print(f"[info] chapters {a}-{b} -> pdf pages {start+1}-{end+1}")
        else:
            print(f"[warn] TOC 未找到第 {a} 章起始页, 回退为全文档", file=sys.stderr)
            start, end = 0, doc.page_count - 1
    elif args.pages:
        a, b = map(int, args.pages.split("-"))
        start, end = a - 1, b - 1
    else:
        start, end = 0, doc.page_count - 1
    start = max(0, start)
    end = min(end, doc.page_count - 1)

    # ---- 2. 探测字号阈值 (全文档采样, 自适应) ----
    sizes = Counter()
    span = max(1, (end - start) // 30)  # 最多 ~30 个采样页, 覆盖全文
    for pno in range(start, end + 1, span):
        d = doc[pno].get_text("dict")
        height = doc[pno].rect.height
        for b in d["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                y0, y1 = l["bbox"][1], l["bbox"][3]
                if y0 < 0.06 * height or y1 > 0.94 * height:  # 页眉页脚区
                    continue
                t = "".join(s["text"] for s in l["spans"])
                if t.strip():
                    sizes[round(l["spans"][0]["size"], 1)] += len(t)
    if not sizes:
        body_size = 10.0
    else:
        body_size = sizes.most_common(1)[0][0]
    # 标题字号: 大于正文; 排除过小的字号与超大装饰字号; 取前 4 档
    title_sizes = sorted([s for s in sizes if s > body_size + 0.3 and 9 < s < 30],
                         reverse=True)
    lvl_map = {sz: i + 1 for i, sz in enumerate(title_sizes[:4])}  # 1=chapter..4=sub-sub
    print(f"[info] body_size={body_size} title_sizes={title_sizes[:4]}")
    print(f"[info] level_map={lvl_map}")

    # ---- 2b. 输出目录与图片目录 (提前, 供图片提取) ----
    outdir = args.outdir or os.path.dirname(os.path.abspath(pdf_path))
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    # 批量模式: 图片按文件隔离, 避免同名覆盖 (fig_p1_1.png 跨文件冲突)
    # 单文件模式: 图片直接放在 outdir 根目录, 避免嵌套 images/ 子目录
    img_rel = f"{base}_images" if batch else ""
    images_dir = os.path.join(outdir, img_rel) if img_rel else outdir
    all_captions = []  # 图片图注去重用

    # ---- 3. 提取 ----
    all_items = []
    seen_h2 = 0
    for pno in range(start, end + 1):
        skip_chapter_title_blocks = False
        if args.chapters:
            for n, p in ch_starts.items():
                if p == pno:
                    all_items.append(("h2", f"{n}. {toc_titles[n]}"))
                    seen_h2 += 1
                    skip_chapter_title_blocks = True
                    break
        page = doc[pno]
        height = page.rect.height
        try:
            tabs = [t for t in page.find_tables().tables if not is_pseudo_table(t)]
        except Exception:
            tabs = []
        # ---- 3a. 图片提取 (存原图 + 图注) ----
        page_figs = []
        try:
            img_infos = page.get_image_info()
        except Exception:
            img_infos = []
        saved_xrefs = {}
        for info in img_infos:
            xref = info.get("number") or info.get("xref")
            rect = info.get("bbox")
            if not (isinstance(rect, (tuple, list)) and len(rect) == 4):
                continue
            x0, y0, x1, y1 = rect
            if (y1 - y0) < 20 or (x1 - x0) < 20:
                continue  # 装饰线/分隔符
            if y1 > 0.94 * height or y0 < 0.06 * height:
                continue  # 页眉页脚区
            if not xref:
                continue
            if xref in saved_xrefs:
                rel = saved_xrefs[xref]
            else:
                seq = len(saved_xrefs) + 1
                rel = _save_image(doc, page, xref, info, (x0, y0, x1, y1),
                                  images_dir, f"fig_p{pno+1}_{seq}", rel_prefix=img_rel)
                if not rel:
                    continue
                saved_xrefs[xref] = rel
            caption = _find_caption(page, x0, y0, x1, y1)
            if caption:
                all_captions.append(caption)
            page_figs.append((rel, caption))

        units = build_units(page, tabs)
        for unit in units:
            if unit[0] == "table":
                md = table_to_md(unit[3])
                if table_is_bad(md):
                    rec = reconstruct_table_md(page, unit[3].bbox)
                    if rec:
                        md = rec
                if md:
                    md = drop_empty_columns(md)
                    all_items.append(("table", md))
                continue
            blk = unit[3]
            y_bottom = blk["bbox"][3]
            y_top = blk["bbox"][1]
            # 整块丢弃页眉/页脚 (须在 footnote 判定之前, 避免页脚误判为脚注)
            if y_bottom > 0.94 * height or y_top < 0.06 * height:
                continue
            # 脚注: 页底明显小字 -> 单独标记
            block_sizes = [round(s["size"], 1) for l in blk["lines"] for s in l["spans"]]
            avg_sz = sum(block_sizes) / len(block_sizes) if block_sizes else body_size
            if y_bottom > 0.9 * height and avg_sz < body_size - 0.5:
                txt = dehyphen([norm(clean("".join(s["text"] for s in l_["spans"])))
                                for l_ in blk["lines"]], args.lang)
                all_items.append(("footnote", txt))
                continue
            # 行级处理
            lines_here = []
            for l in blk["lines"]:
                x0, y0, x1, y1 = l["bbox"]
                sz = round(l["spans"][0]["size"], 1)
                if (y0 < 0.06 * height or y1 > 0.94 * height) and sz <= 8.6:
                    continue  # 页眉页脚
                if in_table(x0, y0, x1, y1, tabs):
                    continue
                txt = "".join(s["text"] for s in l["spans"])
                if not txt.strip():
                    continue
                bold = any(s["flags"] & 16 for s in l["spans"])
                lines_here.append([y0, sz, txt, bold, x0])
            lines_here.sort(key=lambda L: (L[0], L[4]))
            merged = []
            for ln in lines_here:
                if merged and abs(merged[-1][0] - ln[0]) < 1.5:
                    merged[-1][2] += " " + ln[2]
                    merged[-1][3] = merged[-1][3] or ln[3]
                else:
                    merged.append(ln)
            merged = [ln for ln in merged if ln[1] < 30]
            if not merged:
                continue
            sz = merged[0][1]
            txt = norm(clean(merged[0][2]))
            # 编号子节标题 (1.1 / 1.1.1) 可能与正文同字号或略小, 用模式识别提升为标题.
            # 对整块文本判别, 且仅当块内容基本就是标题时提升, 避免吞掉后续正文.
            full = norm(clean(" ".join(ln[2] for ln in merged)))
            hm = re.match(r"^(\d+\.)+\d+\s+([A-Z][^.]*?)(?:\.|$)", full)
            if hm and len(full) <= len(hm.group(0)) + 2:
                nlv = numbered_heading_level(full)
                if nlv is not None:
                    all_items.append((f"h{nlv}", hm.group(0).rstrip(".").strip()))
                    continue
            # 作者行: 须在标题定级之前判定 (h2 后首个含人名的块)
            if args.chapters and body_size < sz <= body_size + 2.5 and seen_h2 <= 1 \
                    and re.search(r",\s|\sand\s| & ", txt) and len(txt) < 200:
                all_items.append(("authors", "*" + txt + "*"))
                continue
            if sz in lvl_map:
                lvl = lvl_map[sz]
                if skip_chapter_title_blocks and lvl == 1:
                    continue
                title = dehyphen([norm(clean(l[2])) for l in merged], args.lang)
                all_items.append((f"h{lvl + 1}", title))
                continue
            if sz >= body_size - 0.4:  # body or author line
                items, cur_kind, cur = [], None, []
                BULLETS = ("\u2022", "\u00b7", "\u2023", "\u25cf", "*", "\u25aa", "\u2043")
                for ln in merged:
                    t = norm(clean(ln[2]))
                    if not t:
                        continue
                    lead = t.lstrip()
                    if lead[:1] in BULLETS:
                        flush()
                        cur_kind = "b"
                        rest = lead.lstrip("".join(BULLETS)).strip()
                        if rest:
                            cur.append(rest)
                        continue
                    if cur_kind is None:
                        cur_kind = "p"
                    cur.append(t)
                flush()
                for kind, parts in items:
                    if kind == "b":
                        all_items.append(("li", dehyphen(parts, args.lang)))
                    else:
                        all_items.append(("p", dehyphen(parts, args.lang)))
                continue
            # 其它小字(如作者简介 8.5pt) -> 保留为段落
            all_items.append(("p", dehyphen([norm(clean(l[2])) for l in merged], args.lang)))

        # 图片 items 置于页末 (原图已存 images/, 图注重复去重见 step4 之后)
        for rel, caption in page_figs:
            all_items.append(("figure", f"![{os.path.basename(rel)}]({rel})"))
            if caption:
                all_items.append(("figcaption", caption))

    # ---- 3c. 清掉与下方表格首行重复的表头段落 ----
    # 重建器已把表头纳入表格, 主提取又独立产出该段落(表头在表格 bbox 上方), 需去重.
    _cleaned = []
    for k, (kind, text) in enumerate(all_items):
        if kind == "p" and k + 1 < len(all_items) and all_items[k + 1][0] == "table":
            tbl = all_items[k + 1][1]
            rows = [r for r in tbl.splitlines() if r.strip().startswith("|")]
            if rows:
                cells = [c.strip().replace("*", "") for c in rows[0].strip().strip("|").split("|")]
                head_norm = " ".join(c for c in cells if c).lower()
                para_norm = re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
                if head_norm and para_norm and head_norm == para_norm:
                    continue  # 跳过重复表头段落
        _cleaned.append((kind, text))
    all_items = _cleaned

    # ---- 4. 跨页合并 (p->p, li->li, p/li 续接) ----
    merged_items = []
    for kind, text in all_items:
        if merged_items and merged_items[-1][0] in ("p", "li") and kind in ("p", "li"):
            prev_k, prev = merged_items[-1]
            cur_start = text[:1] if text else ""
            if args.lang == "en":
                if prev.endswith("-") and cur_start.islower():
                    merged_items[-1] = (prev_k, prev[:-1] + text)
                    continue
                if (prev.endswith("\u2014") or prev.endswith("\u2013")) and cur_start.isalpha():
                    merged_items[-1] = (prev_k, prev + text)
                    continue
                if not re.search(r"[.!?:;\u201d\"']$", prev) and cur_start.islower():
                    merged_items[-1] = (prev_k, prev + " " + text)
                    continue
            else:  # zh: 中文无词间空格, 按句末/句首标点判断是否续接, 不插入空格
                prev_end = prev[-1:] if prev else ""
                if not re.search(r"[。！？!?；;:：\.…\u201d”]", prev_end) \
                        and not re.search(r"[““「（【《]", cur_start):
                    merged_items[-1] = (prev_k, prev + text)
                    continue
        merged_items.append((kind, text))

    # 4b. 图注重复过滤: 移除被图片图注覆盖的普通段落(避免正文重复出现图注)
    if all_captions:
        def _cap_match(t):
            t = t.strip()
            for cap in all_captions:
                c = cap.strip()
                if not c:
                    continue
                if t == c or (len(c) > 15 and t.startswith(c)):
                    return True
            return False
        merged_items = [(k, t) for (k, t) in merged_items
                        if not (k == "p" and _cap_match(t))]

    # ---- 5. 渲染 (修复列表断裂: 连续列表项间不插空行) ----
    if batch:
        title = f"{doc.metadata.get('title', base)} (extracted)"
    else:
        title = args.title or f"{doc.metadata.get('title', 'PDF')} (extracted)"
    out = ["# " + title, "", "> 由 fallon-pdf-extract 从 PDF 提取生成", ""]
    prev = None
    for kind, text in merged_items:
        if kind == "h2":
            line = f"## {text}"
        elif kind == "h3":
            line = f"### {text}"
        elif kind == "h4":
            line = f"#### {text}"
        elif kind == "h5":
            line = f"##### {text}"
        elif kind == "label":
            line = f"**{text}**"
        elif kind == "authors":
            line = text
        elif kind == "footnote":
            line = f"> *注：{text}*"
        elif kind == "li":
            line = "- " + text
        elif kind == "table":
            line = text
        elif kind == "figure":
            line = text
        elif kind == "figcaption":
            line = f"*{text}*"
        else:
            line = text
        if kind == "li" and prev == "li":
            out.append(line)  # 连续列表项: 不插空行
        elif kind == "figcaption" and prev == "figure":
            out.append(line)  # 图注紧跟图, 不插空行
        else:
            out.append("")
            out.append(line)
        prev = kind
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    result = result.replace("\u00ad", "")  # 清理任何残留软连字符

    outpath = os.path.join(outdir, f"{base}.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(result)

    # ---- 6. 校验摘要 ----
    n_h2 = len(re.findall(r"^## ", result, re.M))
    n_h3 = len(re.findall(r"^### ", result, re.M))
    n_tab = len(re.findall(r"^\|[-|]+\|$", result, re.M))
    n_fig = len(re.findall(r"^!\[", result, re.M))
    print(f"[done] {outpath}")
    print(f"[stats] chars={len(result)} h2={n_h2} h3={n_h3} tables={n_tab} figures={n_fig}")
    return outpath


# ---------- 入口 / 模式分发 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="?", default=None, help="PDF 文件路径 (单文件模式)")
    ap.add_argument("--batch", default=None, help="批量模式: 处理指定目录下的所有 *.pdf")
    ap.add_argument("--outdir", default=None, help="输出目录 (默认 PDF 同目录; 批量模式可统一输出到此)")
    ap.add_argument("--pages", default=None, help="页码范围, 如 '222-393' (1-based PDF 页码)")
    ap.add_argument("--chapters", default=None, help="章节范围, 如 '8-17' (从 TOC 自动定位)")
    ap.add_argument("--title", default=None, help="输出文档标题 (批量模式忽略)")
    ap.add_argument("--lang", default="en", choices=["en", "zh"], help="语言, 影响断词规则")
    args = ap.parse_args()

    if args.batch:
        d = args.batch
        if not os.path.isdir(d):
            print(f"[error] --batch 目录不存在: {d}", file=sys.stderr)
            sys.exit(1)
        pdfs = sorted(glob.glob(os.path.join(d, "*.pdf")))
        if not pdfs:
            print(f"[warn] 目录内无 PDF: {d}", file=sys.stderr)
            return
        print(f"[batch] 发现 {len(pdfs)} 个 PDF @ {d}")
        ok = 0
        for pdf in pdfs:
            try:
                process_single(pdf, args, batch=True)
                ok += 1
            except Exception as e:
                print(f"[error] 处理失败 {os.path.basename(pdf)}: {e}", file=sys.stderr)
        print(f"[batch] 完成 {ok}/{len(pdfs)}")
    else:
        if not args.pdf:
            ap.error("缺少 PDF 路径: 单文件模式需提供 <pdf>, 或使用 --batch <dir>")
        process_single(args.pdf, args, batch=False)


if __name__ == "__main__":
    main()
