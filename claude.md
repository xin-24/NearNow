# NearNow 邻刻计划 AI 辅助开发说明

本文档用于后续 Claude/Codex 等 AI 助手快速理解当前项目状态、已实现能力、已知短板和下一步开发计划。修改代码前请先阅读本文件、`README.md`、`docs/design.md`、`docs/api_contract.md`，并检查当前工作区是否有用户未提交修改。

## 当前项目定位

NearNow 是一个本地短时活动规划与执行 Agent。目标是让用户用一句自然语言表达需求，例如“今天下午想和老婆孩子、朋友出去玩几个小时，别离家太远”，系统自动完成：

- 理解时间、出发地、同行人、人数、饮食偏好和特殊约束。
- 查询附近活动、餐厅和路线。
- 生成一条包含出行、活动、饭前/饭后轻活动、餐厅的可执行时间轴。
- 输出备选方案、风险提示、交通方式比较和待确认动作。
- 用户确认后执行 Mock 预约、订座和通知。

项目不是纯搜索推荐，而是“规划 + 确认 + 执行动作”的本地生活 Agent Demo。

## 当前核心链路：一句话 + 地理位置如何生成附近规划

当前项目的核心不是“让模型编一个行程”，而是把用户的一句话目标和地理位置信息转成结构化约束，再用 Provider 在出发地附近查真实或 Mock 候选，最后通过规则评分和可选 LLM 决策生成可执行计划。

### 1. 前端收集用户目标和位置

入口在 `web/src/App.tsx` 和 `web/src/hooks/useLocation.ts`。

用户在 Web UI 输入：

- 自然语言目标：例如“今天下午是空的，想和老婆孩子、朋友出去玩几个小时，别离家太远，老婆最近在减肥，孩子 5 岁”。
- 出发位置：可手动输入“北京 朝阳区 望京 SOHO”，也可以点击定位。
- 同行通知人：例如“小张 朋友 13800000000”。

定位处理方式：

- 浏览器定位成功后，前端会把经纬度降精度到约 1km 网格，避免使用过精确坐标。
- 前端调用 `/api/location/reverse-geocode`，后端用 `AmapLocationProvider.reverse_geocode()` 把坐标反查为“城市 + 区/县 + 商圈/地标”。
- 如果用户手动输入位置，前端会拆出 city、district、landmark；真实模式下后端会用 `AmapLocationProvider.geocode()` 把手动地址转为坐标。

最终发给后端 `/api/agent/plan` 的关键字段是：

```json
{
  "message": "今天下午想和老婆孩子、朋友出去玩几个小时，别离家太远...",
  "mode": "real",
  "user_context": {
    "home_location": "北京 朝阳区 望京 SOHO",
    "city": "北京",
    "district": "朝阳区",
    "landmark": "望京 SOHO",
    "coordinates": {"lat": 39.99, "lng": 116.48},
    "location_source": "browser或manual",
    "precision": "approximate或manual_area"
  },
  "companions": []
}
```

这一步的核心产物是：一句话 `message` + 出发点文本 `home_location` + 出发点坐标 `coordinates`。

### 2. 后端把一句话解析成 PlanningIntent

入口在 `app/agent/orchestrator.py` 的 `LocalPlannerAgent.plan()`。

处理顺序：

1. `LongCatIntentParser` 先用规则解析作为 fallback，再在配置 LongCat 时尝试 LLM 增强。
2. `IntentParser` 从文本里识别时间、角色、人数、偏好和距离：
   - “下午”默认 `14:00-18:00`。
   - “老婆/妻子” -> `spouse`。
   - “孩子 5 岁” -> `child`，带 `kid_friendly`、`child_safe` 约束。
   - “朋友/4个人” -> `friend_group`，默认或解析多人数量。
   - “减肥/轻食/清淡” -> `low_calorie`、`light_food`。
   - “别太远/附近” -> 半径约 `6km`。
3. `ParticipantConstraintBuilder` 把参与者角色补成统一的硬约束和软偏好。

这一步的核心产物是 `PlanningIntent`：

```text
start_time / end_time
participants
preferences
scenario_tags
radius_km
party_size
```

例如家庭 + 朋友场景会得到：自己、配偶、孩子、朋友组，餐饮偏好包含低卡/轻食，活动偏好包含亲子安全和多人友好。

### 3. 后端把位置补成 PlanningContext

入口在 `app/agent/context_builder.py`。

`ContextBuilder.build()` 会把前端传来的位置上下文转换成规划上下文：

