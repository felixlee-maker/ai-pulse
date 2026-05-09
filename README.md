# AI-Pulse

多领域技术资讯聚合监控系统 —— 从 20+ RSS 源抓取 AI / 前端 / DevOps 文章，
经 AI 智能过滤后推送到飞书与邮箱，并按天导出结构化数据，方便其他 agent 二次分析。

> 同一份代码，两种部署模式：**GitHub Actions**（云端定时，仅支持 OpenAI 兼容 API）
> 或 **服务器 / 本地 Cron**（自部署，可额外使用 Claude Code CLI / Claude 订阅额度）。

---

## 目录

- [功能特性](#功能特性)
- [整体流程](#整体流程)
- [部署模式选择](#部署模式选择)
- [AI 咨询获取机制](#ai-咨询获取机制)
  - [方案 A：OpenAI 兼容 API](#方案-aopenai-兼容-api)
  - [方案 B：Claude Code CLI（headless）](#方案-bclaude-code-cliheadless)
- [飞书（Lark）通知](#飞书lark通知)
- [邮件通知](#邮件通知)
- [部署一：GitHub Actions](#部署一github-actions)
- [部署二：服务器 / 本地 Cron](#部署二服务器--本地-cron)
- [配置参考](#配置参考)
- [每日结构化数据导出](#每日结构化数据导出)
- [项目结构](#项目结构)

---

## 功能特性

- **多源聚合**：20+ RSS 源，覆盖中英文 AI、前端、DevOps、官方博客、学术论文
- **多领域分级 Prompt**：按文章 `domain` 选用专属 system prompt（AI / frontend / devops）
- **可插拔 AI 后端**：`openai`（任意 OpenAI 兼容服务）或 `claude-code`（CLI headless）
- **双通道通知**：飞书 Top N 精华卡片 + 邮件全量 HTML 日报
- **每日结构化导出**：JSON + Markdown 双格式，方便 agent 解析或人工浏览
- **可在 GitHub Actions / 自有服务器 / 本地任选其一部署**
- **去重与持久化**：SQLite 存储，自动跨日去重

---

## 整体流程

```
┌────────────┐    ┌─────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────────┐
│  RSS 源 N  ├──▶│ Dedup   ├──▶│ AI 过滤后端   ├──▶│ SQLite   ├──▶│ 飞书 Top N    │
│ (RSSHub /  │   │ (SQLite)│    │ openai/      │   │          │   │ 邮件 全量      │
│  官方 RSS) │   │         │    │ claude-code  │   │          │   │ data/daily/* │
└────────────┘   └─────────┘    └──────────────┘   └──────────┘   └──────────────┘
```

每篇文章经过：**抓取 → 关键词预过滤 → AI 相关性打分 → 阈值筛选 → 通知 + 导出**。

---

## 部署模式选择

| 维度 | GitHub Actions | 服务器 / 本地 Cron |
|------|---------------|------------------|
| 配置位置 | GitHub Secrets | `.env` 文件 |
| 是否需要服务器 | 否 | 是 |
| 支持的 AI 后端 | **仅** OpenAI 兼容 API | OpenAI 兼容 API **或** Claude Code CLI |
| 是否能复用 Claude 订阅额度 | ❌ | ✅（本地 `claude login`） |
| 上手成本 | 低 | 中 |
| 数据持久化 | Artifact（7~30 天） | 本地 SQLite，永久 |

> GitHub Actions 中无法完成 `claude login` 的浏览器交互，因此 workflow 强制
> `AI_BACKEND=openai`。想用 Claude Code CLI（复用已有 Claude 订阅额度），
> 请走自部署模式。

---

## AI 咨询获取机制

`src/processors/filter.py` 中定义了统一的 `AIFilter`，内部根据 `ai_backend` 选择具体后端：

```python
if backend == "openai":
    self.backend = OpenAIBackend(api_key=..., base_url=..., model=...)
elif backend == "claude-code":
    self.backend = ClaudeCodeBackend(model=..., max_concurrency=...)
```

切换方式（任选其一，**仅自部署模式可用**；GitHub Actions 强制 `openai`）：

1. `.env` 设置 `AI_BACKEND=openai` 或 `AI_BACKEND=claude-code`
2. `config/config.yaml` 中 `filter.ai_backend` 字段

> 优先级：环境变量 / `.env` > `config.yaml` > 代码默认值。

### 方案 A：OpenAI 兼容 API

适用于 OpenAI、MiniMax、DeepSeek、智谱、Moonshot、本地 vLLM 等任意兼容 OpenAI Chat Completions 协议的服务。

**所需变量**

| 变量 | 必填 | 说明 |
|------|------|------|
| `AI_BACKEND` | 是 | 设为 `openai` |
| `OPENAI_API_KEY` | 是 | 对应服务的 API Key |
| `OPENAI_BASE_URL` | 否 | 自定义 base URL，缺省为 OpenAI 官方 |
| `OPENAI_MODEL` | 否 | 模型名，默认 `gpt-4o-mini` |
| `AI_MAX_CONCURRENCY` | 否 | 并发请求数，默认 3 |

**常见服务示例**

| 提供方 | `OPENAI_BASE_URL` | 推荐模型 |
|--------|-------------------|---------|
| OpenAI 官方 | `https://api.openai.com/v1` | `gpt-4o-mini` |
| MiniMax | `https://api.minimax.chat/v1` | `abab6.5s-chat` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 智谱 BigModel | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |

> 调用细节见 `src/processors/filter.py:OpenAIBackend`。`temperature=0.3, max_tokens=500`，
> 若使用强制 JSON 输出的服务（如 Moonshot），可自行扩展 `response_format`。

### 方案 B：Claude Code CLI（headless）

> ⚠️ **仅适用于自部署模式**（服务器 / 本地 Cron / Docker），GitHub Actions 不支持。

通过子进程 `claude -p --output-format text` 调用本地 Claude Code CLI，
可直接复用已有的 **Claude 订阅** 额度（无需 API Key），
亦可使用 `ANTHROPIC_API_KEY` 走 API 计费。

**安装**

```bash
# 1) 安装 CLI
npm install -g @anthropic-ai/claude-code
claude --version

# 2) 选择授权方式
#    a. Claude 订阅（推荐，本地 / 个人服务器）：
claude login          # 浏览器扫码，一次完成
#    b. API Key（适合无登录态的服务器）：
export ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
```

**所需变量**

| 变量 | 必填 | 说明 |
|------|------|------|
| `AI_BACKEND` | 是 | 设为 `claude-code` |
| `CLAUDE_MODEL` | 否 | 模型名，默认 `claude-haiku-4-5` |
| `ANTHROPIC_API_KEY` | 视情况 | 已 `claude login`（Claude 订阅授权）时不需要；无登录态的服务器需填 |
| `AI_MAX_CONCURRENCY` | 否 | 同时启动的 `claude` 子进程数，建议 2~5 |

**调用片段**（来自 `src/processors/filter.py:ClaudeCodeBackend`）

```python
cmd = ["claude", "-p", "--output-format", "text"]
if self.model:
    cmd.extend(["--model", self.model])
proc = await asyncio.create_subprocess_exec(*cmd, ...)
stdout, _ = await asyncio.wait_for(proc.communicate(input=prompt.encode()), timeout=60)
```

---

## 飞书（Lark）通知

发送当日相关性 Top N 的卡片消息，使用飞书自定义机器人 Webhook。

### 1. 创建机器人并取得 Webhook

1. 进入目标群聊 → **群设置** → **群机器人** → **添加机器人**
2. 选择「**自定义机器人**」
3. （可选）配置签名校验或 IP 白名单
4. 复制生成的 Webhook URL

### 2. 配置变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `LARK_WEBHOOK_URL` | 是 | 形如 `https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxx` |
| `LARK_MAX_ITEMS` | 否 | Top N 推送条数，默认 10 |
| `LARK_TEXT_MAX_BYTES` | 否 | 文本消息单条字节上限，默认 3800 |
| `LARK_CARD_MAX_BYTES` | 否 | 卡片消息单条字节上限，默认 3200 |

> 飞书单条卡片有大小限制，`LarkNotifier` 会自动按字节切分为多页（`第 X/Y 页`）。

### 3. 启停 / 测试

```bash
# 测试一次发送
python -m src.main test-notify
```

`config/config.yaml` 中可关闭飞书：

```yaml
notifier:
  lark:
    enabled: false
```

---

## 邮件通知

发送当日**全量**相关文章的 HTML 日报，适合归档或在邮箱客户端阅读。

### 1. 准备 SMTP 凭证

以 Gmail 为例：

1. Google 账户 → 安全 → **开启两步验证**
2. 安全 → **应用专用密码** → 生成 16 位密码

QQ 邮箱 / 163 等同理：在邮箱后台开启 SMTP 服务并申请授权码。

### 2. 配置变量

| 变量 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `EMAIL_SMTP_HOST` | 否 | `smtp.gmail.com` | SMTP 服务器 |
| `EMAIL_SMTP_PORT` | 否 | `587` | STARTTLS 端口 |
| `EMAIL_SMTP_USER` | 是 | — | 发件邮箱 |
| `EMAIL_SMTP_PASSWORD` | 是 | — | 应用专用密码 / 授权码 |
| `EMAIL_TO` | 是 | — | 收件人邮箱 |

> 程序根据 `EMAIL_SMTP_USER + EMAIL_SMTP_PASSWORD` 是否同时存在自动启用邮件通知，
> 见 `src/config.py:154`。

### 3. 常用 SMTP 配置

| 邮箱服务 | Host | Port |
|---------|------|------|
| Gmail | `smtp.gmail.com` | `587` |
| Outlook | `smtp.office365.com` | `587` |
| QQ 邮箱 | `smtp.qq.com` | `587` |
| 163 邮箱 | `smtp.163.com` | `465`（SSL）/ `587` |
| iCloud | `smtp.mail.me.com` | `587` |

---

## 部署一：GitHub Actions

适合零成本、零运维、纯云端方案。代码仓库 fork 到自己账户即可。
**此模式仅支持 OpenAI 兼容 API**，workflow 内已硬编码 `AI_BACKEND=openai`。

### 1. 配置 Secrets

在仓库 → **Settings** → **Secrets and variables** → **Actions** 添加：

**必填**

| Secret | 说明 |
|--------|------|
| `LARK_WEBHOOK_URL` | 飞书 Webhook |
| `OPENAI_API_KEY` | OpenAI / MiniMax / DeepSeek 等的 API Key |
| `OPENAI_BASE_URL` | API 地址（如 `https://api.minimax.chat/v1`） |
| `OPENAI_MODEL` | 模型名（如 `gpt-4o-mini` / `abab6.5s-chat`） |

**可选**

| Secret | 说明 |
|--------|------|
| `RSSHUB_BASE_URL` | 自建 RSSHub 地址（OpenAI / 36氪 / Anthropic 等源依赖） |
| `AI_MAX_CONCURRENCY` | 默认 3 |
| `EMAIL_SMTP_HOST` / `EMAIL_SMTP_PORT` | 邮件 SMTP 配置 |
| `EMAIL_SMTP_USER` / `EMAIL_SMTP_PASSWORD` / `EMAIL_TO` | 邮件凭证与收件人 |

### 2. 触发

- **定时**：默认 `cron: '0 22 * * *'`（UTC 22:00 ≈ 北京 06:00），可在
  `.github/workflows/scheduled-run.yml` 修改
- **手动**：仓库 → **Actions** → 选择 workflow → **Run workflow**

### 3. 产物

- `articles-db` artifact：当次运行的 SQLite 数据库（保留 7 天）
- `daily-report` artifact：`data/daily/*.{json,md}` 每日结构化数据（保留 30 天）

> 想用 Claude Code CLI（复用 Claude 订阅额度）？请走「[部署二：服务器 / 本地 Cron](#部署二服务器--本地-cron)」。

---

## 部署二：服务器 / 本地 Cron

适合需要复用本地 **Claude 订阅** 额度，或希望长期持久化数据库的场景。

### 1. 安装

```bash
git clone https://github.com/<your-fork>/ai-pulse.git
cd ai-pulse
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. （可选）启动自建 RSSHub

```bash
docker run -d --name rsshub --restart unless-stopped \
  -p 1200:1200 diygod/rsshub
```

### 3. （可选）安装并登录 Claude Code

只在选择 `claude-code` 后端时需要：

```bash
npm install -g @anthropic-ai/claude-code

# 二选一：
claude login                                  # Claude 订阅，浏览器扫码
export ANTHROPIC_API_KEY=sk-ant-xxxxxxxx      # 或者 API Key
```

### 4. 写入 `.env`

```bash
cp .env.example .env
$EDITOR .env
```

最少要配置：

- `LARK_WEBHOOK_URL`
- `AI_BACKEND` + 对应后端的 Key
- 如使用 RSSHub 源：`RSSHUB_BASE_URL`

### 5. 运行

```bash
# 单次运行（手动调试）
python -m src.main run

# 守护进程（内置 APScheduler，按 config.yaml 中的 cron 调度）
python -m src.main daemon

# 查看数据库统计
python -m src.main status

# 测试飞书通知
python -m src.main test-notify
```

### 6. 系统级 Cron（推荐）

```bash
crontab -e
# 每天早上 9 点执行（北京时间）
0 9 * * * cd /path/to/ai-pulse && /path/to/.venv/bin/python -m src.main run >> logs/cron.log 2>&1
```

### 7. Docker

```bash
docker compose up -d
docker compose logs -f
```

`docker-compose.yml` 默认以守护进程模式运行；`.env` 与 `data/` 通过 volume 挂载。

---

## 配置参考

### `config/config.yaml`

```yaml
filter:
  enabled: true
  ai_backend: claude-code        # 被环境变量 AI_BACKEND 覆盖
  relevance_threshold: 0.85      # 相关性阈值 (0-1)
  max_concurrency: 3             # 被 AI_MAX_CONCURRENCY 覆盖
  keywords:
    include: [AI, 大模型, LLM, ...]
    exclude: [广告, 招聘, ...]

notifier:
  lark:
    enabled: true
    message_type: interactive    # 卡片消息

scheduler:
  timezone: Asia/Shanghai
  jobs:
    - name: daily_check
      cron: "0 9 * * *"
      enabled: true
```

### 添加 / 修改 RSS 源

```yaml
scraper:
  rss:
    feeds:
      - name: "源名称"
        url: "https://example.com/feed"
        category: "分类"
        domain: ai            # ai / frontend / devops，决定使用哪套 prompt
      - name: "RSSHub 源"
        url: "${RSSHUB_BASE_URL}/route/path"
        category: "分类"
        domain: ai
```

### 环境变量优先级

```
环境变量 / .env  >  GitHub Secrets  >  config.yaml  >  代码默认值
```

---

## 每日结构化数据导出

每次执行后 `src/exporters/daily_report.py` 会将**当天全量相关文章**写入：

```
data/daily/
├── 2026-04-25.json     # 结构化，供程序 / agent 解析
└── 2026-04-25.md       # Markdown，供人或 Claude Code agent 直接阅读
```

JSON 结构示例：

```json
{
  "date": "2026-04-25",
  "generated_at": "2026-04-25T09:15:30+08:00",
  "stats": {
    "total_fetched": 120,
    "after_dedup": 85,
    "relevant": 32,
    "avg_score": 0.88,
    "by_source": {"机器之心": 5, "Anthropic": 3},
    "by_tier": {"core (≥0.9)": 12, "general (0.7-0.89)": 15, "edge (0.5-0.69)": 5}
  },
  "articles": [
    {
      "title": "...",
      "url": "https://...",
      "source": "Anthropic",
      "domain": "ai",
      "relevance_score": 0.95,
      "ai_summary": "...",
      "published_at": "2026-04-25T08:00:00+00:00"
    }
  ]
}
```

> 与飞书 Top N 限额无关，导出始终包含全部命中阈值的文章。

---

## 项目结构

```
ai-pulse/
├── .github/workflows/
│   └── scheduled-run.yml       # GitHub Actions 入口
├── config/
│   └── config.yaml             # RSS 源、过滤、调度配置
├── prompts/
│   └── tech-digest.md          # 离线 prompt（人工策展用）
├── src/
│   ├── main.py                 # CLI 入口
│   ├── config.py               # 配置加载（env > yaml）
│   ├── scrapers/               # RSS 抓取
│   ├── processors/
│   │   ├── filter.py           # AIFilter + ClaudeCodeBackend / OpenAIBackend
│   │   └── dedup.py
│   ├── exporters/              # 每日 JSON / Markdown 导出
│   ├── notifiers/
│   │   ├── lark.py             # 飞书卡片
│   │   └── email.py            # SMTP 邮件
│   ├── storage/                # SQLAlchemy + SQLite
│   └── scheduler/              # APScheduler 守护进程
├── data/
│   ├── articles.db
│   └── daily/                  # 每日导出
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## License

MIT
