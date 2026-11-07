#!/bin/zsh
cd "${0:A:h}" || exit 1
if [[ ! -x .venv/bin/pdf2zh_next ]] || ! .venv/bin/python -c 'import cv2, dotenv, numpy, PIL, pymupdf, pypdfium2, pypandoc' 2>/dev/null; then
  if [[ ! -x .venv/bin/python ]]; then
    export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.12/bin:$PATH"
    interpreter=$(command -v python3.12)
    if [[ -z "$interpreter" ]]; then
      print "首次使用需要 Python 3.12。请安装 python.org 的 macOS 版 Python 3.12，然后重新双击本文件。"
      exit 1
    fi
    "$interpreter" -m venv .venv || exit 1
  fi
  print "首次启动，正在安装论文翻译依赖。"
  .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
source_pdf=$(osascript -e 'POSIX path of (choose file with prompt "选择要翻译的论文" of type {"com.adobe.pdf"})') || exit 0
fmt=pdf
layout=auto
vision=1
backend=(--backend vision)
service=()
if [[ "$1" == --options ]]; then
  kind=$(osascript -e 'choose from list {"PDF", "Markdown", "PDF + Markdown"} with prompt "选择译文格式" default items {"PDF"}') || exit 0
  case "$kind" in
    PDF) fmt=pdf ;;
    Markdown) fmt=md; layout=reflow; backend=(); vision=0 ;;
    'PDF + Markdown') fmt=both ;;
    *) exit 0 ;;
  esac
fi
if [[ "$1" == --options && "$fmt" != md ]]; then
  mode=$(osascript -e 'choose from list {"跨页重排（双栏阅读）", "LaTeX 双栏", "DeepSeek 视觉翻译 + LaTeX 跟随原稿", "跨页重排（单栏阅读）", "保留原分页（对照阅读）"} with prompt "选择译文版式" default items {"DeepSeek 视觉翻译 + LaTeX 跟随原稿"}') || exit 0
  [[ "$mode" == false ]] && exit 0
  vision=0; backend=(); service=(--pdf-service deepseek)
  case "$mode" in
    "DeepSeek 视觉翻译 + LaTeX 跟随原稿") backend=(--backend vision); service=(); vision=1 ;;
    "LaTeX 双栏") layout=reflow-two; backend=(--backend latex) ;;
    "保留原分页（对照阅读）") layout=original ;;
    "跨页重排（双栏阅读）") layout=reflow-two; backend=(--backend mupdf) ;;
    "跨页重排（单栏阅读）") layout=reflow ;;
  esac
fi
if [[ "$vision" == 1 ]]; then
  export OPENAI_BASE_URL="${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"
  export PAPER_MODEL="${DEEPSEEK_MODEL:-deepseek-flash}"
  export OPENAI_API_KEY="$DEEPSEEK_API_KEY"
fi
if [[ "$fmt" != pdf || "$vision" == 1 ]]; then
  if [[ -z "$OPENAI_BASE_URL" ]]; then
    export OPENAI_BASE_URL=$(osascript -e 'text returned of (display dialog "输入视觉模型服务的兼容 API 地址" default answer "https://api.openai.com/v1")')
    [[ -n "$OPENAI_BASE_URL" ]] || exit 0
  fi
  if [[ -z "$PAPER_MODEL" ]]; then
    export PAPER_MODEL=$(osascript -e 'text returned of (display dialog "输入服务商提供的视觉模型名称" default answer "")')
    [[ -n "$PAPER_MODEL" ]] || exit 0
  fi
  if [[ -z "$OPENAI_API_KEY" && ! ( "$OPENAI_BASE_URL" == https://api.deepseek.com* && -f .env.deepseek.local ) ]]; then
    key=$(osascript -e 'text returned of (display dialog "输入该服务的 API 密钥。本地免密服务可留空。" default answer "" with hidden answer)') || exit 0
    export OPENAI_API_KEY="$key"
    [[ "$OPENAI_BASE_URL" == https://api.deepseek.com* ]] && export DEEPSEEK_API_KEY="$key"
  fi
fi
if [[ "$vision" == 0 && "$fmt" != md && -z "$DEEPSEEK_API_KEY" && ! -f .env.deepseek.local ]]; then
  key=$(osascript -e 'text returned of (display dialog "PDF 默认由 DeepSeek 翻译。输入 DeepSeek API 密钥，本次使用后即丢弃。" default answer "" with hidden answer)') || exit 0
  [[ -n "$key" ]] || exit 0
  export DEEPSEEK_API_KEY="$key"
fi
target_dir="${source_pdf:r}-translated"
if [[ -e "$target_dir" ]]; then
  target_dir="$target_dir-$(date +%Y%m%d-%H%M%S)"
fi
.venv/bin/python translate.py "$source_pdf" "${service[@]}" --format "$fmt" --layout "$layout" "${backend[@]}" --out "$target_dir" && open "$target_dir"