- `origin_name`：用于展示和路线起点，例如“北京 朝阳区 望京 SOHO”或“我的大概位置”。
- `origin_coordinates`：用于附近 POI 搜索和路线计算。
- `user_context.city/district/landmark`：用于真实 Provider 查询、handoff 链接和前端展示。
- `strategy`：由下一步策略构建器生成后一起传入规划引擎。

如果没有出发地也没有坐标，后端返回 `MISSING_ORIGIN`，让用户先补充“从哪里出发”。这保证“附近规划”一定有空间锚点。

### 4. 根据用户画像生成附近搜索策略

入口在 `app/agent/strategy.py` 和 `app/agent/persona_query.py`。

`PersonaStrategyBuilder` 根据参与者关系决定“应该找什么”：

- 孩子：亲子场馆、游乐场、公园、博物馆；餐厅要家庭友好、正餐、少排队。
- 配偶减肥：餐厅偏低卡、轻食、清淡。
- 朋友组：活动要多人参与、空间容量和社交属性；餐厅要多人桌和预算稳定。
- 宠物、老人、闺蜜、恋人、同事等也有各自策略。

`PersonaQueryPlanner` 会把策略扩展成 Provider 查询标签：

- 活动标签：`亲子`、`儿童`、`游乐场`、`公园`、`博物馆`、`kid_friendly`、`group_friendly` 等。
- 餐厅标签：`light_food`、`清淡`、`轻食`、`group_table`、`proper_meal`、`少排队` 等。
- 最小候选数量和最大扩圈半径：候选太少时最多扩到约 12km。

这一步的核心是把“用户想法”变成“附近应该搜哪些类型的活动和店”。

### 5. 用地理坐标查询附近活动和餐厅

入口在 `app/agent/planner.py` 的 `PlanningEngine.generate_plan()`。

规划引擎会调用 `_search_candidates()`，再并发调用 Provider：

- `provider.search_activities(tags, party_size, radius_km, origin_coordinates)`
- `provider.search_restaurants(tags, party_size, radius_km, origin_coordinates)`

Mock 模式：

- 使用 `MockLocalLifeProvider` 内置活动和餐厅数据。
- 当前 Mock 数据本身带 `distance_km`、capacity、table_size、wait_minutes、tags。
- Mock 查询主要按人数容量、桌位容量、距离半径过滤，适合离线演示规划和执行闭环。

真实模式：

- 使用 `AmapLocalLifeProvider`。
- 活动和餐厅都会调用高德 `/v3/place/around`，以 `origin_coordinates` 为圆心、`radius_km` 为半径查附近 POI。
- 活动 types 会根据画像查公园、景区、娱乐场所、购物中心、咖啡等。
- 餐厅 types 使用高德餐饮大类 `050000`，keywords 根据画像生成，例如“清淡”“咖啡”“露台”“西餐”“餐厅”。
- 高德返回的 POI 会被转换成 `Activity` / `Restaurant`，保留真实 name、address、coordinates、provider_place_id。

注意：当前真实餐厅的余位、排队和预约状态并不来自美团真实交易系统，而是估算字段；文案和前端应提示需要出发前或跳转后确认。

### 6. 在附近候选中做过滤、路线计算和组合评分

入口仍在 `PlanningEngine.generate_plan()`。

当前规划方式是“候选组合搜索”：

1. 对活动候选排序：
   - 是否满足硬约束，例如宠物场景必须宠物友好。
   - 是否命中策略偏好，例如亲子、儿童安全、多人友好、室内/户外等。
   - 距离越近越好，但不会只按最近排序。
2. 对餐厅候选排序：
   - 排队时间大于 40 分钟会被过滤。
   - 根据低卡/轻食、儿童友好、多人桌、安静、宠物友好等标签打分。
3. 对每个活动计算从出发点到活动点的路线：
   - Mock 模式支持步行、驾车、公交/地铁、网约车、骑行。
   - 真实高德模式当前主要返回驾车路线，这是后续需要补强的点。
4. 将活动和餐厅两两配对：
   - 首段路线分。
   - 活动画像匹配分。
   - 餐厅画像匹配分。
   - 活动到餐厅距离分。
   - 总体近距离和少折腾分。
5. 选择最高分候选；如果配置 LongCat，会让 `LongCatCandidateSelector` 在候选 JSON 中二次选择，但它只能从已有真实或 Mock 候选中选，不能编造新地点。

这一步的核心是：附近候选不是直接展示列表，而是被组合成“先去哪玩 + 再去哪吃 + 怎么过去”的可执行路径。

### 7. 生成时间轴、备选方案和待执行动作

入口在 `PlanningEngine._build_plan()`。

当前支持多活动串联，根据 `intent.start_time` 和 `intent.end_time` 的时间预算自动选择 2-3 个活动。典型 4 小时方案生成 6 段时间轴：

