---
name: wespy-fetcher
description: 获取并转换微信公众号/网页文章为 Markdown 的封装 Skill，完整支持 WeSpy 的单篇抓取、微信专辑批量下载、HTML/JSON/PDF/Markdown 多格式输出、公众号订阅同步与批量正文下载，以及调用 MinerU 对公众号图片做 OCR 并合并进 Markdown。Use when user asks to 抓取微信公众号文章、公众号专辑批量下载、URL 转 Markdown、保存微信文章、公众号订阅同步、公众号批量下载、公众号图片 OCR、网页导出 PDF、mp.weixin.qq.com to markdown.
---

# wespy-plus Fetcher

封装当前 fork 仓库 [whynpc9/WeSpy](https://github.com/whynpc9/WeSpy) 中的 `wespy-plus` 能力。

## 功能范围

- 单篇文章抓取（微信公众号 / 通用网页 / 掘金）
- 微信专辑文章列表获取（`--album-only`）
- 微信专辑批量下载（`--max-articles`）
- 公众号订阅、同步与批量下载（`auth` / `subscribe` / `sync` / `download-account` / `sync-and-download`）
- 多格式输出（Markdown 默认，支持 HTML / JSON / PDF / 全部）
- 图片 OCR 合并（`--image-ocr` / `--mineru-url`）
- 显式交互模式（`--interactive`）

## Default Workflow

当 agent 使用这个 Skill 时，默认按下面顺序执行：

1. 优先走非交互命令，直接传完整参数，不依赖提示输入
2. 先使用最小功能集合，只输出 Markdown
3. 只有确认环境存在时，才追加 `--pdf` 或 `--image-ocr`
4. 批量任务先用 `--limit 1 --dry-run --output-json` 做 smoke test
5. 在当前仓库内做验证时，测试产物统一写到 `.tmp/test-output/`

如果用户没有明确要求交互模式，不要使用 `python3 scripts/wespy_cli.py --interactive`。

## 最小可用能力

只安装 Python 依赖时，Skill 仍可直接使用这些能力：

- 单篇文章抓取并输出 Markdown
- 微信专辑文章列表获取与批量 Markdown 下载
- 通用网页文章抓取
- 公众号订阅数据的本地 SQLite 存储

可选能力按需启用：

- `--pdf` 依赖 `agent-browser`
- `--image-ocr` 依赖 MinerU 服务
- `subscribe` / `sync` / `download-account` 依赖公众号后台登录态

## Failure Handling

- 缺少 URL 时，直接报错并给出示例，不要进入交互模式
- 缺少登录态时，先提示 `auth login` 或 `auth set --token --cookie`
- 缺少 `agent-browser` 时，不要尝试 `--pdf`
- 缺少 MinerU 服务时，不要尝试 `--image-ocr`
- 如果需要机器可读结果，优先加 `--output-json`

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

# 单篇文章，输出结构化 JSON
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --output-json

# 只预览执行计划
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --dry-run

# 输出 markdown + html
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --html

# 输出 markdown + json
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --json

# 输出所有格式
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --all

# 导出页面 PDF（依赖 agent-browser）
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --pdf

# 对公众号图片启用 OCR，并把结果作为引用块合并进 Markdown
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx" --image-ocr --mineru-url http://172.16.3.132:8523

# 专辑只拉列表
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/mp/appmsgalbum?..." --album-only --max-articles 20

# 专辑批量下载
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/mp/appmsgalbum?..." --max-articles 20 --all

# 扫码登录公众号后台并写入 SQLite
python3 scripts/wespy_cli.py auth login

# 保存公众号后台 token / cookie 到 SQLite
python3 scripts/wespy_cli.py auth set --token 123456 --cookie "pass_ticket=...; wap_sid2=...; ..."

# 订阅公众号并同步文章列表
python3 scripts/wespy_cli.py subscribe "人民日报"
python3 scripts/wespy_cli.py sync "人民日报"

# 批量下载该公众号尚未下载的文章
python3 scripts/wespy_cli.py download-account "人民日报"

# 批量下载该公众号文章，并同时导出 PDF
python3 scripts/wespy_cli.py download-account "人民日报" --pdf

# 批量任务先做 smoke test
python3 scripts/wespy_cli.py download-account "人民日报" --limit 1 --dry-run --output-json

# 显式进入交互模式
python3 scripts/wespy_cli.py --interactive
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
- `--pdf`
- `--image-ocr`
- `--mineru-url`
- `--interactive`
- `--dry-run`
- `--output-json`
- `--db-path`
- `auth`
- `subscribe`
- `subscriptions`
- `sync`
- `download-account`
- `sync-and-download`

## 实现说明

- 优先使用 `WESPY_REPO_DIR`
- 若 Skill 嵌在 WeSpy 仓库内，自动使用当前仓库源码
- 若本地不存在源码，则自动 clone `https://github.com/whynpc9/WeSpy.git`
- 通过导入 `wespy.main.main` 直接调用 CLI，保持行为一致
- CLI 默认非交互，只有显式传 `--interactive` 才进入提示输入
- 订阅数据使用 SQLite，默认路径 `~/.wespy/wespy.db`
- 公众号订阅功能支持 `auth login` 扫码登录，也支持手动提供公众号后台的 `token + cookie`
- `--pdf` 依赖本机可用的 `agent-browser`，必要时可通过 `WESPY_AGENT_BROWSER_CMD` 覆盖命令
- OCR 依赖本地可访问的 MinerU 服务，也可通过环境变量 `WESPY_MINERU_URL` 提供服务地址
- 图片 OCR 结果会作为引用块追加到对应图片下方，避免打乱正文标题层级
- `--dry-run` 可用于预览批量任务计划
- `--output-json` 可用于把结果交给其他 agent 或脚本继续消费

## 可选依赖配置

基础能力只需要：

```bash
pip3 install -r scripts/requirements.txt
```

按需启用增强能力时，再补充下面的环境：

### PDF 导出

```bash
npm install -g agent-browser
agent-browser install
```

如果命令名不在默认 `PATH`：

```bash
export WESPY_AGENT_BROWSER_CMD="npx agent-browser"
```

### OCR

```bash
export WESPY_MINERU_URL="http://172.16.3.132:8523"
```

### 公众号订阅

推荐使用扫码登录写入 SQLite：

```bash
python3 scripts/wespy_cli.py auth login
```

也可以手动写入后台 `token + cookie`：

```bash
python3 scripts/wespy_cli.py auth set --token 123456 --cookie "pass_ticket=...; wap_sid2=...; ..."
```
