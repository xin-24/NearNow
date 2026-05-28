# NearNow (邻刻计划) — 项目架构与实现文档

## 一、项目概述

NearNow 是一个**本地短时活动规划与执行 Agent**。用户输入一句自然语言目标（如"今天下午想和老婆孩子出去玩"），系统自动理解参与者画像、距离偏好、餐饮需求，生成可执行的活动方案。用户确认后，Agent 自动处理预订、通知等执行动作。

### 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11+, FastAPI, Uvicorn, Pydantic |
| 前端 | React 18, TypeScript, Vite 6, CSS Modules |
| 存储 | 内存 (默认) / MySQL (可切换) |
| LLM | LongCat LLM API (OpenAI 兼容协议) |
| 地图 | 高德地图 Web Service + JavaScript API |
| 构建 | setuptools (后端), npm (前端) |

---

## 二、目录结构

```
meituan/
├── app/                              # Python 后端
│   ├── main.py                       # FastAPI 入口，路由、中间件、静态文件服务
│   ├── auth.py                       # 认证服务 (PBKDF2 密码哈希、Session 管理)
│   ├── domain/                       # 领域模型
│   │   ├── models.py                 # 所有数据类: Plan, Activity, Restaurant, RouteOption 等
│   │   └── enums.py                  # 枚举: RunMode, TransportMode, ActionStatus
│   ├── agent/                        # Agent 核心编排层
│   │   ├── orchestrator.py           # LocalPlannerAgent — plan() 和 confirm() 生命周期
│   │   ├── intent_parser.py          # 确定性中文 NLP 意图解析器
│   │   ├── longcat_intent_parser.py  # LLM 增强意图解析器 (包装确定性解析器)
│   │   ├── participant_constraints.py# 参与者约束归一化
│   │   ├── strategy.py               # 策略构建器 (确定性 + LLM)
│   │   ├── context_builder.py        # PlanningContext 组装
│   │   ├── persona_query.py          # 人物画像搜索配置 + 候选质量门控
│   │   ├── planner.py                # PlanningEngine — 候选搜索、评分、方案构建
│   │   ├── candidate_selector.py     # LLM 候选选择器
│   │   ├── executor.py               # ExecutionManager — 执行待确认动作
│   │   ├── response_generator.py     # 确定性方案摘要生成器
│   │   └── longcat_response_generator.py # LLM 增强方案摘要生成器
│   ├── providers/                    # 外部服务适配器
│   │   ├── base.py                   # LocalLifeProvider Protocol 接口定义
│   │   ├── mock_provider.py          # Mock 数据 Provider (6 活动 + 6 餐厅)
│   │   ├── real_provider.py          # OpenStreetMap Provider (Overpass + OSRM)
│   │   ├── amap_provider.py          # 高德地图 Provider (POI、路线、地理编码)
│   │   ├── location_provider.py      # 地理编码 Provider (Mock/OSM/Nominatim)
│   │   ├── longcat_client.py         # LongCat LLM API 客户端 (纯 stdlib)
│   │   └── meituan_link.py           # 美团/大众点评跳转链接构建器
│   ├── storage/                      # 持久化层
│   │   ├── repository.py             # AppRepository Protocol + Memory/MySQL 实现
│   │   └── schema.sql                # MySQL 建表 DDL
│   └── utils/                        # 工具函数
│       ├── geo.py                    # 距离计算 (Haversine)、坐标格式化/解析
│       ├── text.py                   # JSON 提取、字符串去重
│       ├── time_utils.py             # 时间加减
│       └── ids.py                    # ID 生成器
├── web/                              # React 前端
│   ├── src/
│   │   ├── App.tsx                   # 主组件，7 视图状态机
│   │   ├── api/
│   │   │   ├── client.ts             # Fetch 封装，API 调用函数
│   │   │   └── types.ts              # TypeScript 接口定义
│   │   ├── views/                    # 7 个视图组件
│   │   ├── components/               # 可复用组件 (Timeline, RouteMap 等)
│   │   ├── hooks/                    # 自定义 Hooks (useAuth, useLocation, useTheme)
│   │   ├── utils/                    # 工具函数 (route, labels, location)
│   │   └── styles/                   # 全局 CSS 变量和主题
│   ├── vite.config.ts                # Vite 配置，开发代理
│   └── package.json                  # 依赖声明
├── cli/                              # CLI 入口
│   └── main.py                       # 命令行测试工具
├── tests/                            # 测试
│   └── test_agent.py                 # 60+ 单元测试
├── docs/                             # 文档
└── pyproject.toml                    # Python 项目配置
```