1. 从出发地到活动1的 travel。
2. 活动1 activity。
3. 从活动1到活动2的 travel。
4. 活动2 activity。
5. 从活动2到餐厅的 travel。
6. 餐厅 restaurant。

活动链选择算法：按画像匹配分排序候选，贪心选择 2-3 个活动，每个活动加入时检查时间预算（活动时长 + 预估移动时间 + 餐厅时间 ≤ 总预算）。餐厅选择考虑距最后活动的 proximity。

同时生成：

- `route_options`：交通方式及耗时、费用、舒适度、路线 geometry。
- `alternatives`：地点优先、距离优先等备选方案。
- `risk_notes`：候选不足、真实数据缺字段、排队、交通风险、儿童适龄性等提示。
- `pending_actions`：
  - `book_activity`
  - `reserve_restaurant`
  - `send_notification`

这一步的产物就是前端展示的完整方案，而不是搜索结果列表。

### 8. 用户确认后才执行副作用动作

入口在 `/api/agent/confirm` 和 `app/agent/executor.py`。

前端点击“一键执行”后，会把 `plan_id`、用户确认的 action ids、选择的交通方式发给后端。

执行规则：

- 用户确认前只规划，不预约、不订座、不发送通知。
- Mock 模式会真正返回模拟确认号，例如活动预约号和餐厅订座号。
- 真实模式如果是 handoff，会返回 `handoff_required` 和美团/点评跳转链接；不能说已经真实订座。
- 执行完成后生成可发给同行人的最终消息，例如“搞定了，14:00 出发，先去城市亲子探索馆，16:15 到绿野轻食融合菜。”

### 9. 当前链路的核心边界

当前项目已经实现了：

- 用户一句话 -> 结构化意图。
- 用户位置 -> 坐标和商圈。
- 坐标 + 画像标签 -> 附近活动/餐厅候选。
- 附近候选 -> 路线和组合评分。
- 最优组合 -> 时间轴、备选方案、风险提示和待执行动作。
- 用户确认 -> Mock 执行闭环或真实 handoff。

当前还没有完全实现：

- 真实美团店铺余位、排队、订座、支付和下单闭环。
- 真实高德多交通方式稳定比较。
- 将 `/api/mock/*` 文档接口逐一暴露成真实 REST 路由。

## 已实现能力

### 后端与 Agent

- `app/main.py` 提供 FastAPI 服务，包含登录、登出、当前用户、历史同行人、生成方案、确认执行、逆地理编码等接口。
- `app/agent/orchestrator.py` 实现 `LocalPlannerAgent.plan()` / `confirm()` 生命周期编排：
  - 解析自然语言目标。
  - 规范化参与者约束。
  - 构建 Planning 策略。
  - 补全用户上下文。
  - 调用规划引擎生成方案。
  - 保存 plan，并在确认后执行 pending actions。
- `app/agent/intent_parser.py` 提供确定性规则解析，可识别老婆/伴侣、孩子、朋友、闺蜜、恋人、宠物、老人、同事、客户等角色。
- `app/agent/longcat_intent_parser.py`、`strategy.py`、`candidate_selector.py`、`longcat_response_generator.py` 支持 LongCat LLM 增强；未配置或调用失败时会降级到规则逻辑。
- `app/agent/planner.py` 实现核心 Planning：
  - 按画像构造搜索标签。
  - 查询活动和餐厅候选。
  - 候选质量不足时扩大半径。
  - 活动/餐厅硬约束过滤和软约束打分。
  - 路线候选计算与交通方式评分。
  - 多活动串联：根据时间预算贪心选择 2-3 个活动，计算活动间路线，就近选择餐厅。
  - 生成主方案和两个备选权重方案。
  - 每个活动独立构造 `book_activity`，加上 `reserve_restaurant`、`send_notification` 等待执行动作。
- `app/agent/executor.py` 在用户确认后执行 pending actions，并返回执行回执。

### Provider 与工具能力

- `app/providers/mock_provider.py` 提供离线 Mock 数据和 Mock 工具：
  - 13 个活动（亲子、宠物、展览、步道、工坊、花艺、市集、咖啡、绿道、摄影、密室、茶室、科技馆）和 6 个餐厅。
  - 活动搜索（按容量和距离过滤）。
  - 餐厅搜索（按可用性、桌位和距离过滤）。
  - 多交通方式路线计算。
  - 活动预约。
  - 餐厅订座。
  - 通知发送。
