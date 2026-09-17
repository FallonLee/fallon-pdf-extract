# 示例 / Examples

本目录提供一个最小可运行的端到端示例，便于在发布前快速验证 skill 行为，也作为技能市场上架时的演示素材。

## 文件

| 文件 | 说明 |
|------|------|
| `sample.pdf` | 由脚本生成的样例 PDF（含 H1/H2/H3 标题层级、正文段落、一个 2×2 表格、一张带图注的图片） |
| `sample.md` | 用本 skill 对 `sample.pdf` 提取产出的结构化 Markdown |
| `images/fig_p1_1.png` | 提取出的原图（与 `sample.md` 中的 `![...](images/...)` 引用对应） |

## 复现命令

```bash
# 单文件
python scripts/extract_pdf.py examples/sample.pdf --outdir examples --lang en

# 批量处理整个目录（输出同名 .md，图片按文件隔离到 <base>_images/）
python scripts/extract_pdf.py --batch examples --lang en
```

## 输出要点对照

- `# Sample Academic Paper` —— 取自 PDF 元数据标题（H1）
- `## 1. Introduction` / `### 1.1 Background` —— 由字号分级 + 编号子节识别得到
- 正文段落 —— 断词连字符复原、跨行合并
- 表格 —— `find_tables` 检测，合并单元格经 `to_markdown` 处理
- 图片 + 图注 —— 原图存盘于 `examples/` 根目录，图注去重后置于页末

> 注：`examples/` 为演示资源，会被一并打包发布；如体积过大可删去 `fig_p1_1.png` 仅保留 `sample.pdf` 与 `sample.md`。