---

## 三、核心功能

### 3.1 自然语言意图解析

用户输入一句中文目标，系统提取：
- **参与者**: 配偶、孩子、朋友、宠物、长辈、同事等
- **偏好**: 附近、安静、拍照友好、宠物友好、儿童安全等
- **时间窗口**: 开始时间、结束时间
- **距离半径**: 根据"附近""别太远"等关键词推断

**实现**: `IntentParser` (确定性规则) + `LongCatIntentParser` (LLM 增强，失败时降级到确定性)

### 3.2 人物画像策略构建

根据参与者画像生成搜索策略：
- **长辈场景**: 优先公园慢走、清淡正餐、低步行强度
- **宠物场景**: 必须宠物友好、户外座位、可外带
- **亲子场景**: 安全适龄、室内优先、少换乘
- **约会场景**: 氛围优先、拍照友好、安静
- **闺蜜场景**: 聊天空间、网红打卡、下午茶

**实现**: `PersonaStrategyBuilder` (确定性) + `LongCatStrategyBuilder` (LLM 增强)

### 3.3 POI 搜索与路线计算

- **活动搜索**: 根据策略标签搜索附近活动场所 (公园、商场、博物馆等)
- **餐厅搜索**: 根据餐饮偏好搜索附近餐厅
- **路线计算**: 并行计算步行、驾车、公交、骑行、网约车 5 种交通方式
- **质量门控**: 候选不足时自动扩大搜索半径

**实现**: `PlanningEngine` + `AmapLocalLifeProvider` (高德 API)

### 3.4 多维度评分与选择

候选方案评分公式：
```
总分 = 活动匹配分 × 0.3 + 餐厅匹配分 × 0.3 + 路线舒适分 × 0.2 + 配对距离分 × 0.1 + 距离近度分 × 0.1
```

支持两种评分配置：
- **地点优先** (`place_first`): 更看重地点和餐厅是否贴合人物画像
- **距离优先** (`distance_first`): 更看重少移动、近距离和动线顺畅

**实现**: `PlanningEngine._score_candidate()` + `LongCatCandidateSelector` (LLM 最终选择)

### 3.5 方案生成与展示

生成完整活动方案，包含：
- **时间表**: 出发 → 交通 → 活动 → 交通 → 餐厅 → 结束
- **路线选项**: 5 种交通方式的耗时、距离、费用、舒适度
- **待确认动作**: 预订活动、预订餐厅、通知同行者
- **备选方案**: 地点优先版、距离优先版
- **风险提示**: 路况、步行距离、营业状态等

**实现**: `PlanningEngine._build_plan()` + `LongCatResponseGenerator` (LLM 摘要)

### 3.6 方案执行

用户确认后执行：
- **活动预订**: 调用 Provider 的 `book_activity()` 接口
- **餐厅预订**: 调用 `reserve_restaurant()` 接口，或生成美团/大众点评跳转链接
- **通知发送**: 调用 `send_notification()` 接口

**实现**: `ExecutionManager.execute()`

### 3.7 地图可视化

前端使用高德地图 JavaScript API：
- 显示起点和终点标记
- 绘制路线轨迹 (支持驾车、步行、公交、骑行)
- 路线图例和缩放控制

**实现**: `RouteMap` 组件 + AMap JSAPI v2.0

### 3.8 用户认证

