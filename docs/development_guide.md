# 开发指南

## 1. 技术栈

后端：

- Python 3.11+
- FastAPI + Uvicorn
- FastAPI 中间件：访问日志、统一异常响应、CORS、Cookie 会话鉴权
- `mysql-connector-python`（可选，MySQL 存储）

前端：

- React 18
- TypeScript
- Vite
- CSS Modules

测试：

- Python 标准库 `unittest`

## 2. 目录职责

```text
app/
├── main.py                  FastAPI 服务入口、路由、中间件、OpenAPI
├── auth.py                  登录/注册/会话认证
├── agent/                   Agent 核心编排
│   ├── orchestrator.py      plan() / confirm() 生命周期
│   ├── intent_parser.py     规则意图解析（中文关键词匹配）
│   ├── longcat_intent_parser.py  LLM 增强意图解析
│   ├── strategy.py          策略构建（确定性 + LLM 增强）
│   ├── context_builder.py   规划上下文构建
│   ├── planner.py           硬约束过滤 + 软约束评分
│   ├── candidate_selector.py  候选方案选择
│   ├── executor.py          执行管理器
│   ├── participant_constraints.py  参与者约束归一化
│   ├── response_generator.py      文本方案生成
│   └── longcat_response_generator.py  LLM 增强方案生成
├── domain/                  领域模型（Plan, Activity, Restaurant 等 dataclass）
│   ├── models.py
│   └── enums.py
├── providers/               外部服务适配层
│   ├── base.py              LocalLifeProvider Protocol 接口
│   ├── mock_provider.py     Mock 数据 Provider
│   ├── real_provider.py     Overpass API + OSRM 真实 Provider
│   ├── location_provider.py Nominatim 地理编码 / 逆地理编码
│   ├── longcat_client.py    LongCat LLM 客户端
│   └── meituan_link.py      美团跳转链接生成
├── storage/                 存储层
│   ├── repository.py        MemoryAppRepository / MySQLAppRepository
│   └── schema.sql           MySQL 建表语句
└── utils/                   工具函数
    ├── time_utils.py        时间加减
    └── ids.py               ID 生成器

web/                         React 前端
├── index.html               Vite 入口
├── package.json             依赖与脚本
├── vite.config.ts           开发代理配置
├── tsconfig.json            TypeScript 配置
└── src/
    ├── main.tsx             React 挂载点
    ├── App.tsx              视图路由与全局状态
    ├── api/
    │   ├── types.ts         TypeScript 接口定义
    │   └── client.ts        fetch 封装
    ├── components/          可复用组件
    │   ├── Ambient.tsx      背景光效
    │   ├── Header.tsx       顶部品牌栏
    │   ├── ProgressRing.tsx SVG 进度环
    │   ├── StepList.tsx     步骤列表
    │   ├── Timeline.tsx     时间轴
    │   ├── RouteSelector.tsx 交通方式选择
    │   ├── ChipList.tsx     标签列表
    │   ├── ExampleGrid.tsx  示例目标网格
    │   └── Receipt.tsx      执行回执
    ├── views/               7 个视图
    │   ├── LoginView.tsx
    │   ├── InputView.tsx
    │   ├── AnalyzingView.tsx
    │   ├── ProposalView.tsx
    │   ├── ExecutingView.tsx
    │   ├── SuccessView.tsx
    │   └── ErrorView.tsx
    ├── hooks/               自定义 Hooks
    │   ├── useAuth.ts       认证状态
    │   ├── useLocation.ts   浏览器定位
    │   └── useTheme.ts      深浅色主题
    ├── utils/               工具函数
    │   ├── labels.ts        中文标签映射
    │   └── route.ts         路线编辑、同伴解析
    └── styles/
        └── global.css       CSS 变量与 reset

cli/                         命令行入口
└── main.py

tests/                       单元测试
└── test_agent.py

docs/                        文档
```

## 3. 开发流程

### 后端

