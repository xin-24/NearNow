# 本地短时活动规划与执行 Agent 总体设计

## 1. 项目背景

周末短时出行通常不是单点搜索问题，而是一个多约束的执行问题。用户关心的不只是“去哪玩”，还包括什么时候出发、谁参与、同行关系是什么、每个参与者有什么偏好或限制、吃什么、有没有位置、是否需要排队、是否能提前预约，以及最终能否一键完成安排。

本项目要构建一个本地场景 Agent，让用户用一句自然语言描述目标，系统在几分钟内完成可落地的活动规划，并在用户确认后自动完成关键下单、预约、排队和通知动作。

## 2. 业务目标

系统需要支持如下典型输入：

```text
今天下午是空的，想和老婆孩子、朋友出去玩几个小时，别离家太远，帮我安排一下。
```

题目中的家庭和朋友只是一个示例。系统设计必须支持更通用的参与者组合，例如闺蜜、恋人、宠物、老人、同事、客户、同学、亲子家庭、多人团建、独自出行等，不能把 Planning 逻辑写死在“老婆、孩子、朋友”这一组角色上。

系统需要输出：

- 结构化理解结果：时间、地点、人数、角色、偏好、限制条件。
- 下午 4-6 小时活动方案：活动点、餐厅、后续活动、交通方式和交通时间。
- 交通方式建议：步行、驾车、公交/地铁、网约车、骑行等可选方式。
- 可执行动作清单：预约门票、预订餐厅、加入排队、发送计划。
- 用户确认后的执行结果：成功动作、失败动作、备选方案。

## 3. 范围边界

MVP 阶段：

- 使用 Mock Provider 验证 Agent 的理解、规划、工具调用和执行闭环。
- 不接入真实支付、真实短信和真实外卖平台。

生产化阶段：

- 必须支持真实地理位置、真实 POI、真实店铺名称、真实营业状态和路线耗时。
- 必须支持交通方式选择，包括步行、驾车、公交/地铁、网约车、骑行等。
- 必须通过 Provider 抽象接入地图、门店、预约和通知服务，避免业务逻辑和某个外部平台强绑定。

始终不做的事情：

- 不做通用旅游规划，只聚焦本地短时活动场景。
- 不做纯搜索结果列表，核心价值是规划和执行闭环。

## 4. 系统架构

```text
User
 │
 ▼
CLI / Web UI
 │
 ▼
Agent API
 │
 ▼
Agent Orchestrator
 │
 ├── Intent Parser
 ├── Context Builder
 ├── Planning Engine
 ├── Tool Router
 ├── Execution Manager
 └── Response Generator
 │
 ▼
Tool Provider Layer
 ├── Mock Provider
 │   ├── Mock Location API
 │   ├── Mock Activity API
 │   ├── Mock Restaurant API
 │   ├── Mock Route API
 │   └── Mock Booking API
 └── Real Provider
     ├── Geo Provider
     ├── POI Provider
     ├── Merchant Provider
     ├── Route Provider
     ├── Booking Provider
     └── Notification Provider
```

## 5. 核心模块

### 5.1 Agent Orchestrator

负责编排一次完整任务生命周期：

1. 接收用户自然语言输入。
2. 调用 Intent Parser 提取结构化目标。
3. 调用 Context Builder 补全上下文。
4. 调用 Tool Router 查询候选活动和餐厅。
5. 调用 Planning Engine 生成并排序方案。
6. 调用 Response Generator 输出给用户确认。
7. 用户确认后调用 Execution Manager 执行动作。

### 5.2 Intent Parser

负责把自然语言转为结构化任务对象：

```json
{
  "date": "today",
  "time_window": {
    "start": "14:00",
    "end": "18:00"
  },
  "participants": [
    {
      "id": "self",
      "relation": "self",
      "count": 1,
      "constraints": []
    },
    {
      "id": "partner",
      "relation": "partner",
      "count": 1,
      "constraints": [
        {
          "type": "diet",
          "value": "low_calorie",
          "priority": "medium"
        }
      ]
    },
    {
      "id": "child_1",
      "relation": "child",
      "count": 1,
      "age": 5,
      "constraints": [
        {
          "type": "activity",
          "value": "kid_friendly",
          "priority": "hard"
        }
      ]
    },
    {
      "id": "friends",
      "relation": "friend_group",
      "count": 4,
      "constraints": [
        {
          "type": "activity",
          "value": "group_friendly",
          "priority": "medium"
        }
      ]
    }
  ],
  "preferences": [
    "nearby",
    "kid_friendly",
    "group_friendly",
    "not_too_tiring"
  ],
  "required_actions": [
    "plan",
    "book",
    "notify"
  ]
}
```