- **注册/登录**: 用户名 + 密码，首次登录自动注册
- **密码安全**: PBKDF2-HMAC-SHA256，120,000 次迭代，随机盐值
- **会话管理**: HTTP-only Cookie，7 天过期，SameSite=Lax

**实现**: `AuthService` + FastAPI 依赖注入

---

## 四、调用的外部工具/服务

### 4.1 LongCat LLM API

| 调用位置 | 用途 | Temperature | Max Tokens |
|---------|------|-------------|------------|
| `LongCatIntentParser` | 中文意图解析增强 | 0.1 | 900 |
| `LongCatStrategyBuilder` | 策略构建增强 | 0.2 | 1200 |
| `LongCatCandidateSelector` | 候选方案选择 | 0.15 | 1000 |
| `LongCatResponseGenerator` | 方案摘要生成 | 0.3 | 1000 |

**协议**: OpenAI 兼容 (`/openai/v1/chat/completions`)
**降级策略**: 所有 LLM 调用失败时自动降级到确定性实现

### 4.2 高德地图 Web Service API

| 接口 | 用途 | 调用位置 |
|------|------|---------|
| `/v3/place/around` | 周边 POI 搜索 | `AmapLocalLifeProvider._fetch_place_pois()` |
| `/v3/direction/driving` | 驾车路线规划 | `_calculate_route()` |
| `/v3/direction/walking` | 步行路线规划 | `_calculate_route()` |
| `/v3/direction/transit/integrated` | 公交路线规划 | `_calculate_route()` |
| `/v4/direction/bicycling` | 骑行路线规划 | `_calculate_route()` |
| `/v3/geocode/regeo` | 逆地理编码 (坐标→地址) | `AmapLocationProvider.reverse_geocode()` |
| `/v3/geocode/geo` | 地理编码 (地址→坐标) | `AmapLocationProvider.geocode()` |

**重试策略**: 遇到频率限制 (CUQPS_HAS_EXCEEDED_THE_LIMIT) 时最多重试 3 次，指数退避
**并行控制**: 最多 2 个并行请求 (AMAP_MAX_WORKERS=2)

### 4.3 高德地图 JavaScript API

| 功能 | 实现 |
|------|------|
| 地图渲染 | `RouteMap` 组件加载 AMap JSAPI v2.0 |
| 路线绘制 | `AMap.Polyline` 绘制交通路线 |
| 标记点 | `AMap.Marker` 标记起点/终点 |
| 坐标转换 | `AMap.convertFrom` GCJ-02 坐标转换 |

### 4.4 美团/大众点评跳转

当餐厅无法自动预订时，生成第三方平台跳转链接：
- 美团 Web: `https://meituan.com/s/{餐厅名}`
- 美团 App: `imeituan://www.meituan.com/restaurant/{id}`
- 大众点评 App: `dianping://shop/{id}`

**实现**: `HandoffLinkBuilder`

### 4.5 OpenStreetMap (备用)

| 服务 | 用途 |
|------|------|
| Overpass API | POI 搜索 (备用) |
| OSRM | 路线规划 (备用) |
| Nominatim | 地理编码 (备用) |

---

## 五、实现流程

### 5.1 方案生成流程 (plan)

