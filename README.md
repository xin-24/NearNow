# Local Weekend Planner Agent

本项目是一个“本地短时活动规划与执行 Agent”。用户输入一句自然语言目标后，系统需要理解出行时间、参与者画像、同行关系、距离偏好、餐饮需求、真实地理位置和交通方式等信息，并生成一条可执行的下午活动方案。在用户确认后，Agent 自动调用工具完成预约、订座、排队、通知等关键动作。

项目采用 Provider 分层实现：Mock Provider 用于测试和离线开发；Web UI 当前默认使用真实模式，已接入 OpenStreetMap Nominatim 地理编码/逆地理编码、Overpass 周边 POI/餐厅搜索、OSRM 路线耗时。营业状态、评分、人均、实时可订和真实预约动作仍保留在后续 Provider 接入阶段。

## 项目目标

- 接收自然语言目标，自动解析用户意图和约束。
- 生成下午 4-6 小时内的本地活动、餐饮和后续安排方案。
- 查询活动、餐厅、余位、排队、距离、路线和交通方式。
- 支持从 Mock 数据平滑迁移到真实地图和真实门店数据。
- 在用户确认后执行预约、订座、排队、下单、通知等动作。
- 提供 CLI 或 Web UI Demo，完整展示 Agent 的规划与执行闭环。

## 推荐项目结构

```text
local-weekend-planner/
├── README.md
├── pyproject.toml
├── .env.example
├── docs/
│   ├── design.md
│   ├── api_contract.md
│   ├── development_guide.md
│   ├── ai_agent_benchmark.md
│   ├── production_integration.md
│   └── demo_script.md
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   ├── agent/
│   ├── domain/
│   ├── tools/
│   ├── providers/
│   ├── mock_api/
│   └── utils/
├── cli/
├── web/
└── tests/
```

## 文档索引

- [总体设计文档](docs/design.md)：项目背景、业务目标、系统架构、Agent 流程、Planning 策略和异常处理。
- [API 契约文档](docs/api_contract.md)：Agent API、Mock API、请求响应结构和错误码约定。
- [开发指南](docs/development_guide.md)：推荐技术栈、目录职责、开发流程、测试策略和里程碑。
- [AI Agent 竞品与能力借鉴](docs/ai_agent_benchmark.md)：当前相关 Agent 应用调研，以及可复用到本项目的产品能力。
- [真实服务接入设计](docs/production_integration.md)：真实地理位置、真实店铺、POI、路线和交通方式接入方案。
- [Demo 脚本](docs/demo_script.md)：演示路径、输入样例、期望输出和异常场景。

## 最小可交付版本

MVP 需要具备以下能力：

- 一个 CLI 或 Web UI 入口。
- `POST /agent/plan` 生成可执行活动方案。
- `POST /agent/confirm` 执行用户确认后的预约和通知动作。
- Mock 活动、餐厅、预约、排队、通知、路线 API。
- 为真实地理位置、真实店铺名和交通方式选择预留 Provider 抽象。
- 至少 3 类异常场景：餐厅无位、活动满员、信息不足。
- 可运行的测试用例覆盖意图解析、规划排序、工具调用和执行结果。

## 本地运行

当前代码框架不依赖外部 Python 包，可直接启动网页 Demo：

```bash
python3 -m app.main
```

打开：

```text
http://127.0.0.1:8000
```

网页中点击出发位置输入框内的“定位”按钮可调用浏览器定位授权。前端会先把经纬度降为约 1km 级别的大概位置，再调用后端地址反查接口，将地址按「城市 + 区/县 + 商圈/地标」填回同一个输入框；定位后的地址仍可直接手动修改。地址反查使用真实地图服务，失败时返回错误并提示手动输入，不使用 Mock 地址。界面和方案不会展示精确坐标。若拒绝授权，则继续按手动输入的出发地规划。

手动输入出发地建议使用「城市 + 区/县 + 商圈/地标」格式，例如 `北京 朝阳区 望京 SOHO`、`上海 徐汇区 徐家汇`。真实模式下，后端会先用 Nominatim 将手动地址解析为大概坐标，再用 Overpass 查询周边真实活动地点和真实餐厅名称，并用 OSRM 计算可用交通方式的路线耗时。如果真实地理编码、POI 或路线 API 失败，接口会直接返回错误，不会使用 Mock 店名或模拟路线假装成功。

## LongCat API

项目已接入 LongCat 的 OpenAI 兼容 Chat Completions API。Agent 会使用 LongCat 增强意图解析和最终计划话术；如果未配置 `LONGCAT_API_KEY` 或 API 调用失败，接口会返回错误，不再使用本地规则或 Mock 数据假装成功。

```bash
export LONGCAT_API_KEY="你的 LongCat API Key"
export LONGCAT_MODEL="LongCat-Flash-Chat"
export NEARNOW_PROVIDER_MODE="real"
python3 -m app.main
```

也可以使用本地 `.env.local` 文件：

```bash
cp .env.local.example .env.local
# 编辑 .env.local，填入真实 LONGCAT_API_KEY
python3 -m app.main
```

可参考 `.env.example` 查看完整环境变量。当前实现使用官方文档中的 `https://api.longcat.chat/openai/v1/chat/completions` 格式，不额外引入第三方依赖。

环境变量文件建议：

- `.env.example`：GitHub 可上传的安全占位模板。
- `.env.local.example`：本地真实 Key 模板，复制为 `.env.local` 后填写真实 `LONGCAT_API_KEY`。
- `.env` / `.env.local`：本地私密配置，已被 `.gitignore` 忽略，不要提交。

命令行试用：

```bash
python3 -m cli.main "下午带狗出去玩，顺便找个能带宠物的地方吃饭。"
```

运行测试：

```bash
python3 -m unittest
```
