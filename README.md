# ACP Dashboard — 多智能体协作可视化监控面板

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg) ![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)

基于 QwenPaw 多智能体框架搭建的实时协作流程可视化平台，用于监控和管理由 8 个专业 AI Agent 组成的协同工作系统。

## 项目背景

在日常使用 QwenPaw 进行多智能体协作开发的过程中，面临的核心问题是：多个 Agent 并行工作时，任务流转状态不透明、异常难以发现、整体效率缺乏量化手段。ACP Dashboard 作为自研的内部工具，解决了这个痛点。

## 核心功能

- **8 节点协作流程可视化** — 将多 Agent 协作过程抽象为「接收→判定→去重→下发→执行→反馈→验收→归档」8 个标准节点，实时呈现任务所处阶段
- **Agent 健康监控** — 8 个 Agent 的运行状态、任务负载、响应速度一目了然
- **告警分级系统** — 异常自动分级（普通/警告/严重），超时任务红色告警
- **知识库浏览器** — 内置文档阅读面板，支持浏览知识库中的协作流程、技术文档等
- **子节点时间轴** — 每个 Agent 独立展示子步骤进度，宏观+微观双重视角

## 技术栈

| 层级 | 技术 | 
|:---|:---|
| 后端 | Python Flask + REST API |
| 前端 | 原生 HTML5 / CSS3 / JavaScript（零框架依赖） |
| 动画 | 纯 CSS @keyframes（GPU 加速，零 JS 动画开销） |
| 数据源 | QwenPaw API + 本地 Markdown 文件双通道 |
| 大模型 | 由所接入的 Agent 平台聚合（模型厂商无关，面板不感知具体厂商） |

## 架构

```
┌──────────────────────────────────────┐
│           浏览器前端                    │
│   流程条 · 卡片 · 告警 · 时间轴        │
└──────────────┬───────────────────────┘
               │ HTTP
┌──────────────▼───────────────────────┐
│        Flask 后端 (app.py)            │
│   /api/workflow  /api/agents          │
│   /api/alerts   /api/docs             │
└──────┬────────────────┬──────────────┘
       │                │
┌──────▼──────┐  ┌──────▼──────────┐
│  QwenPaw    │  │  本地文件系统     │
│  API:8088   │  │  (Markdown)     │
└─────────────┘  └─────────────────┘
```

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动 QwenPaw 服务（需提前安装，默认探测 http://127.0.0.1:8088）

# 3. 启动 Dashboard
python app.py

# 4. 浏览器打开 http://127.0.0.1:8083
```

> 默认仅监听本机（`127.0.0.1:8083`）。局域网访问可设环境变量
> `ACP_HOST=0.0.0.0`；调试模式 `ACP_DEBUG=1`（⚠️ Werkzeug 调试器有代码执行风险，勿在对外环境开启）。

## 项目结构

```
acp-dashboard/
├── app.py                  # Flask 主程序
├── requirements.txt        # Python 依赖
├── startup.bat             # Windows 启动脚本
├── check_and_start.bat     # 健康检查 + 启动脚本
├── templates/
│   ├── index.html          # 主面板页面
│   └── logs.html           # 日志页面
└── static/
    └── css/
        └── style.css       # 全局样式 + CSS 动画
```

## 项目状态

内部工具，持续迭代中。近期更新：

- V0.1 — 基础框架搭建（Flask + AdminLTE）
- V0.2 — 流程可视化升级（8 节点流程条 + 跑马灯动画 + 告警分级）

## License

[MIT](LICENSE)