```
用户输入 "今天下午想和老婆孩子出去玩"
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 输入校验                                                  │
│    - 检查 message 非空                                        │
│    - 确定模式 (mock/real)                                     │
│    - 提取显式参与者信息                                        │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 意图解析 (LongCatIntentParser)                            │
│    ├─ 确定性解析: 提取参与者、偏好、时间、半径                    │
│    └─ LLM 增强: 细化理解 (失败时降级到确定性)                    │
│                                                              │
│    输出: PlanningIntent                                      │
│    - participants: [{relation: "spouse"}, {relation: "child"}]│
│    - preferences: ["nearby", "kid_friendly"]                 │
│    - start_time: "14:00", end_time: "18:00"                  │
│    - radius_km: 6.0                                          │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 约束归一化 (ParticipantConstraintBuilder)                  │
│    - 为每个参与者角色添加默认约束                                │
│    - child → kid_friendly, safe 硬约束                        │
│    - pet → pet_friendly 硬约束                                │
│    - elder → low_walking, rest_available 硬约束               │
│    - 生成场景标签: "parent_child"                              │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. 策略构建 (LongCatStrategyBuilder)                         │
│    ├─ 确定性策略: 根据场景标签选择基础策略                       │
│    │  - parent_child → 安全、适龄、少换乘                       │
│    │  - 搜索标签: ["kid_friendly", "indoor", "playground"]    │
│    └─ LLM 增强: 细化策略 (失败时降级到确定性)                    │
│                                                              │
│    输出: PlanningStrategy                                    │
│    - name: "parent_child_afternoon"                          │
│    - preferred_activity_tags: ["kid_friendly", "safe"]        │
│    - preferred_restaurant_tags: ["kid_friendly", "highchair"] │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. 上下文组装 (ContextBuilder)                               │
│    - 合并意图 + 用户位置 + 策略                                 │
│    - 地理编码 (real 模式): 文字地址 → 坐标                      │
│                                                              │
│    输出: PlanningContext                                     │
│    - origin_name: "北京 朝阳区 望京 SOHO"                     │
│    - origin_coordinates: {lat: 39.99, lng: 116.48}           │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. 候选搜索 (PlanningEngine)                                 │
│    ├─ 构建搜索配置 (PersonaQueryPlanner)                      │
│    │  - 活动标签: ["kid_friendly", "indoor"]                  │
│    │  - 餐厅标签: ["kid_friendly", "highchair"]               │
│    │  - 最少活动数: 4, 最少餐厅数: 5                            │
│    ├─ 并行搜索活动和餐厅 (ThreadPoolExecutor)                  │
│    ├─ 质量门控: 候选不足时扩大半径重新搜索                       │
│    └─ 并行计算每个活动的 5 种交通路线                            │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. 评分与选择 (PlanningEngine + LongCatCandidateSelector)    │
│    ├─ 多维度评分:                                             │
│    │  - 活动匹配分 (标签匹配度)                                 │
│    │  - 餐厅匹配分 (标签匹配度)                                 │
│    │  - 路线舒适分 (舒适度、步行时间)                            │
│    │  - 配对距离分 (活动↔餐厅距离)                              │
│    │  - 距离近度分 (起点↔活动距离)                              │
│    ├─ LLM 最终选择 (失败时使用最高分候选)                        │
│    └─ 生成备选方案 (地点优先、距离优先)                          │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 8. 方案构建 (PlanningEngine._build_plan())                   │
│    - 时间表: 出发→交通→活动→交通→餐厅→结束                      │
│    - 路线选项: 5 种交通方式                                    │
│    - 待确认动作: 预订活动、预订餐厅、通知同行者                   │
│    - 风险提示: 路况、步行距离、营业状态                          │
│    - 备选方案: 2 个 (地点优先、距离优先)                         │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 9. 摘要生成 (LongCatResponseGenerator)                       │
│    - LLM 生成自然语言摘要 (失败时使用确定性摘要)                 │
│    - 避免提及工程术语 (provider, API, amap 等)                 │
│    - 提示出发前确认营业状态                                     │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 10. 返回结果                                                 │
│     {                                                        │
│       "success": true,                                       │
│       "data": { plan_id, title, summary, schedule, ... },    │
│       "error": null                                          │
│     }                                                        │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 方案确认与执行流程 (confirm)

```
用户点击 "确认执行"
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 查找存储的方案 (PlanStore)                                 │
│    - 根据 plan_id 获取 Plan 对象                               │
│    - 不存在则返回 PLAN_NOT_FOUND 错误                          │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 应用路线变更 (可选)                                        │
│    - 用户切换交通方式时重新计算时间                               │
│    - 更新后续行程的时间安排                                     │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 执行待确认动作 (ExecutionManager)                          │
│    ├─ book_activity: 调用 Provider 预订活动                    │
│    ├─ reserve_restaurant: 调用 Provider 预订餐厅               │
│    │   └─ 或生成美团/大众点评跳转链接 (handoff)                  │
│    └─ send_notification: 调用 Provider 发送通知                │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. 返回执行结果                                               │
│     {                                                        │
│       "success": true,                                       │
│       "data": {                                              │
│         "plan_id": "plan_001",                               │
│         "execution_status": "completed",                     │
│         "results": [...],                                    │
│         "final_message": "搞定了，14:00 出发..."              │
│       }                                                      │
│     }                                                        │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 前端视图状态机

