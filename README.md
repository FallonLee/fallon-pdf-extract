# fallon-pdf-extract

**PDF → 结构化 Markdown 提取工具（CLI / 技能包）**

将任意 PDF 提取为结构清晰的 Markdown：保留标题层级（章/节/小节）、列表、表格、图注，并修复 PDF 文本层常见噪声——多栏错序、跨页段落、断词连字符、页眉页脚、脚注、列表断裂。适用于学术文献、教材、技术手册、行业报告、项目文档、白皮书等几乎所有文本型 PDF。扫描版 PDF 需 OCR，本工具不处理。

## 功能亮点

| 能力 | 说明 |
|------|------|
| 标题层级 | 全文档采样探测正文字号，更大字号按降序映射 章(h2)/节(h3)/小节(h4)/次小节(h5) |
| 多栏重排 | 按文本块 x 坐标 1D 聚类分栏，修复双栏阅读顺序 |
| 跨页合并 | 段落 / 列表跨页续接（en 按小写续接、zh 按句末标点续接） |
| 表格提取 | PyMuPDF `find_tables()` 检测，优先 `Table.to_markdown()`（支持合并单元格），过滤伪表 |
| 图片提取 | 原图无损存盘 + 图注匹配，输出到输出目录根，可作二次素材（如配图） |
| 批量模式 | `--batch <dir>` 整目录处理，图片按文件隔离，单文件失败不中断 |
| 章节定位 | `--chapters "8-17"` 从 TOC 自动定位，兼容罗马数字 / § / 多种章号格式 |

## 安装

**方式 A — 技能市场（推荐）**
在对应平台的技能市场搜索 `fallon-pdf-extract` 安装，依赖会自动建本地 `.venv` 并安装 `pymupdf`。

**方式 B — 手动 / Git 克隆**
```bash
git clone <本仓库地址> fallon-pdf-extract
cd fallon-pdf-extract
python3 -m venv .venv
# Linux / macOS
.venv/bin/pip install pymupdf
# Windows (PowerShell)
.venv\Scripts\pip.exe install pymupdf
```

依赖：`pymupdf`（唯一第三方依赖，见 `requirements.txt`）。

## 用法

单文件：
```bash
# Linux / macOS
.venv/bin/python scripts/extract_pdf.py <pdf_path> [--chapters "8-17"] [--pages "222-393"] [--outdir <dir>] [--title "标题"] [--lang en|zh]
# Windows (PowerShell)
.venv\Scripts\python.exe scripts\extract_pdf.py <pdf_path> [--chapters "8-17"] [--pages "222-393"] [--outdir <dir>] [--title "标题"] [--lang en|zh]
```

批量（整目录）：
```bash
.venv/bin/python scripts/extract_pdf.py --batch <dir> [--lang en|zh]
```

端到端示例（自带 `examples/`）：
```bash
.venv/bin/python scripts/extract_pdf.py examples/sample.pdf --outdir examples --lang en
# 输出 examples/sample.md + examples/fig_p1_1.png
```

质量校验（可选）：
```bash
.venv/bin/python scripts/verify.py <md_path> --pdf <pdf_path> [--pages "222-393"] [--sample 12] [--threshold 0.6]
```

参数速查：

| 参数 | 用途 | 示例 |
|------|------|------|
| `pdf` | PDF 路径（必填，单文件模式） | `paper.pdf` |
| `--batch` | 批量模式，后接目录 | `./papers` |
| `--chapters` | 章节范围（从 TOC 定位） | `8-17` |
| `--pages` | 页码范围（1-based PDF 页） | `222-393` |
| `--outdir` | 输出目录 | `./out` |
| `--title` | 文档标题（批量模式忽略） | `"My Paper"` |
| `--lang` | 语言，影响断词/续接规则 | `en` / `zh` |

## 目录结构

```
fallon-pdf-extract/
├── SKILL.md              # 技能定义（含触发词与依赖元数据）
├── FLOW.md               # 处理流程详解
├── README.md             # 本文件
├── requirements.txt      # pip 依赖（pymupdf）
├── .gitignore            # 排除 .venv / __pycache__
├── skill.icon.png        # 图标（512×512，≤500KB）
├── scripts/
│   ├── extract_pdf.py    # 主提取脚本
│   └── verify.py         # 提取质量校验脚本
└── examples/             # 演示资源（两级目录，无嵌套）
    ├── sample.pdf        # 程序化生成的样例 PDF
    ├── sample.md         # 提取输出样例
    ├── fig_p1_1.png      # 提取出的原图
    └── README.md         # 示例说明
```

> 目录层级限制：打包仅支持两级目录结构（根目录 / 二级目录 / 文件），故 `examples/` 内图片直接置于其根，不另设 `images/` 子目录。

## 适用场景（触发词）

把 PDF 转成 md、PDF 转 Markdown、PDF 提取、提炼 PDF 第 X 章/第 X 部分、PDF 结构化、PDF 转文字、知识库 PDF 提取。

## 已知边界

- 扫描版 / 图片型 PDF 无法提取（需 OCR，未内置）。
- 表格为单页检测，**无跨页自动拼接**（跨页长表会断开）。
- 三栏以上复杂版面检测可能失效。
- 图片统一置于页末（非原文精确坐标位置）。
- 中文图注识别有限（`图\d+`/`图表` 前缀支持中，其他中文图注格式可能漏匹配）。

## 许可

MIT
