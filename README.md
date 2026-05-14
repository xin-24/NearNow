# NearNow 邻刻计划

本地短时活动规划与执行 Agent。用户输入一句自然语言目标后，系统理解出行时间、参与者画像、距离偏好和餐饮需求，生成可执行的活动方案。用户确认后，Agent 自动完成预约、订座和通知。

## 项目结构

```text
nearnow/
├── app/                        Python 后端
│   ├── main.py                 FastAPI 服务入口、路由、中间件、OpenAPI
│   ├── auth.py                 登录/注册/会话
│   ├── agent/                  Agent 核心编排
│   │   ├── orchestrator.py     plan() / confirm() 生命周期
│   │   ├── intent_parser.py    规则意图解析
│   │   ├── longcat_intent_parser.py  LLM 增强意图解析
│   │   ├── strategy.py         策略构建（确定性 + LLM）
│   │   ├── context_builder.py  规划上下文构建
│   │   ├── planner.py          硬约束过滤 + 软约束评分
│   │   ├── executor.py         执行管理器
│   │   ├── response_generator.py     文本方案生成
│   │   └── longcat_response_generator.py  LLM 增强方案生成
│   ├── domain/                 数据模型与枚举
│   ├── providers/              外部服务适配层
│   │   ├── mock_provider.py    Mock 数据
│   │   ├── real_provider.py    Overpass + OSRM 真实数据
│   │   ├── location_provider.py  Nominatim 地理编码
│   │   └── longcat_client.py   LongCat LLM 客户端
│   ├── storage/                存储层（内存 / MySQL）
│   └── utils/                  时间、ID 工具
├── web/                        React 前端
│   ├── index.html              Vite 入口
│   ├── package.json            React 18 + Vite + TypeScript
│   ├── vite.config.ts          开发代理 :3000 → :8000
│   └── src/
│       ├── main.tsx            React 挂载点
│       ├── App.tsx             视图路由与状态编排
│       ├── api/                类型定义与 fetch 封装
│       ├── components/         可复用组件（Header, Timeline, RouteSelector 等）
│       ├── views/              7 个视图（Login, Input, Analyzing, Proposal, Executing, Success, Error）
│       ├── hooks/              useAuth, useLocation, useTheme
│       ├── utils/              标签映射、路线编辑、同伴解析
│       └── styles/             CSS 变量与 reset
├── cli/                        命令行入口
├── tests/                      单元测试
├── docs/                       设计文档与 API 契约
├── pyproject.toml              Python 项目配置
├── .env.example                环境变量模板（安全）
└── .env.local.example          真实 Key 模板（本地）
```

## 本地运行

### 环境要求

- Python 3.11+
- Node.js 18+

### 快速启动

```bash
# 1. 创建并启用后端虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 2. 安装后端依赖
python -m pip install -e .

# 3. 安装前端依赖
cd web && npm install && cd ..

# 4. 配置环境变量
cp .env.local.example .env.local
# 编辑 .env.local，填入 LONGCAT_API_KEY

# 5. 启动后端
python -m app.main

# 6. 另一个终端，启动前端开发服务器
cd web && npm run dev
```

打开 `http://localhost:3000`，Vite 会自动代理 API 请求到后端 `:8000`。

FastAPI 文档地址：

- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

### 生产构建

```bash
cd web && npm run build
source .venv/bin/activate
python -m app.main
# 打开 http://127.0.0.1:8000
```

后端直接 serve `web/dist/` 的构建产物。

### 命令行试用

```bash
source .venv/bin/activate
python -m cli.main "下午带狗出去玩，顺便找个能带宠物的地方吃饭。"
```

### 运行测试

```bash
source .venv/bin/activate
python -m unittest
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LONGCAT_API_KEY` | LongCat LLM API Key | 空（未配置时 LLM 增强不可用） |
| `LONGCAT_BASE_URL` | LongCat API 地址 | `https://api.longcat.chat/openai/v1` |
| `LONGCAT_MODEL` | 模型名称 | `LongCat-Flash-Chat` |
| `NEARNOW_PROVIDER_MODE` | `real` / `mock` | `mock` |
| `NEARNOW_CORS_ORIGINS` | 允许跨域访问的前端地址，逗号分隔 | `http://localhost:3000,http://127.0.0.1:3000` |
| `NEARNOW_LOG_LEVEL` | 后端日志等级 | `INFO` |
| `NEARNOW_COOKIE_SECURE` | Cookie 是否仅 HTTPS 传输 | `false` |
| `NEARNOW_STORAGE_BACKEND` | `memory` / `mysql` | `memory` |
| `MYSQL_HOST` / `PORT` / `DATABASE` / `USER` / `PASSWORD` | MySQL 连接 | - |

完整变量见 [.env.example](.env.example)。

## 登录与存储

首次使用同一账号和密码会自动创建本地账号。登录后保存出发位置、计划记录和同行通知人。

默认内存存储，适合本地调试。如需 MySQL：

```bash
pip install -e .
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS nearnow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p nearnow < app/storage/schema.sql
export NEARNOW_STORAGE_BACKEND=mysql
```

设置 `NEARNOW_MYSQL_AUTO_MIGRATE=true` 可在启动时自动建表。

## 定位

网页中点击「定位」按钮调用浏览器定位授权。前端将经纬度降为约 1km 级别后调用后端地址反查，按「城市 + 区/县 + 商圈/地标」填回输入框。手动输入建议同一格式，例如 `北京 朝阳区 望京 SOHO`。

## 文档

- [总体设计](docs/design.md) — 架构、Agent 流程、Planning 策略
- [API 契约](docs/api_contract.md) — 请求响应结构与错误码
- [开发指南](docs/development_guide.md) — 技术栈、目录职责、测试策略
- [竞品调研](docs/ai_agent_benchmark.md) — 可借鉴的 Agent 产品能力
- [真实服务接入](docs/production_integration.md) — 地图、POI、路线接入方案
- [Demo 脚本](docs/demo_script.md) — 演示路径与异常场景
