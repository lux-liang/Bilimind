"use client";

import { CompileResult } from "@/lib/api";

interface HarnessPanelProps {
  result: CompileResult;
}

const STAGE_LABELS: Record<string, string> = {
  ingest: "1. 元数据获取",
  transcript: "2. 字幕/文本获取",
  extract: "3. 知识点抽取",
  merge: "4. 实体去重归并",
  graph: "5. 知识树构建",
  plan: "6. 学习路径生成",
  validate: "7. 验证反馈闭环",
  extract_merge: "抽取与归并",
};

export default function HarnessPanel({ result }: HarnessPanelProps) {
  const harness = result.harness;
  if (!harness) {
    return (
      <div className="harness-empty">
        当前结果尚未包含 Harness trace。运行 sample demo 可查看完整阶段产物。
      </div>
    );
  }

  const warnings = harness.validation?.warnings || [];
  const errors = harness.validation?.errors || [];
  const checks = harness.validation?.checks || [];

  return (
    <div className="harness-panel">
      <section className="harness-hero">
        <div>
          <p className="harness-kicker">Harness Engineering Trace</p>
          <h2>{result.video.title}</h2>
          <p>
            这不是一次聊天回答，而是从数据源、字幕、抽取、归并、路径规划到自动校验的可回放 AI 工作流。
          </p>
        </div>
        <div className={`harness-status ${harness.validation_passed ? "ok" : "fail"}`}>
          <span>{harness.validation_passed ? "已验证" : "需修复"}</span>
          <strong>{harness.pipeline_version}</strong>
        </div>
      </section>

      <section className="harness-grid">
        <div className="harness-card">
          <span>数据来源</span>
          <strong>{harness.datasource}</strong>
          <p>通过 Tool Adapter 获取，不把来源隐藏在模型回答里。</p>
        </div>
        <div className="harness-card">
          <span>Transcript</span>
          <strong>{harness.transcript_source}</strong>
          <p>可切换真实接口、ASR、本地导出或 sample fallback。</p>
        </div>
        <div className="harness-card">
          <span>证据链接</span>
          <strong>{harness.validation?.summary?.validated_evidence_links ?? result.stats.claim_count}</strong>
          <p>知识点必须能回链到视频时间片段。</p>
        </div>
        <div className="harness-card">
          <span>待确认节点</span>
          <strong>{harness.validation?.summary?.low_confidence_nodes ?? 0}</strong>
          <p>低置信度不伪装成确定结论，而是进入 review 状态。</p>
        </div>
      </section>

      <section className="harness-section">
        <div className="harness-section-head">
          <h3>Pipeline 阶段</h3>
          {harness.artifact_dir && <code>{harness.artifact_dir}</code>}
        </div>
        <div className="harness-stage-list">
          {harness.stages.map((stage, index) => (
            <div key={`${stage.name}-${index}`} className="harness-stage">
              <div className="harness-stage-index">{index + 1}</div>
              <div>
                <div className="harness-stage-title">
                  <strong>{STAGE_LABELS[stage.name] || stage.name}</strong>
                  <span className={`harness-badge ${stage.status}`}>{stage.status}</span>
                  <span>{stage.duration_ms}ms</span>
                </div>
                <p>{stage.input_summary}</p>
                <p className="harness-output">{stage.output_summary}</p>
                {stage.warnings.length > 0 && (
                  <div className="harness-warning">
                    {stage.warnings.join(" / ")}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      {result.learning_path && (
        <section className="harness-section">
          <div className="harness-section-head">
            <h3>学习路径</h3>
            <span>{result.learning_path.total_steps} steps</span>
          </div>
          <div className="harness-path">
            {result.learning_path.steps.map((step) => (
              <div key={step.node_id} className="harness-path-step">
                <span>{step.order}</span>
                <div>
                  <strong>{step.title}</strong>
                  <p>{step.reason}</p>
                </div>
                <em>{step.status === "verified" ? "已验证" : "待确认"}</em>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="harness-section">
        <div className="harness-section-head">
          <h3>验证与反馈闭环</h3>
          <span>{checks.filter((c) => c.passed).length}/{checks.length} checks</span>
        </div>
        <div className="harness-checks">
          {checks.map((check) => (
            <span key={check.name} className={check.passed ? "ok" : "fail"}>
              {check.passed ? "✓" : "!"} {check.name}
            </span>
          ))}
        </div>
        {warnings.length > 0 && (
          <div className="harness-report warn">
            {warnings.slice(0, 4).map((item) => (
              <p key={`${item.code}-${item.message}`}>{item.code}: {item.message}</p>
            ))}
          </div>
        )}
        {errors.length > 0 && (
          <div className="harness-report fail">
            {errors.map((item) => (
              <p key={`${item.code}-${item.message}`}>{item.code}: {item.message}</p>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
