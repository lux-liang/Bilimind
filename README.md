# BiliMind

BiliMind 是一个面向 B 站收藏视频的 AI 原生知识导航系统。它解决的不是“看视频”本身，而是一个长期存在、足够繁琐且值得自动化的学习痛点：

- 用户收藏了大量课程、讲座、技术分享视频，但收藏夹只会堆链接，不会组织知识。
- 视频知识天然碎片化，用户知道“看过”，却不知道“学会了什么、还缺什么、先看什么”。
- 用户记得一个知识点出自某个视频，却很难回到具体时间点。
- 单次聊天回答无法替代“知识抽取、结构归并、路径规划、证据回链、自动校验”这一整套工作流。

因此，BiliMind 的目标不是做一个普通聊天机器人，而是把收藏视频编译成可浏览知识树、可执行学习路径、可回放证据链和可检查的 Harness pipeline。

![BiliMind 首页](assets/screenshots/landing.png)

## A. 仓库当前状态审查

### 当前已有哪些能力

- 已有 FastAPI 后端和 Next.js 前端工作台，具备视频编译、知识展示、学习路径与证据浏览的产品雏形。
- 已有真实数据接入能力，后端保留了 B 站接口、字幕获取、ASR 降级与基础信息 fallback。
- 已有知识编译相关能力，包括概念/论断提取、知识树构建、学习路径推荐和前端展示页面。
- 已有一条离线 Harness demo pipeline，可从 sample transcript 生成中间产物并在工作台展示。

### 当前离比赛要求还缺什么

- pipeline 还不够显式，原先只有 `ingest -> transcript -> extract -> merge -> graph -> plan -> validate`，没有把 `evidence` 和 `render` 单独成阶段。
- Harness 设计证据还不够集中，README 需要更清楚地说明痛点、规则、工具层、反馈闭环和对应代码路径。
- sample/demo 目录结构还不够比赛导向，缺少清晰的 `sample_inputs`、独立输出验证脚本和 committed sample output 说明。
- 前端虽然能展示结果，但还需要更明确地展示“这不是聊天结果，而是 pipeline 产物”的阶段信息和校验信息。

## B. 最小改造计划

按优先级执行如下修改：

1. 保留现有产品与代码骨架，不推倒重写，只补一层比赛可证明的 Harness pipeline。
2. 把 pipeline 拆成显式九阶段：
   `ingest -> transcript -> extract -> merge -> graph -> plan -> evidence -> validate -> render`
3. 补齐 Agent Skill / prompt contract，让每个阶段的输入、输出 JSON schema、约束和失败回退都有文件证据。
4. 保留真实工具链，增加稳定 sample mode 和 committed sample artifacts，保证离线 demo 可跑。
5. 强化验证与反馈闭环，增加 evidence 覆盖校验、step-evidence 引用检查、render bundle 校验。
6. 重写 README，让评审能通过文档和代码路径快速确认 Harness 设计已落地。

## 为什么这不是普通聊天机器人

普通聊天式 AI demo 的结构通常是：

```text
用户提问 -> 大模型直接回答
```

BiliMind 的结构是：

```text
视频/收藏夹/URL/本地样例
  -> ingest: 元数据接入
  -> transcript: 字幕/ASR/本地 transcript
  -> extract: 分段知识点抽取
  -> merge: 归并去重
  -> graph: 构建知识树/知识图
  -> plan: 生成学习路径
  -> evidence: 绑定回视频时间点证据
  -> validate: 自动校验与低置信标记
  -> render: 前端展示包
```

最终展示的是结构化学习资产，不是一段不可检查的自然语言答案。

## 系统架构 / Pipeline

### 后端

- `app/services/harness_pipeline.py`
  离线可回放 Harness pipeline，负责九阶段 artifact 产出、trace 和 validation。
- `app/routers/compile.py`
  暴露 `POST /compile/demo` 和 `POST /compile/video`，分别对应离线 demo 和真实编译入口。
- `app/services/content_fetcher.py`
  真实工具层 adapter，负责字幕、ASR、基础信息三级降级。
- `app/services/bilibili.py`
  B 站 API 封装。
