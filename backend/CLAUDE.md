# Backend 模块文档

[根目录](../CLAUDE.md) > **backend**

> 最后更新：2025-12-10 19:50:29

---

## 变更记录

### 2025-12-10 19:50:29
- 初始化后端模块文档
- 记录 API 端点、数据模型、业务服务结构

---

## 模块职责

Backend 是 MuMuAINovel 的后端服务模块，基于 **FastAPI** 构建，负责：

1. **API 服务**：提供 RESTful API 和 SSE 流式接口
2. **数据持久化**：PostgreSQL 数据库的 ORM 操作（SQLAlchemy 异步）
3. **AI 集成**：统一的 AI 服务抽象层，支持多模型（OpenAI、Gemini、Claude）
4. **长期记忆**：基于 ChromaDB 的向量存储和语义搜索
5. **MCP 插件系统**：Model Context Protocol 插件管理和工具调用
6. **多用户隔离**：PostgreSQL 多租户数据隔离（通过 `user_id` 字段）
7. **认证授权**：LinuxDO OAuth 和本地账户登录，会话管理

---

## 入口与启动

### 主入口文件
- **`backend/app/main.py`**：FastAPI 应用定义、中间件配置、路由注册
- **`backend/run.py`**：本地开发启动脚本

### 启动方式

**开发模式：**
```bash
cd backend
python -m uvicorn app.main:app --host localhost --port 8000 --reload
```

**生产模式（通过 Docker）：**
```bash
docker-compose up -d
```

### 应用生命周期

`app/main.py` 中的 `lifespan` 管理器：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时：初始化数据库表结构
    # 运行中：处理请求
    yield
    # 关闭时：清理 MCP 插件、HTTP 客户端、数据库连接
