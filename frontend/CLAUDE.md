# Frontend 模块文档

[根目录](../CLAUDE.md) > **frontend**

> 最后更新：2025-12-10 19:50:29

---

## 变更记录

### 2025-12-10 19:50:29
- 初始化前端模块文档
- 记录页面组件、路由结构、状态管理

---

## 模块职责

Frontend 是 MuMuAINovel 的前端应用模块，基于 **React 18 + TypeScript** 构建，负责：

1. **用户界面**：提供友好的 Web 界面，支持小说创作全流程
2. **路由管理**：基于 React Router v6 的单页应用（SPA）
3. **状态管理**：使用 Zustand 管理全局状态
4. **API 通信**：封装 Axios 调用后端 API
5. **SSE 流式渲染**：实时显示 AI 生成内容
6. **组件库**：基于 Ant Design 构建 UI 组件

---

## 入口与启动

### 主入口文件
- **`frontend/src/main.tsx`**：React 应用入口，挂载根组件
- **`frontend/src/App.tsx`**：路由配置、全局布局

### 启动方式

**开发模式：**
```bash
cd frontend
npm install
npm run dev
# 访问 http://localhost:5173
```

**生产构建：**
```bash
npm run build
# 输出到 dist/ 目录（或 ../backend/static/）
```

**预览生产构建：**
```bash
npm run preview
```

### 应用入口代码（`main.tsx`）

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './App.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

---

## 路由结构（`App.tsx`）

### 路由配置

```tsx
<BrowserRouter>
  <Routes>
    {/* 公开路由 */}
    <Route path="/login" element={<Login />} />
    <Route path="/auth/callback" element={<AuthCallback />} />

    {/* 保护路由（需要登录） */}
    <Route path="/" element={<ProtectedRoute><ProjectList /></ProtectedRoute>} />
    <Route path="/projects" element={<ProtectedRoute><ProjectList /></ProtectedRoute>} />
    <Route path="/wizard" element={<ProtectedRoute><ProjectWizardNew /></ProtectedRoute>} />
    <Route path="/inspiration" element={<ProtectedRoute><Inspiration /></ProtectedRoute>} />
    <Route path="/settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
    <Route path="/prompt-templates" element={<ProtectedRoute><PromptTemplates /></ProtectedRoute>} />
    <Route path="/mcp-plugins" element={<ProtectedRoute><MCPPlugins /></ProtectedRoute>} />
    <Route path="/user-management" element={<ProtectedRoute><UserManagement /></ProtectedRoute>} />
    <Route path="/chapters/:chapterId/reader" element={<ProtectedRoute><ChapterReader /></ProtectedRoute>} />

    {/* 项目详情（嵌套路由） */}
    <Route path="/project/:projectId" element={<ProtectedRoute><ProjectDetail /></ProtectedRoute>}>
      <Route index element={<Navigate to="world-setting" replace />} />
      <Route path="world-setting" element={<WorldSetting />} />
      <Route path="outline" element={<Outline />} />
      <Route path="characters" element={<Characters />} />
      <Route path="relationships" element={<Relationships />} />
      <Route path="organizations" element={<Organizations />} />
      <Route path="chapters" element={<Chapters />} />
      <Route path="chapter-analysis" element={<ChapterAnalysis />} />
      <Route path="writing-styles" element={<WritingStyles />} />
    </Route>
  </Routes>
</BrowserRouter>
```

### 保护路由（`ProtectedRoute`）

```tsx
// src/components/ProtectedRoute.tsx
const ProtectedRoute = ({ children }) => {
  const token = localStorage.getItem('token');
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
};
```

---

## 页面组件（`src/pages/`）

### 核心页面列表

| 页面文件 | 路由 | 职责 |
|----------|------|------|
| `Login.tsx` | `/login` | 用户登录（LinuxDO OAuth / 本地账户） |
| `AuthCallback.tsx` | `/auth/callback` | OAuth 回调处理 |
| `ProjectList.tsx` | `/projects` | 项目列表、创建/删除项目 |
| `ProjectWizardNew.tsx` | `/wizard` | AI 向导式项目创建（SSE 流式） |
| `Inspiration.tsx` | `/inspiration` | 灵感生成模式 |
| `ProjectDetail.tsx` | `/project/:projectId` | 项目详情（嵌套路由容器） |
| `WorldSetting.tsx` | `/project/:projectId/world-setting` | 世界观设定 |
| `Outline.tsx` | `/project/:projectId/outline` | 大纲管理（树形结构） |
| `Characters.tsx` | `/project/:projectId/characters` | 角色管理（卡片视图） |
| `Relationships.tsx` | `/project/:projectId/relationships` | 角色关系图（可视化） |
| `Organizations.tsx` | `/project/:projectId/organizations` | 组织/团体管理 |
| `Chapters.tsx` | `/project/:projectId/chapters` | 章节管理（列表/批量生成） |
| `ChapterAnalysis.tsx` | `/project/:projectId/chapter-analysis` | 章节分析（AI 分析结果） |
| `ChapterReader.tsx` | `/chapters/:chapterId/reader` | 章节阅读器（全屏模式） |
| `WritingStyles.tsx` | `/project/:projectId/writing-styles` | 项目写作风格管理 |
| `Settings.tsx` | `/settings` | 系统设置（AI 模型配置） |
| `PromptTemplates.tsx` | `/prompt-templates` | 提示词模板管理 |
| `MCPPlugins.tsx` | `/mcp-plugins` | MCP 插件管理 |
| `UserManagement.tsx` | `/user-management` | 用户管理（管理员） |
| `Polish.tsx` | `/project/:projectId/polish` | 章节润色（已注释，功能合并到 Chapters） |

