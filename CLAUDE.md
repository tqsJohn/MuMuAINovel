# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

MuMuAINovel 是一个基于 AI 的智能小说创作助手，采用前后端分离架构：
- **后端**：FastAPI + SQLAlchemy (异步) + SQLite (每用户独立数据库)
- **前端**：React 18 + TypeScript + Ant Design + Zustand
- **AI集成**：OpenAI、Anthropic Claude、支持中转 API

核心功能：向导式小说项目创建、AI 生成大纲/角色/世界观、章节编辑与润色、RAG 记忆系统、写作风格管理。

## 开发环境设置

### 快速启动

**后端**：
```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # 编辑 .env 配置至少一个 AI 服务的 API Key
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**前端**：
```bash
cd frontend
npm install
npm run dev          # 开发模式
npm run build        # 生产构建
npm run lint         # Lint 检查
```

**Docker 部署**：
```bash
# 配置 .env 后直接启动
docker-compose up -d
docker-compose logs -f  # 查看日志
```

## 核心架构

### 后端架构 (backend/app/)

```
app/
├── main.py              # FastAPI 应用入口，路由注册，全局异常处理，SPA 服务
├── config.py            # Pydantic Settings 配置管理
├── database.py          # 异步 SQLAlchemy，多用户数据库隔离（重要！）
├── user_manager.py      # 用户会话管理（Cookie + 内存存储）
├── logger.py            # 日志配置
├── api/                 # API 路由层
│   ├── auth.py          # 认证（LinuxDO OAuth + 本地账户）
│   ├── projects.py      # 项目 CRUD
│   ├── wizard_stream.py # ⭐ SSE 流式向导生成
│   ├── chapters.py      # 章节生成、编辑、润色
│   ├── characters.py    # 角色管理
│   ├── outlines.py      # 大纲管理
│   ├── writing_styles.py# 写作风格管理
│   ├── memories.py      # RAG 记忆系统
│   └── ...
├── models/              # SQLAlchemy 模型（异步）
│   ├── project.py
│   ├── character.py
│   ├── chapter.py
│   ├── relationship.py  # 角色关系、组织
│   ├── memory.py        # RAG 记忆
│   └── ...
├── schemas/             # Pydantic 验证模型
├── services/            # 业务逻辑层
│   ├── ai_service.py    # ⭐ AI 统一封装（OpenAI/Claude，自定义 httpx 客户端）
│   ├── prompt_service.py# 提示词和写作风格管理
│   ├── memory_service.py# ChromaDB + sentence-transformers
│   └── oauth_service.py # LinuxDO OAuth2
├── middleware/          # 中间件
│   ├── auth_middleware.py # 从 Cookie 提取 user_id 注入 request.state
│   └── request_id.py    # 请求 ID 追踪
└── utils/               # 工具函数
    ├── sse_response.py  # SSE 流式响应封装
    └── ...
