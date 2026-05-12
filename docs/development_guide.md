# 开发指南

## 1. 技术栈

推荐以 Python 后端为主完成 MVP 和后续真实服务接入：

- Python 3.11+
- FastAPI
- Pydantic
- pytest
- Typer 或 argparse

若需要 Web UI：

- React
- TypeScript
- Vite

## 2. 目录职责

```text
app/
├── main.py                  FastAPI 应用入口
├── config.py                配置项
├── api/                     HTTP 路由和请求响应 Schema
├── agent/                   Agent 核心编排
├── domain/                  领域模型、枚举、约束对象
├── tools/                   工具抽象和工具实现
├── providers/               Mock/真实服务 Provider 适配层
├── mock_api/                Mock 数据与 Mock 服务
└── utils/                   时间、距离、日志等通用能力
```

核心目录说明：

| 目录 | 职责 |
| --- | --- |
| `app/api` | 暴露 `/agent/plan`、`/agent/confirm`、Mock Provider API 和后续真实模式入口 |
| `app/agent` | 实现意图解析、规划、工具路由、执行和回复生成 |
| `app/domain` | 定义 Plan、Schedule、Action、Activity、Restaurant 等模型 |
| `app/tools` | 封装可被 Agent 调用的工具，不直接写业务编排 |
| `app/providers` | 封装地图、POI、门店、路线、预约等 Provider，支持 Mock 和真实实现切换 |
| `app/mock_api` | 提供活动、餐厅、预约、通知等假数据和假接口 |
| `tests` | 覆盖核心路径和异常路径 |

## 3. 推荐实现顺序

### 阶段 1：基础骨架

1. 初始化 Python 项目和依赖。
2. 创建 FastAPI 应用。
3. 定义 Pydantic 领域模型。
4. 提供 `/api/agent/plan` 和 `/api/agent/confirm` 空实现。

### 阶段 2：Mock API

1. 创建活动、餐厅、预约、通知 Mock 数据。
2. 实现活动查询、餐厅查询、活动预约、餐厅预订、通知发送。
3. 加入可控异常数据，例如满员活动和无位餐厅。

### 阶段 3：Agent 编排

1. 实现 `IntentParser`，从输入中提取时间、人数、偏好。
2. 接入 `LongCatClient` 作为 LLM Provider，用于增强意图解析和最终回复生成；未配置 API Key 或 API 调用失败时必须返回错误，不得使用本地规则或 Mock 数据假装成功。
3. 实现 `ParticipantConstraintBuilder` 和 `ContextBuilder`，补全默认时间、距离、参与者画像和约束。
4. 实现 `ToolRouter`，统一调用 Provider 工具。
5. 实现 `PlanningEngine`，完成硬约束过滤和软约束评分。
6. 实现 `ResponseGenerator`，生成用户可读方案。

### 阶段 4：执行闭环

1. 保存 `plan_id` 到内存状态。
2. 用户确认后读取待执行动作。
3. 依次执行预约、订座、通知。
4. 支持部分失败和补救输出。

### 阶段 5：Provider 抽象

1. 定义 `GeoProvider`、`PoiProvider`、`MerchantProvider`、`RouteProvider`、`BookingProvider` 接口。
2. 将 Mock API 包装为 `MockProvider` 实现。
3. Agent 只依赖 Provider 接口，不依赖 Mock 数据结构。
4. 为 `mock`、`real`、`hybrid` 三种运行模式预留配置。

### 阶段 6：真实位置、店铺和交通接入

1. 接入真实定位或地址解析能力，支持经纬度和地址互转。
2. 接入真实 POI，返回真实活动地点和真实店铺名称。
3. 接入真实餐厅或商家数据，支持营业时间、评分、人均、标签和可订状态。
4. 接入路线服务，支持步行、驾车、公交/地铁、网约车、骑行。
5. 将交通方式纳入 Planning 评分。
6. 增加 Provider 超时、限流、无结果和权限失败处理。

### 阶段 7：Demo 与测试

