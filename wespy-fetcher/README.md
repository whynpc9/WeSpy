# WeSpy Fetcher Skill

> 仓库地址: https://github.com/whynpc9/WeSpy
> 版本: v1.1.0

把当前 fork 的 [whynpc9/WeSpy](https://github.com/whynpc9/WeSpy) 封装成可直接调用的 Skill，支持微信公众号文章抓取、专辑批量下载、URL 转 Markdown 等完整能力。

## 依赖仓库

- 当前仓库：`https://github.com/whynpc9/WeSpy`
- 与上游 WeSpy 行为保持尽量一致

## 功能特性

- 抓取微信公众号单篇文章
- 抓取通用网页文章
- 支持掘金文章提取
- 微信专辑列表获取（`--album-only`）
- 微信专辑批量下载（`--max-articles`）
- Markdown 默认输出
- 可选对公众号图片调用 MinerU OCR，并把结果以引用块合并进 Markdown
- 可选 HTML / JSON / 全格式输出（`--html` / `--json` / `--all`）
- 兼容交互模式（不传 URL）

## 快速开始

```bash
# 查看帮助
python3 scripts/wespy_cli.py --help

# 公众号文章转 Markdown
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx"

# 公众号文章转 Markdown，并对正文图片做 OCR
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --image-ocr --mineru-url http://172.16.3.132:8523

# 专辑批量下载
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=...&album_id=..." --max-articles 10 --all
```

## 路径约定

- 默认 clone 目录：`~/Documents/QNSZ/project/WeSpy`
- 可通过 `WESPY_REPO_DIR` 覆盖
- 如果 Skill 目录本身就在 WeSpy 仓库中，会直接复用当前仓库源码
- MinerU 地址也可通过 `WESPY_MINERU_URL` 提供

## 依赖

- Python 3.8+
- git
- requests
- beautifulsoup4
- 可选：本地可访问的 MinerU 服务（用于 `--image-ocr`）

安装依赖：

```bash
pip3 install -r scripts/requirements.txt
```
