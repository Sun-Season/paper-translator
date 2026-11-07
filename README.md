# 论文翻译工具

将英文论文 PDF 翻译成中文 PDF 或 Markdown。默认 macOS 启动器使用千问视觉模型翻译，以 LaTeX 排版，再运行程序验收和模型视觉复核。

## 开始使用

需要 Python 3.12、Tectonic 或 XeLaTeX，以及宋体 Songti SC 和 Times New Roman。首次运行需要联网安装依赖，模型调用按服务商规则计费。

1. 双击 **翻译论文.command**。
2. 选择 PDF，按提示填写视觉模型的 API 密钥。
3. 在原稿旁的结果目录查看 `paper.pdf` 和验收记录。

双击 **其他导出选项.command** 可以选择 Markdown、PDF + Markdown 或其他后端。

## 命令行

在工程根目录安装依赖。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

配置 `OPENAI_API_KEY` 后，执行默认视觉流程。

```sh
.venv/bin/python translate.py "/路径/论文.pdf"   --backend vision --layout auto --format both   --model deepseek-flash   --base-url https://api.deepseek.com   --out "/路径/译文"
```

也支持 `.venv/bin/python -m paper_translator`，参数相同。直接运行不带后端参数的命令行仍沿用既有的 DeepSeek + LaTeX 路径。

## 输出与检查

- `paper.pdf`、`paper.md`、`figures/` 保存正文和图片。
- `质量验收.json` 记录程序检查，`视觉审阅记录.json` 和 `每轮修改记录.md` 记录模型复核。
- `视觉待复核.md` 列出已确认、但执行器无法自动落地或仅有轻微的问题；它们不阻断发布。
- `参考文献检查.json` 统计参考文献条目是否仍为中文；新译稿应保留全部原文条目。
- `needs_review` 表示仍有阻断问题：候选保存在 `.job` 中，工具不会发布为完成版。
- 同名 `.job` 目录保存阶段检查点、请求状态和候选版本。失败后用相同命令恢复；参数或代码变化时应使用新输出目录。
- 成功发布后 `.job` 会自动删除，只保留交付目录；需要保留检查点时设置 `PAPER_KEEP_JOB=1`。

题头尽量保留原稿。正文和摘要分别跟随原稿栏式，中文使用宋体，英文和数字使用 Times New Roman。正文首行缩进两字，摘要标签 **_Abstract_** 加粗斜体，摘要正文加粗。参考文献条目、作者、题名和会议名保留原文，不翻译或音译。

## 工程结构

```text
paper_translator/
  cli.py             命令行、服务请求及任务入口
  config/            共用规则和排版参数
  translation/       译稿检查、语言判别和边界处理
  source/            原稿栏式、题头、图表和公式识别
  render/            LaTeX、矢量表格和算法排版
  harness/           任务恢复、程序验收和视觉循环
  legacy/            仍被其他后端或共享解析调用的旧版实现
tests/               回归测试
docs/                使用和维护说明
translate.py         兼容现有命令的入口
```

[详细使用说明](docs/usage.md) · [维护与验证](docs/development.md)

## 实现来源

默认视觉流程调用用户配置的模型服务。PDF 读取与裁片使用 PyMuPDF 和 pypdfium2，Markdown 解析使用 Pandoc，PDF 排版使用 Tectonic 或 XeLaTeX。本项目实现了流程编排、版式规则、对象验收和视觉修改循环。

其他 PDF 后端使用 PDFMathTranslate-next 2.9.0 与 BabelDOC 0.6.2；两个上游项目均标注 AGPL-3.0。使用或分发相关组件时应遵守各自许可。[PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next) · [BabelDOC](https://github.com/funstory-ai/BabelDOC)

默认视觉入口现使用 DeepSeek `deepseek-flash`，读取环境变量 `DEEPSEEK_API_KEY` 或本机 `.env.deepseek.local`。密钥文件不纳入 Git。视觉翻译和审阅仍使用现有 harness，排版仍由 LaTeX 完成。切换服务不会复用其他模型的视觉审阅通过结论。