- `app/services/asr.py`
  ASR 封装。

### 前端

- `frontend/app/workspace/page.tsx`
  工作台入口，可直接运行 Harness demo。
- `frontend/components/HarnessPanel.tsx`
  展示 pipeline 阶段、artifact 路径、校验状态、覆盖率。
- `frontend/components/ConceptClaimList.tsx`
  展示节点、论断、原文片段和待确认状态。

### Demo 与脚本

- `demo/sample_inputs/sample_video_request.json`
  committed sample ingest 输入。
- `demo/sample_videos.json`
  sample metadata adapter 数据源。
- `demo/sample_transcripts/BVDEMOHARNESS01.json`
  sample transcript 数据源。
- `demo/sample_output/BVDEMOHARNESS01/`
  committed sample outputs，便于直接录制 demo。
- `scripts/run_demo_pipeline.py`
  一键生成离线 artifacts。
- `scripts/check_pipeline.py`
  校验最新运行结果。
- `scripts/validate_outputs.py`
  校验 committed sample outputs 是否仍满足 Harness contract。

## C. 实际修改内容

### 1. 显式 pipeline 改造

修改文件：

- [app/services/harness_pipeline.py](/home/lux_liang/work/Bilimind/app/services/harness_pipeline.py)

做了什么：

- 将 pipeline 扩展为九阶段：`ingest / transcript / extract / merge / graph / plan / evidence / validate / render`。
- 新增 `evidence_map.json`，将 graph 中的 evidence link 绑定成前端可展示的 evidence packet，并计算学习路径覆盖率。
- 新增 `render_bundle.json`，把 timeline、concept card、validation banner 做成独立展示层产物。
- 强化 `validate` 阶段，新增：
  - learning step 是否引用有效 evidence packet
  - learning step 是否缺失 traceable evidence
  - renderable evidence packet 是否存在
- 在 `pipeline_trace.json` 中记录 `stage_order`，让 demo 和脚本更容易检查。

### 2. Harness 文档与规则合同

修改文件：

- [docs/agent/SKILL.md](/home/lux_liang/work/Bilimind/docs/agent/SKILL.md)
- [prompts/extract_knowledge.md](/home/lux_liang/work/Bilimind/prompts/extract_knowledge.md)
- [prompts/build_graph.md](/home/lux_liang/work/Bilimind/prompts/build_graph.md)
- [prompts/plan_learning_path.md](/home/lux_liang/work/Bilimind/prompts/plan_learning_path.md)
- [prompts/bind_evidence.md](/home/lux_liang/work/Bilimind/prompts/bind_evidence.md)
- [prompts/render_workspace.md](/home/lux_liang/work/Bilimind/prompts/render_workspace.md)

做了什么：

- 明确每个阶段的输入、输出、上下文预算、JSON 契约和失败策略。
- 补上 `evidence` 和 `render` 两个阶段的 prompt/contract 文件。
- 明确长 transcript 不能被全量塞给所有阶段，而要按 segment 切块、按结构摘要传递。

### 3. sample/demo 可运行能力

修改文件：

- [scripts/run_demo_pipeline.py](/home/lux_liang/work/Bilimind/scripts/run_demo_pipeline.py)
- [scripts/check_pipeline.py](/home/lux_liang/work/Bilimind/scripts/check_pipeline.py)
- [scripts/validate_outputs.py](/home/lux_liang/work/Bilimind/scripts/validate_outputs.py)
- [demo/sample_inputs/sample_video_request.json](/home/lux_liang/work/Bilimind/demo/sample_inputs/sample_video_request.json)
- [demo/sample_inputs/README.md](/home/lux_liang/work/Bilimind/demo/sample_inputs/README.md)
- [demo/sample_outputs/README.md](/home/lux_liang/work/Bilimind/demo/sample_outputs/README.md)

做了什么：

- `run_demo_pipeline.py` 输出新增 `stage_order`，便于录制 demo 时直接展示阶段链路。
- `check_pipeline.py` 会检查 `evidence_map.json` 和 `render_bundle.json`。
- 新增 `validate_outputs.py`，专门校验 committed sample outputs。
- 新增 `sample_inputs` 目录，提供稳定的 ingest 输入样例。
- 新增 `sample_outputs` 说明目录，兼容比赛叙事命名。

