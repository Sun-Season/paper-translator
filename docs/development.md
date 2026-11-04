# 维护与验证

## 执行流程

默认视觉路径由 `paper_translator.cli` 进入，`harness.job_runtime.Job` 保存阶段状态。译稿检查完成后，`harness.visual_agent` 调用 `harness.vision_harness`，由后者编排 LaTeX 生成与程序验收。视觉反馈通过受限执行器进入下一轮候选。

`config/layout_policy.py` 控制排版参数，`config/object_policy.py` 保存翻译和视觉审阅共用要求。原稿解析放在 `source/`，排版放在 `render/`。改变格式时应同时检查生成参数、程序验收和视觉提示是否一致。

`legacy/` 保留仍有实际调用者的早期实现。默认视觉流程也复用其中部分图形和算法解析函数，不能仅凭目录名称删除。

## 检查命令

在工程根目录运行。

```sh
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python translate.py --help
.venv/bin/python -m paper_translator --help
```

测试包含模拟模型响应，用于验证修复动作、失败恢复、语言判别和排版边界。涉及版式的更改还应真实编译 PDF 并查看页面。真实服务验证需单独报告，不能用模拟响应代替。

## 路径与任务兼容

根目录 `translate.py` 和两个 macOS 启动器保留。Python 内部模块改为 `paper_translator` 包内导入。DeepSeek 本地配置仍从工程根目录读取。任务代码指纹递归覆盖包内 Python 文件，整理前的未完成任务因代码变化需要新建输出目录。

## 提交内容

提交源码、测试、依赖清单、启动器和维护文档。虚拟环境、密钥、缓存、任务目录和翻译产物由 `.gitignore` 排除。旧版演示样例已清理。
