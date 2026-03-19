"use client";

import { useEffect, useState, useCallback } from "react";
import NavSidebar from "@/components/NavSidebar";
import KnowledgeTree from "@/components/KnowledgeTree";
import { treeApi, TreeStats, NodeDetail } from "@/lib/api";
import UserTopbar from "@/components/UserTopbar";
import Link from "next/link";

export default function TreePage() {
  const [stats, setStats] = useState<TreeStats | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [nodeDetail, setNodeDetail] = useState<NodeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [treeCollapsed, setTreeCollapsed] = useState(false);

  useEffect(() => {
    treeApi.getStats().then(setStats).catch(() => {});
  }, []);

  const handleNodeSelect = useCallback((nodeId: number) => {
    setSelectedNodeId(nodeId);
    if (nodeId <= 0) {
      setNodeDetail(null);
      return;
    }
    setDetailLoading(true);
    treeApi
      .getNodeDetail(nodeId)
      .then(setNodeDetail)
      .catch(() => setNodeDetail(null))
      .finally(() => setDetailLoading(false));
  }, []);

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <div className="landing-logo" style={{ width: 32, height: 32 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <circle cx="12" cy="8" r="3" />
              <circle cx="6" cy="18" r="2.5" />
              <circle cx="18" cy="18" r="2.5" />
              <path d="M12 11v3M8.5 16l2-2M15.5 16l-2-2" />
            </svg>
          </div>
          <div>
            <span className="brand-title">BiliMind</span>
            <span className="brand-subtitle">知识树</span>
          </div>
        </div>
        <div className="topbar-actions">
          {stats && (
            <div className="topbar-stats">
              <span className="topbar-stat"><strong>{stats.total_nodes}</strong> 知识点</span>
              <span className="topbar-stat"><strong>{stats.total_videos}</strong> 视频</span>
              <span className="topbar-stat"><strong>{stats.total_segments}</strong> 片段</span>
            </div>
          )}
          <UserTopbar />
        </div>
      </header>
      <main className="app-main">
        <div className="app-with-nav">
          <NavSidebar />
          <div className="tree-workspace">
            {/* 左：知识树面板 */}
            <div className={`tree-panel-left ${treeCollapsed ? "collapsed" : ""}`}>
              <div className="tree-panel-header">
                <h3>知识树导航</h3>
                <button className="btn-icon-mini" onClick={() => setTreeCollapsed(!treeCollapsed)} title={treeCollapsed ? "展开" : "折叠"}>
                  {treeCollapsed ? "→" : "←"}
                </button>
              </div>
              {!treeCollapsed && (
                <KnowledgeTree onNodeSelect={handleNodeSelect} selectedNodeId={selectedNodeId} />
              )}
            </div>

            {/* 中：节点工作台 */}
            <div className="tree-panel-center">
              {detailLoading ? (
                <div className="center-placeholder">
                  <div className="placeholder-spinner" />
                  <span>加载中...</span>
                </div>
              ) : nodeDetail ? (
                <div className="node-workspace">
                  {/* 面包屑 */}
                  {nodeDetail.tree_position && nodeDetail.tree_position.length > 0 && (
                    <div className="node-breadcrumb">
                      {nodeDetail.tree_position.map((pos, i) => (
                        <span key={pos.id}>
                          {i > 0 && <span className="breadcrumb-arrow">›</span>}
                          <span
                            className={`breadcrumb-item ${pos.id === nodeDetail.id ? "current" : "clickable"}`}
                            onClick={() => pos.id !== nodeDetail.id && handleNodeSelect(pos.id)}
                          >
                            {pos.name}
                          </span>
                        </span>
                      ))}
                    </div>
                  )}

                  {/* 节点卡片 */}
                  <div className="node-hero-card">
                    <div className="node-hero-top">
                      <span className={`node-type-pill pill-${nodeDetail.node_type}`}>{nodeDetail.node_type}</span>
                      <div className="node-hero-metrics">
                        <span className="metric">
                          <span className="metric-value">{"●".repeat(nodeDetail.difficulty)}</span>
                          <span className="metric-label">难度</span>
                        </span>
                        <span className="metric">
                          <span className="metric-value">{Math.round(nodeDetail.confidence * 100)}%</span>
                          <span className="metric-label">置信度</span>
                        </span>
                        <span className="metric">
                          <span className="metric-value">{nodeDetail.source_count}</span>
                          <span className="metric-label">来源</span>
                        </span>
                      </div>
                    </div>
                    <h2 className="node-hero-name">{nodeDetail.name}</h2>
                    {nodeDetail.definition && (
                      <p className="node-hero-def">{nodeDetail.definition}</p>
                    )}
                    <div className="node-hero-actions">
                      <Link href={`/node/${nodeDetail.id}`} className="btn btn-sm btn-outline">完整详情</Link>
                      <Link href={`/learning-path?target=${encodeURIComponent(nodeDetail.name)}`} className="btn btn-sm btn-primary">生成学习路径</Link>
                      {nodeDetail.videos.length > 0 && (
                        <a
                          href={`https://www.bilibili.com/video/${nodeDetail.videos[0].bvid}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn btn-sm btn-bilibili"
                        >
                          ▶ 去 B 站观看
                        </a>
                      )}
                    </div>
                  </div>

                  {/* 关系网络 */}
                  <div className="node-relations-grid">
                    {nodeDetail.prerequisites.length > 0 && (
                      <div className="relation-block">
                        <h4 className="relation-title">
                          <span className="relation-icon">↑</span> 前置知识
                        </h4>
                        <div className="relation-chips">
                          {nodeDetail.prerequisites.map((p) => (
                            <span key={p.id} className="relation-chip" onClick={() => handleNodeSelect(p.id)}>
                              {p.name}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {nodeDetail.successors.length > 0 && (
                      <div className="relation-block">
                        <h4 className="relation-title">
                          <span className="relation-icon">↓</span> 后续知识
                        </h4>
                        <div className="relation-chips">
                          {nodeDetail.successors.map((s) => (
                            <span key={s.id} className="relation-chip" onClick={() => handleNodeSelect(s.id)}>
                              {s.name}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {nodeDetail.related_nodes.length > 0 && (
                      <div className="relation-block">
                        <h4 className="relation-title">
                          <span className="relation-icon">↔</span> 相关知识
                        </h4>
                        <div className="relation-chips">
                          {nodeDetail.related_nodes.map((r) => (
                            <span key={r.id} className="relation-chip" onClick={() => handleNodeSelect(r.id)}>
                              <small className="chip-type">{r.node_type}</small>{r.name}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {nodeDetail.main_topic && (
                      <div className="relation-block">
                        <h4 className="relation-title">
                          <span className="relation-icon">◎</span> 所属主题
                        </h4>
                        <div className="relation-chips">
                          <span className="relation-chip topic-chip" onClick={() => handleNodeSelect(nodeDetail.main_topic!.id)}>
                            {nodeDetail.main_topic.name}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="center-placeholder">
                  <div className="placeholder-illustration">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.2">
                      <circle cx="12" cy="8" r="3" />
                      <circle cx="6" cy="18" r="2.5" />
                      <circle cx="18" cy="18" r="2.5" />
                      <path d="M12 11v3M8.5 16l2-2M15.5 16l-2-2" />
                    </svg>
                  </div>
                  <h3 className="placeholder-title">选择一个知识节点</h3>
                  <p className="placeholder-desc">在左侧知识树中点击节点，查看详情、关联关系和视频证据</p>
                </div>
              )}
            </div>

            {/* 右：视频证据面板 */}
            <div className="tree-panel-right">
              <div className="evidence-header">
                <h3>视频证据</h3>
                {nodeDetail && nodeDetail.videos.length > 0 && (
                  <span className="evidence-count">{nodeDetail.videos.length} 个视频</span>
                )}
              </div>
              <div className="evidence-body">
                {nodeDetail && nodeDetail.videos.length > 0 ? (
                  <div className="evidence-list">
                    {nodeDetail.videos.map((v, vi) => (
                      <div key={v.bvid} className={`evidence-card ${vi === 0 ? "evidence-primary" : ""}`}>
                        {vi === 0 && <div className="evidence-badge">代表视频</div>}
                        <h5 className="evidence-title">
                          <Link href={`/video/${v.bvid}`}>{v.title}</Link>
                        </h5>
                        {v.owner_name && <span className="evidence-owner">UP: {v.owner_name}</span>}
                        {v.segments && v.segments.length > 0 && (
                          <div className="evidence-segments">
                            <div className="evidence-seg-label">可跳转片段：</div>
                            {v.segments.map((seg, i) => (
                              <a
                                key={i}
                                href={`https://www.bilibili.com/video/${v.bvid}?t=${Math.floor(seg.start_time || 0)}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="evidence-jump"
                                title={seg.text ? seg.text.slice(0, 100) : undefined}
                              >
                                <span className="jump-play">▶</span>
                                <span className="jump-time">{seg.time_label}</span>
                              </a>
                            ))}
                          </div>
                        )}
                        {v.segments && v.segments[0]?.text && (
                          <p className="evidence-excerpt">{v.segments[0].text.slice(0, 150)}{v.segments[0].text.length > 150 ? "..." : ""}</p>
                        )}
                      </div>
                    ))}
                  </div>
                ) : nodeDetail ? (
                  <div className="evidence-empty">
                    <p>该知识点暂无关联视频证据</p>
                  </div>
                ) : (
                  <div className="evidence-empty">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.2">
                      <rect x="3" y="3" width="18" height="14" rx="2" />
                      <polygon points="10,7 10,13 15,10" />
                      <path d="M7 21h10M12 17v4" />
                    </svg>
                    <p>选择节点后<br />显示关联视频和可跳转时间片段</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