- `app/providers/amap_provider.py` 接入高德 Web 服务，用于真实地理编码、逆地理编码、POI 搜索和路线。
- `app/providers/real_provider.py` 保留 OSM/OSRM 真实 Provider 兼容实现。
- `app/providers/meituan_link.py` 可生成美团、大众点评、网页多平台 handoff 链接。
- 真实模式下当前不伪造真实下单：餐厅执行以 handoff 链接为主，活动真实预约尚未接入。

### 前端与 CLI

- `web/` 是 React + Vite + TypeScript 前端，包含登录、输入、分析、方案、执行中、成功、错误等视图。
- 前端支持：
  - 出发位置输入与浏览器定位。
  - 同行人输入与历史保存。
  - 方案时间轴展示。
  - 路线地图展示。
  - 交通方式切换。
  - 备选方案切换。
  - 时间轴编辑和节点删除。
  - pending actions 展示与一键执行。
  - 执行回执展示。
- `cli/main.py` 提供命令行 Demo，默认使用 Mock Provider。

### 存储、认证、测试

- `app/auth.py` 支持本地登录/首次注册和 cookie session。
- `app/storage/repository.py` 支持内存存储和 MySQL 存储接口。
- `tests/test_agent.py` 覆盖意图解析、参与者约束、真实 Provider 转换、Amap Provider、规划排序、LongCat 降级、执行管理、认证和存储等路径。
- 当前验证命令：
  - `python3 -m unittest`：已通过 65 个测试。
  - `cd web && npm run build`：已通过生产构建。

## 比赛需求对照与差距分析

### 比赛核心要求

比赛要求构建一个本地场景短时活动规划与执行 Agent，输入一句自然语言目标，输出可执行的完整方案并自动完成关键下单/预订动作。两个核心场景：

- **家庭场景**：孩子 5 岁，老婆最近在减肥，下午 4-6 小时。
- **朋友场景**：总共 4 个人，2 男 2 女，下午 4-6 小时。

交付物：Demo（Web UI）、完整 Tool 实现代码（含 Mock API）、设计文档（≤2 页，说明 Planning 策略、工具调用链路、异常处理机制）。

评分维度：创新性、完整性、应用效果、商业价值。

### 当前状态与差距总览

| 比赛要求 | 当前状态 | 差距等级 |
|---------|---------|---------|
| 规划出下午 4-6 小时综合方案 | ✅ 2 个活动串联，约 3.6-3.9 小时 | 已修复 |
| 家庭场景：孩子 5 岁 + 老婆减肥 | ✅ 多策略合并 + kid_friendly + low_calorie | 已修复 |
| 朋友场景：4 人 2 男 2 女 | ✅ group_friendly + 2 个活动 + 多人桌餐厅 | 已修复 |
| 查餐厅有没有位置/是否需要排队 | ⚠️ Mock 有 wait_minutes | 低 |
| 吃饭前后活动安排（2-3 个活动） | ✅ 多活动串联已实现 | 已修复 |
| 确认后一键下单/预约/送蛋糕鲜花 | ✅ Mock 有 book_activity + reserve + notify | 已修复 |
| 把计划发给同行人 | ✅ send_notification 已实现 | 已修复 |
| 完整 Tool 实现代码（含 Mock API） | ✅ 完成 | 已修复 |
| 设计文档 ≤2 页 | ✅ `docs/competition_design.md` | 已修复 |
| 备选方案不包含无关场景 | ✅ mock 标签过滤已生效 | 已修复 |

### 评分维度分析

**创新性（较强）**：AI Agent 编排（意图解析→策略→搜索→评分→执行）、备选方案对比、时间轴可编辑、交通方式切换、美团/点评 handoff 跳转。从”搜索推荐”到”帮你做完”的 Agent 范式转变是核心创新点。

**完整性（接近完成）**：多活动串联、4-6 小时时长、主/备选方案、多策略合并、mock 标签过滤和 2 页内比赛设计文档均已实现。

**应用效果（较完整）**：前端 7 个视图完整流程、地图、时间轴编辑、交通切换、执行回执演示效果完整；后端已补齐 4-6 小时时长、主/备选一致性、备选去重和多活动 pending action 对齐。

**商业价值（有潜力）**：美团/点评 handoff 跳转、同行人通知、预约订座闭环已实现。

## 5 个阻塞项及修复方案

### 阻塞 1：方案时长只有 ~3 小时（题目要求 4-6 小时）✅ 已修复并补测试

**修复内容**（已完成）：