### 5.3 Participant & Constraint Builder

负责从用户输入中抽取通用参与者画像，并把角色信息转成 Planning 可执行约束。角色不应被硬编码为家庭场景，而应通过统一模型表达。

参与者关系示例：

| 关系 | 典型约束 |
| --- | --- |
| `self` | 个人偏好、预算、时间 |
| `partner` | 约会氛围、私密性、餐厅品质、拍照体验 |
| `spouse` | 家庭便利性、饮食限制、舒适度 |
| `child` | 年龄、安全、亲子友好、步行距离、卫生间便利 |
| `friend_group` | 社交互动、多人桌、拍照、可聊天、不太无聊 |
| `bestie` | 逛街、下午茶、拍照、轻松聊天、审美偏好 |
| `pet` | 宠物友好、户外空间、可携宠入内、交通限制 |
| `elder` | 少走路、安静、座位充足、无障碍、离医院或停车点近 |
| `colleague` | 团建、预算合规、交通公平、可容纳多人 |
| `client` | 商务氛围、隐私、交通便利、服务稳定 |

约束类型示例：

| 类型 | 示例 |
| --- | --- |
| `diet` | 低脂、清真、素食、忌口、儿童餐、宠物不可进餐厅 |
| `mobility` | 少走路、轮椅友好、婴儿车友好、老人友好 |
| `atmosphere` | 约会、安静、热闹、适合聊天、适合拍照 |
| `activity` | 亲子、宠物友好、团建、闺蜜逛街、展览、citywalk |
| `transport` | 不开车、少换乘、可停车、可打车、宠物可乘坐 |
| `budget` | 人均上限、公司报销、轻奢、低成本 |
| `time` | 午睡时间、遛宠时间、老人休息时间、孩子作息 |
| `safety` | 儿童安全、宠物牵引、夜间安全、少过马路 |

典型非样例输入：

```text
和闺蜜下午逛逛，想拍照喝下午茶，不想太吵。
```

应解析为：`bestie`、拍照友好、下午茶、安静、适合聊天。

```text
周末和恋人约会，想有点仪式感，别太贵。
```

应解析为：`partner`、约会氛围、品质感、预算上限、低打扰环境。

```text
下午带狗出去玩，顺便找个能带宠物的地方吃饭。
```

应解析为：`pet`、宠物友好、可携宠入内、户外或半户外空间、交通方式可携宠。

```text
陪爸妈附近走走，别太累，晚饭清淡一点。
```

应解析为：`elder`、少走路、座位充足、安静、清淡饮食、无障碍优先。

```text
和同事做个小团建，预算人均 150，最好交通都方便。
```

应解析为：`colleague`、团建、多人容量、人均预算、公共交通便利、公平到达成本。

### 5.4 Context Builder

负责生成规划所需上下文：

- 出发地：优先使用用户授权定位，其次使用手动输入地址，缺失时追问。
- 经纬度：真实模式下必须将地址解析为 `lat/lng`，并保留原始地址文本。
- 时间：若只说“下午”，默认按 14:00-18:00 处理。
- 人数：由参与者画像聚合，不假设固定家庭结构。
- 餐饮偏好：从所有参与者的饮食约束中归并，例如低脂、儿童餐、宠物友好、老人清淡、情侣约会氛围。
- 距离偏好：“别离家太远”默认半径 5-8 公里。
- 交通偏好：若未指定，默认综合比较步行、驾车、公共交通和网约车，按时间、稳定性和同行者便利性排序。

### 5.5 Planning Engine

负责生成候选方案并排序。推荐采用“硬约束过滤 + 软约束评分”的方式。

硬约束：

