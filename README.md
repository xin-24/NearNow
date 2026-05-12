# Local Weekend Planner Agent

本项目是一个“本地短时活动规划与执行 Agent”。用户输入一句自然语言目标后，系统需要理解出行时间、参与者画像、同行关系、距离偏好、餐饮需求、真实地理位置和交通方式等信息，并生成一条可执行的下午活动方案。在用户确认后，Agent 自动调用工具完成预约、订座、排队、通知等关键动作。

项目采用两阶段实现：第一阶段使用 Mock Provider 完成可运行 Demo，第二阶段接入真实地图、真实 POI、真实店铺名称、实时营业状态、可选交通方式和真实预约能力。

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

网页中点击出发位置输入框内的“定位”按钮可调用浏览器定位授权。前端会先把经纬度降为约 1km 级别的大概位置，再调用后端地址反查接口，将地址按「城市 + 区/县 + 商圈/地标」填回同一个输入框；定位后的地址仍可直接手动修改。地址反查优先使用真实地图服务，失败时回落到 Mock。界面和方案不会展示精确坐标。若拒绝授权，则继续按手动输入的出发地规划。

手动输入出发地建议使用「城市 + 区/县 + 商圈/地标」格式，例如 `北京 朝阳区 望京 SOHO`、`上海 徐汇区 徐家汇`。如果只填写 `望京 SOHO`，网页会按默认城市归一为 `北京 望京 SOHO`；不需要填写门牌号或精确住址。

命令行试用：

```bash
python3 -m cli.main "下午带狗出去玩，顺便找个能带宠物的地方吃饭。"
```

运行测试：

```bash
python3 -m unittest
```