1. `app/agent/planner.py`：新增 `_select_activity_chain()` 贪心链选择、`_routes_between_chain()` 活动间路线计算、`_select_restaurant_for_chain()` 就近餐厅选择。重写 `_build_plan()` 接受 `activity_chain: list[Activity]`，循环构建时间轴。移除 90 分钟活动时长上限。`MAX_ROUTE_ACTIVITY_CANDIDATES` 从 6 提升到 8。
2. `app/providers/mock_provider.py`：新增 7 个 Mock 活动（创意市集手作体验、望湖咖啡品鉴、朝阳绿道漫步、798艺术区摄影漫步、桌游密室体验馆、悠享茶室品茗、科技互动探索馆 100 分钟）。
3. `app/agent/orchestrator.py`：`_sync_pending_action_times()` 支持多个 `book_activity` 动作。
4. `app/agent/executor.py`：`_final_itinerary_message()` 支持多活动行程消息。
5. `tests/test_agent.py`：2 处 schedule 长度断言从 `==5` 改为 `>=4`。

**新时间轴结构**：

```text
出发 → 活动1 → 移动 → 活动2 → [移动 → 活动3 →] 移动 → 餐厅
```

家庭场景示例：科技互动探索馆(100分钟) → 创意市集手作体验(70分钟) + 绿野轻食融合菜，总时长约 3.9 小时。
朋友场景示例：桌游密室体验馆(80分钟) → 创意市集手作体验(70分钟) + 合席小厨，总时长约 3.6 小时。

**2026-06-07 复查结论**：多活动串联已实现，但比赛要求的 4 小时下限曾未被硬性保证。实测 Mock 家庭+朋友场景曾输出 `14:00-17:55`，差 5 分钟到 4 小时；朋友 4 人场景曾输出 `14:00-17:35`，约 3 小时 35 分钟。

**2026-06-07 修复结果**：`app/agent/planner.py` 新增 4 小时目标时长补齐逻辑，优先自然延长用餐段，缺口过大时追加餐后周边轻逛/休息收尾段，并限制目标补齐不超过 6 小时。新增 `tests/test_agent.py::LocalPlannerAgentTest.test_competition_mock_plans_are_at_least_four_hours`，锁定两个比赛输入的 schedule 首尾跨度 `>= 240` 且 `<= 360` 分钟。修复后两个 Mock 主场景均输出 `14:00-18:00`。

### 阻塞 2：多人策略只生效一个（家庭+朋友场景）✅ 已修复

**修复内容**（已完成）：

1. `app/agent/strategy.py`：将 `if/elif` 链改为全 `if` 语句，多个参与者关系的策略标签全部合并。
2. `app/agent/persona_query.py`：`min_activities/min_restaurants` 改为 `max()` 合并，取各策略中的最大值。

家庭+朋友场景验证：策略包含 `kid_friendly`（亲子）+ `group_friendly`（朋友）+ `group_table`（多人桌），reasoning 同时包含两条策略原因。

### 阻塞 3：mock 标签过滤未生效 ✅ 已修复

**修复内容**（已完成）：

`app/providers/mock_provider.py`：`search_activities()` 和 `search_restaurants()` 现在按 tags 过滤候选。当 tags 非空时，只返回至少有一个标签匹配的候选；如果无匹配则回退到全量候选。

验证：纯 kid 场景只返回 kid_friendly 活动，纯 pet 场景只返回 pet_friendly 活动，low_calorie 场景只返回低卡/轻食餐厅。

### 阻塞 4：比赛设计文档 ≤2 页 ✅ 已修复

**根因**：`docs/competition_design.md` 未创建。现有 `docs/design.md` 有 528 行，远超 2 页限制。

**修复内容**（已完成）：新增 `docs/competition_design.md`，覆盖 Demo 目标与边界、Planning 策略、工具调用链路、异常处理机制、Mock 与真实模式边界；内容基于当前已实现能力，不写未落地的真实交易能力。

### 阻塞 5：备选方案可能与主方案重复 ✅ 已修复

**根因**：`app/agent/planner.py` 第 368 行 `_best_weighted_candidate` 在所有候选耗尽时无条件返回 `ranked[0]`，即使它已在 `used_pairs` 中。

**修复内容**（已完成）：

1. `_best_weighted_candidate()` 不再在所有候选已使用时回退 `ranked[0]`，候选耗尽时返回 `None`。
2. 备选方案生成时记录已使用的活动+餐厅组合，避免与主方案或其他备选重复。
3. 备选 plan 不再只包含单活动，而是以备选候选为锚点复用 `_select_activity_chain()` 扩展多活动链，并继续生成独立 `plan_id`、时间轴、预约动作和餐厅动作。
4. 新增回归测试锁定候选耗尽不重复、备选方案组合不重复、备选时间轴包含多活动且稳定覆盖 4-6 小时。

## 2026-06-07 新增审查结论与需求

本轮复查命令：