```

---

## 对外接口

### API 路由总览

所有 API 路由都在 `/api` 前缀下，详见下表：

| 路由前缀 | 文件 | 主要功能 |
|----------|------|----------|
| `/api/auth/*` | `api/auth.py` | 登录（LinuxDO OAuth、本地账户）、登出、会话刷新 |
| `/api/users/*` | `api/users.py` | 用户信息、权限管理 |
| `/api/admin/*` | `api/admin.py` | 管理员功能（用户管理、系统监控） |
| `/api/projects/*` | `api/projects.py` | 项目 CRUD、导入导出 |
| `/api/inspiration/*` | `api/inspiration.py` | 灵感生成（AI） |
| `/api/wizard-stream/*` | `api/wizard_stream.py` | SSE 流式向导（大纲/角色/世界观生成） |
| `/api/outlines/*` | `api/outlines.py` | 大纲 CRUD、AI 生成/续写 |
| `/api/characters/*` | `api/characters.py` | 角色 CRUD、AI 生成 |
| `/api/relationships/*` | `api/relationships.py` | 角色关系、关系类型 |
| `/api/organizations/*` | `api/organizations.py` | 组织/团体、成员管理 |
| `/api/chapters/*` | `api/chapters.py` | 章节 CRUD、AI 生成/续写/重写/润色、批量生成、章节分析 |
| `/api/writing-styles/*` | `api/writing_styles.py` | 自定义写作风格、预设风格 |
| `/api/memories/*` | `api/memories.py` | 长期记忆（ChromaDB 向量存储） |
| `/api/mcp-plugins/*` | `api/mcp_plugins.py` | MCP 插件管理、工具调用 |
| `/api/prompt-templates/*` | `api/prompt_templates.py` | 提示词模板管理 |
| `/api/settings/*` | `api/settings.py` | AI 模型配置、系统设置 |
| `/api/changelog/*` | `api/changelog.py` | GitHub 更新日志同步 |

### 核心端点示例

#### 1. 认证登录
```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}
```

#### 2. 创建项目
```http
POST /api/projects
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "我的小说",
  "description": "一部奇幻冒险小说",
  "genre": "奇幻"
}
```

#### 3. AI 生成章节（SSE 流式）
```http
POST /api/chapters/{chapter_id}/generate-content
Authorization: Bearer <token>
Content-Type: application/json

{
  "use_memory": true,
  "ai_provider": "openai",
  "model": "gpt-4o-mini"
}
```

响应：`Content-Type: text/event-stream`
```
data: {"type": "start", "message": "开始生成"}
data: {"type": "content", "content": "第一章的内容..."}
data: {"type": "content", "content": "继续生成..."}
data: {"type": "complete", "chapter_id": 123}
```

---

## 关键依赖与配置

### Python 依赖（`requirements.txt`）

**核心框架：**
- `fastapi==0.121.0` - Web 框架
- `uvicorn[standard]==0.38.0` - ASGI 服务器
- `sqlalchemy==2.0.25` - ORM
- `asyncpg==0.29.0` - PostgreSQL 异步驱动
- `pydantic==2.12.4` - 数据验证

**AI 集成：**
- `openai==2.7.0` - OpenAI SDK
- `anthropic==0.72.0` - Claude SDK
- `mcp==1.21.0` - Model Context Protocol

**向量数据库：**
- `chromadb==1.3.2` - 向量数据库
- `sentence-transformers==5.1.2` - Embedding 模型
- `transformers==4.57.1` - Hugging Face Transformers

### 环境变量配置（`.env`）

**必需配置：**
```bash
# 数据库
DATABASE_URL=postgresql+asyncpg://mumuai:password@localhost:5432/mumuai_novel

# AI 服务（至少配置一个）
OPENAI_API_KEY=sk-xxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_AI_PROVIDER=openai
DEFAULT_MODEL=gpt-4o-mini

# 本地账户登录
LOCAL_AUTH_ENABLED=true
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD=admin123
```

**可选配置：**
```bash
# LinuxDO OAuth
LINUXDO_CLIENT_ID=xxxxx
LINUXDO_CLIENT_SECRET=xxxxx
LINUXDO_REDIRECT_URI=http://localhost:8000/api/auth/linuxdo/callback

# 连接池优化
DATABASE_POOL_SIZE=50
DATABASE_MAX_OVERFLOW=30

# 日志配置
LOG_LEVEL=INFO
LOG_TO_FILE=true
```

详见 `app/config.py` 中的 `Settings` 类。

---

## 数据模型

### 核心模型（`app/models/`）

| 模型文件 | 表名 | 职责 |
|----------|------|------|
| `user.py` | `users` | 用户信息、认证、权限 |
| `project.py` | `projects` | 项目基本信息 |
| `outline.py` | `outlines` | 大纲内容 |
| `character.py` | `characters` | 角色信息 |
| `relationship.py` | `relationship_types`, `character_relationships` | 角色关系 |
| `chapter.py` | `chapters` | 章节内容、状态 |
| `writing_style.py` | `writing_styles` | 写作风格 |
| `project_default_style.py` | `project_default_styles` | 项目默认风格关联 |
| `memory.py` | `story_memories`, `plot_analyses` | 长期记忆、剧情分析 |
| `generation_history.py` | `generation_histories` | 生成历史记录 |
| `batch_generation_task.py` | `batch_generation_tasks` | 批量生成任务 |
| `regeneration_task.py` | `regeneration_tasks` | 重新生成任务 |
| `analysis_task.py` | `analysis_tasks` | 章节分析任务 |
| `mcp_plugin.py` | `mcp_plugins` | MCP 插件配置 |
| `prompt_template.py` | `prompt_templates` | 提示词模板 |
| `settings.py` | `settings` | 系统设置 |

### 数据隔离机制

**PostgreSQL 多租户隔离：**
- 所有核心表都包含 `user_id` 字段（外键关联 `users` 表）
- 查询时自动过滤：`WHERE user_id = :current_user_id`
- 会话管理：`get_db(request)` 从 `request.state.user_id` 获取用户 ID

### 模型关系图

```
users (用户)
  ├─ projects (项目)
  │   ├─ outlines (大纲)
  │   ├─ characters (角色)
  │   │   └─ character_relationships (角色关系)
  │   ├─ chapters (章节)
  │   │   ├─ generation_histories (生成历史)
  │   │   ├─ story_memories (长期记忆)
  │   │   └─ plot_analyses (剧情分析)
  │   ├─ writing_styles (写作风格)
  │   └─ organizations (组织)
  ├─ batch_generation_tasks (批量任务)
  ├─ regeneration_tasks (重生成任务)
  ├─ analysis_tasks (分析任务)
  ├─ mcp_plugins (MCP 插件)
  ├─ prompt_templates (提示词模板)
  └─ settings (设置)
```

---

## 业务服务（`app/services/`）

| 服务文件 | 职责 |
|----------|------|
| `ai_service.py` | AI 服务统一抽象层（OpenAI、Gemini、Claude）、流式生成、HTTP 客户端池管理 |
| `prompt_service.py` | 提示词模板管理、写作风格管理 |
| `memory_service.py` | ChromaDB 向量存储、语义搜索、记忆提取 |
| `chapter_regenerator.py` | 章节重新生成逻辑、任务队列管理 |
| `plot_analyzer.py` | 章节分析（情节、角色、语言、节奏） |
| `plot_expansion_service.py` | 剧情扩展规划、章节规划生成 |
| `import_export_service.py` | 项目导入导出（JSON 格式） |
| `mcp_tool_service.py` | MCP 工具调用、参数转换 |
| `mcp_test_service.py` | MCP 插件测试 |
| `oauth_service.py` | LinuxDO OAuth 认证 |

### 核心服务详解

#### 1. AI 服务抽象层（`ai_service.py`）

```python
class AIService:
    async def generate_text(
        self,
        prompt: str,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False
    ) -> Union[str, AsyncIterator[str]]:
        """统一的 AI 文本生成接口"""
        # 支持 OpenAI、Gemini、Claude
        # 支持流式和非流式输出
        # 支持 MCP 工具调用
```

#### 2. 长期记忆服务（`memory_service.py`）

```python
class MemoryService:
    async def add_memory(self, project_id: int, content: str, memory_type: str):
        """添加记忆到向量数据库"""

    async def search_memories(self, project_id: int, query: str, limit: int = 5):
        """语义搜索相关记忆"""

    async def get_relevant_context(self, chapter_id: int):
        """获取章节相关的上下文记忆"""
```

#### 3. 章节重生成（`chapter_regenerator.py`）

```python
class ChapterRegenerator:
    async def regenerate_chapter(
        self,
        chapter_id: int,
        regeneration_plan: dict,
        ai_provider: str,
        model: str
    ):
        """根据重生成计划重写章节"""
        # 支持保留/删除/重写特定部分
        # 支持调整情节方向、角色表现、语言风格
```

---

## 中间件（`app/middleware/`）

| 中间件 | 职责 |
|--------|------|
| `request_id.py` | 为每个请求生成唯一 ID，用于日志追踪 |
| `auth_middleware.py` | 认证中间件，验证会话 Token，注入 `request.state.user_id` |

### 认证流程

```
1. 客户端发送请求，携带 Authorization Header
   Authorization: Bearer <session_token>

2. AuthMiddleware 拦截请求
   - 验证 Token 有效性
   - 从数据库查询用户信息
   - 将 user_id 注入到 request.state.user_id

3. 业务层通过 Depends(get_db) 获取数据库会话
   - get_db() 从 request.state.user_id 获取用户 ID
   - 返回该用户的数据库会话（自动过滤数据）

4. 响应返回客户端
```

---

## 数据库管理（`app/database.py`）

### 核心功能

**1. 连接池管理**
```python
async def get_engine(user_id: str):
    """获取或创建用户专属的数据库引擎"""
    # PostgreSQL: 所有用户共享一个引擎和连接池
    # 连接池配置：50 核心连接 + 30 溢出连接 = 80 总连接
```

**2. 会话管理**
```python
async def get_db(request: Request):
    """依赖注入函数，返回数据库会话"""
    # 自动获取 user_id
    # 自动管理会话生命周期（创建、提交、回滚、关闭）
    # 监控连接泄漏
```

**3. 初始化**
```python
async def init_db(user_id: str):
    """初始化用户数据库"""
    # 创建所有表结构
    # 插入预置关系类型
    # 插入全局预设写作风格
```

### 连接池监控

访问 `GET /health/db-sessions` 查看实时统计：
```json
{
  "session_stats": {
    "created": 1000,
    "closed": 998,
    "active": 2,
    "errors": 1,
    "generator_exits": 5
  },
  "pool_stats": {
    "size": 50,
    "checked_in": 48,
    "checked_out": 2,
    "overflow": 0,
    "usage_percent": 2.5
  }
}
```

---

## MCP 插件系统（`app/mcp/`）

### 目录结构
```
app/mcp/
├── __init__.py
├── config.py          # MCP 插件配置管理
├── registry.py        # 插件注册表、生命周期管理
├── http_client.py     # MCP HTTP 客户端
└── adapters/          # 适配器（自动检测 API 能力）
    ├── base.py        # 基础适配器
    ├── function_calling.py   # Function Calling 适配器
    ├── prompt_injection.py   # 提示词注入适配器
    └── universal.py   # 通用适配器
```

### MCP 工作流程

```
1. 用户配置 MCP 插件
   - 插件类型：stdio / sse / http
   - 启动命令/连接地址
   - 工具列表

2. 插件启动（registry.py）
   - 根据类型启动进程或建立连接
   - 获取工具列表和 Schema

3. AI 调用时自动检测（adapters/）
   - 检测 API 是否支持 Function Calling
   - 支持：使用 function_calling.py（原生工具调用）
   - 不支持：使用 prompt_injection.py（提示词注入）

4. 工具调用
   - 解析 AI 返回的工具调用
   - 通过 MCP 协议调用插件
   - 将结果返回给 AI 继续对话

5. 插件清理（应用关闭时）
   - 停止所有插件进程
   - 关闭所有连接
```

---

## 测试与质量

### 当前状态
- ❌ **单元测试**：未发现 `backend/tests/` 目录
- ❌ **集成测试**：未发现测试用例

### 建议的测试结构

```
backend/tests/
├── conftest.py               # pytest 配置、Fixture
├── test_api/
│   ├── test_auth.py         # 认证 API 测试
│   ├── test_projects.py     # 项目 API 测试
│   ├── test_chapters.py     # 章节 API 测试
│   └── ...
├── test_services/
│   ├── test_ai_service.py   # AI 服务测试
│   ├── test_memory_service.py
│   └── ...
├── test_models/
│   ├── test_user.py         # 数据模型测试
│   └── ...
└── test_mcp/
    ├── test_registry.py     # MCP 注册表测试
    └── test_adapters.py     # 适配器测试
```

### 测试依赖
```bash
pip install pytest pytest-asyncio pytest-cov httpx
```

### 运行测试
```bash
pytest -v --cov=app
```

---

## 常见问题 (FAQ)

### 1. 数据库连接泄漏怎么办？
**症状**：活跃会话数持续增长，不回落

**排查**：
1. 访问 `GET /health/db-sessions` 查看统计
2. 检查代码中是否所有 `get_db()` 都使用了 `Depends(get_db)`
3. 确认 SSE 流式接口的 `GeneratorExit` 异常处理是否正确

**解决**：
- 使用 `Depends(get_db)` 而不是手动创建会话
- SSE 流式接口：捕获 `GeneratorExit`，在 `finally` 中关闭会话

### 2. AI 生成速度慢怎么办？
**排查**：
1. 检查网络延迟（是否使用代理）
2. 检查 AI 模型选择（`gpt-4o-mini` 比 `gpt-4` 快）
3. 检查提示词长度（包含长期记忆可能增加输入 Token）

**优化**：
- 使用更快的模型
- 减少记忆注入数量（调整 `limit` 参数）
- 使用流式输出（SSE）提升用户体验

### 3. 长期记忆不准确怎么办？
**排查**：
1. 检查 Embedding 模型是否正确加载
2. 检查记忆的语义相关性（可能需要调整搜索阈值）

**优化**：
- 增加记忆样本数量
- 调整搜索相似度阈值
- 使用更强的 Embedding 模型

### 4. MCP 插件启动失败？
**排查**：
1. 检查插件配置（`command`、`args`、`env`）
2. 查看日志：`docker-compose logs -f mumuainovel`
3. 手动测试插件命令是否能运行

**常见原因**：
- 插件依赖未安装
- 路径配置错误
- 环境变量缺失

---

## 相关文件清单

### 核心文件
- `app/main.py` - 应用入口
- `app/config.py` - 配置管理
- `app/database.py` - 数据库连接
- `app/logger.py` - 日志系统

### API 路由（19 个文件）
```
app/api/
├── __init__.py
├── admin.py
├── auth.py
├── changelog.py
├── chapters.py
├── characters.py
├── inspiration.py
├── mcp_plugins.py
├── memories.py
├── organizations.py
├── outlines.py
├── polish.py
├── projects.py
├── prompt_templates.py
├── relationships.py
├── settings.py
├── users.py
├── wizard_stream.py
└── writing_styles.py
```

### 数据模型（17 个文件）
```
app/models/
├── __init__.py
├── analysis_task.py
├── batch_generation_task.py
├── chapter.py
├── character.py
├── generation_history.py
├── mcp_plugin.py
├── memory.py
├── outline.py
├── project.py
├── project_default_style.py
├── prompt_template.py
├── regeneration_task.py
├── relationship.py
├── settings.py
├── user.py
└── writing_style.py
```

### 业务服务（11 个文件）
```
app/services/
├── __init__.py
├── ai_service.py
├── chapter_regenerator.py
├── import_export_service.py
├── mcp_test_service.py
├── mcp_tool_service.py
├── memory_service.py
├── oauth_service.py
├── plot_analyzer.py
├── plot_expansion_service.py
└── prompt_service.py
```

### 其他重要目录
- `app/schemas/` - Pydantic 验证模型
- `app/middleware/` - 中间件
- `app/mcp/` - MCP 插件系统
- `app/utils/` - 工具函数
- `scripts/` - 数据库迁移脚本

---

## 下一步建议

1. **补充测试**：创建 `backend/tests/` 目录，编写单元测试和集成测试
2. **性能优化**：监控慢查询，优化数据库索引
3. **文档补充**：为每个 API 端点添加详细的 docstring
4. **错误处理**：统一的异常处理和错误码体系
5. **监控告警**：集成 Prometheus + Grafana 监控

---

[返回根文档](../CLAUDE.md)
