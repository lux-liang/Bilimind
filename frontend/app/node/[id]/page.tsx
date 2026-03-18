"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { treeApi, NodeDetail, LearningPathResponse } from "@/lib/api";
import NavSidebar from "@/components/NavSidebar";

export default function NodeDetailPage() {
  const params = useParams();
  const nodeId = Number(params.id);
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [path, setPath] = useState<LearningPathResponse | null>(null);
  const [pathMode, setPathMode] = useState<"beginner" | "standard" | "quick">("standard");
  const [pathLoading, setPathLoading] = useState(false);

  useEffect(() => {
    if (!nodeId) return;
    treeApi.getNodeDetail(nodeId)
      .then(setDetail)
      .catch((e) => console.error("Failed to load node:", e))
      .finally(() => setLoading(false));
  }, [nodeId]);

  if (loading) return <div className="loading-state">Loading...</div>;
  if (!detail) return <div className="loading-state">Node not found.</div>;

  const stars = Array.from({ length: detail.difficulty }, () => "\u25CF").join("");

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <span className="brand-title">BiliMind</span>
        </div>
      </header>
      <main className="app-main">
        <div className="app-with-nav">
          <NavSidebar />
          <div className="app-content">
            <Link href="/tree" className="detail-back">&larr; Back to tree</Link>

            <div className="detail-header">
              <h1>{detail.name}</h1>
              <div className="detail-meta">
                <span className={`node-badge ${detail.node_type}`}>{detail.node_type}</span>
                {detail.difficulty > 0 && <span className="node-stars">{stars}</span>}
                <span>Confidence: {(detail.confidence * 100).toFixed(0)}%</span>
                <span>{detail.source_count} sources</span>
                <span>Status: {detail.review_status}</span>
              </div>
            </div>

            {detail.definition && (
              <div className="detail-section">
                <h2>Definition</h2>
                <p>{detail.definition}</p>
              </div>
            )}

            {detail.tree_position && detail.tree_position.length > 0 && (
              <div className="detail-section">
                <h2>Position in Tree</h2>
                <div className="breadcrumb">
                  {detail.tree_position.map((item, i) => (
                    <span key={item.id}>
                      {i > 0 && <span className="breadcrumb-sep"> &gt; </span>}
                      <Link href={`/node/${item.id}`}>{item.name}</Link>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {detail.main_topic && (
              <div className="detail-section">
                <h2>Main Topic</h2>
                <Link href={`/node/${detail.main_topic.id}`} className="node-link">
                  {detail.main_topic.name}
                </Link>
              </div>
            )}

            {detail.related_topics.length > 0 && (
              <div className="detail-section">
                <h2>Related Topics</h2>
                <div className="node-link-list">
                  {detail.related_topics.map((t) => (
                    <Link key={t.id} href={`/node/${t.id}`} className="node-link">{t.name}</Link>
                  ))}
                </div>
              </div>
            )}

            {detail.prerequisites.length > 0 && (
              <div className="detail-section">
                <h2>Prerequisites</h2>
                <div className="node-link-list">
                  {detail.prerequisites.map((n) => (
                    <Link key={n.id} href={`/node/${n.id}`} className="node-link">{n.name}</Link>
                  ))}
                </div>
              </div>
            )}

            {detail.successors.length > 0 && (
              <div className="detail-section">
                <h2>Next Steps</h2>
                <div className="node-link-list">
                  {detail.successors.map((n) => (
                    <Link key={n.id} href={`/node/${n.id}`} className="node-link">{n.name}</Link>
                  ))}
                </div>
              </div>
            )}

            {detail.related_nodes.length > 0 && (
              <div className="detail-section">
                <h2>Related</h2>
                <div className="node-link-list">
                  {detail.related_nodes.map((n) => (
                    <Link key={n.id} href={`/node/${n.id}`} className="node-link">
                      <span className={`node-badge ${n.node_type}`}>{n.node_type}</span>
                      {n.name}
                    </Link>
                  ))}
                </div>
              </div>
            )}

            {detail.videos.length > 0 && (
              <div className="detail-section">
                <h2>Related Videos</h2>
                {detail.videos.map((v) => (
                  <div key={v.bvid} className="video-card">
                    <Link href={`/video/${v.bvid}`} className="video-card-title">{v.title}</Link>
                    {v.owner_name && <div className="video-card-meta">UP: {v.owner_name}</div>}
                    {v.segments.map((seg, i) => (
                      <div key={i} className="segment-item">
                        <span className="segment-time">
                          {seg.time_label ? (
                            <a href={`${v.url}?t=${Math.floor(seg.start_time || 0)}`} target="_blank" rel="noopener noreferrer">
                              {seg.time_label}
                            </a>
                          ) : "--:--"}
                        </span>
                        <span className="segment-text">{seg.text}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}

            {/* Learning Path */}
            <div className="detail-section">
              <h2>Learning Path</h2>
              <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                {(["beginner", "standard", "quick"] as const).map((m) => (
                  <button
                    key={m}
                    className={`btn ${pathMode === m ? "btn-primary" : "btn-outline"}`}
                    style={{ fontSize: 13, padding: "6px 12px" }}
                    onClick={() => {
                      setPathMode(m);
                      setPathLoading(true);
                      treeApi.getLearningPath(nodeId, m)
                        .then(setPath)
                        .catch(() => {})
                        .finally(() => setPathLoading(false));
                    }}
                  >
                    {m === "beginner" ? "Beginner" : m === "standard" ? "Standard" : "Quick Review"}
                  </button>
                ))}
              </div>
              {pathLoading && <div className="loading-state">Generating path...</div>}
              {path && !pathLoading && (
                <div className="path-steps">
                  {path.steps.length === 0 ? (
                    <p style={{ color: "#6b6560", fontSize: 13 }}>No prerequisite steps needed.</p>
                  ) : (
                    path.steps.map((step) => (
                      <div key={step.order} className="path-step" style={{
                        display: "flex", gap: 12, padding: "10px 0",
                        borderBottom: "1px solid rgba(0,0,0,0.06)",
                        opacity: step.is_optional ? 0.7 : 1,
                      }}>
                        <span style={{ fontWeight: 600, color: "#d98b2b", minWidth: 24 }}>{step.order}</span>
                        <div style={{ flex: 1 }}>
                          <Link href={`/node/${step.node_id}`} className="kp-name">{step.name}</Link>
                          <span className={`node-badge ${step.node_type}`} style={{ marginLeft: 8 }}>{step.node_type}</span>
                          <span className="node-stars" style={{ marginLeft: 6 }}>
                            {Array.from({ length: step.difficulty }, () => "\u25CF").join("")}
                          </span>
                          {step.is_optional && <span className="node-meta" style={{ marginLeft: 6 }}>(optional)</span>}
                          <div style={{ fontSize: 13, color: "#6b6560", marginTop: 2 }}>{step.reason}</div>
                          {step.videos && step.videos.length > 0 && (
                            <div style={{ marginTop: 4 }}>
                              {step.videos.map((v) => (
                                <span key={v.bvid} style={{ fontSize: 12, marginRight: 8 }}>
                                  <a href={v.url} target="_blank" rel="noopener noreferrer" style={{ color: "#2f7c78" }}>{v.title}</a>
                                  {v.segments.map((s, i) => s.url ? (
                                    <a key={i} className="kp-time-badge" href={s.url} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 4 }}>{s.time_label}</a>
                                  ) : null)}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                  {path.total_steps > 0 && (
                    <div style={{ fontSize: 13, color: "#6b6560", marginTop: 8 }}>
                      {path.total_steps} steps, {path.estimated_videos} with videos
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