- `python3 -m unittest`：通过 65 个测试。
- `cd web && npm run build`：通过生产构建。
- 本轮 P1 修复涉及：`app/agent/planner.py`、`tests/test_agent.py`、`web/src/utils/route.ts`、`web/src/views/ProposalView.tsx`、`claude.md`。

新增必须修复项：

1. **比赛主方案时长仍不稳（P0，已修复）**
   - 现象：家庭+朋友场景 `14:00-17:55`；朋友 4 人场景 `14:00-17:35`。
   - 要求：主方案 schedule 第一个节点 `start_time` 到最后一个节点 `end_time` 必须稳定 `>= 4 小时`，且不超过题目 6 小时上限。
   - 建议：调整 `PlanningEngine._target_activity_count()`、`_select_activity_chain()`、餐厅用餐时长或增加餐后轻活动/缓冲段；新增端到端测试锁定 `>= 240 分钟`。

2. **多活动 pending action 时间错误（P0，已修复）**
   - 现象：实测家庭+朋友场景第二个活动 `创意市集手作体验` 的日程开始是 `15:50`，但 `book_activity` payload 中 `start_time` 是 `15:35`。
   - 根因：`app/agent/planner.py` 中 `_build_plan()` 生成多个活动预约时用 `act_arrive = add_minutes(act_arrive, min(activity.duration_minutes, 90))` 推算，没有使用真实 schedule，也没有计入活动间 travel。
   - 要求：每个 `book_activity` 的 `start_time` 必须和对应 activity schedule item 的 `start_time` 一致。`app/agent/orchestrator.py`、前端 `web/src/utils/route.ts` 的同步逻辑也要支持多个活动。
   - 修复：`app/agent/planner.py` 初次生成时记录每个活动真实 schedule start_time 并写入对应 `book_activity`；`app/agent/orchestrator.py` 后端确认切换交通时按 action target 对齐 activity schedule；`web/src/utils/route.ts` 前端本地切换路线时逐个同步多个活动预约时间；`web/src/views/ProposalView.tsx` 删除单个活动时只移除对应预约动作。新增测试覆盖比赛主场景初次生成和确认切换交通后的预约时间对齐。

3. **朋友场景“总共 4 个人”被算成 5 人（P0，已修复）**
   - 现象：输入“今天下午和朋友出去玩，总共4个人，2男2女，安排4-6小时”时，pending action 的 `party_size` 为 5。
   - 根因：`IntentParser._parse_group_count()` 将“4个人”解析为朋友组人数，再加上 `self=1`。
   - 要求：识别“总共/一共/总人数/总共4个人”等表达时，`party_size` 应为 4；纯“和4个朋友”才应表示朋友 4 人 + 自己 1 人。需要补朋友主场景测试。
   - 修复：`app/agent/intent_parser.py` 新增总人数识别，支持 `总共/一共/总人数/总计/共 N 人` 和 `2男2女`，按已解析固定参与者扣减朋友/同事组人数；保留“和 4 个朋友”表示朋友 4 人 + 自己 1 人。新增 parser 单测和比赛主场景端到端 party_size 断言。实测朋友场景 pending actions 均为 `party_size=4`。

4. **主方案选择与候选选择器不一致（P1，已修复）**
   - 现象：`selected_candidate` 可以由 LongCat 或候选评分选出，但主方案随后又用 `_select_activity_chain()` 独立重选活动和餐厅，导致 `selection_reasoning`、备选方案和最终主方案来源不完全一致。
   - 要求：主方案应以 `selected_candidate` 为锚点扩展活动链，或在多活动链维度构造候选并统一评分/选择，避免解释和结果脱节。
   - 修复：`app/agent/planner.py` 现在先确定评分/LongCat 选出的 `selected_candidate`，再以该候选的 activity 作为活动链锚点、以该候选的 restaurant 作为主餐厅扩展时间轴；补活动时同时考虑活动间距离和到选中餐厅的距离。新增测试构造“规则评分第一”和“选择器指定 option_2”不一致的场景，断言主方案使用选择器指定活动和餐厅。

5. **备选方案仍需去重并支持多活动（P1，已修复）**
   - 现象：`_best_weighted_candidate()` 在所有候选耗尽时仍可能回退 `ranked[0]`；备选 plan 当前只用单活动链，与主方案多活动体验不一致。
   - 要求：备选方案不得与主方案活动+餐厅组合重复；如主方案是多活动，备选也应尽量给出完整 4 小时方案，或明确说明是轻量备选。
   - 修复：`_best_weighted_candidate()` 候选耗尽时返回 `None`；`_weighted_alternatives()` 持续维护已用组合；`_alternative_payload()` 以备选候选为锚点从完整候选池重建多活动链，生成独立可确认的 4-6 小时备选 plan。新增测试覆盖去重、多活动和时长。

