# Knowledge-to-Video Evidence Relevance Classifier

这个模块用于解决“知识节点右侧视频证据错配”的问题。它不是替换现有召回，而是作为二阶段精排与过滤器：

1. 第一阶段：沿用现有 `NodeSegmentLink + 规则召回`
2. 第二阶段：`EvidenceRanker` 对候选片段做相关性判别
3. 展示策略：
   - `high`：直接展示
   - `medium`：展示并标记为中置信
   - `low`：不展示，前端显示“暂无高置信视频证据”

## 为什么先做这个模型

- 当前系统最大的可信性问题不是“搜不到”，而是“错证据也会展示”
- 现有系统已经沉淀了可复用的弱监督数据：
  - 正样本：`KnowledgeNode -> NodeSegmentLink -> Segment`
  - 负样本：同视频非绑定片段、跨视频 hard negative、随机负样本
- 这类问题适合做轻量 pairwise classifier，而不是一上来训练大模型

## 模型定义

输入字段：

- `node_name`
- `node_definition`
- `node_aliases`
- `node_type`
- `video_title`
- `segment_text`
- `segment_source_type`
- `link_confidence`
- `segment_confidence`
- `knowledge_density`
- `is_peak`

输出字段：

- `relevance_score: float`
- `is_relevant: bool`
- `confidence_level: high | medium | low`

## 当前实现

当前默认实现是轻量特征哈希二分类器：

- 特征类型：
  - 规则特征：overlap、title overlap、name exact match、alias match、knowledge density、length bucket
  - 结构特征：node type、relation、content source
  - token 特征：node/title/segment token 与 overlap token
- 模型结构：
  - `HashedBinaryLogisticModel`
  - 优点：训练成本低、无大型依赖、CPU 可训、推理可直接嵌进 FastAPI

说明：

- 这版是“比赛交付优先”的轻量模型
- 如果后续要用 GPU，可以把二阶段替换成 `bge-reranker / MiniLM / TinyBERT cross-encoder`
- 上层接口不需要大改，只替换 `EvidenceRanker` 内部模型即可

## 数据集构造

脚本：`scripts/build_evidence_training_data.py`

输出目录结构：

```text
data/training/evidence_ranker/
  train.jsonl
  val.jsonl
  test.jsonl
  summary.json
```

每条样本包含：

- `sample_id`
- `query_id`
- `split`
- `label`
- `node_id / node_name / node_definition / node_aliases / node_type`
- `video_id / video_title`
- `segment_id / segment_text / segment_source_type`
- `link_confidence / segment_confidence / knowledge_density / is_peak`
- `rule_score`
- `negative_kind`
- `numeric_features`
- `token_features`

切分策略：

- 按 `video_id` 哈希切分 `train/val/test`
- 避免同一视频片段同时进入多个集合造成泄漏

## 训练命令

```bash
./.venv/bin/python scripts/build_evidence_training_data.py --output-dir data/training/evidence_ranker
```

从当前数据库导出证据相关性训练集，并自动切分 train/val/test。

```bash
./.venv/bin/python scripts/train_evidence_ranker.py --input data/training/evidence_ranker --output data/models/evidence_ranker.json
```

训练轻量相关性判别器，并自动读取 `train.jsonl`，若存在则同时评估 `val.jsonl`。

```bash
./.venv/bin/python scripts/eval_evidence_ranker.py --input data/training/evidence_ranker --split test --model data/models/evidence_ranker.json
```

在测试集上对比“规则分基线”和“规则分 + 判别器”。

```bash
./.venv/bin/python scripts/infer_evidence_ranker.py --input sample.json --model data/models/evidence_ranker.json
```

对单条或批量样本做离线推理，输出 `relevance_score / is_relevant / confidence_level`。

## 评估指标

模型级指标：

- Accuracy
- Precision
- Recall
- F1
- AUC

系统级指标：

- `Top-1 evidence precision`
- `error_display_rate`
- `empty_state_rate`

推荐答辩时重点看：

- `Top-1 evidence precision` 提升
- `error_display_rate` 下降
- 在允许少量 `empty_state_rate` 上升的前提下，降低错证据展示

## 系统接入点

- 线上接入文件：`app/routers/tree.py`
- 服务实现：`app/services/evidence_ranker.py`

当前链路：

1. 查询节点绑定片段
2. 规则分粗排
3. `EvidenceRanker.score(...)`
4. 过滤 `is_relevant = false`
5. 输出 `match_confidence / confidence_level / match_reason`

## 后续升级路线

1. 用人工修正样本继续补 hard negative
2. 用点击日志或“用户确认正确证据”做在线校准
3. 把当前轻量模型替换成 cross-encoder reranker
4. 增加 per-node-type 阈值，降低 topic 类节点误配
