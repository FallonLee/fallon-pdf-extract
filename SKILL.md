---
name: fallon-pdf-extract
description: 将 PDF 提取为结构化 Markdown 的技能。当用户要求把 PDF 转成 md、PDF 转 Markdown、提炼 PDF 的某章或某部分（如"第 8-17 章"）、或做知识库 PDF 批量结构化提取时使用本技能。适用于学术文献、教材、技术手册、行业报告、项目文档、白皮书等文本型 PDF。保留标题层级（章/节/小节）、列表、表格、图注，并自动修复断词连字符、特殊字符、跨页段落、多栏乱序、列表断裂，过滤页眉页脚与图形噪声。扫描版 PDF 需要 OCR，本技能不做。
agent_created: true
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["python3"] },
        "install":
          [
            {
              "id": "venv",
              "kind": "exec",
              "command": "python3 -m venv .venv && (.venv/bin/pip install pymupdf || .venv/Scripts/pip.exe install pymupdf)",
              "label": "Create virtual environment and install pymupdf from PyPI",
            },
          ],
      },
  }
---

# fallon-pdf-extract — PDF → Markdown 提取

将 PDF 提取为结构化 Markdown，保留标题层级、列表、表格与图注，并修复 PDF 文本层常见噪声（含多栏、跨页、脚注等进阶处理）。

## 安装（依赖 pymupdf）

- **从技能市场安装**：环境由技能元数据自动创建本地 `.venv` 并安装 `pymupdf`，无需手动操作。
- **从 GitHub 克隆手动安装**：在技能目录下执行
  - Linux / macOS：`python3 -m venv .venv && .venv/bin/pip install pymupdf`
  - Windows (PowerShell)：`python3 -m venv .venv; .venv\Scripts\pip.exe install pymupdf`
  - 也可用项目根 `requirements.txt`：`pip install -r requirements.txt`

## 触发场景

- 用户提供 PDF 路径，要求转成 Markdown
- 提炼 PDF 的某一部分 / 某几章（如 "第 8-17 章"）
- 知识库 PDF 批量转 Markdown

## 执行流程

1. **确认输入**：单文件模式提供 PDF 路径；可选 `--chapters "8-17"`（从 TOC 定位）或 `--pages "222-393"`；可选 `--outdir` 输出目录、`--title` 文档标题、`--lang en|zh`。**批量模式**用 `--batch <目录>` 处理该目录下所有 `*.pdf`（忽略 `--title`，图片按文件隔离到 `<base>_images/`，单个文件失败不影响其余）。
2. **运行环境**：脚本依赖 `pymupdf`，由技能安装时自动建好的本地 `.venv` 提供（见上方「安装」一节）。无需本机全局 Python 或硬编码路径。
3. **运行提取脚本**（先 `cd` 到技能目录）：
   - **Linux / macOS**：
     ```bash
     ./.venv/bin/python scripts/extract_pdf.py <pdf_path> [--chapters "8-17"] [--pages "222-393"] [--outdir <dir>] [--title "标题"] [--lang en|zh]
     ```
   - **Windows (PowerShell / Git Bash)**：
     ```bash
     .venv\Scripts\python.exe scripts\extract_pdf.py <pdf_path> [--chapters "8-17"] [--pages "222-393"] [--outdir <dir>] [--title "标题"] [--lang en|zh]
     ```
   - **批量模式**（`--batch <目录>` 处理该目录下所有 `*.pdf`，忽略 `--title`）：
     ```bash
     # Linux / macOS
     ./.venv/bin/python scripts/extract_pdf.py --batch <目录> [--outdir <dir>] [--lang en|zh]
     # Windows
     .venv\Scripts\python.exe scripts\extract_pdf.py --batch <目录> [--outdir <dir>] [--lang en|zh]
     ```
   - **端到端示例**：技能自带 `examples/`（`sample.pdf` → `sample.md` + `fig_p1_1.png`），可直接运行验证效果：
     ```bash
     ./.venv/bin/python scripts/extract_pdf.py examples/sample.pdf --outdir examples --lang en
     ```
