# wespy-plus

`wespy-plus` 是一个面向 Markdown 输出的文章抓取工具，重点支持微信公众号文章、微信公众号专辑，以及基于公众号后台登录态的订阅同步和批量下载。

这个项目基于原始的 [tianchangNorth/WeSpy](https://github.com/tianchangNorth/WeSpy) 持续演进；公众号订阅、扫码登录、批量同步这条链路参考了 [wechat-article-exporter](https://github.com/wechat-article/wechat-article-exporter) 的思路。

如果你要启用“订阅公众号 / 同步文章列表 / 批量下载正文”这组能力，请先完成这份前置准备工作：
[mptext 使用说明](https://docs.mptext.top/get-started/usage.html)

## 当前能力

- 单篇文章抓取，默认导出 Markdown
- 微信公众号专辑列表获取与批量下载
- 公众号订阅、本地 SQLite 存储、文章列表同步
- 批量下载公众号文章，默认 Markdown，可附带 HTML / JSON / PDF
- 图片 OCR 合并进 Markdown
- 浏览器渲染 PDF 导出
- `--dry-run` 计划预览
- `--output-json` 结构化输出

## 安装

推荐直接从源码安装：

```bash
git clone https://github.com/whynpc9/WeSpy.git
cd WeSpy
pip install -e .
```

安装后主命令为：

```bash
wespy-plus --help
```

兼容性说明：

- 当前同时保留 `wespy-plus` 和 `wespy` 两个 CLI 入口
- Python 包名暂时仍然是 `wespy`

## 快速开始

### 单篇文章

```bash
# 默认只输出 Markdown
wespy-plus "https://mp.weixin.qq.com/s/xxxxx"

# 输出结构化 JSON
wespy-plus "https://mp.weixin.qq.com/s/xxxxx" --output-json

# 只预览执行计划
wespy-plus "https://mp.weixin.qq.com/s/xxxxx" --dry-run

# 同时导出 PDF
wespy-plus "https://mp.weixin.qq.com/s/xxxxx" --pdf

# 显式进入交互模式
wespy-plus --interactive
```

### 微信专辑

```bash
# 只获取专辑文章列表
wespy-plus "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=...&album_id=..." --album-only

# 批量下载专辑文章
wespy-plus "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=...&album_id=..." --max-articles 10
```

### 公众号订阅与批量下载

先完成上面的 mptext 前置准备，再执行：

```bash
# 扫码登录公众号后台
wespy-plus auth login

# 或者手动写入 token / cookie
wespy-plus auth set --token 123456 --cookie "pass_ticket=...; wap_sid2=...; ..."

# 订阅公众号
wespy-plus subscribe "人民日报"
wespy-plus subscribe "https://mp.weixin.qq.com/s/xxxxx"

# 查看本地订阅
wespy-plus subscriptions

# 同步文章列表
wespy-plus sync "人民日报"

# 预览同步计划
wespy-plus sync "人民日报" --dry-run --output-json

# 批量下载正文
wespy-plus download-account "人民日报"

# 先做一篇 smoke test
wespy-plus download-account "人民日报" --limit 1 --dry-run --output-json

# 同步后立即下载新增文章
wespy-plus sync-and-download "人民日报"
```

默认 SQLite 数据库位置：

```bash
~/.wespy/wespy.db
```

如果需要自定义数据库路径：

```bash
wespy-plus --db-path /path/to/wespy.db subscriptions
```

## 可选依赖

基础能力只需要 Python 依赖。下面这些属于按需启用。

### PDF 导出

`--pdf` 依赖 [agent-browser](https://github.com/vercel-labs/agent-browser)：

```bash
npm install -g agent-browser
agent-browser install
```

如果命令名不在默认 `PATH`：

```bash
export WESPY_AGENT_BROWSER_CMD="npx agent-browser"
```

### 图片 OCR

`--image-ocr` 依赖可访问的 MinerU 服务：

```bash
export WESPY_MINERU_URL="http://172.16.3.132:8523"
wespy-plus "https://mp.weixin.qq.com/s/xxxxx" --image-ocr
```

## Agent / 自动化调用建议

- 默认走非交互命令，不要依赖提示输入
- 批量任务先执行 `--limit 1 --dry-run --output-json`
- 只有确认环境存在时，才启用 `--pdf` 或 `--image-ocr`
- 如果需要机器可读结果，优先使用 `--output-json`

## Skill

仓库内提供了对应的 Codex skill：
[wespy-fetcher](wespy-fetcher/SKILL.md)

## 开发说明

- 仓库内人工测试产物统一写到 `.tmp/test-output/`
- 程序默认业务输出目录仍然是 `articles/`
