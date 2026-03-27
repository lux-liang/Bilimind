"use client";

import { useState, useEffect, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import NavSidebar from "@/components/NavSidebar";
import UserTopbar from "@/components/UserTopbar";
import KnowledgeGraph3D from "@/components/KnowledgeGraph3D";
import Link from "next/link";
import AIAssistant from "@/components/AIAssistant";
import {
  learningPathApi,
  LearningPathResponse,
  LearningPathStep,
  PopularTopic,
} from "@/lib/api";
import { useAuthSession } from "@/lib/session";

export default function LearningPathPage() {
  return (
    <Suspense>
      <LearningPathContent />
    </Suspense>
  );
}

function LearningPathContent() {
  const searchParams = useSearchParams();
  const initialTarget = searchParams.get("target") || "";
  const { sessionId, scopeKey } = useAuthSession();

  const [query, setQuery] = useState(initialTarget);
  const [mode, setMode] = useState<"beginner" | "standard" | "quick">("standard");
  const [path, setPath] = useState<LearningPathResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [popularTopics, setPopularTopics] = useState<PopularTopic[]>([]);
  const [focusedStepId, setFocusedStepId] = useState<number | null>(null);

  // 从路径步骤中提取节点 ID 列表（用于 3D 图谱高亮）
  const pathNodeIds = useMemo(() => {
    if (!path) return [];
    return path.steps.map((s) => s.node_id);
  }, [path]);

  useEffect(() => {
    setPath(null);
    setError("");
    setFocusedStepId(null);
    setLoading(false);
    setPopularTopics([]);
    if (!sessionId) {
      return;
    }
    learningPathApi.getPopularTopics(12).then(setPopularTopics).catch(() => {});
  }, [sessionId, scopeKey]);

  // 如果从知识树页面带了 target 参数，自动生成
  useEffect(() => {
    if (initialTarget && sessionId) {
      handleGenerate(initialTarget);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, scopeKey]);

  const handleGenerate = async (target?: string) => {
    const t = (target || query).trim();
    if (!t || !sessionId) return;
    setQuery(t);
    setLoading(true);
    setError("");
    setPath(null);
    try {
      const result = await learningPathApi.generate({ target: t, mode });
      setPath(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "生成路径失败，请检查是否配置了 DashScope API Key");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <div className="brand-mark">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="5" cy="6" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="18" r="2" />
              <path d="M7 7l3 3M14 13l3 3" />
            </svg>
          </div>
          <div>
            <span className="brand-title">BiliMind</span>
            <span className="brand-subtitle">学习路径</span>
          </div>
        </div>
        <div className="topbar-actions">
          <UserTopbar />
        </div>
      </header>
      <main className="app-main">
        <div className="app-with-nav">
          <NavSidebar />
          <div className="app-content" style={{ maxWidth: 900, margin: "0 auto", padding: "24px 16px" }}>
            <div className="learning-path-hero">
              <h2>学习路径规划器</h2>
              <p>输入目标知识点，自动生成从基础到目标的学习路线，每步附带视频证据和可跳转时间片段</p>
            </div>

            {!sessionId && (
              <div className="tree-empty" style={{ marginBottom: 20 }}>
                <p>请先登录后生成当前账号的学习路径</p>
              </div>
            )}

            {/* 输入区 */}
            <div className="path-input-bar">
              <input
                className="search-input"
                style={{ flex: 1 }}
                type="text"
                placeholder="输入目标知识点，如: 机器学习、React Hooks、动态规划..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleGenerate()}
              />
              <select
                className="tree-filter"
                value={mode}
                onChange={(e) => setMode(e.target.value as "beginner" | "standard" | "quick")}
                style={{ padding: "8px 12px" }}
              >
                <option value="beginner">入门路径</option>
                <option value="standard">标准路径</option>
                <option value="quick">快速复习</option>
              </select>
              <button className="btn btn-primary" onClick={() => handleGenerate()} disabled={loading || !query.trim() || !sessionId}>
                {loading ? "生成中..." : "生成路径"}
              </button>
            </div>

            {/* 热门主题 */}
            {!path && popularTopics.length > 0 && (
              <div className="topics-grid">
                {popularTopics.map((t) => (
                  <button
                    key={t.id}
                    className="topic-chip"
                    onClick={() => { setQuery(t.name); handleGenerate(t.name); }}
                  >
                    {t.name}
                    <small style={{ marginLeft: 4, opacity: 0.6 }}>({t.video_count})</small>
                  </button>
                ))}
              </div>
            )}

            {/* 错误 */}
            {error && (
              <div style={{ padding: 12, background: "rgba(220, 38, 38, 0.06)", border: "1px solid rgba(220, 38, 38, 0.2)", borderRadius: "var(--radius)", color: "var(--danger)", marginBottom: 16, fontSize: 14 }}>
                {error}
              </div>
            )}

            {/* 路径结果：左右分栏 */}
            {path && (
              <div className="learning-path-result">
                <div className="path-result-header">
                  <h3>学习路径: {path.target.name}</h3>
                  <span className={`node-type-badge badge-${path.target.node_type}`}>{path.target.node_type}</span>
                  <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                    {path.total_steps} 步 · {path.estimated_videos} 个视频 · {mode === "beginner" ? "入门" : mode === "quick" ? "快速" : "标准"}模式
                  </span>
                </div>

                {path.summary && (
                  <div className="path-metrics-grid">
                    <div className="path-metric-card">
                      <span className="path-metric-label">路径模式</span>
                      <strong>{path.summary.mode_label}</strong>
                    </div>
                    <div className="path-metric-card">
                      <span className="path-metric-label">平均路径优先级</span>
                      <strong>{path.summary.avg_priority_score.toFixed(2)}</strong>
                    </div>
                    <div className="path-metric-card">
                      <span className="path-metric-label">平均证据支撑</span>
                      <strong>{(path.summary.avg_evidence_score ?? path.summary.avg_support_score).toFixed(2)}</strong>
                    </div>
                    <div className="path-metric-card">
                      <span className="path-metric-label">直接前置节点</span>
                      <strong>{path.summary.direct_prerequisites}</strong>
                    </div>
                  </div>
                )}

                <div className="path-explanation">
                  该路径从基础概念出发，逐步递进到目标知识点「{path.target.name}」。
                  每一步都标注了推荐理由和关联视频，展开步骤可查看对应的视频片段。
                </div>

                <div className="path-split-view">
                  {/* 左侧：步骤卡片 */}
                  <div className="path-steps-panel">
                    <div className="path-steps">
                      {path.steps.map((step, i) => (
                        <PathStepCard
                          key={step.node_id}
                          step={step}
                          isLast={i === path.steps.length - 1}
                          isFocused={focusedStepId === step.node_id}
                          onFocus={() => setFocusedStepId(step.node_id)}
                        />
                      ))}
                    </div>
                  </div>

                  {/* 右侧：3D 图谱（高亮路径） */}
                  <div className="path-graph-panel">
                    <KnowledgeGraph3D
                      selectedNodeId={focusedStepId}
                      onNodeSelect={(id) => setFocusedStepId(id)}
                      highlightPath={pathNodeIds}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
      <AIAssistant />
    </div>
  );
}

function PathStepCard({ step, isLast, isFocused, onFocus }: { step: LearningPathStep; isLast: boolean; isFocused?: boolean; onFocus?: () => void }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`path-step${step.is_optional ? " path-step-optional" : ""}${isFocused ? " path-step-focused" : ""}`}>
      <div className="path-step-connector">
        <div className={`path-step-dot${isFocused ? " dot-focused" : ""}`} />
        {!isLast && <div className="path-step-line" />}
      </div>
      <div className="path-step-content" onClick={() => onFocus?.()}>
        <div className="path-step-header" onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); onFocus?.(); }}>
          <span className="path-step-order">{step.order}</span>
          <span className={`node-type-badge badge-${step.node_type}`}>{step.node_type}</span>
          <Link href={`/node/${step.node_id}`} className="path-step-name" onClick={(e) => e.stopPropagation()}>
            {step.name}
          </Link>
          <span className="node-stars">{"●".repeat(step.difficulty)}</span>
          {step.is_optional && <span className="path-optional-badge">可选</span>}
          {step.video_count > 0 && <span className="node-meta">{step.video_count} 视频</span>}
          <span className="path-expand">{expanded ? "▲" : "▼"}</span>
        </div>

        <p className="path-step-reason">{step.reason}</p>

        <div className="path-step-metrics">
          <span className="node-meta">路径分 {step.composite_score.toFixed(2)}</span>
          <span className="node-meta">支撑 {step.evidence_score.toFixed(2)}</span>
          <span className="node-meta">层级 {step.dependency_depth}</span>
          <span className={`path-support-badge support-${step.support_label}`}>
            {step.support_label === "strong" ? "证据强" : step.support_label === "medium" ? "证据中" : "证据弱"}
          </span>
        </div>

        {step.reason_tags && step.reason_tags.length > 0 && (
          <div className="path-step-tags">
            {step.reason_tags.map((tag) => (
              <span key={tag} className="path-reason-chip">{tag}</span>
            ))}
          </div>
        )}

        {step.definition && <p className="path-step-definition">{step.definition}</p>}

        {expanded && step.videos && step.videos.length > 0 && (
          <div className="path-step-videos">
            {step.videos.map((v) => (
              <div key={v.bvid} className="video-card-mini">
                <a href={v.url} target="_blank" rel="noopener noreferrer" className="video-card-title">
                  {v.title}
                </a>
                {v.segments && v.segments.length > 0 && (
                  <div className="video-segments-list">
                    {v.segments.map((seg, j) => (
                      <a
                        key={j}
                        href={seg.url || v.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="jump-bilibili-btn"
                      >
                        ▶ {seg.time_label}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {expanded && (!step.videos || step.videos.length === 0) && (
          <div style={{ fontSize: 13, color: "var(--text-tertiary)", marginTop: 8 }}>
            暂无关联视频
          </div>
        )}
      </div>
    </div>
  );
}