### 页面职责详解

#### 1. ProjectList（项目列表）
- 显示用户的所有项目（卡片视图）
- 创建新项目（普通 / 向导模式）
- 删除项目
- 项目导入导出

#### 2. ProjectWizardNew（AI 向导）
- 步骤 1：输入项目基本信息（名称、类型、题材、简介）
- 步骤 2：AI 生成大纲、角色、世界观（SSE 流式显示）
- 步骤 3：预览和编辑生成结果
- 步骤 4：保存项目

#### 3. Chapters（章节管理）
- 章节列表（表格视图）
- 创建/编辑/删除章节
- AI 生成章节内容（SSE 流式）
- AI 续写章节
- AI 重写章节（根据分析建议）
- AI 润色章节
- 批量生成（选择多个章节，队列生成）
- 章节规划（扩展大纲为详细章节规划）

#### 4. Characters（角色管理）
- 角色列表（卡片视图）
- 创建/编辑/删除角色
- AI 生成角色（基于大纲）
- 角色详情（姓名、性格、背景、关系）

#### 5. Relationships（角色关系）
- 关系图可视化（使用 D3.js 或类似库）
- 添加/编辑/删除关系
- 关系类型管理（父子、师徒、敌对等）

---

## 通用组件（`src/components/`）

### 核心组件列表

| 组件文件 | 职责 |
|----------|------|
| `ProtectedRoute.tsx` | 路由保护，验证登录状态 |
| `SSEProgressBar.tsx` | SSE 流式进度条 |
| `SSELoadingOverlay.tsx` | SSE 流式加载遮罩 |
| `SSEProgressModal.tsx` | SSE 流式进度弹窗 |
| `CharacterCard.tsx` | 角色卡片组件 |
| `MemorySidebar.tsx` | 长期记忆侧边栏 |
| `ChapterAnalysis.tsx` | 章节分析结果展示 |
| `ChapterContentComparison.tsx` | 章节内容对比（重生成前后） |
| `ChapterRegenerationModal.tsx` | 章节重生成配置弹窗 |
| `ExpansionPlanEditor.tsx` | 章节规划编辑器 |
| `FloatingIndexPanel.tsx` | 浮动索引面板（章节目录） |
| `AIProjectGenerator.tsx` | AI 项目生成器（向导流程） |
| `AnnotatedText.tsx` | 带注释的文本展示 |
| `AnnouncementModal.tsx` | 公告弹窗 |
| `ChangelogModal.tsx` | 更新日志弹窗 |
| `ChangelogFloatingButton.tsx` | 更新日志悬浮按钮 |
| `AppFooter.tsx` | 应用页脚 |
| `UserMenu.tsx` | 用户菜单（头像、登出） |
| `CardStyles.tsx` | 卡片样式工具 |

### SSE 流式组件详解

#### SSEProgressBar
```tsx
interface SSEProgressBarProps {
  visible: boolean;
  message: string;
  progress?: number;
}

// 使用示例
<SSEProgressBar
  visible={generating}
  message="正在生成章节内容..."
  progress={50}
/>
```

#### SSEProgressModal
```tsx
interface SSEProgressModalProps {
  visible: boolean;
  title: string;
  onCancel: () => void;
  content: React.ReactNode;
}

// 使用示例
<SSEProgressModal
  visible={modalVisible}
  title="AI 生成进度"
  onCancel={handleCancel}
  content={
    <div>{generatedContent}</div>
  }
/>
```

---

## API 服务封装（`src/services/`）

### 核心服务文件

| 文件 | 职责 |
|------|------|
| `api.ts` | Axios 实例配置、请求拦截器、响应拦截器 |
| `sseClient.ts` | SSE 客户端封装 |
| `changelogService.ts` | 更新日志服务 |
| `versionService.ts` | 版本检查服务 |

### API 服务示例（`api.ts`）

