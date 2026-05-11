# AI Agent 竞品与能力借鉴

调研时间：2026-05-11

本文档用于总结当前与“本地短时活动规划与执行 Agent”相关的 AI Agent 产品，并提炼可复用到本项目的能力。重点不是复制竞品功能，而是抽象出适合本项目的产品机制、技术架构和用户体验策略。

## 1. 结论摘要

本项目最值得借鉴的方向有 8 个：

1. 从“回答问题”升级为“完成任务”：用户确认后自动订座、预约、排队、通知。
2. 真实数据接地：地点、店铺、路线、余位必须来自 Provider，不能由模型编造。
3. 多工具协同：地图、POI、餐厅、路线、预约、通知应由 Tool Router 统一编排。
4. 用户始终可控：所有有副作用动作都要先展示计划并等待确认。
5. 参与者画像融合：支持闺蜜、恋人、孩子、朋友、宠物、老人、同事等不同同行关系和约束。
6. 交通方式参与规划：步行、驾车、公交/地铁、网约车不能只是展示字段，而要进入评分。
7. 计划可编辑和可解释：允许用户换餐厅、缩短活动、改交通方式，并解释为什么推荐。
8. 异常可恢复：餐厅无位、活动满员、路线拥堵、定位失败时自动给替代方案。

## 2. 相关产品与可借鉴能力

| 产品 | 相关能力 | 可借鉴点 |
| --- | --- | --- |
| ChatGPT agent / Operator | 浏览器操作、跨工具执行、用户确认 | 用“计划-确认-执行”闭环，敏感动作前必须二次确认 |
| Google Maps + Gemini | 真实 POI、对话式本地发现、路线权衡 | 地点推荐必须接真实地图数据，并把路线、停车、交通方式纳入决策 |
| Yelp Assistant | 本地推荐、餐厅预订、服务预约、评论依据 | 推荐要给出依据，最好能展示“为什么适合这群人” |
| Expedia Romie | 群聊规划、行程构建、突发情况替代方案 | 支持朋友群体、多角色偏好和动态重排 |
| Booking.com AI Trip Planner | 结构化库存 + 非结构化评论理解 | 结合真实可用性、价格、评论、标签做推荐，不只靠文本生成 |
| Perplexity + OpenTable | AI 搜索中直接展示可订时间并预订 | 餐厅推荐必须绑定实时余位和一键订座动作 |
| 美团“小美” | 本地生活交易闭环、内部接口调用、周期代办 | 从“推荐”走向“代办”，支持下单、订座、排队、重复任务 |
| 高德 AI 导航智能体 | 路况感知、路线预判、Planner-Executor | 把交通作为独立智能子模块，能实时调整路线 |
| Zest Maps | 个性化餐饮发现、消费行为和朋友信号 | 引入历史偏好、真实消费、朋友偏好作为个性化信号 |

## 3. 重点产品分析

### 3.1 ChatGPT agent / Operator

OpenAI 的 ChatGPT agent 将 Operator 的网页操作能力、Deep Research 的研究能力和 ChatGPT 的对话能力合并到一个可执行 Agent 中。它能使用视觉浏览器、代码执行、连接器和终端完成复杂任务，并在关键动作前请求用户确认。

可借鉴能力：

- 任务生命周期：`理解目标 -> 研究/查询 -> 生成计划 -> 请求确认 -> 执行动作 -> 汇报结果`。
- 控制权设计：用户可以中断、接管、停止任务，Agent 遇到不确定信息会主动追问。
- 安全机制：登录、支付、提交订单、预约等动作必须让用户确认。

对本项目的启发：

- `ExecutionManager` 必须只在用户确认后执行预约、订座、排队和通知。
- 每个动作需要有 `pending_confirmation`、`executing`、`success`、`failed` 状态。
- Web UI 应支持“修改方案”和“仅执行部分动作”。

参考来源：

- OpenAI ChatGPT agent：https://openai.com/index/introducing-chatgpt-agent/
- OpenAI Help Center：https://help.openai.com/en/articles/11752874-chatgpt-agent
- OpenAI Operator：https://openai.com/index/introducing-operator/