```

### 前端架构 (frontend/src/)

```
src/
├── pages/               # 页面组件
│   ├── ProjectList.tsx
│   ├── ProjectWizardNew.tsx  # ⭐ SSE 流式接收
│   ├── Chapters.tsx
│   ├── Characters.tsx
│   └── Outline.tsx
├── components/          # 通用组件
├── services/            # API 调用（Axios）
├── store/               # Zustand 状态管理
│   └── authStore.ts     # 认证状态
├── types/               # TypeScript 类型定义
└── utils/
```

## 关键架构模式

### 1. 多用户数据库隔离 (database.py)

**核心机制**：每个用户独立的 SQLite 文件
```python
# 数据库文件: data/ai_story_user_{user_id}.db
# 引擎缓存: _engine_cache 字典，按 user_id 索引
# 线程安全: asyncio.Lock 保护引擎创建过程
```

**工作流程**：
1. `AuthMiddleware` 从 Cookie 提取 `user_id` → `request.state.user_id`
2. API 依赖 `get_db(request)` → 根据 `user_id` 获取用户专属引擎
3. 引擎缓存避免重复创建，首次创建时自动初始化数据库表

**会话统计监控**：访问 `/health/db-sessions` 查看连接泄漏

### 2. AI 服务封装 (services/ai_service.py)

**关键优化**（避免 Cloudflare 拦截）：
```python
# ❌ 不直接使用 OpenAI SDK 的默认 HTTP 客户端
# ✅ 使用自定义 httpx.AsyncClient
http_client = httpx.AsyncClient(
    headers={"User-Agent": "Mozilla/5.0 ..."},  # 模拟浏览器
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=100)
)
```

**统一接口**：
- `stream_chat()` - 流式生成（SSE）
- `chat()` - 一次性生成
- 支持 OpenAI 兼容接口（含中转 API）和 Anthropic Claude

**Deepseek 模型特殊处理**：自动丢弃 `reasoning_content`，仅保留 `content`

### 3. SSE 流式响应 (wizard_stream.py + utils/sse_response.py)

**后端**：
```python
async def generator() -> AsyncGenerator[str, None]:
    yield await SSEResponse.send_progress("开始生成...", 10)
    async for chunk in ai_service.stream_chat(...):
        yield await SSEResponse.send_chunk(chunk)
    yield await SSEResponse.send_complete(accumulated_text)

return create_sse_response(generator())
```

**前端**：使用 EventSource 或 `fetch` + ReadableStream 接收
- 避免长时间阻塞超时
- 实时反馈生成进度

**数据库会话管理**：SSE 中手动控制事务提交，避免 GeneratorExit 泄漏

### 4. 会话与认证

- **会话存储**：`user_manager.py` 内存存储（重启后失效）
- **Cookie 传递**：`user_id` Cookie → `AuthMiddleware` → `request.state.user_id`
- **过期时间**：默认 120 分钟，刷新阈值 30 分钟（`/api/auth/refresh-session`）

### 5. RAG 记忆系统

- **向量数据库**：ChromaDB
- **Embeddings**：sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
- **功能**：章节内容语义检索、剧情分析
- **模型**：`StoryMemory`, `PlotAnalysis`, `AnalysisTask`

## 常见开发任务

### 添加新 API 端点

1. **创建路由**：`backend/app/api/your_router.py`
   ```python
   from fastapi import APIRouter, Depends
   from app.database import get_db

   router = APIRouter(prefix="/your-prefix", tags=["标签"])

   @router.get("/")
   async def your_endpoint(db: AsyncSession = Depends(get_db)):
       # user_id 已通过 AuthMiddleware 注入到 request.state
       pass
   ```

2. **添加模型**（如需要）：
   - `backend/app/models/your_model.py` - SQLAlchemy 模型
   - `backend/app/schemas/your_schema.py` - Pydantic 模型

3. **注册路由**：`backend/app/main.py`
   ```python
   from app.api import your_router
   app.include_router(your_router.router, prefix="/api")
   ```

4. **前端集成**：
   - `frontend/src/services/yourService.ts` - API 调用
   - `frontend/src/types/your.ts` - TypeScript 类型

### 修改 AI 提示词

**预设风格**：`backend/app/services/prompt_service.py` - `WritingStyleManager`
- 6种预设风格：玄幻仙侠、现代都市、科幻未来、悬疑推理、武侠江湖、古风言情

**提示词模板**：
- 向导生成：`wizard_stream.py` - `world_building_generator()`, `character_generator()` 等
- 章节生成：`chapters.py` - `generate_chapter_content()`

**应用风格**：
```python
from app.services.prompt_service import WritingStyleManager
styled_prompt = WritingStyleManager.apply_style_to_prompt(base_prompt, style_config)
```

### 数据库迁移

**当前方式**：未集成 Alembic，手动管理
1. 修改 `backend/app/models/` 中的模型
2. 删除/备份数据库文件：`backend/data/ai_story_user_*.db`
3. 重启应用，`database.py` 的 `init_db()` 自动重建

**生产环境建议**：集成 Alembic 进行版本化迁移

### 添加新 AI 提供商

1. **修改 AI 服务**：`backend/app/services/ai_service.py`
   - `__init__()` - 初始化客户端
   - `stream_chat()` / `chat()` - 添加调用逻辑

2. **配置管理**：
   - `backend/.env.example` - 添加示例配置
   - `backend/app/config.py` - 添加配置字段

3. **前端设置**：更新设置页面支持新提供商选择

### 调试 SSE 流式生成问题

**后端检查**：
```bash
# 查看数据库会话统计，检测连接泄漏
curl http://localhost:8000/health/db-sessions