### 4. 前端展示增强

修改文件：

- [frontend/components/HarnessPanel.tsx](/home/lux_liang/work/Bilimind/frontend/components/HarnessPanel.tsx)
- [frontend/lib/api.ts](/home/lux_liang/work/Bilimind/frontend/lib/api.ts)
- [app/routers/compile.py](/home/lux_liang/work/Bilimind/app/routers/compile.py)

做了什么：

- Harness 面板新增 `evidence` 和 `render` 阶段展示。
- 新增“学习路径覆盖”“Render Bundle”两项指标，让评委看到验证闭环与展示层是分开的。
- `/compile/demo` 返回的 `harness.stats` 中加入覆盖率和 render 统计，前端无需重构即可展示。

## D. Harness 设计

### 1. 上下文管理 / Agent Skill

对应代码与文档：

- [docs/agent/SKILL.md](/home/lux_liang/work/Bilimind/docs/agent/SKILL.md)
- [prompts/extract_knowledge.md](/home/lux_liang/work/Bilimind/prompts/extract_knowledge.md)
- [prompts/build_graph.md](/home/lux_liang/work/Bilimind/prompts/build_graph.md)
- [prompts/plan_learning_path.md](/home/lux_liang/work/Bilimind/prompts/plan_learning_path.md)
- [prompts/bind_evidence.md](/home/lux_liang/work/Bilimind/prompts/bind_evidence.md)
- [prompts/render_workspace.md](/home/lux_liang/work/Bilimind/prompts/render_workspace.md)

落地方式：

- transcript 先被切成带时间戳 segment。
- `extract` 阶段一次只处理一个 segment。
- `graph` 阶段只看结构化候选，不重读整段 transcript。
- `plan` 阶段只看 graph summary、难度与 evidence 引用。
- `validate` 和 `render` 阶段不依赖 LLM，完全基于结构化 artifacts。

### 2. 外部工具调用

对应代码：

- [app/services/bilibili.py](/home/lux_liang/work/Bilimind/app/services/bilibili.py)
- [app/services/content_fetcher.py](/home/lux_liang/work/Bilimind/app/services/content_fetcher.py)
- [app/services/asr.py](/home/lux_liang/work/Bilimind/app/services/asr.py)
- [app/services/harness_pipeline.py](/home/lux_liang/work/Bilimind/app/services/harness_pipeline.py)

落地方式：

- 真实模式：
  - B 站接口拿元数据和收藏夹内容
  - 字幕优先
  - ASR fallback
  - 基础信息兜底
- demo 模式：
  - `SampleHarnessTool` 从本地 JSON 文件读取元数据与 transcript
  - 不依赖网络、不依赖登录、稳定可录制

### 3. 验证与反馈闭环

对应代码：

- [app/services/harness_pipeline.py](/home/lux_liang/work/Bilimind/app/services/harness_pipeline.py)
- [scripts/check_pipeline.py](/home/lux_liang/work/Bilimind/scripts/check_pipeline.py)
- [scripts/validate_outputs.py](/home/lux_liang/work/Bilimind/scripts/validate_outputs.py)
- [frontend/components/HarnessPanel.tsx](/home/lux_liang/work/Bilimind/frontend/components/HarnessPanel.tsx)
- [frontend/components/ConceptClaimList.tsx](/home/lux_liang/work/Bilimind/frontend/components/ConceptClaimList.tsx)

当前自动检查项：

- JSON 结构是否完整
- 节点 normalized name 是否重复
- graph edge 是否指向存在节点
- evidence timestamp 是否合法
- learning path step 是否指向存在节点
- learning path step 的 `evidence_refs` 是否有效
- learning step 是否缺少 traceable evidence
- 低置信度 / 单一来源节点是否被标记为 `needs_review`

前端反馈方式：

- Harness 面板显示 `已验证 / 需修复`
- 节点和论断显示 `已验证 / 待确认 / 低置信`
- artifact 目录可直接打开查看中间产物

