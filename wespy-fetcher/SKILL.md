---
name: wespy-fetcher
description: 获取并转换微信公众号/网页文章为 Markdown 的封装 Skill，完整支持 WeSpy 的单篇抓取、微信专辑批量下载、专辑列表获取、HTML/JSON/Markdown 多格式输出，以及调用 MinerU 对公众号图片做 OCR 并合并进 Markdown。Use when user asks to 抓取微信公众号文章、公众号专辑批量下载、URL 转 Markdown、保存微信文章、公众号图片 OCR、mp.weixin.qq.com to markdown.
---

# WeSpy Fetcher

封装当前 fork 仓库 [whynpc9/WeSpy](https://github.com/whynpc9/WeSpy) 的完整能力。

## 功能范围

- 单篇文章抓取（微信公众号 / 通用网页 / 掘金）
- 微信专辑文章列表获取（`--album-only`）
- 微信专辑批量下载（`--max-articles`）
- 多格式输出（Markdown 默认，支持 HTML / JSON / 全部）
- 图片 OCR 合并（`--image-ocr` / `--mineru-url`）
- 交互模式（不传 URL 时）

## 依赖来源

- 当前仓库：`https://github.com/whynpc9/WeSpy`
- 默认克隆目录：`~/Documents/QNSZ/project/WeSpy`
- 可通过环境变量 `WESPY_REPO_DIR` 指定本地源码路径

## 使用

脚本位置：`scripts/wespy_cli.py`

```bash
# 查看帮助
python3 scripts/wespy_cli.py --help

# 单篇文章（默认输出 markdown）
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx"

# 输出 markdown + html
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --html

# 输出 markdown + json
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --json

# 输出所有格式
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --all

# 对公众号图片启用 OCR，并把结果作为引用块合并进 Markdown
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --image-ocr --mineru-url http://172.16.3.132:8523

# 专辑只拉列表
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/mp/appmsgalbum?..." --album-only --max-articles 20

# 专辑批量下载
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/mp/appmsgalbum?..." --max-articles 20 --all
```

## 参数

透传 WeSpy 原生命令参数：

- `url`
- `-o, --output`
- `-v, --verbose`
- `--html`
- `--json`
- `--all`
- `--max-articles`
- `--album-only`
- `--image-ocr`
- `--mineru-url`

## 实现说明

- 优先使用 `WESPY_REPO_DIR`
- 若 Skill 嵌在 WeSpy 仓库内，自动使用当前仓库源码
- 若本地不存在源码，则自动 clone `https://github.com/whynpc9/WeSpy.git`
- 通过导入 `wespy.main.main` 直接调用 CLI，保持行为一致
- OCR 依赖本地可访问的 MinerU 服务，也可通过环境变量 `WESPY_MINERU_URL` 提供服务地址
- 图片 OCR 结果会作为引用块追加到对应图片下方，避免打乱正文标题层级