### 3.2 Google Maps + Gemini

Google Maps 正在把地图从搜索框升级为对话式本地发现工具。Ask Maps 支持用户提出复杂的真实世界问题并返回个性化地点推荐；Gemini 导航能力强调路线权衡、自然语音、地标导航、实时路况和停车帮助。

可借鉴能力：

- 地点推荐必须依赖真实 POI、评论、图片、营业信息和位置数据。
- 用户可以用非常自然的约束表达需求，例如“孩子能玩、朋友不无聊、宠物能进、老人少走路、适合约会”。
- 路线结果不仅包含耗时，还包含停车、拥堵、收费、备选路线等决策信息。

对本项目的启发：

- 真实模式下必须接入 `GeoProvider`、`PoiProvider`、`RouteProvider`。
- `PlanningEngine` 的评分要加入 `route_and_transport_score`。
- 输出方案时要解释交通方式选择，例如“带宠物，驾车比地铁更可控”“老人同行，网约车比地铁少步行 12 分钟”。

参考来源：

- Google Maps Ask Maps：https://blog.google/products-and-platforms/products/maps/ask-maps-immersive-navigation/
- Google Maps Gemini navigation：https://blog.google/products/maps/gemini-navigation-features-landmark-lens/
- Google Maps Gemini local discovery：https://blog.google/products-and-platforms/products/maps/gemini-google-maps-navigation-updates/

### 3.3 Yelp Assistant

Yelp 在 2026 年发布的新 Yelp Assistant 将本地发现从“搜索列表”推进到“答案和行动”。它支持跨品类推荐、餐厅预订、外卖、服务预约，并强调基于真实评论给出透明推荐。

可借鉴能力：

- 推荐不是单个结果，而是对用户目标的回答。
- 推荐需要有证据，例如评论摘要、标签、适配原因。
- 用户可以在一个对话中完成查询、比较、预订、下单。

对本项目的启发：

- Response Generator 不能只输出地点列表，应输出“为什么这条路线适合你们”。
- 餐厅卡片需要展示可解释字段：适合同行关系、饮食约束、可容纳人数、距离近、有余位。
- 可加入 `evidence` 字段，记录推荐依据来源。

参考来源：

- Yelp 2026 Spring Release：https://www.yelp-press.com/press-releases/press-release-details/2026/Yelp-Launches-the-New-Yelp-Assistant-Transforming-Local-Discovery-from-Search-to-Answers-and-Actions/default.aspx

### 3.4 Expedia Romie

Expedia 的 Romie 定位为旅行伙伴、礼宾和个人助理。它支持加入群聊理解多人偏好，构建行程，从邮件中提取旅行信息，并在天气或行程变化时给出替代方案。

可借鉴能力：

- 多人协同：从群聊或多人需求中提炼共识。
- 偏好记忆：记录用户喜欢的餐厅、活动和酒店类型。
- 动态服务：天气、延误、地点关闭时主动调整计划。

对本项目的启发：

- 不要把角色写死为家庭和朋友场景，应抽象为通用 `ParticipantProfile`，支持闺蜜、恋人、孩子、宠物、老人、同事、客户等角色。
- 可支持“发送给小张后等待小张反馈”，再重排方案。
- 加入 `PlanRevision` 模型，允许活动、餐厅、交通方式被替换。

参考来源：

- Expedia Romie：https://www.expedia.com/newsroom/spring-product-release-2024/

### 3.5 Booking.com AI Trip Planner

Booking.com 的 AI Trip Planner 将自然语言理解和平台内结构化数据结合起来，例如房源价格、可用性、取消政策、评论和图片。其 Smart Filters 可以理解“日落景观”“健身房好”等自然语言过滤条件。

可借鉴能力：

- 结构化数据和非结构化数据混合检索。
- 将自然语言偏好映射为可执行过滤器。
- 对具体问题进行 Q&A，而不是让用户读完整详情页。

