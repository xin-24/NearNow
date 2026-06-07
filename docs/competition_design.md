# NearNow 比赛设计文档

## 1. Demo 目标与边界

NearNow 是一个本地短时活动规划与执行 Agent。用户只输入一句自然语言目标和出发位置，系统生成 4-6 小时可执行方案，并在用户确认后完成 Mock 预约、订座和通知。

比赛重点场景：

- 家庭场景：老婆最近在减肥、孩子 5 岁、下午附近玩 4-6 小时。
- 朋友场景：总共 4 人、2 男 2 女、下午附近玩 4-6 小时。

当前 Demo 已实现完整闭环：意图解析、画像策略、附近候选搜索、多活动时间轴、备选方案、交通切换、待确认动作和 Mock 执行。真实模式接入高德地理编码、POI 和路线；真实订座/交易能力通过美团/点评 handoff 链接表达，不伪造真实下单成功。

## 2. Planning 策略

Planning 不依赖模型直接编行程，而是把一句话转成结构化约束，再从 Provider 候选中组合可执行方案。

1. 意图解析：`IntentParser` / `LongCatIntentParser` 识别时间窗口、半径、参与者、人数、饮食偏好和特殊约束。例如“孩子 5 岁”转成 `kid_friendly`，“减肥/清淡”转成 `low_calorie/light_food`，“总共 4 个人”按总人数解析。
2. 画像策略：`ParticipantConstraintBuilder` 和 `PersonaStrategyBuilder` 合并多个角色需求。家庭+朋友会同时保留亲子安全、多人互动、多人桌和轻食餐厅约束。
3. 候选搜索：`PersonaQueryPlanner` 将画像扩展成活动/餐厅 tags，并在候选不足时扩大搜索半径。Mock Provider 按 tags、容量、桌位、距离过滤；真实 Provider 按坐标调用高德附近 POI。
4. 组合评分：`PlanningEngine` 对活动、餐厅、首段路线、活动-餐厅距离和整体 proximity 打分。配置 LongCat 时，LLM 只能在已有候选中选择，不能编造地点。
5. 时间轴生成：主方案以选中候选为锚点扩展 2-3 个活动，再接餐厅和餐后轻活动/缓冲，保证首节点到末节点稳定覆盖至少 240 分钟且不超过 360 分钟。
6. 备选方案：按“地点优先”“距离优先”重新加权，避免复用主方案活动+餐厅组合，并同样生成多活动、可确认的完整 plan。

## 3. 工具调用链路

一次 `/api/agent/plan` 的核心链路如下：

```text
用户目标 + 出发位置
  -> parse_intent
  -> build_participant_constraints
  -> build_persona_strategy
  -> build_context(resolve_location / coordinates)
  -> search_activities(tags, party_size, radius)
  -> search_restaurants(tags, party_size, radius)
  -> calculate_routes(origin -> activities, activity -> activity, activity -> restaurant)
  -> build_plan(schedule, alternatives, route_options, pending_actions)
```

用户点击“一键执行”后才进入 `/api/agent/confirm`：

```text
confirmed_action_ids
  -> book_activity
  -> reserve_restaurant 或 handoff link
  -> send_notification
  -> execution_receipt + final_message
```

待执行动作在确认前只展示为 `pending_confirmation`，不产生副作用。交通切换或前端编辑时间轴后，会同步对应活动预约时间和餐厅到店时间，避免多活动方案执行错位。

## 4. 异常处理机制

- 缺少出发地：`ContextBuilder` 返回 `MISSING_ORIGIN`，前端引导用户补充位置。
- 候选不足：候选质量门禁触发扩大半径；仍不足时返回可恢复失败方案和风险提示。
- 活动或餐厅不满足硬约束：容量不足、桌位不足、排队超过阈值或宠物场景不友好时过滤；真实 POI 标签不足时作为强偏好处理并给出提醒。
- 路线失败：单段路线失败时使用距离估算兜底；全部路线失败时返回 Provider 错误。
- LLM 失败：未配置或调用失败时降级到规则解析、规则策略和规则摘要；如果用户明确要求真实 LongCat 能力，则返回可恢复错误。
- 真实交易边界：真实模式不声明已完成真实订座/支付，只返回美团/点评跳转链接和“需出发前确认”的说明。

## 5. Mock 与真实边界

Mock 模式用于比赛演示和离线测试，内置活动、餐厅、路线、预约、订座和通知，可完整展示 Agent 执行闭环。

真实模式当前使用高德地理编码、逆地理编码、附近 POI 和路线能力，地点名称来自真实 Provider；餐厅余位、排队和真实交易尚未接入美团交易系统，因此通过 handoff 链接完成后续确认。生产化需要继续接入真实店铺库存、排队、订座、支付、短信/IM 通知和合规授权。

