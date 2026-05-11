# 真实地理位置、店铺与交通方式接入设计

## 1. 目标

项目后期不能停留在 Mock Demo，需要支持真实本地生活场景：

- 获取用户真实出发位置。
- 使用真实地图 POI 和真实店铺名称。
- 查询真实地址、经纬度、营业时间、评分、人均、标签和可订状态。
- 计算真实路线耗时。
- 在步行、驾车、公交/地铁、网约车、骑行等交通方式中做选择。
- 在用户确认后执行真实或半真实预约、排队、通知动作。

核心原则：Agent 只负责理解、规划和决策；真实数据和执行能力通过 Provider Layer 接入。

## 2. 分层架构

```text
Agent Orchestrator
 │
 ▼
Tool Layer
 │
 ▼
Provider Layer
 ├── GeoProvider
 ├── PoiProvider
 ├── MerchantProvider
 ├── RouteProvider
 ├── BookingProvider
 └── NotificationProvider
 │
 ▼
External Services
 ├── 地图服务
 ├── 本地生活/商家服务
 ├── 预约/排队服务
 └── 消息通知服务
```

Provider Layer 需要支持三种模式：

| 模式 | 用途 |
| --- | --- |
| `mock` | 本地 Demo、单元测试、离线开发 |
| `real` | 接入真实服务，输出真实地点和真实店铺 |
| `hybrid` | 优先真实服务，失败时使用缓存或 Mock 降级 |

## 3. 真实定位设计

### 3.1 定位来源优先级

1. 用户授权的实时定位，经纬度可信度最高。
2. 用户手动输入的地址，需要地理编码。
3. 用户保存的家庭地址或常用地址。
4. 最近一次成功定位缓存。

### 3.2 标准位置模型

```json
{
  "label": "家",
  "address": "北京市朝阳区望京 SOHO",
  "city": "北京",
  "district": "朝阳区",
  "coordinates": {
    "lat": 39.9957,
    "lng": 116.4813
  },
  "source": "user_permission",
  "precision": "exact"
}
```

### 3.3 定位失败处理

- 用户拒绝授权：切换到手动地址输入。
- 地址过于模糊：追问区、商圈或地标。
- 地理编码失败：提示换一种更具体的地址。
- Provider 超时：使用最近一次位置缓存，但需要向用户说明。

## 4. 真实店铺和活动地点设计

### 4.1 数据来源

真实活动和餐厅数据应通过 POI 与 Merchant Provider 获取。可接入的平台类型包括：

- 地图 POI 服务：适合地点、距离、地址、营业时间。
- 本地生活服务：适合餐厅、人均、评分、团购、排队、可订状态。
- 预约平台：适合活动票、场馆预约、餐厅订座。
- 自有业务数据：适合补充商家标签和活动规则。

### 4.2 标准地点模型

```json
{
  "provider": "amap",
  "provider_place_id": "poi_001",
  "name": "真实地点名称",
  "address": "真实地点地址",
  "coordinates": {
    "lat": 39.9981,
    "lng": 116.4812
  },
  "category": "parent_child",
  "opening_hours": "10:00-21:00",
  "distance_km": 4.2,
  "rating": 4.6,
  "price_level": 2,
  "tags": [
    "亲子",
    "室内",
    "适合多人"
  ],
  "booking_supported": true,
  "availability": {
    "available": true,
    "capacity_left": 12
  }
}
```

### 4.3 真实店名约束

真实模式下必须满足：

- `name` 必须来自真实 Provider 返回结果。
- 不能由模型凭空编造店铺名。
- 如果 Provider 只返回地点不返回可订状态，需要标记为 `booking_supported=false`。
- 如果没有合适真实结果，应返回“未找到合适地点”，而不是生成虚假方案。

## 5. 交通方式选择设计

### 5.1 支持模式

| 交通方式 | 适用条件 | 风险 |
| --- | --- | --- |
| 步行 | 商圈内、距离短、天气好 | 儿童、老人或宠物同行时耗时可能更长 |
| 驾车 | 多人同行、带孩子、带宠物、距离中等 | 停车、拥堵 |
| 公交/地铁 | 城市核心区、停车困难 | 换乘、步行距离 |
| 网约车 | 时间紧、天气差、停车难 | 费用和等待时间 |
| 骑行 | 短距离成人出行 | 带儿童、老人或宠物时默认不推荐 |

### 5.2 路线模型

```json
{
  "from": "家",
  "to": "城市亲子探索馆",
  "mode": "driving",
  "duration_minutes": 20,
  "distance_km": 4.2,
  "estimated_cost": 18,
  "walking_minutes": 3,
  "transfer_count": 0,
  "parking_required": true,
  "traffic_risk": "medium",
  "kid_friendly_score": 0.9,
  "selected": true
}
```

### 5.3 交通评分

```text
transport_score =
  0.30 * duration_score +
  0.20 * distance_score +
  0.20 * kid_convenience_score +
  0.15 * stability_score +
  0.10 * cost_score +
  0.05 * low_transfer_score
```

特殊参与者场景默认规则：

- 公共交通换乘超过 1 次降权。
- 儿童、老人或宠物同行时，单段步行超过 12 分钟降权。
- 儿童、老人或宠物同行时，骑行默认不作为首选。
- 驾车若停车不可用，需要切换网约车或公共交通。
- 宠物同行时，必须确认场地、餐厅和交通方式是否允许携宠。
- 老人同行时，无障碍、座位、噪音和步行距离进入硬约束或高权重软约束。

## 6. Planning 接入方式

Planning Engine 不直接搜索地点，而是通过 Tool Router 调用 Provider：

```text
1. resolve_user_location
2. search_real_activities
3. search_real_restaurants
4. check_merchant_availability
5. calculate_route_matrix
6. score_activity_restaurant_route_bundle
7. generate_plan
8. wait_for_user_confirmation
9. execute_booking_actions
```

组合方案时，每个候选 bundle 包含：

- 活动地点。
- 餐厅。
- 活动到餐厅的路线。
- 出发地到活动地的路线。
- 总耗时。
- 总成本。
- 可预约动作。
- 风险提示。

## 7. 缓存和降级

建议缓存：

- 地址解析结果。
- POI 详情。
- 餐厅基础信息。
- 短时间路线矩阵。
- 非实时标签和评分。

不建议长期缓存：

- 餐厅余位。
- 排队时间。
- 活动剩余名额。
- 实时路况。

降级策略：

- Geo Provider 失败：要求用户输入更具体地址。
- POI Provider 失败：切换备选 Provider 或返回无法规划。
- Route Provider 失败：只展示地点候选，不执行最终规划。
- Merchant Availability 失败：标记“需到店确认”，降低方案评分。

## 8. 安全与合规

- 实时定位必须用户授权。
- 精确经纬度不写入普通业务日志。
- 真实预约、排队、下单前必须展示确认信息。
- 对外部 Provider 返回的数据进行脱敏、过滤和异常兜底。
- Provider 凭证通过环境变量或密钥管理系统配置，不进入代码仓库。

## 9. 验收标准

真实接入阶段需要满足：

- 输入真实地址后能返回真实活动地点和真实餐厅。
- 每个地点包含真实地址、经纬度和 Provider ID。
- 至少支持两种交通方式比较。
- 输出中明确选择交通方式的原因。
- 用户确认前不执行真实预约或排队。
- 真实 Provider 失败时返回可恢复错误或降级方案。
