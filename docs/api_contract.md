# API 契约文档

## 1. 通用约定

基础路径：

```text
/api
```

OpenAPI 文档：

```text
Swagger UI: /docs
OpenAPI JSON: /openapi.json
```

运行模式：

| 模式 | 说明 |
| --- | --- |
| `mock` | 使用本地 Mock Provider，适合 Demo、测试和离线开发 |
| `real` | 使用高德地图 Web 服务提供真实 Geo、POI、Route；当前真实商家预约通过跳转链接完成，不伪造真实订座 |

当前接口实现只按 `real` / `mock` 分流：`mode=mock` 使用 Mock Provider，其余值都会归一为 `real`。Web UI 发起规划时固定传 `real`。

响应统一包含：

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

错误响应：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "RESTAURANT_UNAVAILABLE",
    "message": "目标餐厅当前无可预订座位",
    "recoverable": true
  }
}
```

## 2. Agent API

### 2.0 地址反查

```http
POST /api/location/reverse-geocode
```

请求：

```json
{
  "coordinates": {
    "lat": 40.0,
    "lng": 116.48
  },
  "precision": "approximate"
}
```

响应中的 `formatted_address` 必须按「城市 + 区/县 + 商圈/地标」返回，供网页自动填入出发地输入框：

```json
{
  "success": true,
  "data": {
    "city": "北京",
    "district": "朝阳区",
    "landmark": "星河广场",
    "formatted_address": "北京 朝阳区 星河广场",
    "source": "amap_geocode",
    "precision": "approximate_area",
    "confidence": "high"
  },
  "error": null
}
```

如果真实地址反查 API 调用失败，接口返回 `REVERSE_GEOCODE_FAILED`，不使用 Mock 地址兜底。

### 2.1 生成活动方案

```http
POST /api/agent/plan
```

请求：

```json
{
  "message": "今天下午想和老婆孩子、朋友出去玩几个小时，别离家太远，帮我安排一下。",
  "mode": "real",
  "user_context": {
    "home_location": "北京 朝阳区 望京 SOHO",
    "city": "北京",
    "coordinates": {
      "lat": 39.9957,
      "lng": 116.4813
    },
    "location_permission_granted": true,
    "location_source": "browser",
    "precision": "approximate"
  },
  "companions": [
    {
      "name": "小张",
      "relation": "朋友",
      "contact_method": "phone",
      "contact_value": "13800000000"
    }
  ]
}
```

真实模式下将 `mode` 设为 `real`，并要求后端已配置 Geo、POI、Merchant 和 Route Provider。真实模式返回的地点和店铺名称必须来自 Provider，不能使用 Mock 名称或模型编造名称。

响应：

```json
{
  "success": true,
  "data": {
    "plan_id": "plan_001",
    "title": "亲子乐园 + 市集散步 + 轻食晚餐",
    "summary": "下午 2 点出发，6 点前结束，路线控制在家附近 6 公里内。",
    "schedule": [
      {
        "start_time": "14:00",
        "end_time": "14:20",
        "type": "travel",
        "name": "从家出发",
        "location": "望京 SOHO",
        "travel_minutes": 20,
        "reason": "错开晚高峰前出发"
      },
      {
        "start_time": "14:20",
        "end_time": "15:40",
        "type": "activity",
        "name": "城市亲子探索馆",
        "location": "星河广场 3F",
        "coordinates": {
          "lat": 39.9981,
          "lng": 116.4812
        },
        "provider": "mock",
        "provider_place_id": "mock_place_001",
        "travel_minutes": 0,
        "transport_mode": "walking",
        "reason": "适合 5 岁儿童，朋友也能参与互动"
      },
      {
        "start_time": "16:00",
        "end_time": "16:50",
        "type": "activity",
        "name": "周末生活市集",
        "location": "星河广场 B1",
        "travel_minutes": 5,
        "reason": "轻量活动，适合饭前散步"
      },
      {
        "start_time": "17:10",
        "end_time": "18:00",
        "type": "restaurant",
        "name": "绿野轻食融合菜",
        "location": "星河广场 5F",
        "travel_minutes": 5,
        "transport_mode": "walking",
        "reason": "有 7 人桌，适合减脂需求"
      }
    ],
    "route_options": [
      {
        "from": "望京 SOHO",
        "to": "城市亲子探索馆",
        "mode": "driving",
        "duration_minutes": 20,
        "distance_km": 4.2,
        "estimated_cost": 18,
        "comfort_score": 0.85,
        "selected": true
      },
      {
        "from": "望京 SOHO",
        "to": "城市亲子探索馆",
        "mode": "public_transit",
        "duration_minutes": 32,
        "distance_km": 5.1,
        "estimated_cost": 6,
        "comfort_score": 0.62,
        "selected": false
      }
    ],
    "pending_actions": [
      {
        "action_id": "action_001",
        "type": "book_activity",
        "target": "城市亲子探索馆",
        "status": "pending_confirmation"
      },
      {
        "action_id": "action_002",
        "type": "reserve_restaurant",
        "target": "绿野轻食融合菜",
        "status": "pending_confirmation"
      },
      {
        "action_id": "action_003",
        "type": "send_notification",
        "target": "小张",
        "status": "pending_confirmation"
      }
    ],
    "alternatives": [
      {
        "title": "亲子书店 + 烘焙体验 + 晚餐",
        "reason": "雨天更稳定，但朋友参与感略弱"
      }
    ],
    "requires_confirmation": true
  },
  "error": null
}
```

### 2.2 确认并执行方案

```http
POST /api/agent/confirm
```

请求：

```json
{
  "plan_id": "plan_001",
  "confirmed_action_ids": [
    "action_001",
    "action_002",
    "action_003"
  ],
  "selected_route_mode": "driving"
}
```

响应：

```json
{
  "success": true,
  "data": {
    "plan_id": "plan_001",
    "execution_status": "completed",
    "results": [
      {
        "action_id": "action_001",
        "type": "book_activity",
        "status": "success",
        "confirmation_no": "A20260511001"
      },
      {
        "action_id": "action_002",
        "type": "reserve_restaurant",
        "status": "success",
        "confirmation_no": "R20260511001"
      },
      {
        "action_id": "action_003",
        "type": "send_notification",
        "status": "success"
      }
    ],
    "final_message": "搞定了，下午 2 点出发，先去城市亲子探索馆，17:10 到绿野轻食融合菜用餐。计划已发给小张。"
  },
  "error": null
}
```

## 3. Mock API

Mock API 是 Demo 和测试阶段的 Provider 实现。生产化阶段应保持上层 Agent API 不变，只替换 Provider 实现。

### 3.1 查询附近活动

```http
GET /api/mock/activities
```

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| city | string | 是 | 城市 |
| origin | string | 是 | 出发地 |
| radius_km | number | 否 | 搜索半径 |
| kid_age | number | 否 | 儿童年龄 |
| party_size | number | 是 | 总人数 |
| start_time | string | 是 | 开始时间 |
| end_time | string | 是 | 结束时间 |

响应：

```json
{
  "success": true,
  "data": [
    {
      "activity_id": "activity_001",
      "name": "城市亲子探索馆",
      "category": "kid_activity",
      "location": "星河广场 3F",
      "distance_km": 4.2,
      "duration_minutes": 80,
      "kid_friendly_age_min": 3,
      "kid_friendly_age_max": 8,
      "capacity_left": 12,
      "reservation_required": true,
      "group_friendly_score": 0.8
    }
  ],
  "error": null
}
```

### 3.2 查询附近餐厅

```http
GET /api/mock/restaurants
```

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| city | string | 是 | 城市 |
| origin | string | 是 | 活动结束地点 |
| party_size | number | 是 | 用餐人数 |
| arrival_time | string | 是 | 到店时间 |
| preferences | string | 否 | 逗号分隔偏好 |

响应：

```json
{
  "success": true,
  "data": [
    {
      "restaurant_id": "restaurant_001",
      "name": "绿野轻食融合菜",
      "location": "星河广场 5F",
      "distance_km": 0.2,
      "available": true,
      "table_size": 8,
      "wait_minutes": 0,
      "tags": [
        "light_food",
        "kid_friendly",
        "group_table"
      ],
      "reservation_required": true
    }
  ],
  "error": null
}
```

### 3.3 预约活动

```http
POST /api/mock/bookings/activity
```

请求：

```json
{
  "activity_id": "activity_001",
  "party_size": 7,
  "start_time": "14:20",
  "contact_name": "小明"
}
```

响应：

```json
{
  "success": true,
  "data": {
    "booking_id": "booking_activity_001",
    "confirmation_no": "A20260511001",
    "status": "confirmed"
  },
  "error": null
}
```

### 3.4 预订餐厅

```http
POST /api/mock/bookings/restaurant
```

请求：

```json
{
  "restaurant_id": "restaurant_001",
  "party_size": 7,
  "arrival_time": "17:10",
  "contact_name": "小明"
}
```

响应：

```json
{
  "success": true,
  "data": {
    "booking_id": "booking_restaurant_001",
    "confirmation_no": "R20260511001",
    "status": "confirmed"
  },
  "error": null
}
```

### 3.5 发送通知

```http
POST /api/mock/notifications/send
```

请求：

```json
{
  "recipient": "小张",
  "channel": "mock_message",
  "content": "搞定了，下午 2 点出发，先去城市亲子探索馆，17:10 到绿野轻食融合菜。"
}
```

响应：

```json
{
  "success": true,
  "data": {
    "message_id": "message_001",
    "status": "sent"
  },
  "error": null
}
```

### 3.6 查询路线与交通方式

```http
POST /api/mock/routes/calculate
```

请求：

```json
{
  "origin": {
    "name": "望京 SOHO",
    "coordinates": {
      "lat": 39.9957,
      "lng": 116.4813
    }
  },
  "destination": {
    "name": "城市亲子探索馆",
    "coordinates": {
      "lat": 39.9981,
      "lng": 116.4812
    }
  },
  "modes": [
    "walking",
    "driving",
    "public_transit",
    "ride_hailing"
  ]
}
```

响应：

```json
{
  "success": true,
  "data": [
    {
      "mode": "driving",
      "duration_minutes": 20,
      "distance_km": 4.2,
      "estimated_cost": 18,
      "traffic_risk": "medium",
      "parking_required": true,
      "walking_minutes": 3,
      "selected": true
    },
    {
      "mode": "public_transit",
      "duration_minutes": 32,
      "distance_km": 5.1,
      "estimated_cost": 6,
      "transfer_count": 1,
      "walking_minutes": 11,
      "selected": false
    }
  ],
  "error": null
}
```

## 4. 错误码

| 错误码 | 说明 | 是否可恢复 |
| --- | --- | --- |
| `MISSING_ORIGIN` | 缺少出发地 | 是 |
| `NO_ACTIVITY_FOUND` | 未找到合适活动 | 是 |
| `ACTIVITY_FULL` | 活动满员 | 是 |
| `NO_RESTAURANT_FOUND` | 未找到合适餐厅 | 是 |
| `RESTAURANT_UNAVAILABLE` | 餐厅无位 | 是 |
| `PLAN_NOT_FOUND` | 找不到方案 | 否 |
| `ACTION_ALREADY_EXECUTED` | 动作已执行 | 否 |
| `MOCK_API_ERROR` | Mock API 调用失败 | 是 |
| `LOCATION_PERMISSION_DENIED` | 用户拒绝定位授权 | 是 |
| `GEOCODING_FAILED` | 地址解析失败 | 是 |
| `GEOCODE_FAILED` | 手动位置真实地理编码失败 | 是 |
| `REVERSE_GEOCODE_FAILED` | 真实地址反查 API 调用失败 | 是 |
| `LONGCAT_API_NOT_CONFIGURED` | LongCat API Key 未配置 | 是 |
| `LONGCAT_API_ERROR` | LongCat API 调用失败 | 是 |
| `REAL_PROVIDER_TIMEOUT` | 真实 Provider 超时 | 是 |
| `REAL_PROVIDER_ERROR` | 真实 POI、餐厅或路线 Provider 调用失败 | 是 |
| `ROUTE_NOT_FOUND` | 指定交通方式不可达 | 是 |
| `REAL_PLACE_REQUIRED` | 真实模式下缺少真实 POI 或店铺 | 否 |

## 5. 真实 Provider 内部契约

真实 Provider 不直接暴露给前端，由 Agent 后端内部调用。所有真实 Provider 必须返回标准化结果。

### 5.1 Geo Provider

```text
geocode(address: string, city?: string) -> GeoPoint
reverse_geocode(lat: number, lng: number) -> Address
```

标准结果：

```json
{
  "formatted_address": "北京市朝阳区望京 SOHO",
  "city": "北京",
  "district": "朝阳区",
  "coordinates": {
    "lat": 39.9957,
    "lng": 116.4813
  },
  "provider": "amap",
  "provider_location_id": "geo_001"
}
```

### 5.2 POI Provider

```text
search_activities(origin, radius_km, filters) -> Activity[]
get_place_detail(provider_place_id) -> PlaceDetail
```

标准结果必须包含真实 Provider 返回的店铺或地点名称：

```json
{
  "provider_place_id": "amap_poi_001",
  "provider": "amap",
  "name": "真实返回的活动地点名称",
  "address": "真实返回的地址",
  "coordinates": {
    "lat": 39.9981,
    "lng": 116.4812
  },
  "category": "parent_child",
  "opening_hours": "10:00-21:00",
  "rating": 4.6,
  "distance_km": 4.2,
  "booking_supported": false
}
```

### 5.3 Merchant Provider

```text
search_restaurants(origin, party_size, arrival_time, filters) -> Restaurant[]
check_availability(merchant_id, party_size, arrival_time) -> Availability
```

标准结果：

```json
{
  "merchant_id": "merchant_001",
  "provider": "merchant_platform",
  "name": "真实返回的餐厅名称",
  "address": "真实返回的餐厅地址",
  "coordinates": {
    "lat": 39.9983,
    "lng": 116.4815
  },
  "available": true,
  "table_size": 8,
  "wait_minutes": 0,
  "booking_supported": true,
  "tags": [
    "light_food",
    "kid_friendly",
    "group_table"
  ]
}
```

### 5.4 Route Provider

```text
calculate_route(origin, destination, mode) -> RouteOption
calculate_route_matrix(points, modes) -> RouteMatrix
```

支持的交通方式：

| mode | 说明 |
| --- | --- |
| `walking` | 步行 |
| `driving` | 驾车 |
| `public_transit` | 公交/地铁 |
| `ride_hailing` | 网约车 |
| `cycling` | 骑行 |

标准结果：

```json
{
  "mode": "driving",
  "duration_minutes": 20,
  "distance_km": 4.2,
  "estimated_cost": 18,
  "traffic_risk": "medium",
  "parking_required": true,
  "transfer_count": 0,
  "walking_minutes": 3,
  "provider": "amap"
}
```