- 活动时间必须落在下午 4-6 小时窗口内。
- 场地或餐厅必须支持总人数。
- 必须满足所有 `priority=hard` 的参与者约束，例如儿童安全、宠物可进入、老人无障碍、过敏忌口。
- 餐厅必须有位，或排队时间在可接受范围内。
- 总路程不超过用户设定的附近范围。
- 真实模式下 POI 和餐厅必须来自真实 Provider，不能使用编造店名。
- 交通方式必须可达，且路线耗时不能破坏整体时间窗口。

软约束评分：

```text
score =
  0.25 * distance_score +
  0.25 * availability_score +
  0.20 * participant_fit_score +
  0.15 * group_fit_score +
  0.10 * route_and_transport_score +
  0.05 * execution_confidence_score
```

输出方案应包含：

- 时间轴。
- 每个地点的原因。
- 交通方式和交通时间。
- 餐厅余位或排队状态。
- 待执行动作。
- 备选方案。

冲突调解策略：

- 硬约束优先于软偏好，例如宠物不可进入时直接排除地点。
- 弱势参与者优先，例如儿童、老人、行动不便者、宠物相关安全限制优先。
- 场景目标优先，例如“恋人约会”优先氛围，“同事团建”优先容纳人数和预算。
- 无法同时满足时，输出权衡说明和备选方案。

### 5.6 Tool Router

负责把 Agent 的计划步骤转化为工具调用：

```text
resolve_location
 -> geocode_origin
 -> search_activities
 -> check_activity_availability
 -> search_restaurants
 -> check_restaurant_availability
 -> calculate_route_options
 -> build_route
 -> prepare_pending_actions
```

工具调用必须记录输入、输出、状态和错误信息，便于调试和 Demo 展示。

### 5.7 Execution Manager

负责处理有副作用的动作。执行动作必须满足一个原则：用户确认前只查询和规划，用户确认后才执行预约、订座、排队、下单和通知。

执行动作示例：

- `book_activity`
- `reserve_restaurant`
- `join_queue`
- `order_gift`
- `send_notification`

### 5.8 Response Generator

负责把结构化结果转成人可读方案，要求：

- 不输出纯搜索列表。
- 明确告诉用户为什么这样安排。
- 明确说明方案如何照顾不同参与者，例如“适合宠物入内”“老人少走路”“适合情侣聊天”。
- 明确列出确认后会执行哪些动作。
- 对失败和备选方案给出清晰说明。

## 6. 数据模型

### 6.1 Plan

```json
{
  "plan_id": "plan_001",
  "title": "亲子乐园 + 市集散步 + 轻食晚餐",
  "summary": "满足主要参与者约束，距离家 6 公里以内",
  "participant_summary": [
    "孩子：活动适龄，步行少",
    "伴侣：晚餐有低脂选择",
    "朋友：路线适合多人聊天和参与"
  ],
  "schedule": [],
  "route_options": [],
  "pending_actions": [],
  "alternatives": [],
  "risk_notes": [],
  "requires_confirmation": true
}
```

### 6.2 Schedule Item

```json
{
  "start_time": "14:00",
  "end_time": "15:30",
  "type": "activity",
  "name": "城市亲子探索馆",
  "location": "星河广场 3F",
  "coordinates": {
    "lat": 39.9981,
    "lng": 116.4812
  },
  "provider": "mock",
  "provider_place_id": "mock_place_001",
  "travel_minutes": 20,
  "transport_mode": "driving",
  "reason": "适合 5 岁儿童，也能让朋友参与互动",
  "reservation_required": true
}
```

### 6.3 Route Option

```json
{
  "from": "家",
  "to": "城市亲子探索馆",
  "mode": "driving",
  "duration_minutes": 20,
  "distance_km": 4.2,
  "estimated_cost": 18,
  "comfort_score": 0.85,
  "kid_friendly_score": 0.9,
  "traffic_risk": "medium"
}
```

### 6.4 Pending Action

```json
{
  "action_id": "act_001",
  "type": "reserve_restaurant",
  "target": "绿野轻食餐厅",
  "payload": {
    "party_size": 7,
    "arrival_time": "17:10"
  },
  "status": "pending_confirmation"
}
```

## 7. 真实地理位置、门店和交通方式设计

真实服务接入必须通过 Provider Layer 完成，Agent 不直接依赖具体地图或本地生活平台。

### 7.1 位置能力