```bash
python3 -m venv .venv        # 创建项目虚拟环境
source .venv/bin/activate    # 启用虚拟环境
python -m pip install -e .   # 安装 FastAPI / Uvicorn / MySQL 驱动
python -m app.main           # 启动 HTTP 服务 :8000
python -m cli.main "query"   # 命令行测试
python -m unittest           # 运行测试
```

### 前端

```bash
cd web
npm install                  # 安装依赖
npm run dev                  # 开发服务器 :3000（API 代理到 :8000）
npm run build                # 生产构建到 dist/
npx tsc --noEmit             # TypeScript 类型检查
```

### 开发模式工作流

1. 终端 A：`source .venv/bin/activate && python -m app.main`（后端 :8000）
2. 终端 B：`cd web && npm run dev`（前端 :3000）
3. 浏览器打开 `http://localhost:3000`
4. Vite 自动代理 `/api/*` 到后端
5. FastAPI 文档：`http://127.0.0.1:8000/docs`

### 生产模式

```bash
cd web && npm run build
source .venv/bin/activate
python -m app.main
# 浏览器打开 http://127.0.0.1:8000
```

## 4. Agent 状态流

```text
created
 → parsed
 → context_ready
 → tools_queried
 → planned
 → waiting_confirmation
 → executing
 → completed
```

失败状态：`failed_recoverable`、`failed_final`

## 5. 核心模块说明

### 5.1 Intent Parser

规则模式 (`intent_parser.py`)：中文关键词匹配，提取参与者类型、偏好、时间窗口和距离半径。

LLM 模式 (`longcat_intent_parser.py`)：调用 LongCat API 增强解析，失败时返回错误而非降级。

### 5.2 Planning Engine

硬约束过滤 → 候选组合评分 → 排序选优。评分因子：参与者适配、距离、交通舒适度、策略标签、等待时间、价格。

### 5.3 Provider 层

所有外部数据通过 `LocalLifeProvider` Protocol 接口获取，支持 Mock 和 Real 实现切换：

- **Mock**: 内置测试数据
- **Real**: Overpass API (POI/餐厅) + OSRM (路线) + Nominatim (地理编码)

### 5.4 前端架构

- 7 个视图组件通过 `currentView` 状态切换
- `useAuth` / `useLocation` / `useTheme` 封装副作用
- CSS Modules 实现样式作用域隔离
- 所有 API 调用通过 `api/client.ts` 封装，带 TypeScript 类型

## 6. 测试策略

当前测试覆盖：

- 意图解析（规则模式 + LLM 模式）
- 参与者约束归一化
- Planning 排序与评分
- LongCat API 集成
- 认证与存储
- 端到端 Agent 流程

运行：`python3 -m unittest`

## 7. 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LONGCAT_API_KEY` | LongCat LLM API Key | 空 |
| `LONGCAT_BASE_URL` | API 地址 | `https://api.longcat.chat/openai/v1` |
| `LONGCAT_MODEL` | 模型名 | `LongCat-Flash-Chat` |
| `LONGCAT_TIMEOUT_SECONDS` | 超时秒数 | `30` |
| `NEARNOW_PROVIDER_MODE` | `real` / `mock` | `mock` |
| `NEARNOW_STORAGE_BACKEND` | `memory` / `mysql` | `memory` |
| `NEARNOW_MYSQL_AUTO_MIGRATE` | 自动建表 | `false` |
| `MYSQL_HOST` / `PORT` / `DATABASE` / `USER` / `PASSWORD` | MySQL 连接 | - |

## 8. 验收标准

功能：

- 输入一句自然语言即可生成完整活动方案
- 方案包含活动、餐厅、时间轴、交通方式和执行动作
- 用户确认后完成预约、订座和通知
- 异常场景有可恢复输出

工程：

- API 请求响应结构稳定
- Provider 接口和业务逻辑解耦
- 测试覆盖正常路径和异常路径
- 文档能指导新开发者完成启动
