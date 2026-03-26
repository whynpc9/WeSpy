# WeSpy Fetcher Skill

> 仓库地址: https://github.com/whynpc9/WeSpy
> 版本: v1.4.1

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
- 公众号订阅、同步与批量下载（SQLite）
- Markdown 默认输出
- 公众号批量下载默认输出 Markdown，也可附带 PDF / HTML / JSON
- 可选导出浏览器渲染后的 PDF（`--pdf`，依赖 `agent-browser`）
- 可选对公众号图片调用 MinerU OCR，并把结果以引用块合并进 Markdown
- 可选 HTML / JSON / 全格式输出（`--html` / `--json` / `--all`）
- 兼容交互模式（不传 URL）

## 最小可用模式

只安装 Python 依赖时，Skill 仍然可以稳定完成：

- 单篇文章抓取并导出 Markdown
- 微信专辑列表获取与批量 Markdown 下载
- 通用网页文章抓取

这些能力不依赖 `agent-browser`、MinerU 或公众号后台登录态。

## 快速开始

```bash
# 查看帮助
python3 scripts/wespy_cli.py --help

# 公众号文章转 Markdown
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx"

# 扫码登录公众号后台并写入 SQLite
python3 scripts/wespy_cli.py auth login

# 保存公众号后台 token / cookie 到 SQLite
python3 scripts/wespy_cli.py auth set --token 123456 --cookie "pass_ticket=...; wap_sid2=...; ..."

# 订阅公众号并同步文章
python3 scripts/wespy_cli.py subscribe "人民日报"
python3 scripts/wespy_cli.py sync "人民日报"

# 下载该公众号尚未下载的文章
python3 scripts/wespy_cli.py download-account "人民日报"

# 下载该公众号文章，并同时导出 PDF
python3 scripts/wespy_cli.py download-account "人民日报" --pdf

# 导出浏览器渲染 PDF
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --pdf

# 公众号文章转 Markdown，并对正文图片做 OCR
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --image-ocr --mineru-url http://172.16.3.132:8523

# 专辑批量下载
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=...&album_id=..." --max-articles 10 --all
```

## 路径约定

- 默认 clone 目录：`~/Documents/QNSZ/project/WeSpy`
- 可通过 `WESPY_REPO_DIR` 覆盖
- 如果 Skill 目录本身就在 WeSpy 仓库中，会直接复用当前仓库源码
- SQLite 默认路径为 `~/.wespy/wespy.db`，也可通过 `--db-path` 覆盖
- `agent-browser` 命令也可通过 `WESPY_AGENT_BROWSER_CMD` 覆盖
- MinerU 地址也可通过 `WESPY_MINERU_URL` 提供

## 依赖

- Python 3.8+
- git
- requests
- beautifulsoup4
- 可选：本机可用的 `agent-browser`（用于 `--pdf`）
- 可选：本地可访问的 MinerU 服务（用于 `--image-ocr`）

## 可选依赖配置

### PDF 导出

```bash
npm install -g agent-browser
agent-browser install
```

如果命令名不在默认 `PATH`，可以设置：

```bash
export WESPY_AGENT_BROWSER_CMD="npx agent-browser"
```

### OCR

```bash
export WESPY_MINERU_URL="http://172.16.3.132:8523"
```

### 公众号订阅

推荐直接扫码登录：

```bash
python3 scripts/wespy_cli.py auth login
```

如果已经有后台凭据，也可以手动写入：

```bash
python3 scripts/wespy_cli.py auth set --token 123456 --cookie "pass_ticket=...; wap_sid2=...; ..."
```

安装依赖：

```bash
pip3 install -r scripts/requirements.txt
```
