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
# 双重锁保护:
#   - _cache_lock: 保护引擎锁字典创建
#   - _engine_locks[user_id]: 每用户独立锁，防止并发创建
```

**SQLite 性能优化**（自动应用）：
```python
PRAGMA journal_mode=WAL        # Write-Ahead Log 模式，提升并发性能
PRAGMA synchronous=NORMAL      # 平衡性能与数据安全
PRAGMA cache_size=-64000       # 64MB 内存缓存
PRAGMA temp_store=MEMORY       # 临时表存储在内存
PRAGMA busy_timeout=5000       # 5秒锁等待超时
```

**工作流程**：
1. `AuthMiddleware` 从 Cookie 提取 `user_id` → `request.state.user_id`
2. API 依赖 `get_db(request)` → 根据 `user_id` 获取用户专属引擎
3. 引擎缓存避免重复创建，首次创建时自动初始化数据库表

**会话统计监控**：
```bash
# 查看连接泄漏和会话统计
curl http://localhost:8000/health/db-sessions

# 返回数据：
# - created: 总创建会话数
# - closed: 总关闭会话数
# - active: 当前活跃会话数（正常应接近 0）
# - errors: 错误次数
# - generator_exits: SSE 断开次数
# - warning: 活跃会话数 >10 时发出警告
```

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

**关键事务管理模式**（防止 GeneratorExit 数据丢失）：
```python
db_committed = False
try:
    # ... 生成流程
    await db.commit()
    db_committed = True
    yield SSEResponse.send_complete(...)
except GeneratorExit:
    # 客户端断开连接
    if not db_committed and db.in_transaction():
        await db.rollback()
        logger.warning("SSE 断开，已回滚未提交事务")
    raise
```

**AI 幻觉引用清理**（批量角色生成）：
- 问题：AI 可能生成不存在的角色/组织引用
- 解决：预处理阶段构建有效实体集合，清理 `relationships_array` 和 `organization_memberships` 中的无效引用
- 避免数据库外键约束错误

**分批生成策略**：
```python
BATCH_SIZE = 3        # 每批生成 3 个角色
MAX_RETRIES = 3       # 最多重试 3 次
# 严格验证生成数量，不匹配则重试
```

**前端接收**：
```typescript
wizardStreamApi.generateWorldBuildingStream(data, {
  onProgress: (msg, prog) => { /* 进度更新 */ },
  onResult: (data) => { /* 结果处理 */ },
  onError: (error) => { /* 错误处理 */ },
  onComplete: () => { /* 完成回调 */ }
})
```

### 4. 会话与认证

**会话管理机制**：
- **会话存储**：`user_manager.py` 内存存储（重启后失效）
- **Cookie 传递**：`user_id` Cookie → `AuthMiddleware` → `request.state.user_id`
- **过期时间**：默认 120 分钟，刷新阈值 30 分钟（`/api/auth/refresh-session`）

**双锁保护机制**（原子性保证）：
```python
async with self._users_lock:
    async with self._admins_lock:
        # 读-改-写操作，确保用户数据和管理员列表一致性
```

**本地用户特殊处理**：
- 所有 `local_` 开头的用户默认为管理员
- 无需手动授权，自动加入 `admins.json`

**OAuth 回调地址验证**：
- 本地开发：`http://localhost:8000/api/auth/callback`
- 生产环境：必须使用实际域名或服务器 IP
- Docker 部署警告：自动检测 `localhost` 并警告

### 5. RAG 记忆系统

**ChromaDB Collection 命名**（重要）：
```python
# 使用 SHA256 哈希压缩 ID 长度，确保不超过 63 字符
user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
project_hash = hashlib.sha256(project_id.encode()).hexdigest()[:8]
collection_name = f"u_{user_hash}_p_{project_hash}"
```

**Embedding 模型加载策略**：
- **主模型**：`paraphrase-multilingual-MiniLM-L12-v2`（支持中文）
- **备用模型**：`all-MiniLM-L6-v2`
- **缓存目录**：`embedding/`（约 420MB）
- **首次使用**：需联网下载模型

**智能上下文构建**（5种检索策略）：
1. **最近章节上下文** - 时间连续性（最近 3 章，重要性 ≥0.5）
2. **语义相关记忆** - 向量相似度检索（10 条，重要性 ≥0.4）
3. **未完结伏笔** - 状态标记检索（`is_foreshadow=1`）
4. **角色相关记忆** - 角色名匹配（8 条）
5. **重要情节点** - 类型+重要性过滤（5 条，重要性 ≥0.7）

### 6. MCP 工具增强架构