6. **前端多活动编辑同步不足（P1，已修复）**
   - 现象：`web/src/utils/route.ts` 的 `syncPendingActionTimes()` 只同步第一个活动；`ProposalView.tsx` 删除任一 activity 时会删除所有 `book_activity` 动作。
   - 要求：按 schedule 中 activity 顺序或 `target/provider_place_id` 精确同步和删除对应 action，避免多活动方案确认后执行错误。
   - 修复：`web/src/utils/route.ts` 新增统一的 action 与 schedule 匹配逻辑，优先按 `provider_place_id/activity_id/restaurant_id`，其次按 `target`，最后按时间轴顺序兜底；同步时跳过餐后缓冲活动。`web/src/views/ProposalView.tsx` 在切换备选、切换交通、手动改时间、删除节点后都会同步 pending action；删除活动或餐厅时只移除对应的单个预约/订座 action。`preparePlanForRouteEditing()` 也移出渲染期，改为初始化可编辑 plan 时执行。验证：`cd web && npm run build` 通过。

7. **设计文档仍是比赛硬缺口（P0，已修复）**
   - 原现状：缺少比赛交付版短设计文档。
   - 要求：新增 2 页内比赛设计文档，必须覆盖 Planning 策略、工具调用链路、异常处理机制和真实/Mock 边界；内容以当前实现为准，不写未落地能力。
   - 修复：已新增 `docs/competition_design.md`，并在 README 文档入口中补充链接。

## 全面审查发现的其他问题

### 后端 Bug

| 文件 | 行号 | 问题 | 优先级 |
|------|------|------|--------|
| `context_builder.py` | 39-41 | 坐标缺失时静默使用北京默认坐标，上海用户会得到北京结果 | P0 |
| `orchestrator.py` | 25-38 | PlanStore 内存泄漏，无 TTL/淘汰机制 | P1 |
| `orchestrator.py` | 56-57 | `self.planner` 和 `self.executor` 是死代码，每次调用都新建实例 | P2 |
| `planner.py` | 368 | 备选方案可能重复（已修复，详见阻塞 5） | 已修复 |
| `planner.py` | 228-246 | `_merge_activities` 和 `_merge_restaurants` 代码重复 | P2 |
| `planner.py` | 380 | proximity 分数使用魔数 18 | P2 |
| `location_provider.py` | 91 | OSM 逆地理编码截断坐标到 2 位小数，精度丢失约 1km | P1 |
| `amap_provider.py` | 398-403 | HTTP 429 限流重试从未触发（except 直接 raise） | P1 |
| `intent_parser.py` | 116-128 | “和同事见客户” 只命中 client，丢失 colleague | P2 |
| `intent_parser.py` | 46-53 | “和朋友约会” 同时触发 partner 和 friend_group，无去重 | P2 |
| `executor.py` | 32 | `except Exception` 捕获范围过大，吞掉 KeyboardInterrupt | P2 |
| `main.py` | 284-302 | `persist_plan` 无事务，部分写入导致数据不一致 | P2 |

### 安全问题

| 文件 | 行号 | 问题 | 优先级 |
|------|------|------|--------|
| `auth.py` | 21-46 | 登录无暴力破解保护 | P1 |
| `repository.py` | 463-472 | MySQL 每次查询新建连接，无连接池 | P1 |
| `repository.py` | 458 | `autocommit=True` 导致多条 INSERT 无事务 | P2 |
| `auth.py` | 23-25 | 密码无上限长度校验 | P2 |
| `.env.local` | — | 含 API key 的文件被 git 跟踪 | P1 |

### 前端 Bug

| 文件 | 行号 | 问题 | 优先级 |
|------|------|------|--------|
| `App.tsx` | 27 | 冗余三元 `loading ? “login” : “login”` 永远返回 “login” | P1 |
| `route.ts` + `ProposalView.tsx` | 55-63, 32 | `preparePlanForRouteEditing` 渲染期间直接修改 React state | P1 |
| `client.ts` | 22 | 非 OK 响应未检查就 parse JSON，HTML 响应抛 SyntaxError | P1 |
| `App.tsx` | 36-44 | `loadCompanions` 失败显示为”登录失败” | P2 |
| `ExecutingView.tsx` | 18 | 空 actions 导致 `activeStep = -1` | P2 |
| `useLocation.ts` | 84 | 闭包中 `city` 可能过期（stale closure） | P2 |
| `RouteMap.tsx` | 67-71 | 三个字符串 key 每次渲染重新拼接，缺 useMemo | P2 |
| `ProposalView.tsx` | 223 | “一键执行” 无确认弹窗 | P2 |