# 查看日志
tail -f backend/logs/app.log
```

**常见问题**：
- `GeneratorExit` - 客户端断开连接，已自动处理事务回滚
- 活跃会话数过多 (>100) - 可能存在连接泄漏
- Cloudflare 拦截 - 检查 `ai_service.py` 的 User-Agent 配置

## 测试与监控

**测试**：目前无单元测试，建议添加：
- 后端：pytest + pytest-asyncio
- 前端：Vitest + React Testing Library

**API 文档**：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

**健康检查**：
- 基础健康：`GET /health`
- 数据库会话统计：`GET /health/db-sessions`

**日志**：
- 文件：`backend/logs/app.log`（按日期轮转，保留 30 个备份）
- 级别：`.env` 中配置 `LOG_LEVEL=INFO`

**数据存储**：
- 数据库：`backend/data/ai_story_user_{user_id}.db`
- ChromaDB：`backend/data/chroma/` 或内存

## 环境变量配置

**必需配置**（`backend/.env`）：
```bash
# AI 服务（至少配置一个）
OPENAI_API_KEY=sk-...           # OpenAI API Key
ANTHROPIC_API_KEY=sk-ant-...    # Anthropic API Key

# 本地账户（生产环境务必修改密码）
LOCAL_AUTH_PASSWORD=your_secure_password_here
```

**推荐配置**：
```bash
# 中转 API（如使用）
OPENAI_BASE_URL=https://api.new-api.com/v1  # 或其他中转服务

# 默认 AI 设置
DEFAULT_AI_PROVIDER=openai                   # openai/anthropic
DEFAULT_MODEL=gpt-4o-mini                    # 或 claude-3-5-sonnet-20241022
DEFAULT_TEMPERATURE=0.8
DEFAULT_MAX_TOKENS=32000

# LinuxDO OAuth（可选）
LINUXDO_CLIENT_ID=...
LINUXDO_CLIENT_SECRET=...
LINUXDO_REDIRECT_URI=http://localhost:8000/api/auth/callback
```

**推荐模型**：
- OpenAI：`gpt-4o`, `gpt-4o-mini`, `gpt-3.5-turbo`
- Anthropic：`claude-3-5-sonnet-20241022`, `claude-3-opus-20240229`
- Deepseek：`deepseek-chat`（自动处理 reasoning_content）

## 已知问题与限制

1. **Deepseek 模型特殊处理**：自动丢弃 `reasoning_content`，仅使用 `content`
2. **SQLite 并发限制**：高并发场景可能出现锁等待，考虑切换 PostgreSQL
3. **Cloudflare 拦截**：已使用自定义 User-Agent 规避，如仍被拦截检查中转 API 配置
4. **会话内存存储**：用户会话存储在内存中，服务重启后需重新登录
5. **无数据库迁移工具**：数据库结构变更需手动处理，生产环境建议集成 Alembic
6. **SSE 连接断开**：客户端断开会触发 `GeneratorExit`，已自动处理事务回滚

## Git 工作流

- **主分支**：`main`
- **开发分支**：`dev`
- **当前分支**：`chaos/增加短篇能力-1104`
- **注意**：不要提交 `.env` 文件和 `data/` 目录（已在 .gitignore）