- 定位来源：浏览器定位、App 定位、用户手动输入地址、历史家庭地址。
- 地址解析：将自然语言地址转为经纬度。
- 逆地址解析：将经纬度转成人类可读地址。
- 附近范围：根据“别太远”“走路能到”“开车 20 分钟内”等表达动态生成搜索半径。

### 7.2 真实店铺能力

真实店铺和活动地点必须包含：

- `provider_place_id`
- `name`
- `address`
- `coordinates`
- `category`
- `opening_hours`
- `rating`
- `price_level`
- `tags`
- `availability`
- `booking_supported`
- `source_provider`

Agent 输出时必须优先使用真实 Provider 返回的 `name`，不能在真实模式下生成不存在的店铺名称。

### 7.3 交通方式能力

路线计算需要支持：

- 步行：适合近距离和商圈内移动。
- 驾车：适合多人同行、带儿童、带宠物或距离中等的场景，需要考虑停车。
- 公交/地铁：适合城市通勤，但需要考虑换乘和步行距离。
- 网约车：适合时间紧、儿童或老人同行、天气差或停车困难场景。
- 骑行：适合短距离成人出行，但儿童、老人或宠物同行时默认降权。

交通方式评分建议：

```text
transport_score =
  0.30 * duration_score +
  0.20 * distance_score +
  0.20 * kid_convenience_score +
  0.15 * weather_and_traffic_stability +
  0.10 * cost_score +
  0.05 * parking_or_transfer_penalty
```

### 7.4 Provider 抽象

推荐定义以下 Provider 接口：

```text
GeoProvider
 ├── geocode(address)
 ├── reverse_geocode(lat, lng)
 └── locate_user()

PoiProvider
 ├── search_activities(origin, radius, filters)
 └── get_place_detail(place_id)

MerchantProvider
 ├── search_restaurants(origin, party_size, arrival_time, filters)
 ├── check_availability(merchant_id, party_size, arrival_time)
 └── get_merchant_detail(merchant_id)

RouteProvider
 ├── calculate_route(origin, destination, mode)
 └── calculate_route_matrix(points, modes)

BookingProvider
 ├── book_activity(activity_id, payload)
 ├── reserve_restaurant(restaurant_id, payload)
 └── join_queue(restaurant_id, payload)
```

### 7.5 隐私和合规

- 获取实时定位前必须获得用户授权。
- 日志中不能记录完整精确定位，可脱敏到商圈或网格。
- 外部 Provider 的错误信息不能直接暴露给用户。
- 对真实预约、排队、下单等副作用动作，必须二次确认。

## 8. 异常处理

| 场景 | 处理策略 |
| --- | --- |
| 出发地缺失 | 追问“从哪里出发？” |
| 活动满员 | 自动切换同类型活动 |
| 餐厅无位 | 切换备选餐厅或建议提前排队 |
| 时间不足 | 减少一个活动点或缩短停留时间 |
| Mock API 失败 | 标记失败工具，返回可恢复方案 |
| 定位授权失败 | 切换为手动输入地址 |
| 地理编码失败 | 提示用户补充更具体地址 |
| 真实 Provider 超时 | 使用缓存或降级到备选 Provider |
| 交通方式不可达 | 移除该交通方式并重排方案 |
| 用户拒绝确认 | 保留方案，不执行副作用动作 |
| 部分执行失败 | 返回已完成动作、失败动作和补救方案 |

## 9. 技术方案

当前实现：

- 后端：Python 3.11+、标准库 `http.server.ThreadingHTTPServer`。
- CLI：argparse。
- Web UI：React 18、Vite、TypeScript、CSS Modules。
- 测试：unittest。
- 数据：内存 Mock 数据（默认）或 MySQL；真实 Provider 使用 Overpass + OSRM + Nominatim。

后续规划：

- 生产化接入更多真实 Provider（高德/Google/美团），引入缓存层保存 POI、路线和可用性查询结果。

## 10. 质量要求

- 每一次工具调用都要可追踪。
- Planning 结果必须稳定可复现。
- 用户确认前不能执行副作用动作。
- API 错误必须返回可读错误信息。
- 测试覆盖核心路径和异常路径。
- 真实模式下不能输出编造店铺名称。
- 交通方式必须来自路线计算结果，不能只凭文本臆测。
