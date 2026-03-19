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

  const formatTime = (seconds?: number) => {
    if (seconds === undefined || seconds === null) return "";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <div className="brand-mark">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 3v18M12 7l-4 4M12 7l4 4M12 13l-6 5M12 13l6 5" />
            </svg>
          </div>
          <div>
            <span className="brand-title">BiliMind</span>
            <span className="brand-subtitle">知识树</span>
          </div>
        </div>
        <div className="topbar-actions">
          {stats && (
            <span className="user-chip">
              <span>{stats.total_nodes} 知识点</span>
              <strong>{stats.total_videos} 视频</strong>
            </span>
          )}
          <UserTopbar />
        </div>
      </header>
      <main className="app-main">
        <div className="app-with-nav">
          <NavSidebar />
          <div className="tree-three-column">
            {/* 左栏：知识树导航 */}
            <div className="tree-col-left">
              <KnowledgeTree onNodeSelect={handleNodeSelect} selectedNodeId={selectedNodeId} />
            </div>

            {/* 中栏：知识节点工作台 */}
            <div className="tree-col-center">
              {detailLoading ? (
                <div className="tree-placeholder">加载中...</div>
              ) : nodeDetail ? (
                <div className="node-preview">
                  {/* 头部信息 */}
                  <div className="node-preview-header">
                    <span className={`node-type-badge badge-${nodeDetail.node_type}`}>{nodeDetail.node_type}</span>
                    <h3>{nodeDetail.name}</h3>
                    <div className="node-meta-row">
                      <span className="meta-item">难度 {"★".repeat(nodeDetail.difficulty)}{"☆".repeat(5 - nodeDetail.difficulty)}</span>
                      <span className="meta-item">置信度 {Math.round(nodeDetail.confidence * 100)}%</span>
                      <span className="meta-item">{nodeDetail.source_count} 来源</span>
                      {nodeDetail.review_status && nodeDetail.review_status !== "auto" && (
                        <span className="meta-item">{nodeDetail.review_status === "approved" ? "已审核" : "待审核"}</span>
                      )}
                    </div>
                  </div>

                  {/* 定义区 */}
                  {nodeDetail.definition && (
                    <p className="node-definition">{nodeDetail.definition}</p>
                  )}

                  {/* 所属主题 */}
                  {nodeDetail.main_topic && (
                    <div className="node-section">
                      <h4>所属主题</h4>
                      <div className="node-tags">
                        <span className="node-tag clickable" onClick={() => handleNodeSelect(nodeDetail.main_topic!.id)}>
                          {nodeDetail.main_topic.name}
                        </span>
                      </div>
                    </div>
                  )}

                  {/* 前置知识 */}
                  {nodeDetail.prerequisites.length > 0 && (
                    <div className="node-section">
                      <h4>前置知识</h4>
                      <div className="node-tags">
                        {nodeDetail.prerequisites.map((p) => (
                          <span key={p.id} className="node-tag clickable" onClick={() => handleNodeSelect(p.id)}>
                            {p.name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* 后续知识 */}
                  {nodeDetail.successors.length > 0 && (
                    <div className="node-section">
                      <h4>后续知识</h4>
                      <div className="node-tags">
                        {nodeDetail.successors.map((s) => (
                          <span key={s.id} className="node-tag clickable" onClick={() => handleNodeSelect(s.id)}>
                            {s.name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* 相关知识 */}
                  {nodeDetail.related_nodes.length > 0 && (
                    <div className="node-section">
                      <h4>相关知识</h4>
                      <div className="node-tags">
                        {nodeDetail.related_nodes.map((r) => (
                          <span key={r.id} className="node-tag clickable" onClick={() => handleNodeSelect(r.id)}>
                            <small className="node-type-mini">{r.node_type}</small> {r.name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* 别名 */}
                  {nodeDetail.aliases && nodeDetail.aliases.length > 0 && (
                    <div className="node-section">
                      <h4>别名</h4>
                      <div className="node-tags">
                        {nodeDetail.aliases.map((a, i) => (
                          <span key={i} className="node-tag">{a}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* 学习动作区 */}
                  <div className="node-preview-footer">
                    <Link href={`/node/${nodeDetail.id}`} className="btn btn-sm btn-outline">
                      查看完整详情
                    </Link>
                    <Link href={`/learning-path?target=${encodeURIComponent(nodeDetail.name)}`} className="btn btn-sm btn-primary">
                      生成学习路径
                    </Link>
                    {nodeDetail.videos.length > 0 && (
                      <Link href={`/video/${nodeDetail.videos[0].bvid}`} className="btn btn-sm btn-ghost">
                        查看代表视频
                      </Link>
                    )}
                  </div>
                </div>
              ) : (
                <div className="tree-placeholder">
                  <div style={{ textAlign: "center" }}>
                    <p style={{ fontSize: 16, marginBottom: 4 }}>选择知识节点</p>
                    <p style={{ fontSize: 13, color: "var(--text-tertiary)" }}>点击左侧知识树中的节点查看详情、关联视频和学习路径</p>
                  </div>
                </div>
              )}
            </div>

            {/* 右栏：证据与资源区 */}
            <div className="tree-col-right">
              {nodeDetail && nodeDetail.videos.length > 0 ? (
                <div className="evidence-panel">
                  <h4>证据与资源</h4>
                  <div className="evidence-subtitle">
                    {nodeDetail.videos.length} 个视频提及此知识点，点击时间片段跳转到 B 站对应位置
                  </div>
                  {nodeDetail.videos.map((v) => (
                    <div key={v.bvid} className="video-card-mini">
                      <Link href={`/video/${v.bvid}`} className="video-card-title">
                        {v.title}
                      </Link>
                      {v.owner_name && <span className="video-card-owner">UP: {v.owner_name}</span>}
                      {v.segments && v.segments.length > 0 && (
                        <div className="video-segments-list">
                          {v.segments.map((seg, i) => (
                            <a
                              key={i}
                              href={`https://www.bilibili.com/video/${v.bvid}?t=${Math.floor(seg.start_time || 0)}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="jump-bilibili-btn"
                              title={seg.text ? seg.text.slice(0, 80) : ""}
                            >
                              ▶ {seg.time_label}
                            </a>
                          ))}
                        </div>
                      )}
                      {v.segments && v.segments.length > 0 && v.segments[0].text && (
                        <div className="segment-summary">
                          {v.segments[0].text.slice(0, 120)}...
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : nodeDetail ? (
                <div className="tree-placeholder">
                  <p>该知识点暂无关联视频证据</p>
                </div>
              ) : (
                <div className="tree-placeholder">
                  <div style={{ textAlign: "center" }}>
                    <p style={{ fontSize: 14, marginBottom: 4 }}>视频证据</p>
                    <p style={{ fontSize: 12, color: "var(--text-tertiary)" }}>选择节点后显示关联视频和可跳转的时间片段</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