对本项目的启发：

- 将“低脂饮食”“孩子 5 岁”“朋友 4 人”“宠物可入内”“老人少走路”“恋人约会氛围”转为餐厅、活动和路线过滤条件。
- 需要标准化标签系统，例如 `kid_friendly`、`light_food`、`group_table`、`low_walking`。
- 真实 Provider 返回的数据要被归一化到统一 Domain Model。

参考来源：

- Booking.com + OpenAI：https://openai.com/index/booking-com/

### 3.6 Perplexity + OpenTable

OpenTable 与 Perplexity 的合作让用户在 AI 搜索中直接看到餐厅推荐和可预订时间，并通过 Reserve 按钮完成订座。这说明餐厅推荐的关键不是“看起来合适”，而是“此刻可执行”。

可借鉴能力：

- 餐厅搜索和实时余位绑定。
- 推荐结果直接连接预订动作。
- AI 推荐应服务于商家转化，而不是停留在内容展示。

对本项目的启发：

- 餐厅候选必须经过 `check_availability`。
- `PendingAction` 必须能携带具体时间、人数、餐厅 ID 和联系人。
- 如果没有实时余位，方案评分应下降，并提示“需到店确认”。

参考来源：

- OpenTable + Perplexity：https://www.opentable.com/restaurant-solutions/resources/perplexity/

### 3.7 美团“小美”

美团“小美”是本地生活 AI Agent 方向里与本项目最贴近的案例。根据公开报道，它通过自然语言交互和内部接口调用，实现外卖下单、餐厅推荐等本地生活服务，并强调从需求到交易的全链路。

可借鉴能力：

- 本地生活交易闭环：推荐、下单、订座、导航等动作串起来。
- 使用真实交易、真实评价和用户偏好做个性化。
- 支持周期性代办，例如早餐、咖啡固定订购。
- 独立 Agent 产品形态，不只是主 App 的搜索增强。

对本项目的启发：

- 本项目定位应坚持“帮你把事情做完”，而不是“给你推荐几个地方”。
- 需要把预约、排队、通知、下单做成一等公民。
- 后续可加入周期性任务，例如“每周六下午帮我安排亲子活动”。

参考来源：

- 科技日报报道：https://www.stdaily.com/web/gdxw/2025-09/12/content_399908.html
- 每经网报道：https://www.nbd.com.cn/articles/2025-09-12/4058414.html

### 3.8 高德 AI 导航智能体

高德推出的 AI 导航智能体强调“思考、预判、行动”的全链路智能，并采用 Planner-Executor 模式。它把导航从固定路线执行升级为实时感知路况、预判风险、主动调整策略的智能伙伴。

可借鉴能力：

- Planner-Executor：先规划，再根据实时状态执行和调整。
- 交通感知：路况、拥堵、停车、换乘等要影响方案。
- 表达层：路线提醒要自然、有温度，而不是机械播报。

对本项目的启发：

- `RouteProvider` 不只是算距离，还要提供路线风险和交通方式比较。
- 方案执行前应检查路线是否仍然可行。
- 如果出发前出现拥堵或天气变化，应自动给出重排方案。

参考来源：

- 每经网高德 AI 导航智能体：https://www.nbd.com.cn/articles/2025-04-14/3831076.html
- 新浪财经高德 NaviAgent：https://finance.sina.com.cn/jjxw/2025-04-15/doc-inetfaka8074842.shtml

### 3.9 Zest Maps

Zest Maps 是一个较新的餐饮发现应用，强调用用户真实消费记录、朋友动态和社区信号来做个性化推荐。它的重点不是通用地图，而是更懂“我和朋友到底会去哪吃”的餐饮发现。

可借鉴能力：

- 用真实消费行为修正口味画像。
- 朋友去过、收藏、复访等社交信号能提升推荐可信度。
- 隐私控制很重要，用户应能隐藏、编辑或不接入敏感数据。

对本项目的启发：