```
                    ┌─────────┐
                    │  login  │
                    └────┬────┘
                         │ 登录成功
                         ▼
                    ┌─────────┐
            ┌──────│  input  │◄─────────────────────┐
            │      └────┬────┘                      │
            │           │ 点击"生成方案"              │
            │           ▼                           │
            │      ┌────────────┐                   │
            │      │ analyzing  │                   │
            │      └────┬───────┘                   │
            │           │                           │
            │     ┌─────┴─────┐                     │
            │     │           │                     │
            │     ▼           ▼                     │
            │ ┌────────┐  ┌───────┐                 │
            │ │proposal│  │ error │─────────────────┤
            │ └───┬────┘  └───────┘                 │
            │     │                                 │
            │     │ 点击"确认执行"                    │
            │     ▼                                 │
            │ ┌────────────┐                        │
            │ │ executing  │                        │
            │ └────┬───────┘                        │
            │      │                                │
            │ ┌────┴────┐                           │
            │ │         │                           │
            │ ▼         ▼                           │
            │ ┌───────┐ ┌───────┐                   │
            │ │success│ │ error │───────────────────┤
            │ └───┬───┘ └───────┘                   │
            │     │                                 │
            │     │ 点击"新方案"                     │
            │     └─────────────────────────────────┘
            │
            │ 点击"返回修改"
            └──────────────────────────────────────┘
```

---

## 六、数据模型

### 6.1 核心数据类关系

```
PlanningIntent (意图)
├── participants: list[ParticipantProfile]
│   └── constraints: list[Constraint]
├── preferences: list[str]
└── scenario_tags: list[str]

PlanningStrategy (策略)
├── preferred_activity_tags: list[str]
├── preferred_restaurant_tags: list[str]
├── hard_constraints: list[str]
└── soft_preferences: list[str]

PlanningContext (上下文)
├── intent: PlanningIntent
├── user_context: UserContext
├── origin_name: str
├── origin_coordinates: Coordinates
└── strategy: PlanningStrategy

Plan (方案)
├── schedule: list[ScheduleItem]
│   ├── type: "travel" | "activity" | "restaurant"
│   ├── coordinates: Coordinates
│   └── route_geometry: list[Coordinates]
├── route_options: list[RouteOption]
│   ├── mode: "walking" | "driving" | "public_transit" | "ride_hailing" | "cycling"
│   └── selected: bool
├── pending_actions: list[PendingAction]
│   ├── type: "book_activity" | "reserve_restaurant" | "send_notification"
│   └── payload: dict
├── alternatives: list[dict]
│   └── plan: Plan (备选方案)
└── risk_notes: list[str]

ExecutionResult (执行结果)
├── plan_id: str
├── execution_status: "completed" | "partial_failed"
└── results: list[dict]
```

### 6.2 前后端数据流

**请求 (前端 → 后端)**:
```typescript
// POST /api/agent/plan
{
  message: string;                    // 自然语言目标
  mode: "real" | "mock";             // 规划模式
  user_context: {
    home_location: string;           // 出发地文字
    city: string;                    // 城市
    coordinates: { lat, lng };       // 坐标
    location_permission_granted: boolean;
    location_source: "browser" | "manual";
    accuracy_m: number;
    precision: string;
    district?: string;
    landmark?: string;
    formatted_address?: string;
  };
  companions: [{
    name: string;
    relation: string;
    contact_method: string;
    contact_value: string;
  }];
}
```