**延迟加载策略**（减少启动时间）：
```python
# 应用启动时不加载 MCP 插件
# 用户首次使用时自动加载
await mcp_registry.get_or_create_plugin(user_id, plugin_name)
```

**用户级隔离**：
- 每个用户独立的 MCP 插件实例
- 避免跨用户工具调用干扰

**两阶段 MCP 增强**（流式生成）：
```python
# 阶段 1：规划阶段（非流式）
# - 调用 MCP 工具收集参考资料
# - 构建增强提示词

# 阶段 2：生成阶段（流式）
# - 使用增强提示词生成内容
# - 实时返回生成进度
```

**工具调用位置**：
- 世界观生成：收集历史背景、地理文化参考
- 角色生成：收集人物原型、社会习俗参考
- 大纲续写：收集情节设计参考
- 章节生成：收集细节参考资料

**工具调用限制**：
```python
MAX_TOOL_CALLS = 3    # 非流式模式最多调用 3 轮工具
```

### 7. 中间件工作流程

**请求处理链**：
```
Request
  → RequestIDMiddleware (生成追踪 ID)
  → AuthMiddleware (提取 user_id)
  → CORSMiddleware (跨域处理)
  → 路由处理器
  → get_db(request) (获取用户数据库会话)
```

**AuthMiddleware 注入的状态**：
```python
request.state.user_id = user_id
request.state.user = user
request.state.is_admin = user.is_admin
```

### 8. 写作风格管理

**预设风格系统**（6种风格）：
```python
natural    # 自然流畅
classical  # 古典优雅
modern     # 现代简约
poetic     # 诗意抒情
concise    # 精炼利落
vivid      # 生动形象
```

**风格应用机制**：
- 全局预设风格：`project_id = NULL`
- 项目默认风格：`ProjectDefaultStyle` 关联表
- 自动初始化：用户数据库创建时插入 6 种预设

**自动初始化的数据**（用户首次使用时）：
1. **关系类型**：20 种预定义关系（家族、社交、职业、敌对）
2. **全局写作风格**：6 种预设风格
3. **项目默认风格**：自动设置为第一个全局预设

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

**健康检查端点**：
```bash
# 基础健康检查
GET /health
# 返回: {"status": "ok"}

# 数据库会话统计（重要调试工具）
GET /health/db-sessions
# 返回:
# {
#   "created": 100,      # 总创建会话数
#   "closed": 98,        # 总关闭会话数
#   "active": 2,         # 当前活跃会话数（应接近 0）
#   "errors": 0,         # 错误次数
#   "generator_exits": 5,# SSE 断开次数
#   "last_check": "2025-11-09T10:30:00",
#   "warning": "活跃会话数过多"  # 当 active > 10 时出现
# }

# 诊断建议：
# - active > 10: 可能存在连接泄漏，检查异常处理
# - errors 持续增长: 检查日志文件
# - generator_exits 频繁: 客户端频繁断开连接
```

**日志管理**：
```bash
# 日志文件位置
backend/logs/app.log

# 日志配置（.env）
LOG_LEVEL=INFO                # DEBUG/INFO/WARNING/ERROR
LOG_TO_FILE=true
LOG_MAX_BYTES=10485760        # 10MB 自动轮转
LOG_BACKUP_COUNT=30           # 保留 30 个备份

# 查看实时日志
tail -f backend/logs/app.log

# 搜索特定错误
grep "ERROR" backend/logs/app.log
grep "GeneratorExit" backend/logs/app.log
```

**数据存储**：
- 数据库：`backend/data/ai_story_user_{user_id}.db`
- ChromaDB：`backend/data/chroma/`（或内存，根据配置）
- Embedding 模型缓存：`backend/embedding/`（约 420MB）
- 用户数据文件：`backend/data/users.json`
- 管理员列表：`backend/data/admins.json`

## 环境变量配置

**必需配置**（`backend/.env`）：
```bash
# AI 服务（至少配置一个）
OPENAI_API_KEY=sk-...           # OpenAI API Key
ANTHROPIC_API_KEY=sk-ant-...    # Anthropic API Key

# 本地账户（生产环境务必修改密码）
LOCAL_AUTH_PASSWORD=your_secure_password_here
```