```typescript
import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
});

// 请求拦截器（自动添加 Token）
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器（统一错误处理）
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token 过期，跳转登录
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;
```

### SSE 客户端示例（`sseClient.ts`）

```typescript
export function createSSEConnection(
  url: string,
  options: {
    onMessage: (data: any) => void;
    onError?: (error: any) => void;
    onComplete?: () => void;
  }
): () => void {
  const token = localStorage.getItem('token');
  const eventSource = new EventSource(`${url}?token=${token}`);

  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'complete') {
      options.onComplete?.();
      eventSource.close();
    } else {
      options.onMessage(data);
    }
  };

  eventSource.onerror = (error) => {
    options.onError?.(error);
    eventSource.close();
  };

  // 返回清理函数
  return () => eventSource.close();
}
```

---

## 状态管理（`src/store/`）

### Zustand Store 结构

```typescript
// src/store/index.ts
import create from 'zustand';

interface AppState {
  user: User | null;
  currentProject: Project | null;
  setUser: (user: User | null) => void;
  setCurrentProject: (project: Project | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  user: null,
  currentProject: null,
  setUser: (user) => set({ user }),
  setCurrentProject: (project) => set({ currentProject: project }),
}));
```

### EventBus（事件总线）

```typescript
// src/store/eventBus.ts
import mitt from 'mitt';

type Events = {
  'chapter:updated': number; // chapter_id
  'project:updated': number; // project_id
  'user:logout': void;
};

export const eventBus = mitt<Events>();

// 使用示例
eventBus.emit('chapter:updated', 123);
eventBus.on('chapter:updated', (chapterId) => {
  console.log('章节更新:', chapterId);
});
```

---

## 工具函数（`src/utils/`）

### 核心工具文件

| 文件 | 职责 |
|------|------|
| `sessionManager.ts` | 会话管理（Token 存储、刷新） |
| `sseClient.ts` | SSE 客户端工具（已移到 services） |

### 会话管理示例（`sessionManager.ts`）

```typescript
export const SessionManager = {
  getToken(): string | null {
    return localStorage.getItem('token');
  },

  setToken(token: string): void {
    localStorage.setItem('token', token);
  },

  removeToken(): void {
    localStorage.removeItem('token');
  },

  isLoggedIn(): boolean {
    return !!this.getToken();
  },

  refreshToken(): Promise<string> {
    // 调用后端刷新 Token API
  },
};
```

---

## 类型定义（`src/types/index.ts`）

### 核心类型

```typescript
export interface User {
  id: number;
  username: string;
  display_name: string;
  is_admin: boolean;
}

export interface Project {
  id: number;
  user_id: number;
  name: string;
  description?: string;
  genre?: string;
  world_setting?: string;
  created_at: string;
  updated_at: string;
}

export interface Character {
  id: number;
  project_id: number;
  name: string;
  age?: number;
  gender?: string;
  personality?: string;
  background?: string;
  appearance?: string;
  created_at: string;
  updated_at: string;
}

export interface Chapter {
  id: number;
  project_id: number;
  title: string;
  content?: string;
  order_index: number;
  word_count: number;
  status: 'draft' | 'generating' | 'completed';
  created_at: string;
  updated_at: string;
}

export interface Outline {
  id: number;
  project_id: number;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface WritingStyle {
  id: number;
  user_id?: number;
  project_id?: number;
  name: string;
  style_type: 'preset' | 'custom';
  preset_id?: string;
  description?: string;
  prompt_content: string;
  order_index: number;
}
```

---

## 构建与配置

### Vite 配置（`vite.config.ts`）

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../backend/static', // 生产构建输出到后端静态目录
    emptyOutDir: true,
  },
});
```

### TypeScript 配置（`tsconfig.json`）

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "jsx": "react-jsx",
    "strict": true,
    "moduleResolution": "node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "allowSyntheticDefaultImports": true,
    "forceConsistentCasingInFileNames": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

### ESLint 配置（`eslint.config.js`）

```javascript
import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
    },
  }
);
```

---

## 测试与质量

### 当前状态
- ❌ **单元测试**：未发现测试文件
- ❌ **E2E 测试**：未发现测试配置

### 建议的测试结构

```
frontend/tests/
├── unit/
│   ├── components/
│   │   ├── CharacterCard.test.tsx
│   │   ├── SSEProgressBar.test.tsx
│   │   └── ...
│   ├── services/
│   │   ├── api.test.ts
│   │   └── sseClient.test.ts
│   └── utils/
│       └── sessionManager.test.ts
├── integration/
│   ├── pages/
│   │   ├── Login.test.tsx
│   │   ├── ProjectList.test.tsx
│   │   └── ...
└── e2e/
    ├── login.spec.ts
    ├── project-workflow.spec.ts
    └── ...