**响应 (后端 → 前端)**:
```typescript
// POST /api/agent/plan 响应
{
  success: boolean;
  data: Plan;                        // 完整方案对象
  error: {
    code: string;                    // 错误码
    message: string;                 // 错误信息
    recoverable: boolean;            // 是否可恢复
  } | null;
}
```

---

## 七、配置说明

### 7.1 环境变量

**LongCat LLM 配置**:
```bash
LONGCAT_API_KEY=your_api_key        # API 密钥
LONGCAT_BASE_URL=https://api.longcat.chat  # API 地址
LONGCAT_MODEL=LongCat-Flash-Chat    # 模型名称
LONGCAT_TIMEOUT_SECONDS=30          # 请求超时 (秒)
```

**高德地图配置 (后端)**:
```bash
AMAP_WEB_SERVICE_KEY=your_key       # Web 服务密钥
AMAP_DEFAULT_CITY=北京              # 默认城市
```

**高德地图配置 (前端)**:
```bash
VITE_AMAP_JS_API_KEY=your_key       # JavaScript API 密钥
VITE_AMAP_SECURITY_JS_CODE=your_code # 安全码
```

**应用配置**:
```bash
NEARNOW_PROVIDER_MODE=real           # real 或 mock
NEARNOW_CORS_ORIGINS=http://localhost:3000
NEARNOW_LOG_LEVEL=INFO
NEARNOW_COOKIE_SECURE=false
```

**存储配置**:
```bash
NEARNOW_STORAGE_BACKEND=memory       # memory 或 mysql
NEARNOW_MYSQL_AUTO_MIGRATE=false     # 自动建表
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=nearnow
MYSQL_USER=nearnow
MYSQL_PASSWORD=your_password
```

### 7.2 开发环境启动

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv/bin/pip install -e .

# 2. 安装前端依赖
cd web && npm install && cd ..

# 3. 配置环境变量
cp .env.local.example .env.local
# 编辑 .env.local 填入 API 密钥

# 4. 启动后端 (端口 8000)
.venv/bin/python -m uvicorn app.main:app --reload

# 5. 启动前端 (端口 3000)
cd web && npm run dev

# 6. 访问 http://localhost:3000
```

### 7.3 生产环境部署

```bash
# 1. 构建前端
cd web && npm run build

# 2. 启动服务 (自动服务静态文件)
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 八、API 接口清单

### 8.1 认证接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录/注册 |
| POST | `/api/auth/logout` | 登出 |
| GET | `/api/auth/me` | 获取当前用户 |

### 8.2 规划接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/agent/plan` | 生成活动方案 |
| POST | `/api/agent/confirm` | 确认并执行方案 |

### 8.3 工具接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/location/reverse-geocode` | 逆地理编码 |
| GET | `/api/companions` | 获取同行者列表 |
| GET | `/health` | 健康检查 |

---

## 九、测试覆盖

测试文件: `tests/test_agent.py` (60+ 测试用例)

| 测试类别 | 覆盖内容 |
|---------|---------|
| 意图解析 | 确定性解析、LLM 增强解析、边界情况 |
| 参与者约束 | 各角色默认约束、场景标签生成 |
| 策略构建 | 确定性策略、LLM 策略、策略合并 |
| 规划引擎 | 候选搜索、评分排序、方案构建 |
| 候选选择 | LLM 选择、降级行为 |
| 认证存储 | 登录注册、Session 管理、内存/MySQL 存储 |
| 错误处理 | API Key 缺失、LLM 超时、Provider 错误 |
| 美团跳转 | 深度链接生成 |

**测试替身**:
- `StubLongCatClient`: 返回预设内容
- `SequencedLongCatClient`: 按顺序返回不同内容
- `RuleBackedLongCatClient`: 基于规则返回内容
- `RaisingLongCatClient`: 始终抛出异常 (测试降级)