## E. Demo 运行说明

### 1. 用 sample 数据跑通

```bash
python3 scripts/run_demo_pipeline.py
python3 scripts/check_pipeline.py
python3 scripts/validate_outputs.py
```

说明：

- 第一条命令会在 `artifacts/harness/` 下生成新的运行产物。
- 第二条命令检查最近一次运行是否通过。
- 第三条命令检查仓库里已提交的 sample outputs，适合比赛现场直接验证。

### 2. 如何查看中间产物

运行后重点查看：

- [demo/sample_output/BVDEMOHARNESS01/raw_metadata.json](/home/lux_liang/work/Bilimind/demo/sample_output/BVDEMOHARNESS01/raw_metadata.json)
- [demo/sample_output/BVDEMOHARNESS01/raw_transcript.json](/home/lux_liang/work/Bilimind/demo/sample_output/BVDEMOHARNESS01/raw_transcript.json)
- [demo/sample_output/BVDEMOHARNESS01/extracted_nodes.json](/home/lux_liang/work/Bilimind/demo/sample_output/BVDEMOHARNESS01/extracted_nodes.json)
- [demo/sample_output/BVDEMOHARNESS01/merged_graph.json](/home/lux_liang/work/Bilimind/demo/sample_output/BVDEMOHARNESS01/merged_graph.json)
- [demo/sample_output/BVDEMOHARNESS01/learning_path.json](/home/lux_liang/work/Bilimind/demo/sample_output/BVDEMOHARNESS01/learning_path.json)
- [demo/sample_output/BVDEMOHARNESS01/evidence_map.json](/home/lux_liang/work/Bilimind/demo/sample_output/BVDEMOHARNESS01/evidence_map.json)
- [demo/sample_output/BVDEMOHARNESS01/validation_report.json](/home/lux_liang/work/Bilimind/demo/sample_output/BVDEMOHARNESS01/validation_report.json)
- [demo/sample_output/BVDEMOHARNESS01/render_bundle.json](/home/lux_liang/work/Bilimind/demo/sample_output/BVDEMOHARNESS01/render_bundle.json)
- [demo/sample_output/BVDEMOHARNESS01/pipeline_trace.json](/home/lux_liang/work/Bilimind/demo/sample_output/BVDEMOHARNESS01/pipeline_trace.json)

### 3. 如何在前端展示

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
cd frontend
npm install
npm run dev
```

打开：

- `http://localhost:3000/workspace`

在工作台点击“运行 Harness Demo”后，可展示：

- 明确的九阶段 pipeline
- 数据来源与 transcript source
- 学习路径覆盖率
- 验证结果与 warning/error
- 节点、论断、原文片段和证据时间点

### 4. 真实模式说明

真实模式继续复用原项目能力，不影响比赛 demo：

- `POST /compile/video`
- B 站扫码登录
- 收藏夹/视频元数据获取
- 字幕优先，ASR 与基础信息 fallback

若真实接口不稳定，直接使用 sample mode 依然可以完整演示 Harness 设计。

## 项目亮点

- 保留了“个人视频知识导航系统”的产品主题，没有被改造成聊天框 demo。
- 显式把 AI 能力放进工程化 pipeline，而不是黑箱一步生成。
- 有上下文管理、工具层接入、验证与反馈闭环三类 Harness 设计证据。
- 有 committed sample inputs / outputs，可离线稳定展示。
- 中间产物、规则文档、前端状态展示、验证脚本彼此一致，便于评审快速确认。

## F. 后续还可以补什么

- 把真实模式的 artifacts 也完整写盘，而不仅是 demo 模式。
- 将 `extract / graph / plan` 从规则抽取进一步升级为可切换 LLM provider 的结构化调用。
- 增加更丰富的 validation，例如图连通性、路径断裂修复建议、节点别名冲突检测。
- 增加多视频 favorites 批处理 demo，让“从收藏夹到知识树”的比赛叙事更完整。
- 增加前端对 `validation_report` 的 drill-down 视图，支持点击 warning 直接跳到对应 artifact。