```

### 测试依赖
```bash
npm install --save-dev vitest @testing-library/react @testing-library/jest-dom
npm install --save-dev @playwright/test  # E2E 测试
```

### 运行测试
```bash
npm run test          # 单元测试（Vitest）
npm run test:e2e      # E2E 测试（Playwright）
npm run test:coverage # 覆盖率报告
```

---

## 常见问题 (FAQ)

### 1. 如何调试 SSE 流式连接？
**方法 1：浏览器开发者工具**
- 打开 Network 标签
- 找到 SSE 请求（Type: `eventsource`）
- 查看 Messages 标签页

**方法 2：添加日志**
```typescript
eventSource.onmessage = (event) => {
  console.log('SSE 消息:', event.data);
  // 业务逻辑
};
```

### 2. Token 过期怎么办？
**自动刷新**：在 API 拦截器中检测 401 错误，自动调用刷新 Token API

```typescript
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      try {
        const newToken = await SessionManager.refreshToken();
        // 重试原请求
        error.config.headers.Authorization = `Bearer ${newToken}`;
        return api.request(error.config);
      } catch {
        // 刷新失败，跳转登录
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);
```

### 3. 如何优化大列表渲染性能？
**使用虚拟滚动**（例如 `react-window`）：

```bash
npm install react-window
```

```tsx
import { FixedSizeList } from 'react-window';

<FixedSizeList
  height={600}
  itemCount={chapters.length}
  itemSize={50}
  width="100%"
>
  {({ index, style }) => (
    <div style={style}>
      {chapters[index].title}
    </div>
  )}
</FixedSizeList>
```

### 4. 如何处理组件间通信？
**方法 1：父子组件通信**（Props）
```tsx
<ParentComponent>
  <ChildComponent data={data} onChange={handleChange} />
</ParentComponent>
```

**方法 2：全局状态**（Zustand）
```tsx
const { user, setUser } = useAppStore();
```

**方法 3：事件总线**（EventBus）
```tsx
eventBus.emit('chapter:updated', chapterId);
eventBus.on('chapter:updated', handleChapterUpdate);
```

---

## 相关文件清单

### 入口文件
- `src/main.tsx` - React 入口
- `src/App.tsx` - 路由配置
- `src/App.css` - 全局样式

### 页面组件（20 个文件）
```
src/pages/
├── AuthCallback.tsx
├── ChapterAnalysis.tsx
├── ChapterReader.tsx
├── Chapters.tsx
├── Characters.tsx
├── Inspiration.tsx
├── Login.tsx
├── MCPPlugins.tsx
├── Organizations.tsx
├── Outline.tsx
├── Polish.tsx (已注释)
├── ProjectDetail.tsx
├── ProjectList.tsx
├── ProjectWizardNew.tsx
├── PromptTemplates.tsx
├── Relationships.tsx
├── Settings.tsx
├── UserManagement.tsx
├── WorldSetting.tsx
└── WritingStyles.tsx
```

### 通用组件（15+ 个文件）
```
src/components/
├── AIProjectGenerator.tsx
├── AnnotatedText.tsx
├── AnnouncementModal.tsx
├── AppFooter.tsx
├── CardStyles.tsx
├── ChangelogFloatingButton.tsx
├── ChangelogModal.tsx
├── ChapterAnalysis.tsx
├── ChapterContentComparison.tsx
├── ChapterRegenerationModal.tsx
├── CharacterCard.tsx
├── ExpansionPlanEditor.tsx
├── FloatingIndexPanel.tsx
├── MemorySidebar.tsx
├── ProtectedRoute.tsx
├── SSELoadingOverlay.tsx
├── SSEProgressBar.tsx
├── SSEProgressModal.tsx
└── UserMenu.tsx
```

### 服务与工具
```
src/services/
├── api.ts
├── changelogService.ts
└── versionService.ts

src/store/
├── eventBus.ts
├── hooks.ts
└── index.ts

src/utils/
├── sessionManager.ts
└── sseClient.ts

src/types/
└── index.ts
```

### 配置文件
- `package.json` - npm 依赖
- `vite.config.ts` - Vite 配置
- `tsconfig.json` - TypeScript 配置
- `tsconfig.app.json` - 应用 TS 配置
- `tsconfig.node.json` - Node TS 配置
- `eslint.config.js` - ESLint 配置

---

## 下一步建议

1. **补充测试**：创建测试文件，覆盖核心组件和业务逻辑
2. **性能优化**：
   - 使用 `React.memo` 避免不必要的重渲染
   - 使用虚拟滚动优化大列表
   - 代码分割（React.lazy + Suspense）
3. **可访问性**：添加 ARIA 标签，支持键盘导航
4. **国际化**：集成 i18n，支持多语言
5. **主题系统**：支持深色模式切换

---

[返回根文档](../CLAUDE.md)
