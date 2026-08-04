# Insight Agent

面向 Hsia 商品企划与研发团队的美国文胸市场洞察 Agent。

项目通过 Web UI 接收研究任务，由 LLM 选择并编排 Skill、SellerSprite、Sif 和 Reddit/Agent Reach 等工具，保留执行证据链，并输出可下载的 HTML 研究报告。

> 当前正式支持的运行环境是 **Windows 10/11 + PowerShell**。本文从一台未安装过本项目的 Windows 电脑开始，按照顺序执行即可完成本地部署。

## 目录

- [1. 当前能力](#1-当前能力)
- [2. 部署前准备](#2-部署前准备)
- [3. 五分钟完成本地部署](#3-五分钟完成本地部署)
- [4. 配置 LLM 与数据源](#4-配置-llm-与数据源)
- [5. 完成第一次 Agent 研究](#5-完成第一次-agent-研究)
- [6. 配置 Agent Reach 与 Reddit](#6-配置-agent-reach-与-reddit)
- [7. 常用脚本](#7-常用脚本)
- [8. 手动安装与分别启动](#8-手动安装与分别启动)
- [9. 测试与构建](#9-测试与构建)
- [10. 数据与文件保存位置](#10-数据与文件保存位置)
- [11. 环境变量说明](#11-环境变量说明)
- [12. 常见问题](#12-常见问题)
- [13. 更新项目](#13-更新项目)
- [14. 内网与生产部署说明](#14-内网与生产部署说明)
- [15. 项目结构](#15-项目结构)
- [16. 当前限制](#16-当前限制)

## 1. 当前能力

### 1.1 Agent Skills

当前前端提供以下独立入口：

| Skill | 用途 | 必填参数 | 完整运行需要 |
| --- | --- | --- | --- |
| `weekly_market_insight` | 每周市场洞察、关键词需求、竞争格局和 Hsia 研发机会 | `brand`、`marketplace`、`category` | LLM、Sif、SellerSprite |
| `tiktok_us_market_insight` | TikTok Shop 美国市场结构、内容动量、入场窗口和 Hsia 机会 | `brand`、`category`；`marketplace=US` | LLM、FastMoss MCP |
| `hot_product_pain_analysis` | 按品类抓取多个头部商品，逐 ASIN 分析评论痛点和喜欢点 | `marketplace`、`category`、`head_listing_count` | LLM、SellerSprite、Sif |
| `competitor_product_deep_dive` | 围绕一个竞品 ASIN 做产品系统、用户、评论、Reddit 和爆款基因深拆 | `marketplace`、`asin` | LLM、SellerSprite、Sif；Reddit 完整证据还需要 Agent Reach |

缺少必填参数时，Agent 会先提问，不会直接启动数据工具。

### 1.2 技术组成

```text
浏览器
  ↓ http://127.0.0.1:5173
React + Vite 前端
  ↓ /api 反向代理
Python Agent API：http://127.0.0.1:8000
  ├─ LangGraph Agent 运行时
  ├─ Markdown Skills / Evidence Contract
  ├─ OpenAI-compatible LLM
  ├─ SellerSprite MCP
  ├─ Sif MCP
  └─ Agent Reach / OpenCLI / Reddit
```

### 1.3 “部署成功”的两个层级

**层级 A：应用启动成功**

- 前端可以打开；
- 后端健康检查返回 `ok: true`；
- 可以进入 Agent 和设置页面。

这一层不需要任何付费 API 凭证。

**层级 B：Agent 研究成功**

- 已配置可用的 LLM；
- 已配置所选 Skill 需要的数据源；
- Agent 可以完成工具调用并生成最终 `report.html`。

当前 Agent 的任务规划和最终 HTML 报告依赖 LLM。只启动页面但没有配置 LLM，不等于完整研究链路已经可用。

## 2. 部署前准备

### 2.1 必装软件

| 软件 | 要求 | 检查命令 |
| --- | --- | --- |
| Git | 任意近期版本 | `git --version` |
| Python | 3.11 或更高 | `py -3 --version` |
| Node.js | 推荐 Node.js 20 LTS | `node --version` |
| npm | 随 Node.js 安装 | `npm --version` |
| PowerShell | Windows PowerShell 5.1 或 PowerShell 7 | `$PSVersionTable.PSVersion` |

项目脚本会优先使用 `pnpm`，找不到时自动使用 `npm`，因此不强制单独安装 pnpm。

### 2.2 建议准备的凭证

| 凭证 | 是否必需 | 用途 |
| --- | --- | --- |
| 一个 OpenAI-compatible LLM API Key | 完整 Agent 必需 | 选择 Skill、规划工具、分析证据、生成 HTML |
| `SELLERSPRITE_MCP_SECRET_KEY` | Amazon 相关 Skill 基本必需 | SellerSprite 市场、商品、评论和 ASIN 数据 |
| `SIF_MCP_TOKEN` | 当前三个 Skill 建议配置 | 搜索需求、关键词、ASIN 信号和销量代理 |
| Agent Reach / OpenCLI | 仅 Reddit 完整证据需要 | 公开 Reddit 帖子、详情与评论正文 |
| Reddit OAuth | 可选 | Reddit 元数据的备用访问方式 |

没有 SellerSprite 或 Sif 凭证时，应用仍能启动，但依赖这些证据的 Skill 会返回 `needs_user_action` 或数据缺口，不会伪造结果。

### 2.3 网络要求

首次安装需要访问：

- Python 包索引；
- npm/pnpm 包仓库；
- 你配置的 LLM 服务；
- SellerSprite/Sif MCP 服务；
- 可选的 GitHub、Agent Reach、OpenCLI 和 Reddit。

公司代理、防火墙或 SSL 检查可能导致安装和长请求中断。出现问题时先看[常见问题](#12-常见问题)。

## 3. 五分钟完成本地部署

下面所有命令都在 **PowerShell** 中执行。

### 3.1 克隆项目

```powershell
git clone <仓库地址>
cd "Insight Agent"
```

如果仓库目录不是 `Insight Agent`，进入实际克隆出的目录即可。

### 3.2 临时允许执行项目脚本

部分 Windows 电脑默认禁止运行本地 PowerShell 脚本。只对当前终端放开：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

关闭当前 PowerShell 后，该设置自动失效。

### 3.3 一键安装依赖

```powershell
.\scripts\setup.ps1
```

该脚本会：

1. 创建 `.venv` Python 虚拟环境；
2. 升级 pip；
3. 以 editable 模式安装项目和开发依赖：`pip install -e ".[dev]"`；
4. 在不存在 `.env` 时从 `.env.example` 创建 `.env`；
5. 在 `frontend/` 安装 pnpm 或 npm 依赖；
6. 在 `chart-runtime/` 安装固定版本的本机 Flint MCP 图表运行时。

重复执行是安全的，不会覆盖已有 `.env`。

### 3.4 同时启动前后端

```powershell
.\scripts\dev-all.ps1
```

默认地址：

```text
前端：http://127.0.0.1:5173
后端：http://127.0.0.1:8000
```

### 3.5 验证后端

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

预期返回类似：

```text
ok   time
--   ----
True 2026-07-10T...
```

### 3.6 验证前端端口

```powershell
Test-NetConnection 127.0.0.1 -Port 5173
```

确认：

```text
TcpTestSucceeded : True
```

### 3.7 打开页面

```powershell
Start-Process http://127.0.0.1:5173
```

此时已经完成“层级 A：应用启动成功”。继续下一节配置 LLM 和数据源，才能完成真实 Agent 研究。

### 3.8 停止服务

```powershell
.\scripts\stop-dev.ps1
```

## 4. 配置 LLM 与数据源

推荐优先使用 Web UI 配置。设置会写入项目根目录 `.env`，保存后立即同步到当前后端进程。

### 4.1 配置 LLM

打开：

```text
设置 → LLM 连接
```

填写：

1. Provider；
2. Model；
3. Base URL；
4. API Key；
5. Temperature 和 Timeout；
6. 点击保存。

项目支持的 Provider 元数据位于：

```text
src/insight_agent/data/llm_providers.json
```

模型名称必须是你的账号和 Provider 当前实际支持的模型。若返回 `model not found`，请在设置页改成对应平台可用的模型名。

### 4.2 配置 SellerSprite 和 Sif

打开：

```text
设置 → 数据源凭证
```

分别填写：

```text
SellerSprite → SELLERSPRITE_MCP_SECRET_KEY
Sif          → SIF_MCP_TOKEN
```

保存后，状态应从“未配置”变成“已配置”。

### 4.3 直接编辑 `.env`

也可以停止后端后直接修改根目录 `.env`。最小示例：

```env
# LLM 示例：请替换成你实际使用的 Provider、模型和密钥
INSIGHT_LLM_PROVIDER=deepseek
INSIGHT_LLM_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_API_KEY=your_key

# Sif MCP
SIF_MCP_URL=https://mcp.sif.com/mcp
SIF_MCP_SCHEMA_URL=https://mcp.sif.com/mcp-api/tool-schema.json
SIF_MCP_TOKEN=your_sif_token

# SellerSprite MCP
SELLERSPRITE_MCP_URL=https://mcp.sellersprite.com/mcp
SELLERSPRITE_MCP_SECRET_KEY=your_sellersprite_secret
```

手动编辑 `.env` 后重启服务：

```powershell
.\scripts\stop-dev.ps1
.\scripts\dev-all.ps1
```

不要把真实密钥提交到 Git。`.env` 已经在 `.gitignore` 中。

### 4.4 检查 MCP 说明

更详细的配置与工具命名规则：

- [Sif MCP](docs/mcp-sif.md)
- [SellerSprite MCP](docs/mcp-sellersprite.md)

Agent 中的工具名会添加前缀，例如：

```text
market_get_keyword_demand → sif_market_get_keyword_demand
market_research           → sellersprite_market_research
```

## 5. 完成第一次 Agent 研究

### 5.1 市场洞察

在前端选择 **市场洞察**，把默认品类改成你要研究的品类，例如：

```text
帮我生成 Hsia 美国市场 sports bra 本周洞察报告。
品牌：Hsia；市场：Amazon US；时间：最近 90 天。
```

该 Skill 会优先使用 Sif 与 SellerSprite 的关键词、市场和商品证据。

### 5.2 爆款痛点分析

选择 **爆款痛点分析**：

```text
使用 hot_product_pain_analysis Skill 分析 Amazon US minimizer bra 前 5 个头部商品。
逐个 ASIN 汇总好评、差评、尺码与结构痛点，并输出 Hsia 研发机会。
```

### 5.3 爆款竞品深度拆解

选择 **爆款竞品深度拆解**，务必提供目标 ASIN：

```text
使用 competitor_product_deep_dive Skill 深拆 Amazon US ASIN B000000000。
从产品系统、核心用户、评论根因、Reddit 语境、可迁移原则和不应照搬项输出报告。
```

请把示例 ASIN 替换成真实的 10 位 ASIN。

### 5.4 一轮成功研究应该看到什么

1. 左侧出现用户消息；
2. 执行时间线显示 Skill 加载和工具调用；
3. 缺少参数时出现补充问题；
4. 数据源返回成功、部分成功或明确的数据缺口；
5. 最终出现 HTML 产物文件；
6. “任务产出”页可以预览 `report.html`；
7. 刷新或切换设置页后，会话和正在执行的任务仍可恢复。

最终运行文件保存在：

```text
.cache/agent-runs/<run_id>/
```

如果只看到 `needs_user_action`，通常不是部署失败，而是对应 LLM/MCP/Agent Reach 凭证还没有配置完整。

## 6. 配置 Agent Reach 与 Reddit

只有需要 Reddit 帖子和评论正文时才需要这一节。当前 `competitor_product_deep_dive` 会使用 Reddit 做用户语境补充；Reddit 缺失属于可披露的数据缺口，但报告证据会不完整。

### 6.1 安装 Agent Reach、OpenCLI 和辅助工具

```powershell
.\scripts\install-agent-reach.ps1
```

该脚本会：

- 在 `%USERPROFILE%\.agent-reach-venv` 创建独立虚拟环境；
- 安装 Agent Reach；
- 全局安装 OpenCLI；
- 安装/配置 mcporter 与 Exa MCP；
- 把本地工具路径写入 `.env`；
- 运行一次 Agent Reach doctor。

脚本可能使用 `winget` 安装 Node.js LTS，并会访问 GitHub 和 npm。

### 6.2 完成 Chrome 登录态

安装脚本不能代替人工登录：

1. 在 Chrome 安装并启用 OpenCLI Browser Bridge 扩展；
2. 使用专门的 Reddit 账号登录 `reddit.com`；
3. 保持该 Chrome Profile 可用；
4. 运行诊断脚本。

```powershell
.\scripts\doctor-agent-reach.ps1
```

诊断结果中至少应能找到：

```text
agent-reach
opencli
```

并确认 OpenCLI 浏览器扩展处于连接状态。

### 6.3 Agent Reach 环境变量

`.env.example` 默认值：

```env
AGENT_REACH_ENABLED=1
AGENT_REACH_BACKEND=opencli
AGENT_REACH_TIMEOUT=90
AGENT_REACH_DETAIL_LIMIT=20
AGENT_REACH_COMMENTS_PER_POST=20
```

其中：

- `DETAIL_LIMIT`：进入帖子详情页补评论的帖子数；
- `COMMENTS_PER_POST`：每个详情帖最多保留多少条评论；
- 增大数值会显著增加浏览器抓取时间。

### 6.4 Reddit 备用模式

项目仍支持：

| 模式 | 说明 |
| --- | --- |
| `agent_reach` | 首选。通过 OpenCLI/rdt 获取帖子、详情和评论正文 |
| `auto` | Agent Reach → OAuth → RSS → sample |
| `oauth` | 需要 Reddit Client ID 和 Secret |
| `rss` | 只能得到有限帖子信息，通常没有评论正文 |
| `sample` | 使用本地样本，仅用于无网络 UI/流程演示 |

可以在 `.env` 中修改：

```env
INSIGHT_RESEARCH_MODE=sample
```

## 7. 常用脚本

| 命令 | 作用 |
| --- | --- |
| `.\scripts\setup.ps1` | 创建虚拟环境、安装 Python 和前端依赖、创建 `.env` |
| `.\scripts\dev-all.ps1` | 后台同时启动前端和后端 |
| `.\scripts\stop-dev.ps1` | 停止由项目脚本启动的前后端进程，并清理占用端口的进程树 |
| `.\scripts\dev.ps1` | 前台启动后端，适合直接查看日志 |
| `.\scripts\dev-frontend.ps1` | 前台启动前端，适合直接查看 Vite 日志 |
| `.\scripts\test.ps1` | 运行 pytest |
| `.\scripts\check.ps1` | 运行 Ruff、pytest 和前端生产构建 |
| `.\scripts\install-agent-reach.ps1` | 安装 Agent Reach/OpenCLI/mcporter |
| `.\scripts\doctor-agent-reach.ps1` | 检查 Agent Reach、OpenCLI、rdt 和 mcporter |

`dev-all.ps1` 的日志位置：

```text
.dev/backend.log
.dev/backend.err.log
.dev/frontend.log
.dev/frontend.err.log
```

## 8. 手动安装与分别启动

不使用一键脚本时，在项目根目录执行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
}

Set-Location frontend
npm install
Set-Location ..

Set-Location chart-runtime
npm install
Set-Location ..
```

项目的 Python 依赖以 `pyproject.toml` 为主；`requirements.txt` 和 `requirements-dev.txt` 仅保留给兼容旧工具链使用。

分别启动需要两个 PowerShell 窗口。

**终端 1：后端**

```powershell
.\scripts\dev.ps1
```

**终端 2：前端**

```powershell
.\scripts\dev-frontend.ps1
```

兼容入口也可以启动后端：

```powershell
.\.venv\Scripts\python.exe app.py
```

## 9. 测试与构建

首次安装后建议立即运行：

```powershell
.\scripts\check.ps1
```

它会依次执行：

```text
python -m ruff check .
python -m pytest
pnpm/npm build
```

只运行 Python 测试：

```powershell
.\scripts\test.ps1
```

只构建前端：

```powershell
Set-Location frontend
pnpm build
# 没有 pnpm 时：npm run build
Set-Location ..
```

前端构建产物位于 `frontend/dist/`。该目录已被 Git 忽略。

## 10. 数据与文件保存位置

| 路径 | 内容 | 是否应提交 Git |
| --- | --- | --- |
| `.env` | API Key、MCP 凭证和本机工具路径 | 否 |
| `.venv/` | Python 虚拟环境 | 否 |
| `frontend/node_modules/` | 前端依赖 | 否 |
| `.cache/agent-runs/` | Agent 运行状态、工具结果和 HTML 报告 | 否 |
| `.cache/mcp-results/` | FastMoss/SellerSprite/Sif 同参数工具结果缓存，默认保存 7 天 | 否 |
| `.cache/research-history.json` | 旧研究流程历史数据 | 否 |
| `.dev/` | 后台进程 PID 和开发日志 | 否 |
| `frontend/dist/` | 前端构建产物 | 否 |
| `skills/` | Agent Skills、证据合同和报告模板 | 是 |

前端会话列表还会写入当前浏览器的 Local Storage，因此：

- 同一台电脑的不同浏览器不会自动共享会话；
- 清除浏览器站点数据会清除前端会话索引；
- 后端运行目录中的 `.cache/agent-runs/` 仍保留运行文件。

## 11. 环境变量说明

完整模板见 `.env.example`。常用变量如下。

### 11.1 服务与项目目录

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8000` | 后端端口 |
| `INSIGHT_AGENT_HOME` | 当前工作目录 | Skill、缓存和 `.env` 的项目根目录 |
| `VITE_API_URL` | `http://127.0.0.1:8000` | Vite 开发代理的后端地址 |

### 11.2 LLM

| 变量 | 说明 |
| --- | --- |
| `INSIGHT_LLM_PROVIDER` | Provider 名称，例如 `openai`、`deepseek`、`qwen`、`gemini`、`ollama` |
| `INSIGHT_LLM_MODEL` | 实际模型名 |
| `INSIGHT_LLM_TEMPERATURE` | 生成温度 |
| `INSIGHT_LLM_TIMEOUT` | 单次 LLM 请求超时秒数 |
| `<PROVIDER>_BASE_URL` | Provider 的 OpenAI-compatible Base URL |
| `<PROVIDER>_API_KEY` | Provider API Key |

### 11.3 MCP 数据源

| 变量 | 说明 |
| --- | --- |
| `FASTMOSS_MCP_URL` | FastMoss MCP 地址，默认 `https://mcp.fastmoss.com/mcp` |
| `FASTMOSS_MCP_API_KEY` | FastMoss MCP API Key；运行时按官方格式附加为 `api_key` 查询参数 |
| `FASTMOSS_MCP_TOOLS` | 暴露给 Agent 的 FastMoss 工具；留空使用 TK 市场洞察精选工具集，`*` 表示全部 |
| `SELLERSPRITE_MCP_URL` | SellerSprite MCP 地址 |
| `SELLERSPRITE_MCP_SECRET_KEY` | SellerSprite MCP 凭证 |
| `SELLERSPRITE_MCP_TOOLS` | 暴露的 SellerSprite 工具，默认 `*` |
| `SIF_MCP_URL` | Sif MCP 地址 |
| `SIF_MCP_SCHEMA_URL` | Sif schema 地址 |
| `SIF_MCP_TOKEN` | Sif MCP Token |
| `SIF_MCP_TOOLS` | 暴露给 Agent 的 Sif 工具列表 |
| `MCP_RESULT_CACHE_TTL_SECONDS` | MCP 结果缓存有效期，默认 `604800` 秒（7 天）；设为 `0` 可关闭 |
| `MCP_RESULT_CACHE_DIR` | MCP 缓存目录，默认 `.cache/mcp-results/` |
| `FLINT_CHART_NODE_COMMAND` | 本机 Flint MCP 使用的 Node 命令，默认 `node` |
| `FLINT_CHART_MCP_CLI` | 可选的 Flint MCP CLI 绝对路径；留空使用 `chart-runtime/` 固定依赖 |
| `FLINT_CHART_TIMEOUT_SECONDS` | 单张图表 MCP 调用超时，默认 `20` 秒 |
| `FLINT_CHART_TOTAL_TIMEOUT_SECONDS` | 单份报告全部图表的总超时，默认 `120` 秒 |

FastMoss、SellerSprite 与 Sif 会按“数据源 + 工具名 + 规范化参数”共享本地缓存。相同参数在有效期内不会再次消耗远端调用额度；失败、鉴权失败和参数缺失结果不会写入缓存。任务参数中的 `bypassCache=true` 会跳过读取、重新调用 MCP，并用新结果覆盖旧缓存。

### 11.4 Reddit 与 Agent Reach

| 变量 | 说明 |
| --- | --- |
| `AGENT_REACH_ENABLED` | 是否启用 Agent Reach |
| `AGENT_REACH_BACKEND` | `opencli` 或其他 Agent Reach 后端 |
| `AGENT_REACH_VENV` | Agent Reach 独立虚拟环境路径 |
| `AGENT_REACH_BIN_DIR` | 本机 npm/OpenCLI/mcporter 命令目录 |
| `REDDIT_CLIENT_ID` | 可选 Reddit OAuth Client ID |
| `REDDIT_CLIENT_SECRET` | 可选 Reddit OAuth Secret |

### 11.5 采集与上下文容量

`.env.example` 中的 `AMAZON_*`、`INSIGHT_RESEARCH_*` 和 `INSIGHT_LLM_*` 容量变量用于旧采集工具和 LLM 上下文限制。增大抓取量会增加运行时间、工具调用次数和模型成本。

## 12. 常见问题

### 12.1 PowerShell 提示“禁止运行脚本”

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

或者直接：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

### 12.2 找不到 Python 或版本低于 3.11

```powershell
py -0p
py -3 --version
```

安装 Python 3.11+ 后重新运行 `setup.ps1`。也可以指定解释器：

```powershell
$env:INSIGHT_PYTHON="C:\Path\To\python.exe"
.\scripts\setup.ps1
```

### 12.3 找不到 npm/pnpm

确认 Node.js LTS 已安装，并重新打开 PowerShell：

```powershell
node --version
npm --version
```

也可以指定 pnpm：

```powershell
$env:INSIGHT_PNPM="C:\Path\To\pnpm.cmd"
.\scripts\setup.ps1
```

### 12.4 端口 8000 或 5173 被占用

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen |
  Select-Object LocalPort,OwningProcess
```

先尝试：

```powershell
.\scripts\stop-dev.ps1
.\scripts\dev-all.ps1
```

前端已经配置 `strictPort`，5173 被占用时会明确失败，不会悄悄切换到 5174。查看 `.dev/frontend.err.log` 获取错误详情。

### 12.5 前端能打开，但 API 请求失败

先检查后端：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Get-Content .dev\backend.err.log -Tail 100
```

再检查 Vite 代理目标是否被自定义：

```powershell
$env:VITE_API_URL
```

默认应为空，前端会代理到 `http://127.0.0.1:8000`。

### 12.6 后端提示无法导入 `insight_agent`

```powershell
.\scripts\setup.ps1
```

不要直接用系统 Python 绕过 `.venv`。项目脚本会自动设置 `PYTHONPATH=src`。

### 12.7 LLM API Key 已填，但仍然失败

依次检查：

1. Provider 与 API Key 是否匹配；
2. Base URL 是否包含正确的 `/v1` 或兼容路径；
3. 模型名是否被该账号支持；
4. 公司代理/SSL 是否中断长请求；
5. `INSIGHT_LLM_TIMEOUT` 是否过小。

如果手动改了 `.env`，必须重启后端。

### 12.8 SellerSprite 或 Sif 返回 `needs_user_action`

- 检查设置页是否显示“已配置”；
- 检查 `.env` 中是否误留 `your_key`、`xxx` 等占位值；
- 确认 Token/Secret 没有过期；
- 确认账号有对应 MCP 工具权限；
- 查看执行时间线中的真实工具名和错误摘要。

### 12.9 Agent Reach/OpenCLI 不可用

```powershell
.\scripts\doctor-agent-reach.ps1
```

确保：

1. Chrome 已启动；
2. OpenCLI 扩展已启用；
3. 使用同一个 Chrome Profile 登录 Reddit；
4. `opencli doctor` 显示连接成功；
5. 修复后重新运行任务，避免继续使用旧缓存结果。

### 12.10 抓到了帖子，但没有评论正文

- RSS 模式通常没有评论正文；
- OAuth 在当前项目中主要提供元数据；
- 使用 Agent Reach + OpenCLI；
- 确认 `AGENT_REACH_DETAIL_LIMIT` 和 `AGENT_REACH_COMMENTS_PER_POST` 大于 0；
- 评论抓取需要浏览器逐页读取，速度会比只搜帖子慢。

### 12.11 后台启动后没有页面

查看四个日志：

```powershell
Get-Content .dev\backend.log -Tail 100
Get-Content .dev\backend.err.log -Tail 100
Get-Content .dev\frontend.log -Tail 100
Get-Content .dev\frontend.err.log -Tail 100
```

也可以分别前台启动，以便直接看到异常：

```powershell
.\scripts\dev.ps1
.\scripts\dev-frontend.ps1
```

## 13. 更新项目

```powershell
.\scripts\stop-dev.ps1
git pull
.\scripts\setup.ps1
.\scripts\check.ps1
.\scripts\dev-all.ps1
```

`setup.ps1` 不会覆盖已有 `.env`。如果 `.env.example` 新增了字段，请手动把需要的字段补到 `.env`，或通过设置页保存。

## 14. 内网与生产部署说明

当前脚本是 **本机内部工具部署**：

- 前后端只绑定 `127.0.0.1`；
- 没有用户账号、权限系统和服务端会话隔离；
- 浏览器会话历史保存在各自 Local Storage；
- `.env` 中保存第三方 API 凭证；
- `dev-all.ps1` 使用开发服务器，不是互联网生产部署方案。

因此：

> 不要直接把 5173 或 8000 端口暴露到公网。

如果要给公司十多人通过内网共同使用，至少需要补充：

1. 正式静态文件服务器和 Python 进程守护；
2. HTTPS 与反向代理；
3. 登录、权限和密钥隔离；
4. 服务端数据库会话；
5. 并发任务队列和取消机制；
6. 日志、备份和运行监控。

在这些能力完成前，推荐每位研究负责人在自己的 Windows 工作站部署，或只在受控内网机器上运行。

## 15. 项目结构

```text
.
├── frontend/                         # React + Vite Web UI
│   ├── src/App.tsx                   # Agent、会话、产物和设置页面
│   └── src/lib/api.ts                # 后端 API 与 SSE 客户端
├── src/insight_agent/
│   ├── server.py                     # HTTP API、工具注册与报告渲染
│   ├── agent_runtime.py              # LangGraph Agent 状态编排
│   ├── agent_params.py               # 参数标准化与工具参数适配
│   ├── llm.py                        # OpenAI-compatible LLM 客户端
│   ├── mcp_sif.py                    # Sif MCP 适配
│   ├── mcp_sellersprite.py           # SellerSprite MCP 适配
│   ├── mcp_fastmoss.py               # FastMoss MCP 适配与缓存接入
│   ├── ingestion/                    # Agent Reach、OpenCLI 等采集层
│   └── data/llm_providers.json       # LLM Provider 元数据
├── skills/
│   ├── weekly_market_insight/
│   ├── tiktok_us_market_insight/
│   ├── hot_product_pain_analysis/
│   ├── competitor_product_deep_dive/
│   └── _template/                    # 新 Skill 模板
├── tests/                            # Python 自动化测试
├── scripts/                          # Windows 安装、启动、检查和诊断脚本
├── docs/                             # MCP、Skill 和架构文档
├── pyproject.toml                    # Python 主依赖与工具配置
├── requirements.txt                 # 兼容旧安装工具
├── .env.example                     # 完整环境变量模板
└── app.py                            # 兼容后端入口
```

新增或修改 Skill 时请遵循：

- [Skill 编写标准](docs/skill-authoring-standard.md)
- [Skill 审核清单](docs/skill-review-checklist.md)

## 16. 当前限制

- SellerSprite、Sif、Amazon 和社媒数据均受账号权限、平台限制、时间窗口和工具口径影响；
- review count、BSR 和第三方销量字段只能作为代理信号，不应被描述为 Amazon 后台真实销量；
- 从单个关键词出发不能证明覆盖完整市场；市场定义、关键词扩展、父子 ASIN 去重和覆盖率仍需要明确审计；
- Reddit 可用性依赖登录态、扩展连接和平台限流；
- LLM 结论必须追溯到工具证据，不能替代运营、设计和研发人员的最终判断；
- 当前没有 SaaS 级多租户、权限、计费和高并发能力。

项目定位是先把“数据获取 → 证据链 → LLM 分析 → HTML 产物”跑通，再逐步加强市场边界、去重、覆盖率和内部决策工作流。
