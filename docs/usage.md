# 使用说明

## 服务配置

macOS 启动器读取 `QWEN_API_KEY`，未设置时弹窗询问。可用 `QWEN_MODEL` 和 `QWEN_BASE_URL` 覆盖默认服务。命令行读取 `OPENAI_API_KEY`，通过 `--model` 和 `--base-url` 指定兼容接口。视觉流程会向服务发送论文页图、文字和复核所需的成品页图。

旧版 DeepSeek 路径读取 `DEEPSEEK_API_KEY`，也支持工程根目录的 `.env.deepseek.local`。密钥文件不会提交到 Git。

## 输出选项

| 参数 | 用途 |
| --- | --- |
| `--format pdf / md / both` | 选择产物 |
| `--backend vision --layout auto` | 视觉翻译，跟随原稿栏式 |
| `--layout reflow` | 视觉后端强制正文单栏 |
| `--layout reflow-two` | 视觉后端强制正文双栏 |
| `--max-review-rounds 5` | 视觉审阅总轮数上限，允许 1～10 |
| `--no-visual-review` | 只运行程序验收 |
| `--dpi 400` | 插图栅格化精度 |
| `--out 目录` | 指定尚不存在的交付目录 |

其他导出选项包括 `--backend latex --layout reflow-two` 和 `--backend mupdf`。完整参数以 `python translate.py --help` 为准。

## 复用译稿

将 `paper.md` 和 `figures/` 放在同一目录，可同时保留 `table-translations.json`。

```sh
.venv/bin/python translate.py "/路径/原稿.pdf"   --vision-draft "/路径/译稿/paper.md" --out "/路径/新结果"
```

不指定模型时执行程序验收。指定模型后还会调用译稿复核及成品视觉循环，可能产生服务费用。

## 验收范围

程序检查已识别的题头、编号图表、子表、算法框、内部链接和可疑英文。视觉模型对照原稿与成品提出修改，执行器支持局部改文、补文、重裁图片，以及表格列宽和单栏／跨栏调整。每轮修改后重新编译并检查，候选没有改善时保留此前版本。

模型判断可能出错，扫描稿、复杂合并表头、细小公式和跨页段落仍可能需要人工复核。程序检查通过不代表逐句翻译全部正确。

## 恢复任务

同名 `.job/task.json` 记录任务阶段和异常。保留 `.job` 目录后用原命令恢复，已完成阶段与验证缓存可复用。代码或参数变化时工具会拒绝复用原任务，应另建输出目录。清理 `.job` 会失去恢复和候选审阅材料，正式结果目录仍可独立阅读。