- 后续可以加入 `UserPreferenceProfile`，记录偏好和历史选择。
- 朋友场景可以加入“朋友喜欢/不喜欢”的约束。
- 用户数据接入必须可选，并提供清晰隐私说明。

参考来源：

- Wired 对 Zest Maps 的报道：https://www.wired.com/story/zest-maps-is-the-second-coming-of-foursquare

## 4. 应用于本项目的产品策略

### 4.1 定位策略

本项目应定位为：

```text
本地生活执行型 Agent：从一句话目标到可执行安排，再到预约和通知完成。
```

不建议定位为：

```text
本地活动搜索工具
餐厅推荐工具
行程生成器
```

原因是竞品趋势已经很清晰：AI Agent 的价值不在“生成更多选项”，而在“减少决策成本并完成动作”。

### 4.2 核心体验原则

- 少问问题：只追问真正阻塞规划的信息，例如出发地。
- 先给方案：默认生成最优方案和 1-2 个备选，而不是让用户填表。
- 可解释：每个地点、餐厅和交通方式都说明理由。
- 可执行：每个推荐必须连接到预约、排队、导航或通知动作。
- 可改动：用户可以说“餐厅换清淡一点”“别开车”“少走路”。
- 可恢复：失败后自动给替代方案。

### 4.3 必须做好的差异化

| 能力 | 普通推荐系统 | 本项目应做到 |
| --- | --- | --- |
| 输入 | 关键词搜索 | 自然语言目标 |
| 输出 | 地点列表 | 时间轴方案 |
| 数据 | 店铺静态信息 | 地点、余位、路线、交通方式、偏好 |
| 决策 | 用户自己比较 | Agent 自动组合和解释 |
| 动作 | 跳转页面 | 确认后自动预约/订座/通知 |
| 异常 | 用户重搜 | Agent 自动替换和重排 |

## 5. 应用于技术设计的能力清单

### 5.1 领域模型增强

建议新增或强化：

- `UserPreferenceProfile`：用户历史偏好、饮食限制、交通偏好。
- `ParticipantProfile`：同行关系、人数、年龄段、行动能力、饮食限制、宠物信息、氛围偏好、预算和特殊需求。
- `Evidence`：推荐依据，例如评论摘要、标签、真实交易数据。
- `RouteOption`：交通方式、耗时、费用、换乘、步行、停车。
- `PlanRevision`：用户修改后的方案版本。
- `ProviderResult`：真实 Provider 的原始 ID、来源、置信度。

### 5.2 Planning 策略增强

规划评分应从“地点好不好”升级为“组合是否可执行”：

```text
plan_score =
  0.20 * intent_match_score +
  0.18 * availability_score +
  0.16 * route_and_transport_score +
  0.14 * kid_friendly_score +
  0.12 * group_fit_score +
  0.10 * dining_preference_score +
  0.06 * execution_confidence_score +
  0.04 * evidence_quality_score
```

### 5.3 工具链增强

建议 Tool Router 支持：

```text
resolve_location
 -> search_real_poi
 -> search_real_restaurants
 -> summarize_review_evidence
 -> check_availability
 -> calculate_route_matrix
 -> generate_plan_bundle
 -> ask_user_confirmation
 -> execute_bookings
 -> notify_contacts
```

### 5.4 安全策略增强

- 预约、订座、排队、下单、发消息都属于副作用动作。
- 副作用动作必须展示确认信息：对象、时间、人数、价格、取消规则。
- 真实定位必须用户授权。
- 日志不能记录完整精确经纬度。
- 真实模式下禁止输出编造店铺名称。

## 6. 建议的下一步实现优先级

1. 先实现 `Provider Layer`，让 Mock 和真实服务可以切换。
2. 实现 `RouteProvider`，让交通方式真正进入规划评分。
3. 给每个推荐加 `evidence`，让方案可信。
4. 实现 `PendingAction` 状态机，严格区分确认前和确认后。
5. 实现 `PlanRevision`，支持用户自然语言改方案。
6. 后续再做偏好记忆和周期任务。
