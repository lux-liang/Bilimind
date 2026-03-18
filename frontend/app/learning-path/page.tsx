"use client";

import { useState, useEffect } from "react";
import NavSidebar from "@/components/NavSidebar";
import UserTopbar from "@/components/UserTopbar";
import Link from "next/link";
import {
  learningPathApi,
  LearningPathResponse,
  LearningPathStep,
  PopularTopic,
} from "@/lib/api";

export default function LearningPathPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"beginner" | "standard" | "quick">("standard");
  const [path, setPath] = useState<LearningPathResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [popularTopics, setPopularTopics] = useState<PopularTopic[]>([]);

  useEffect(() => {
    learningPathApi.getPopularTopics(12).then(setPopularTopics).catch(() => {});
  }, []);

  const handleGenerate = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    setPath(null);
    try {
      const result = await learningPathApi.generate({ target: query.trim(), mode });
      setPath(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "生成路径失败");
    } finally {
      setLoading(false);
    }
  };

  const handleTopicClick = (name: string) => {
    setQuery(name);
  };

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <div className="brand-mark">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M9 20l-5.5-5.5L9 9M15 4l5.5 5.5L15 15" />
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
            <h2 style={{ fontSize: 22, fontWeight: 600, marginBottom: 8 }}>学习路径生成</h2>
            <p style={{ color: "var(--text-secondary)", marginBottom: 24 }}>
              输入你想学的知识点，自动生成从基础到目标的学习路径，每步附带视频和时间片段。
            </p>

            {/* 搜索区 */}
            <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
              <input
                className="tree-search"
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
              >
                <option value="beginner">入门路径</option>
                <option value="standard">标准路径</option>
                <option value="quick">快速复习</option>
              </select>
              <button className="btn btn-primary" onClick={handleGenerate} disabled={loading || !query.trim()}>
                {loading ? "生成中..." : "生成路径"}
              </button>
            </div>

            {/* 热门主题 */}
            {!path && popularTopics.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <h4 style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 8 }}>热门学习目标</h4>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {popularTopics.map((t) => (
                    <button
                      key={t.id}
                      className="node-tag clickable"
                      onClick={() => handleTopicClick(t.name)}
                      style={{ cursor: "pointer" }}
                    >
                      {t.name}
                      <small style={{ marginLeft: 4, opacity: 0.7 }}>({t.video_count} 视频)</small>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 错误 */}
            {error && (
              <div style={{ padding: 12, background: "#fff3f3", border: "1px solid #fcc", borderRadius: 8, color: "#c00", marginBottom: 16 }}>
                {error}
              </div>
            )}

            {/* 路径结果 */}
            {path && (
              <div className="learning-path-result">
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
                  <h3 style={{ fontSize: 18, fontWeight: 600 }}>
                    学习路径: {path.target.name}
                  </h3>
                  <span className={`node-type-badge badge-${path.target.node_type}`}>{path.target.node_type}</span>
                  <span style={{ color: "var(--text-secondary)", fontSize: 14 }}>
                    {path.total_steps} 步 · {path.estimated_videos} 个视频 · {path.mode === "beginner" ? "入门" : path.mode === "quick" ? "快速" : "标准"}模式
                  </span>
                </div>

                <div className="path-steps">
                  {path.steps.map((step, i) => (
                    <PathStepCard key={step.node_id} step={step} isLast={i === path.steps.length - 1} />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

function PathStepCard({ step, isLast }: { step: LearningPathStep; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`path-step${step.is_optional ? " path-step-optional" : ""}`}>
      <div className="path-step-connector">
        <div className="path-step-dot" />
        {!isLast && <div className="path-step-line" />}
      </div>
      <div className="path-step-content">
        <div className="path-step-header" onClick={() => setExpanded(!expanded)}>
          <span className="path-step-order">{step.order}</span>
          <span className={`node-type-badge badge-${step.node_type}`}>{step.node_type}</span>
          <Link href={`/node/${step.node_id}`} className="path-step-name">
            {step.name}
          </Link>
          <span className="node-stars">{"★".repeat(step.difficulty)}{"☆".repeat(5 - step.difficulty)}</span>
          {step.is_optional && <span className="path-optional-badge">可选</span>}
          {step.video_count > 0 && <span className="node-meta">{step.video_count} 视频</span>}
          <span className="path-expand">{expanded ? "▲" : "▼"}</span>
        </div>

        <p className="path-step-reason">{step.reason}</p>

        {step.definition && (
          <p className="path-step-definition">{step.definition}</p>
        )}

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
                        className="segment-chip"
                      >
                        {seg.time_label}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
