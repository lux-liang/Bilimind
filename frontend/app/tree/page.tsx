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

  // 当用户在树中点击节点时加载详情
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
          <div className="brand-mark">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M12 3v18M12 7l-4 4M12 7l4 4M12 13l-6 5M12 13l6 5" />
            </svg>
          </div>
          <div>
            <span className="brand-title">BiliMind</span>
            <span className="brand-subtitle">知识树导航</span>
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
            {/* 左栏：知识树 */}
            <div className="tree-col-left">
              <KnowledgeTree onNodeSelect={handleNodeSelect} selectedNodeId={selectedNodeId} />
            </div>

            {/* 中栏：节点详情 */}
            <div className="tree-col-center">
              {detailLoading ? (
                <div className="tree-placeholder">加载中...</div>
              ) : nodeDetail ? (
                <div className="node-preview">
                  <div className="node-preview-header">
                    <span className={`node-type-badge badge-${nodeDetail.node_type}`}>{nodeDetail.node_type}</span>
                    <h3>{nodeDetail.name}</h3>
                    <div className="node-meta-row">
                      <span>难度 {"★".repeat(nodeDetail.difficulty)}{"☆".repeat(5 - nodeDetail.difficulty)}</span>
                      <span>置信度 {Math.round(nodeDetail.confidence * 100)}%</span>
                      <span>{nodeDetail.source_count} 来源</span>
                    </div>
                  </div>
                  {nodeDetail.definition && (
                    <p className="node-definition">{nodeDetail.definition}</p>
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

                  {/* 相关节点 */}
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

                  <div className="node-preview-footer">
                    <Link href={`/node/${nodeDetail.id}`} className="btn btn-sm">
                      查看完整详情 →
                    </Link>
                  </div>
                </div>
              ) : (
                <div className="tree-placeholder">
                  <p>← 点击左侧知识树中的节点查看详情</p>
                </div>
              )}
            </div>

            {/* 右栏：关联视频和片段 */}
            <div className="tree-col-right">
              {nodeDetail && nodeDetail.videos.length > 0 ? (
                <div className="video-list-panel">
                  <h4>关联视频 ({nodeDetail.videos.length})</h4>
                  {nodeDetail.videos.map((v) => (
                    <div key={v.bvid} className="video-card-mini">
                      <Link href={`/video/${v.bvid}`} className="video-card-title">
                        {v.title}
                      </Link>
                      {v.owner_name && <span className="video-card-owner">{v.owner_name}</span>}
                      {v.segments && v.segments.length > 0 && (
                        <div className="video-segments-list">
                          {v.segments.map((seg, i) => (
                            <a
                              key={i}
                              href={`https://www.bilibili.com/video/${v.bvid}?t=${Math.floor(seg.start_time || 0)}`}
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
              ) : nodeDetail ? (
                <div className="tree-placeholder">
                  <p>该知识点暂无关联视频</p>
                </div>
              ) : (
                <div className="tree-placeholder">
                  <p>选择节点后显示关联视频</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
