# BiliMind — 面向视频学习的 AI Harness 知识导航系统

BiliMind 解决一个很常见但很繁琐的问题：学习者在 B 站收藏了大量课程、讲座、技术分享以后，很难知道“这些视频讲了什么知识点、先看什么、某个结论来自哪个时间点”。

本项目把收藏视频或本地样例数据转成可验证的知识树、学习路径和视频证据链。它不是一个把问题丢给大模型的聊天机器人，而是一个分阶段 AI 工作流：每一步都有输入、输出、中间产物和自动校验。

![BiliMind 首页](assets/screenshots/landing.png)

---

## 为什么不是普通聊天机器人

普通 AI demo 往往是“用户提问 -> LLM 直接回答”。BiliMind 的核心不是聊天，而是知识构建 Harness：

```text
视频/收藏夹/导出列表
  -> 元数据获取
  -> 字幕/文本获取
  -> 知识点抽取
  -> 实体去重归并
  -> 知识树构建
  -> 学习路径生成
  -> 视频时间点证据回链
  -> 自动校验与低置信度标记
  -> 前端展示
```

最终用户看到的不是一句回答，而是一套可以浏览、可以追溯、可以被检查的结构化学习资产。

---

## 核心场景与用户价值

- 收藏了很多课程、讲座、技术视频，但无法形成系统知识结构。
- 记得某个知识点来自某个视频，却无法快速回到具体时间点。
- 想学习一个主题，不知道先看基础概念、工具调用，还是验证机制。
- AI 抽取可能会错，系统需要把低置信度和缺少证据的内容标出来，而不是直接展示成“确定结论”。

---

## 系统架构

```text
Frontend: Next.js 工作台
  - Harness 阶段视图
  - 知识时间轴
  - 知识图 / 论断 / 证据

Backend: FastAPI
  - /compile/video 真实视频编译入口
  - /compile/demo  离线 sample Harness demo

Harness Pipeline
  - app/services/harness_pipeline.py
  - demo/sample_videos.json
  - demo/sample_transcripts/
  - demo/sample_output/
  - scripts/run_demo_pipeline.py
  - scripts/check_pipeline.py

Existing Knowledge System
  - app/services/content_fetcher.py
  - app/services/knowledge_compiler.py
  - app/services/graph_store.py
  - app/services/tree_builder.py
  - app/services/path_recommender.py
```

当前迭代没有推倒重写原项目，而是在现有“视频知识编译 + 证据回链 + 工作台 UI”上增加显式 Harness 层：阶段 trace、sample datasource、artifact 输出、验证报告和 UI 展示。

---

## Harness Engineering 设计

### Harness 1：上下文管理 / Agent Skill

为什么需要：

长视频 transcript 直接塞给模型会带来上下文过长、噪声节点多、证据不可追溯的问题。

如何实现：

- `docs/agent/SKILL.md` 定义了 BiliMind Agent Skill：每个阶段的输入、输出 JSON、上下文预算、失败回退策略。
- `prompts/extract_knowledge.md` 限制抽取阶段一次只读取一个 timestamp segment。
- `prompts/build_graph.md` 要求图谱阶段只读取结构化候选节点和证据 ID。
- `prompts/plan_learning_path.md` 要求学习路径阶段只读取依赖关系、难度和证据摘要。

代码位置：

- [docs/agent/SKILL.md](docs/agent/SKILL.md)
- [prompts/extract_knowledge.md](prompts/extract_knowledge.md)
- [prompts/build_graph.md](prompts/build_graph.md)
- [prompts/plan_learning_path.md](prompts/plan_learning_path.md)
- [app/services/harness_pipeline.py](app/services/harness_pipeline.py)

效果：

系统不把全量 transcript 混塞给同一个模型调用，而是让不同阶段只读必要上下文，并把每一步输出写成可检查 JSON。

### Harness 2：外部工具调用

为什么需要：

学习工具不能只靠模型“猜”。视频标题、字幕、ASR、收藏夹列表、时间戳证据都应来自外部工具或明确数据源。

如何实现：

- 真实模式沿用现有 `BilibiliService`、`ContentFetcher`、`ASRService`，可从 B 站接口、字幕、ASR 或基础信息获取内容。
- demo 模式使用 `SampleHarnessTool`，从本地 `demo/sample_videos.json` 和 `demo/sample_transcripts/` 读取稳定样例数据。
- pipeline trace 会记录每个阶段调用了什么 tool、读取了什么 source。

代码位置：

- [app/services/bilibili.py](app/services/bilibili.py)
- [app/services/content_fetcher.py](app/services/content_fetcher.py)
- [app/services/asr.py](app/services/asr.py)
- [app/services/harness_pipeline.py](app/services/harness_pipeline.py)
- [demo/sample_videos.json](demo/sample_videos.json)
- [demo/sample_transcripts/BVDEMOHARNESS01.json](demo/sample_transcripts/BVDEMOHARNESS01.json)

效果：

即使真实 B 站接口或 ASR 不稳定，sample mode 也能离线跑通完整 demo；真实模式则保留 API/字幕/ASR 接入位置。

### Harness 3：验证与反馈闭环

为什么需要：

AI 抽取知识点可能重复、缺少证据、时间戳非法，或者学习路径出现断层。比赛中必须证明系统不是“生成完就展示”。

如何实现：

- `validate` 阶段检查 JSON 结构、重复节点、缺少 evidence、非法 timestamp、graph edge 是否指向不存在节点、learning path 是否重复节点。
- 低置信度或单一来源节点会进入 `needs_review` 状态。
- 前端 Harness 页签显示 `已验证 / 待确认 / warning / artifact_dir`。
- `scripts/check_pipeline.py` 可一键检查 sample artifacts。