4. **输出位置**：默认与 PDF 同目录，生成 `<PDF名>.md`；脚本会打印校验统计（字数、h2/h3 数、表格数）。
5. **质量检查**（必做）：打开生成的 md，抽查
   - 章节标题是否完整、层级是否合理（多栏是否按阅读顺序、列表是否连续不断裂）
   - 表格是否保留（`|` 管道格式）、合并单元格是否完整
   - 有无残留断词（如 "technol- ogy"）、分数符号是否正常（¼ ½ ¾）、乱码、孤立残片
   - 页眉页脚/页码是否已去除、页底脚注是否单独标记为 `> *注：...*`
6. **交付**：用 present_files 展示生成的 md 文件。
7. **（可选）质量校验**：转完后运行 `scripts/verify.py <md> --pdf <原pdf>` 做召回率兜底 + 随机抽段本地 diff，输出 PASS/WARN 与低相似度片段。纯本地，不消耗 LLM token。

## 关键技术规则（踩坑沉淀）

| 规则 | 说明 |
|------|------|
| 页眉页脚过滤 | **相对页面边距**：`y < 6%·页高` 或 `y > 94%·页高` 且字号 ≤8.6 才丢弃，自适应 A4/Letter 等不同尺寸；作者简介（8.5pt）在正文区须保留。整块页眉/页脚在 footnote 判定**之前**丢弃，避免页脚误判为脚注 |
| 脚注识别 | 页底明显小字（`y > 90%·页高` 且 `字号 < body-0.5`）单独标记 `> *注：...*`（实验特性，复杂脚注可能遗漏） |
| 断词复原 | 行尾 `-` + 下词小写开头 → 删连字符合并；em/en dash（`—`/`–`）保留并紧接 |
| 特殊字符 | ligature 规范化（ﬁ→fi, ﬂ→fl, ﬀ→ff, ffi→ffi, ffl→ffl）；分数 `¼ ½ ¾ ⅓ ⅔` 保留原字符（不再错误映射为 `=`）；`\x01`/`\x02` → `×`；软连字符 `\xad` 删除 |
| 伪表格过滤 | 内容仅 "Abstract"/"Keywords" 的标签框；含乱码 token（字母数字混合如 "B57uilding" 占比 >30%）的图形标注 |
| 表格提取 | 优先 `Table.to_markdown()`（支持合并单元格 colspan/rowspan），回退手写管道表；跨页表格按页分别提取（PyMuPDF 为单页检测，无跨页自动拼接） |
| 跨页合并 | 上段无句末标点 + 下段小写开头 → 合并（覆盖 p→p、li→li、p/li 续接） |
| 列表断裂修复 | 连续列表项之间**不插空行**，避免 Markdown 渲染把同一列表拆成多个独立列表 |
| 字号分级 | 全文档采样探测 body_size（字符量最大档）；更大字号按降序映射 章/节/小节/次小节（h2-h5）；排除过小的字号(≤9pt)与超大装饰字号(≥30pt) |
| 章节定位 | 正则兼容 `8.` / `8:` / `8 ` / `Chapter 8` / `§8` / 罗马数字；通过 TOC 第 1-2 级条目标起始页；章节标题由 TOC 输出（去前缀、加 `N. `），页内同章大字号标题块跳过 |
| 多栏检测 | 按行中心 x 做 1D 聚类（相邻中心差 >18%·页宽即切栏），栏按 x 升序、栏内按 y 排序重组，纠正双栏/多栏段落交错乱序 |
| 作者行 | h2 后首个 body 级块（`body < 字号 ≤ body+2.5` 且含 `, ` / ` and ` / ` & ` 且 <200 字符）→ 输出为 `*作者*` |
| block = 段落 | PyMuPDF dict 模式每 block 一组行，天然保留段落边界 |
| 图片提取 | `page.get_image_info()` 取 xref+位置；优先 `doc.extract_image()` 存无损原图(png/jpg/bmp/gif)，失败回退 `page.get_pixmap(clip=区域, 2x)` 渲染；图片存 `<outdir>/fig_p{页码}_{序号}.{ext}`（批量模式隔离到 `<outdir>/<base>_images/` 以防同名覆盖），MD 插入对应 `![图](...)`；仅提取尺寸 >20px 且非页眉页脚区的图，跳过装饰线/分隔符 |
| 图注识别 | 图片下方最近、x 重叠 >30%、且匹配 `^(Figure\|Fig.\|Illustrations?\|Illust.\|Plate\|Diagram\|Map\|Chart)\s*[\d.]+` 的文本块 → 输出为 `*图注*` 斜体；正文里被识别为图注的段落自动去重（不重复出现） |