**完整配置列表及默认值**：
```bash
# ===== AI 服务配置 =====
OPENAI_API_KEY=                           # OpenAI API Key
OPENAI_BASE_URL=https://api.openai.com/v1 # 中转 API 地址
ANTHROPIC_API_KEY=                        # Anthropic API Key
ANTHROPIC_BASE_URL=https://api.anthropic.com

# 默认 AI 设置
DEFAULT_AI_PROVIDER=openai                # openai/anthropic
DEFAULT_MODEL=gpt-4o-mini                 # 默认模型
DEFAULT_TEMPERATURE=0.8                   # 温度参数
DEFAULT_MAX_TOKENS=32000                  # 最大生成 token 数

# ===== 应用配置 =====
APP_NAME=MuMuAINovel
APP_VERSION=1.0.0
APP_HOST=0.0.0.0
APP_PORT=8000
DEBUG=false

# ===== 会话配置 =====
SESSION_EXPIRE_MINUTES=120                # 会话过期时间（分钟）
SESSION_REFRESH_THRESHOLD_MINUTES=30      # 刷新阈值（分钟）

# ===== LinuxDO OAuth（可选）=====
LINUXDO_CLIENT_ID=
LINUXDO_CLIENT_SECRET=
LINUXDO_REDIRECT_URI=http://localhost:8000/api/auth/callback
FRONTEND_URL=http://localhost:8000

# ===== 本地账户配置 =====
LOCAL_AUTH_ENABLED=true                   # 启用本地登录
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD=your_secure_password_here
LOCAL_AUTH_DISPLAY_NAME=管理员

# ===== 日志配置 =====
LOG_LEVEL=INFO                            # DEBUG/INFO/WARNING/ERROR
LOG_TO_FILE=true
LOG_FILE_PATH=logs/app.log
LOG_MAX_BYTES=10485760                    # 10MB
LOG_BACKUP_COUNT=30                       # 保留 30 个备份

# ===== CORS 配置 =====
# CORS_ORIGINS=https://your-domain.com,https://www.your-domain.com
```

**推荐模型**：
- OpenAI：`gpt-4o`, `gpt-4o-mini`, `gpt-3.5-turbo`
- Anthropic：`claude-3-5-sonnet-20241022`, `claude-3-opus-20240229`
- Deepseek：`deepseek-chat`（自动处理 reasoning_content）

## 依赖版本管理

**后端关键依赖**（requirements.txt）：
```python
fastapi==0.121.0
uvicorn[standard]==0.38.0
sqlalchemy==2.0.25              # 异步 ORM
aiosqlite==0.19.0              # 异步 SQLite 驱动
openai==2.7.0
anthropic==0.72.0
mcp==1.21.0                    # Model Context Protocol SDK
chromadb==1.3.2                # 向量数据库
sentence-transformers==2.3.1   # Embedding 模型
numpy==1.26.4                  # 锁定版本（兼容性要求）
transformers==4.35.2           # 锁定版本
```

**前端关键依赖**（package.json）：
```json
{
  "react": "^18.3.1",
  "typescript": "^5.9.3",
  "antd": "^5.27.0",
  "zustand": "^5.0.0",
  "axios": "^1.7.9",
  "react-router-dom": "^6.28.0",
  "vite": "^7.1.0"
}
```

**版本升级注意事项**：
- NumPy 和 Transformers 已锁定版本，升级前测试兼容性
- ChromaDB 升级可能影响 Collection 命名和数据格式
- MCP SDK 处于快速迭代期，升级前查阅更新日志

## 已知问题与限制

1. **Deepseek 模型特殊处理**：自动丢弃 `reasoning_content`，仅使用 `content`
2. **SQLite 并发限制**：
   - 已优化：WAL 模式、5 秒锁超时、64MB 缓存
   - 高并发场景（>50 并发）考虑切换 PostgreSQL
3. **Cloudflare 拦截**：已使用自定义 User-Agent 规避，如仍被拦截检查中转 API 配置
4. **会话内存存储**：用户会话存储在内存中，服务重启后需重新登录
5. **无数据库迁移工具**：数据库结构变更需手动处理，生产环境建议集成 Alembic
6. **SSE 连接断开**：客户端断开会触发 `GeneratorExit`，已自动处理事务回滚
7. **Embedding 模型下载**：
   - 首次使用需联网下载约 420MB 模型
   - 国内网络可能较慢，建议配置镜像源或手动下载
8. **MCP 插件隔离**：
   - 每个用户独立插件实例，内存占用较高
   - 高并发场景需监控内存使用

## Git 工作流

- **主分支**：`main`
- **开发分支**：`dev`
- **当前分支**：`chaos/增加短篇能力-1104`
- **注意**：
  - 不要提交 `.env` 文件和 `data/` 目录（已在 .gitignore）
  - 不要提交 `embedding/` 模型缓存目录
  - 前端构建产物 `backend/static/` 由部署流程生成