1. 补充 CLI 或 Web UI。
2. 完成 Mock 正常场景 Demo。
3. 完成真实模式的规划链路冒烟测试。
4. 完成至少 3 个异常场景 Demo。
5. 编写 pytest 测试用例。

## 4. Agent 状态流

```text
created
 -> parsed
 -> context_ready
 -> tools_queried
 -> planned
 -> waiting_confirmation
 -> executing
 -> completed
```

失败状态：

```text
failed_recoverable
failed_final
```

## 5. 关键接口设计

### 5.1 工具基类

```python
from typing import Protocol, Any


class Tool(Protocol):
    name: str

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...
```

### 5.2 Provider 接口

```python
from typing import Protocol


class GeoProvider(Protocol):
    def geocode(self, address: str, city: str | None = None) -> GeoPoint:
        ...


class PoiProvider(Protocol):
    def search_activities(self, query: ActivitySearchQuery) -> list[Activity]:
        ...


class MerchantProvider(Protocol):
    def search_restaurants(self, query: RestaurantSearchQuery) -> list[Restaurant]:
        ...

    def check_availability(self, query: AvailabilityQuery) -> Availability:
        ...


class RouteProvider(Protocol):
    def calculate_route(self, query: RouteQuery) -> RouteOption:
        ...

    def calculate_route_matrix(self, query: RouteMatrixQuery) -> RouteMatrix:
        ...
```

### 5.3 规划器接口

```python
class PlanningEngine:
    def generate_plan(self, context: PlanningContext) -> Plan:
        ...
```

### 5.4 执行器接口

```python
class ExecutionManager:
    def execute(self, plan: Plan, action_ids: list[str]) -> ExecutionResult:
        ...
```

## 6. 测试策略

必须覆盖：

- `IntentParser` 能从自然语言中提取时间、人数、参与者关系和偏好。
- `LongCatIntentParser` 在 API 可用时能解析结构化 JSON，在 API 不可用或返回异常时返回可恢复错误。
- `LongCatResponseGenerator` 在 API 可用时能润色方案，在 API 不可用时返回可恢复错误。
- `ParticipantConstraintBuilder` 能处理闺蜜、恋人、孩子、宠物、老人、同事等通用角色，而不是只支持题目样例。
- `PlanningEngine` 能过滤不满足硬约束的活动和餐厅。
- `PlanningEngine` 能在多个候选方案中选择高分方案。
- `PlanningEngine` 能根据步行、驾车、公共交通等路线结果选择合理交通方式。
- `ExecutionManager` 只执行用户确认的动作。
- 餐厅无位时返回备选餐厅。
- 活动满员时返回备选活动。
- 出发地缺失时返回追问，而不是生成假方案。
- 真实模式下不得输出 Mock 店铺名或编造店铺名。
- Provider 超时或无结果时能降级到可恢复状态。

推荐测试文件：

```text
tests/
├── test_intent_parser.py
├── test_context_builder.py
├── test_planner.py
├── test_tool_router.py
├── test_executor.py
└── test_agent_api.py
```

## 7. 日志与可观测性

每次 Agent 调用需要记录：

- `request_id`
- 原始用户输入
- 解析后的结构化上下文
- 工具调用名称
- 工具调用输入摘要
- 工具调用结果状态
- Provider 名称和运行模式
- 路线交通方式和耗时
- 最终选中方案
- 执行动作结果

日志示例：

```json
{
  "request_id": "req_001",
  "stage": "tool_call",
  "tool": "restaurant_search",
  "status": "success",
  "candidate_count": 3
}
```

## 8. 验收标准

功能验收：

- 输入一句自然语言即可生成完整下午方案。
- 方案中包含活动、餐厅、时间轴和执行动作。
- 用户确认后可完成预约、订座和通知。
- 异常场景有可恢复输出。

工程验收：

- 所有核心模块有清晰职责。
- API 请求响应结构稳定。
- Mock 数据可复现。
- Provider 接口和业务逻辑解耦。
- 真实地理位置、真实店铺名和交通方式选择有明确接入路径。
- 测试覆盖正常路径和异常路径。
- README 和文档能指导新开发者完成项目启动。
