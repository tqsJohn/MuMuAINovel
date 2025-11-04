# CLAUDE.md

这个文件为 Claude Code (claude.ai/code) 在此代码库中工作提供指导。

## 项目概述

MuMuAINovel 是一个基于 AI 的智能小说创作助手，采用前后端分离架构：
- **后端**：FastAPI + SQLAlchemy (异步) + SQLite
- **前端**：React 18 + TypeScript + Ant Design + Zustand
- **AI集成**：支持 OpenAI、Anthropic Claude、Google Gemini 等多个 AI 提供商

核心功能包括：向导式小说项目创建、AI 自动生成大纲/角色/世界观、章节编辑与润色、RAG 记忆系统、写作风格管理等。

## 开发环境设置

### 后端开发

```bash
# 进入后端目录
cd backend

# 创建并激活虚拟环境
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量（从示例文件复制）
cp .env.example .env
# 编辑 .env，至少配置一个 AI 服务的 API Key

# 运行开发服务器（带热重载）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 或直接运行
python -m app.main
```

### 前端开发

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 开发模式（需要后端已启动在 8000 端口）
npm run dev

# 生产构建
npm run build

# Lint 检查
npm run lint
```

### Docker 部署

```bash
# 使用 Docker Compose 启动（会自动构建）
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down

