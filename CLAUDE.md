# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

MuMuAINovel（木木AI小说助手）是一个基于AI的智能小说创作助手，支持多AI模型、角色管理、章节编辑和世界观设定。

**技术栈**: FastAPI + React 18 + PostgreSQL + TypeScript + Zustand

## 常用命令

### 后端开发

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
python -m uvicorn app.main:app --host localhost --port 8000 --reload
```

### 前端开发

```bash
cd frontend
npm install
npm run dev      # 开发模式
npm run build    # 生产构建
npm run lint     # 代码检查
```

### Docker 部署

```bash
docker-compose up -d              # 启动服务
docker-compose logs -f mumuainovel  # 查看日志
docker-compose down               # 停止服务
```

### API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 架构概述

### 后端结构 (backend/app/)

```
api/           # API路由（17个模块）
├── auth.py           # 认证（LinuxDO OAuth + 本地账户）
├── wizard_stream.py  # 项目创建向导（SSE流式）
├── chapters.py       # 章节管理和内容生成
├── outlines.py       # 大纲管理
├── characters.py     # 角色管理
├── mcp_plugins.py    # MCP插件管理
└── ...

models/        # SQLAlchemy ORM模型
schemas/       # Pydantic数据验证
services/      # 业务逻辑
├── ai_service.py     # AI集成（OpenAI/Claude/Gemini）
├── memory_service.py # 向量化和记忆系统（ChromaDB）
├── mcp_tool_service.py # MCP工具调用
└── prompt_service.py # 提示词管理

mcp/           # Model Context Protocol实现
├── registry.py       # 插件注册
└── adapters/         # 适配器（UniversalMCPAdapter等）

middleware/    # 认证和请求追踪中间件
```

### 前端结构 (frontend/src/)

```
pages/         # 页面组件（ProjectList, Chapters, Characters等）
components/    # 可复用组件（SSELoadingOverlay等）
services/api.ts    # Axios实例和API方法
store/index.ts     # Zustand全局状态
types/index.ts     # TypeScript接口定义
utils/sseClient.ts # SSE客户端
```

## 关键架构模式

### 1. 数据隔离
- 多用户共享数据库，通过 `user_id` 字段隔离数据
- 所有查询必须过滤 `user_id`（通过 `request.state.user_id` 获取）

### 2. SSE流式生成
- 用于长时间AI生成操作（避免HTTP超时）
- 后端: `utils/sse_response.py` + `api/wizard_stream.py`
- 前端: `utils/sseClient.ts` + `components/SSELoadingOverlay.tsx`
- 注意处理 `GeneratorExit` 异常防止会话泄漏

### 3. MCP工具调用
- 适配器模式: `UniversalMCPAdapter`（自动检测AI能力）、`FunctionCallingAdapter`、`PromptInjectionAdapter`
- 生命周期管理: `mcp/registry.py`

### 4. 大纲模式
- **one-to-one**: 一个大纲点对应一个章节（传统模式）
- **one-to-many**: 一个大纲点可扩展为多个章节（细化模式）

### 5. 连接池管理
- PostgreSQL: 50核心连接 + 30溢出连接
- HTTP客户端: 按配置分类复用
- 配置: `database.py` 中的 `DATABASE_POOL_SIZE`、`DATABASE_MAX_OVERFLOW`

## 开发约定

### 后端
- 所有I/O操作使用 `async def`
- 使用 `Depends(get_db)` 获取数据库会话
- 日志使用 `logger.info/warning/error`
- 错误返回 `HTTPException`

### 前端
- 所有组件和函数标注TypeScript类型
- API调用通过 `services/api.ts` 统一接口
- 状态管理使用Zustand store

### 新增功能流程
1. 后端: `api/` 路由 → `models/` ORM → `schemas/` 验证 → `services/` 逻辑
2. 前端: `pages/` 页面 → `services/api.ts` API → `types/index.ts` 类型

## 环境配置

关键配置项（`.env`文件）:

```bash
# 数据库
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/db

# AI服务
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_MODEL=gpt-4o-mini

# 认证
LOCAL_AUTH_ENABLED=true
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD=your_password
```

## 调试端点

- `GET /health` - 应用健康状态
- `GET /health/db-sessions` - 数据库会话统计