代码位置：

- [app/services/harness_pipeline.py](app/services/harness_pipeline.py)
- [scripts/run_demo_pipeline.py](scripts/run_demo_pipeline.py)
- [scripts/check_pipeline.py](scripts/check_pipeline.py)
- [frontend/components/HarnessPanel.tsx](frontend/components/HarnessPanel.tsx)
- [frontend/components/ConceptClaimList.tsx](frontend/components/ConceptClaimList.tsx)
- [demo/sample_output/BVDEMOHARNESS01/validation_report.json](demo/sample_output/BVDEMOHARNESS01/validation_report.json)

效果：

生成结果会先被验证，前端会显式展示校验状态和低置信度标记。错误不会被静默包装成正确答案。

---

## 工作流示例

输入：

- `BVDEMOHARNESS01`
- 本地 sample transcript：`demo/sample_transcripts/BVDEMOHARNESS01.json`

输出：

- `raw_metadata.json`：视频元数据
- `raw_transcript.json`：带时间戳 transcript
- `extracted_nodes.json`：分段抽取的候选概念和论断
- `merged_nodes.json`：归一化与去重后的节点、论断、证据链接
- `merged_graph.json`：去重后的知识节点、关系、证据链接
- `learning_path.json`：可执行学习顺序
- `validation_report.json`：自动校验结果
- `pipeline_trace.json`：每个阶段的输入摘要、输出摘要、耗时、warning

仓库内已保留一份 sample 输出：

- [demo/sample_output/BVDEMOHARNESS01](demo/sample_output/BVDEMOHARNESS01)

---

## Demo 运行方式

### 1. 只跑离线 Harness pipeline

这个路径不需要 B 站登录、不需要 LLM key、不需要网络。

```bash
python3 scripts/run_demo_pipeline.py
python3 scripts/check_pipeline.py
```

运行后会在 `artifacts/harness/` 下生成一套新的中间产物。`artifacts/` 是运行时输出，已加入 `.gitignore`；仓库内固定样例在 `demo/sample_output/BVDEMOHARNESS01/`。

### 2. 启动后端

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

关键 API：

- `GET /health`
- `POST /compile/demo`
- `POST /compile/video`
- `GET /compile/result/{bvid}`

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端地址：

- `http://localhost:3000/workspace`

在工作台左侧点击 `运行 Harness Demo`，无需登录即可看到：

- pipeline 阶段状态
- 数据来源
- transcript source
- 验证结果
- 学习路径
- 时间点证据
- 低置信度/待确认标记

### 4. 真实模式

真实模式沿用原有 BiliMind 能力：

- B 站扫码登录
- 收藏夹/视频元数据获取
- 字幕优先
- ASR fallback
- 基础信息 fallback
- 知识编译并写入数据库

需要配置：

```bash
cp .env.example .env
# 填写 DASHSCOPE_API_KEY 或兼容 OpenAI 的配置
```

如果真实接口失败，比赛 demo 仍可使用 sample mode 完整展示 Harness 设计。

---

## 可运行代码证据

```bash
python3 scripts/run_demo_pipeline.py
python3 scripts/check_pipeline.py
python3 -m py_compile app/services/harness_pipeline.py scripts/run_demo_pipeline.py scripts/check_pipeline.py app/routers/compile.py
```

当前 sample pipeline 校验项：

- 有知识节点
- 有 evidence links
- 有学习路径
- 有完整 stage trace
- validation passed

---

## 3 分钟 Demo 建议

1. 0:00 - 0:30：打开 README，说明痛点：收藏视频很多，但没有知识结构、学习顺序和时间点证据。
2. 0:30 - 1:10：运行 `python3 scripts/run_demo_pipeline.py`，展示生成的 artifact 目录。
3. 1:10 - 1:50：打开 `demo/sample_output/BVDEMOHARNESS01/`，快速展示 `raw_transcript.json`、`merged_graph.json`、`validation_report.json`。
4. 1:50 - 2:30：打开前端 `/workspace`，点击 `运行 Harness Demo`，展示 Harness 阶段视图和验证结果。
5. 2:30 - 3:00：切到时间轴和论断页，展示知识点如何回链到视频时间段，以及低置信度/待确认机制。

---

## 技术栈

| 层面 | 技术 |
| --- | --- |
| 后端 | Python, FastAPI, SQLAlchemy async |
| Harness Pipeline | Python 标准库 JSON artifact + deterministic validator |
| 视频/外部工具 | Bilibili API adapter, subtitle/ASR fetcher, sample datasource |
| 知识结构 | Concept / Claim / Evidence, networkx graph store |
| 前端 | Next.js, React, TypeScript |
| 存储 | SQLite, JSON artifacts |

---

## 项目亮点

- 产品形态不是聊天框，而是视频学习工作台。
- 每个知识点和论断都能回到视频时间片段。
- Harness pipeline 有阶段 trace 和中间产物。
- demo mode 不依赖外部网络，适合比赛现场稳定录制。
- 真实模式保留 B 站、字幕、ASR、数据库和前端工作台接入。
- 验证闭环会标记低置信度或缺证据结果。

---

## 局限性与后续计划

当前版本优先保证比赛 demo 可运行、可解释、可验证。真实 B 站接口和 ASR 仍可能受登录、网络、音频权限影响，因此保留了 sample fallback。

后续可以继续增强：

- 把真实 `/compile/video` 也完整写出 artifacts，而不只是 demo pipeline。
- 增加人工 review 后的反馈学习机制。
- 接入更稳定的字幕下载工具或本地 Whisper CLI。
- 把 validation warning 直接转成修复任务。
- 增加多视频/收藏夹级别的跨视频概念对齐报告。

---

## License

MIT