# 重新构建
docker-compose up -d --build
```

## 核心架构

### 后端架构 (backend/app/)

**入口与配置**：
- `main.py` - FastAPI 应用入口，路由注册，全局异常处理，SPA 静态文件服务
- `config.py` - 基于 Pydantic Settings 的配置管理，从 .env 加载环境变量
- `database.py` - 异步 SQLAlchemy 引擎和会话管理，**多用户数据隔离**（每个用户独立的 SQLite 文件）

**数据层** (models/):
- 使用 SQLAlchemy 异步 ORM
- 核心模型：`Project`, `Outline`, `Character`, `Chapter`, `WritingStyle`, `StoryMemory`, `PlotAnalysis`
- 关系管理：`CharacterRelationship`, `Organization`, `OrganizationMember`
- 用户和设置：通过 `user_manager.py` 管理，支持 LinuxDO OAuth 和本地账户登录

**业务逻辑** (services/):
- `ai_service.py` - **AI 服务统一封装**，使用 httpx 自定义请求头避免触发 Cloudflare，支持流式响应
  - OpenAI 兼容接口（支持中转 API）
  - Anthropic Claude 接口
  - 统一的 `stream_chat()` 和 `chat()` 方法
- `prompt_service.py` - 写作风格管理（6种预设风格）和提示词应用
- `memory_service.py` - RAG 长期记忆系统（ChromaDB + sentence-transformers）
- `plot_analyzer.py` - 章节剧情分析服务
- `import_export_service.py` - 项目数据导入导出
- `oauth_service.py` - LinuxDO OAuth2 认证服务

**API 路由** (api/):
- `auth.py` - 认证接口（LinuxDO OAuth、本地账户登录、会话刷新）
- `projects.py` - 项目 CRUD
- `wizard_stream.py` - **向导流式生成**（SSE 流式返回 AI 生成的大纲、角色、世界观）
- `chapters.py` - 章节生成、编辑、润色、重新生成
- `characters.py` - 角色管理
- `outlines.py` - 大纲管理
- `writing_styles.py` - 写作风格管理
- `memories.py` - 记忆系统 API

**中间件** (middleware/):
- `RequestIDMiddleware` - 为每个请求添加唯一 ID
- `AuthMiddleware` - 会话验证和用户身份识别（从 session token 提取 user_id）

**工具** (utils/):
- 包含各种辅助函数和工具类

### 前端架构 (frontend/src/)

**状态管理** (store/):
- 使用 Zustand 进行全局状态管理
- `authStore` - 用户认证状态和会话管理

**页面组件** (pages/):
- `ProjectList.tsx` - 项目列表页
- `ProjectWizardNew.tsx` - **向导式创建**（SSE 流式接收 AI 生成内容）
- `Chapters.tsx` - 章节管理页（生成、编辑、润色）
- `Characters.tsx` - 角色管理页
- `Outline.tsx` - 大纲管理页

**服务层** (services/):
- 使用 Axios 进行 API 调用
- 自动处理认证 token 和错误

**类型定义** (types/):
- TypeScript 类型定义，与后端 schemas 对应

## 重要实现细节

### 多用户数据隔离

数据库使用**用户级隔离**策略，每个用户有独立的 SQLite 文件：
- 数据库文件路径：`data/ai_story_user_{user_id}.db`
- 在 `database.py` 的 `get_engine()` 中实现引擎缓存和线程安全
- API 中通过 `AuthMiddleware` 从 session token 提取 `user_id`
- 使用 `get_db_session(request: Request)` 获取用户专属数据库会话

### AI 服务调用机制

**关键优化**（避免触发 Cloudflare）：
- 不使用 OpenAI SDK 的内置 HTTP 客户端
- 使用 httpx 构建自定义 HTTP 客户端，添加标准浏览器 User-Agent
- 连接池配置：max_keepalive_connections=50, max_connections=100

**流式响应**：
- 后端使用 `StreamingResponse` + `text/event-stream`
- 前端使用 EventSource 或 fetch + ReadableStream 接收

**Deepseek 模型特殊处理**：
- 舍弃 `reasoning_content`（思考过程），只保留 `content`（结果内容）

### 会话管理

- 会话过期时间：默认 120 分钟（可通过 `SESSION_EXPIRE_MINUTES` 配置）
- 会话刷新阈值：默认 30 分钟（可通过 `SESSION_REFRESH_THRESHOLD_MINUTES` 配置）
- 前端应在会话即将过期时调用 `/api/auth/refresh-session` 刷新

### RAG 记忆系统

- 使用 ChromaDB 作为向量数据库
- sentence-transformers 生成 embeddings
- 支持章节内容的语义检索和剧情分析
- 相关模型：`StoryMemory`, `PlotAnalysis`, `AnalysisTask`

## 常见开发任务

### 添加新的 API 端点

1. 在 `backend/app/api/` 创建或编辑路由文件
2. 在 `backend/app/models/` 添加或修改数据模型（如需要）
3. 在 `backend/app/schemas/` 添加 Pydantic 验证模型
4. 在 `main.py` 中注册路由：`app.include_router(your_router, prefix="/api")`
5. 前端在 `src/services/` 添加 API 调用函数
6. 在 `src/types/` 添加 TypeScript 类型定义

### 修改 AI 提示词

1. 查看 `backend/app/services/prompt_service.py` 中的预设风格
2. 具体的提示词模板通常嵌入在各个 API 路由中（如 `wizard_stream.py`, `chapters.py`）
3. 注意写作风格的应用：使用 `WritingStyleManager.apply_style_to_prompt()`

### 数据库迁移

项目使用 SQLAlchemy，但**未集成 Alembic**。数据库结构变更：
1. 修改 `backend/app/models/` 中的模型定义
2. 删除或备份现有的数据库文件（`backend/data/ai_story_user_*.db`）
3. 重启应用，数据库会自动重建（通过 `database.py` 中的 `init_db()`）

**生产环境建议**：集成 Alembic 进行版本化迁移管理。

### 添加新的 AI 提供商

1. 在 `backend/app/services/ai_service.py` 的 `AIService` 类中添加新客户端初始化
2. 在 `stream_chat()` 和 `chat()` 方法中添加对应的调用逻辑
3. 在 `backend/.env.example` 和 `backend/app/config.py` 添加配置项
4. 更新前端设置页面以支持新提供商配置

## 测试

目前项目**未包含单元测试**。建议添加：
- 后端：使用 pytest + pytest-asyncio
- 前端：使用 Vitest + React Testing Library

## API 文档

启动后端后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 日志

- 后端日志：`backend/logs/app.log`（按日期轮转，保留 30 个备份）
- 日志级别在 `.env` 中配置：`LOG_LEVEL=INFO`

## 数据存储

- 数据库文件：`backend/data/ai_story_user_{user_id}.db`
- 向量数据库（ChromaDB）：存储在内存或 `backend/data/chroma/`（取决于配置）

## 环境变量关键配置

**必需配置**：
- `OPENAI_API_KEY` 或 `ANTHROPIC_API_KEY`：至少配置一个 AI 服务
- `LOCAL_AUTH_PASSWORD`：本地登录密码（生产环境务必修改）

**可选但推荐**：
- `OPENAI_BASE_URL`：使用中转 API 时修改（如 New API、API2D 等）
- `DEFAULT_AI_PROVIDER`：选择默认提供商（openai/anthropic）
- `DEFAULT_MODEL`：选择默认模型（如 gpt-4o-mini, claude-3-sonnet）
- `SESSION_EXPIRE_MINUTES`：会话过期时间
- `LINUXDO_CLIENT_ID`, `LINUXDO_CLIENT_SECRET`：启用 LinuxDO OAuth 登录

## 已知问题与注意事项

1. **Deepseek 模型**：会返回思考过程（`reasoning_content`），代码中已处理，只使用 `content`
2. **并发生成**：向导式生成使用 SSE，注意数据库会话管理避免连接泄漏
3. **Cloudflare 拦截**：使用自定义 User-Agent 和 httpx 客户端避免被部分公益站拦截
4. **Token 限制**：注意不同模型的 token 限制，`DEFAULT_MAX_TOKENS=32000` 仅为默认值
5. **数据库锁**：SQLite 在高并发下可能出现锁等待，考虑切换到 PostgreSQL（需修改 `database.py`）

## Git 工作流

- 主分支：`main`
- 开发分支：`dev`
- 提交信息遵循常规格式（如有约定）
- **重要**：不要提交 `.env` 文件和 `data/` 目录（已在 .gitignore 中）