### 测试覆盖缺口

| 缺失的测试 | 说明 |
|-----------|------|
| `app/main.py` 全部 HTTP 路由 | 零测试覆盖 |
| 家庭场景端到端 | 无 party_size=7、low_calorie、kid_friendly 断言 |
| 朋友场景端到端 | 无 party_size=4、group_friendly 断言 |
| 方案时长 ≥ 4 小时 | 无测试验证（当前约 3.6-3.8 小时） |
| `persona_query.py` | 无单元测试 |
| `app/utils/` 全部模块 | 无测试 |
| `MySQLAppRepository` | 零测试 |

### 文档不一致

| 文档 | 问题 |
|------|------|
| `docs/api_contract.md` | 第 3 节 `/api/mock/*` 路由在代码中不存在 |
| `docs/design.md` | 评分公式与实际 `planner.py` 实现不符 |
| `docs/architecture.md` | 评分公式与实际不符（权重全 1.0 而非 0.3/0.3/0.2/0.1/0.1） |
| `docs/design.md` | 声称 CLI 使用 `argparse`，实际是 `sys.argv` |
| `docs/architecture.md` | 声称 “60+ 测试”，实际约 40 个 |
| `docs/development_guide.md` | utils 目录缺少 `geo.py` 和 `text.py` |

## 比赛修复计划（按优先级排序）

### 第一步：修复 strategy.py 多策略合并（阻塞 2）✅ 已完成

已完成。详见阻塞 2 修复内容。

### 第二步：修改 planner.py 支持多活动串联（阻塞 1）✅ 已完成

已完成。详见阻塞 1 修复内容。

### 第三步：补充 mock 数据 + 标签过滤（阻塞 3）✅ 已完成

已完成。详见阻塞 3 修复内容。Mock 数据已增加 7 个新活动（亲子、朋友、老年人等场景），标签过滤已生效。

### 第四步：修复备选方案去重（阻塞 5）✅ 已完成

已完成。详见阻塞 5 修复内容。

### 第五步：创建比赛设计文档（阻塞 4）✅ 已完成

已完成。详见阻塞 4 修复内容。

### 第六步：补主场景测试

在 `tests/test_agent.py` 中新增：
- 家庭场景测试：断言 party_size=7（自己+老婆+孩子+4 朋友）、餐厅包含 low_calorie/light_food、活动包含 kid_friendly、总时长 ≥ 4 小时。
- 朋友场景测试：断言 party_size=4、活动包含 group_friendly、餐厅 table_size ≥ 4。
- 备选方案测试：断言备选方案不包含无关场景标签（如宠物公园）。
- 时长测试：断言生成的方案时间跨度 ≥ 4 小时。

### 第七步：修复其他 P1 问题

- `context_builder.py`：坐标缺失时返回 MISSING_ORIGIN 而非默认北京坐标。
- `location_provider.py`：OSM 逆地理编码精度从 2 位小数改为 6 位。
- `App.tsx`：修复冗余三元表达式。
- `route.ts`：`preparePlanForRouteEditing` 移入 useEffect。
- `client.ts`：添加 response.ok 检查。

### 第八步：更新文档

- 修正 `docs/api_contract.md` 中不存在的 `/api/mock/*` 路由描述。
- 修正 `docs/design.md` 和 `docs/architecture.md` 中不一致的评分公式。
- 更新 `docs/demo_script.md`：家庭场景完整演示、朋友场景完整演示。
- 更新 `README.md`：添加 Mock 离线演示命令和推荐输入。

## 开发注意事项

- 不要覆盖用户未提交改动。当前如果看到 `git status --short` 中已有修改，先阅读 diff，再决定如何叠加。
- 手工编辑文件优先使用 `apply_patch`。
- 搜索文件优先使用 `rg` 或 `rg --files`。
- 后端测试使用 `python3 -m unittest`。当前环境可能没有 `python` 命令，优先用 `python3`。
- 前端构建使用 `cd web && npm run build`。
- 真实模式依赖 `LONGCAT_API_KEY`、`AMAP_WEB_SERVICE_KEY`、`VITE_AMAP_JS_API_KEY` 等环境变量；未配置时应能在 Mock 或规则降级路径下演示。
- 不要在真实模式输出编造商家名、虚假余位、虚假订座成功。
- 用户确认前不能执行任何有副作用动作。
- 对真实支付、下单、短信、定位等能力，需要明确合规边界和二次确认。
- 本次修改聚焦比赛 Demo 主链路，不追求生产级质量。P2 及以下问题可在比赛后处理。
