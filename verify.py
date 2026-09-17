# -*- coding: utf-8 -*-
"""
fallon-pdf-extract - 提取质量校验脚本 (verify.py)

用法:
  python verify.py <md_path> --pdf <pdf_path> [--pages "222-393"] [--chapters "8-17"]
         [--sample N] [--seg-len 800] [--seed 42] [--threshold 0.6]

功能:
  - 召回率兜底: 原文 get_text() 全量 vs MD 纯文字量, 比值接近 1 说明无丢字
    (图片内文字不计入 MD, 故含图 PDF 召回率偏低属正常, 仅作参考)
  - 随机抽段本地 diff: 按页分层抽样(层数=抽样段数, seed 可复现), 每层随机抽一页,
    从该页原文随机抽一段, 在 MD 全文滑窗搜最相似子串, 报告相似度
  - 纯本地计算 (pymupdf + difflib), 不消耗任何 LLM token

输出:
  - 召回率 / MD 统计(h2表数/表格行数/图片数)
  - 抽样段数, 平均 & 最低相似度
  - 低于阈值的片段: 列出原文片段与 MD 中最相似片段, 供复查
  - 结论 PASS / WARN
"""
import argparse
import re
import sys
import os
import random
import difflib

# 复用 extract_pdf 的章节号解析, 保证校验阶段与提取阶段的章节定位逻辑一致
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from extract_pdf import parse_chapter_label
except Exception:
    parse_chapter_label = None


def norm(s):
    """去所有空白, 用于字符量比较与相似度比对."""
    return re.sub(r"\s+", "", s)


def md_plain(md):
    """剥离 markdown 标记, 仅留纯文字."""
    t = re.sub(r"!\[.*?\]\(.*?\)", " ", md)          # 图引用
    t = re.sub(r"```.*?```", " ", t, flags=re.S)     # 代码块
    t = re.sub(r"[#>*`|_]", " ", t)                  # 标题/强调/表格等标记
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md", help="提取生成的 .md 文件路径")
    ap.add_argument("--pdf", default=None, help="原 PDF 路径 (用于召回率与抽段原文)")
    ap.add_argument("--pages", default=None, help="页码范围, 如 '222-393' (1-based)")
    ap.add_argument("--chapters", default=None, help="章节范围, 如 '8-17' (需 --pdf)")
    ap.add_argument("--sample", type=int, default=None, help="抽样段数 (默认按页数自动)")
    ap.add_argument("--seg-len", type=int, default=800, help="单段字符上限")
    ap.add_argument("--seed", type=int, default=42, help="随机种子 (可复现)")
    ap.add_argument("--threshold", type=float, default=0.6, help="相似度告警阈值")
    args = ap.parse_args()

    import pymupdf  # PyMuPDF

    # ---- 1. 读取 MD ----
    with open(args.md, encoding="utf-8") as f:
        md = f.read()
    ext_plain = md_plain(md)
    ext_norm = norm(ext_plain)

    # MD 统计
    n_h2 = len(re.findall(r"^## ", md, re.M))
    n_tab = len(re.findall(r"^\|[-|]+\|$", md, re.M))
    n_fig = len(re.findall(r"^!\[", md, re.M))

    # ---- 2. 确定原文页范围 ----
    doc = None
    pages = None
    total_pages = 0
    if args.pdf:
        doc = pymupdf.open(args.pdf)
        total_pages = doc.page_count
        if args.pages:
            a, b = map(int, args.pages.split("-"))
            pages = range(a - 1, b)
        elif args.chapters:
            toc = doc.get_toc()
            starts = {}
            for lvl, title, page in toc:
                if lvl > 2:
                    continue
                n = None
                if parse_chapter_label:
                    parsed = parse_chapter_label(title)
                    if parsed:
                        n = parsed[0]
                if n is None:
                    m = re.match(r"^(\d{1,3})\s*[.:]", title)
                    if m:
                        n = int(m.group(1))
                if n is None:
                    continue
                starts[n] = min(starts.get(n, page), page - 1)
            if starts:
                a, b = map(int, args.chapters.split("-"))
                if a in starts:
                    pages = range(starts[a], starts.get(b + 1, total_pages))
        if pages is None:
            pages = range(total_pages)

    # ---- 3. 召回率兜底 ----
    recall = None
    if doc is not None and pages is not None:
        orig_full = "\n".join(doc[p].get_text() for p in pages)
        orig_norm = norm(orig_full)
        if orig_norm:
            recall = len(ext_norm) / len(orig_norm)

    # ---- 4. 随机抽段本地 diff (分层抽样) ----
    sample_n = args.sample or max(5, min(15, round((total_pages or 50) ** 0.5 / 1.5)))
    ratios = []
    low = []
    if doc is not None and pages is not None:
        plist = list(pages)
        if len(plist) >= sample_n:
            step = len(plist) / sample_n
            rng_layer = random.Random(args.seed)
            layer_pages = []
            for i in range(sample_n):
                lo, hi = int(i * step), int((i + 1) * step)
                seg = plist[lo:hi] if hi > lo else plist[lo:lo + 1]
                if seg:
                    layer_pages.append(rng_layer.choice(seg))
        else:
            rng_layer = random.Random(args.seed)
            layer_pages = rng_layer.sample(plist, len(plist))
        rng_frag = random.Random(args.seed + 1)
        L = args.seg_len
        step_w = max(1, L // 2)
        for p in layer_pages:
            ptxt = norm(doc[p].get_text())
            if len(ptxt) < 50:
                continue
            start = rng_frag.randint(0, max(0, len(ptxt) - L))
            frag = ptxt[start:start + L]
            if len(frag) < 30:
                continue
            best, best_seg = 0.0, ""
            for i in range(0, max(1, len(ext_plain) - len(frag)), step_w):
                window = ext_plain[i:i + len(frag)]
                if not window.strip():
                    continue
                r = difflib.SequenceMatcher(None, frag, norm(window)).ratio()
                if r > best:
                    best, best_seg = r, window
            ratios.append(best)
            if best < args.threshold:
                low.append((p + 1, frag[:120], best_seg[:120], round(best, 2)))

    # ---- 5. 报告 ----
    print("=" * 50)
    print("[verify] fallon-pdf-extract 质量校验")
    print(f"[verify] md         = {args.md}")
    print(f"[verify] h2={n_h2}  tables={n_tab}  figures={n_fig}")
    if recall is not None:
        print(f"[verify] 召回率     = {recall:.1%}  (含图 PDF 偏低属正常, 仅参考)")
    print(f"[verify] 抽样段数   = {len(ratios)}  阈值={args.threshold}")
    if ratios:
        print(f"[verify] 平均相似度 = {sum(ratios)/len(ratios):.1%}  最低={min(ratios):.1%}")
    if low:
        print(f"[verify] 低相似度片段 {len(low)} 处, 建议复查:")
        for pno, frag, seg, r in low:
            print(f"  - 页{pno} ratio={r}")
            print(f"      原文: {frag}")
            print(f"      MD  : {seg}")
        print("[verify] 结论: WARN")
    else:
        print("[verify] 结论: PASS")
    print("=" * 50)


if __name__ == "__main__":
    main()