## 已知边界

- **扫描版 PDF**（纯图片无文字层）需要 OCR，本技能不做，应告知用户。
- **复杂排版**（浮动框、公式）可能丢失部分格式；LaTeX 生成的书（Springer 等）效果最好。
- 图表内的图例文字（Legend、坐标轴标签）会作为零散行保留。
- 原文数字格式保留（如德式小数 "0,6" 不转换）。
- 跨页表格按页分别提取（PyMuPDF 为单页检测，无跨页自动拼接）；合并单元格经 `to_markdown` 处理。
- 脚注为实验特性：仅识别页底明显小字块，复杂脚注/尾注可能遗漏或误标。
- 多栏检测对三栏及窄栏距可能失效；异常时回退为整页 y 序。
- 章节号依赖 TOC；无 TOC 的 PDF 用 `--pages` 指定范围，章节标题由字号探测生成（无 `N. ` 前缀）。
- **图片**：原图存于输出目录下的 `images/` 子目录（批量模式为 `<base>_images/`），可作为二次素材（如小红书配图）；图片统一置于**页末**（非原文精确坐标位置）。
- 图注仅识别英文/通用前缀（Figure/Fig./Illust./Plate/Diagram/Map/Chart），中文"图X"暂未覆盖；复杂或跨页图注可能遗漏。
- 扫描版 PDF 的图片为位图，仍按方案 B 提取为图片文件，但图内文字不可检索（需 OCR 另做）。
- 原图提取失败时回退区域渲染（2x），可能与原文略有视觉差异；`extract_image` 取不到时方才渲染。

## 参数速查

| 参数 | 用途 | 示例 |
|------|------|------|
| `pdf` | PDF 路径（单文件模式必填） | `D:\Knowledgebase\xxx.pdf` |
| `--batch` | 批量模式：处理 `<目录>` 下所有 `*.pdf`（忽略 `--title`） | `D:\Knowledgebase\papers` |
| `--chapters` | 章节范围（从 TOC 自动定位，兼容多种章号格式） | `8-17` |
| `--pages` | 页码范围（1-based PDF 页码） | `222-393` |
| `--outdir` | 输出目录 | `D:\Knowledgebase\extracted` |
| `--title` | 输出标题 | `Part II Case Studies` |
| `--lang` | 语言（en/zh），影响断词规则 | `en` |

## 质量校验（verify.py）

转完 PDF 后可选运行，自动检验提取质量（纯本地，零 token）：

```bash
# Linux / macOS
./.venv/bin/python scripts/verify.py <md_path> --pdf <pdf_path> [--pages "222-393"] [--sample N] [--seg-len 800] [--seed 42] [--threshold 0.6]
# Windows
.venv\Scripts\python.exe scripts\verify.py <md_path> --pdf <pdf_path> [--pages "222-393"] [--sample N] [--seg-len 800] [--seed 42] [--threshold 0.6]
```

- **召回率兜底**：原文 `get_text()` 全量 vs MD 纯文字量比值（图片文字不计入，偏低属正常）
- **随机抽段本地 diff**：按页分层抽样（层数=抽样段数，seed 可复现），每层随机抽一页，从原文随机抽段在 MD 全文搜最相似子串，报告相似度
- **抽样规模**：`n = clamp(round(√页数 / 1.5), 5, 15)`；单段上限 800 字
- 输出平均/最低相似度，低于阈值（默认 0.6）的片段列出原文与 MD 对照，供复查
