"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import NavSidebar from "@/components/NavSidebar";
import KnowledgeTree from "@/components/KnowledgeTree";
import KnowledgeGraph3D from "@/components/KnowledgeGraph3D";
import ImportUrlModal from "@/components/ImportUrlModal";
import AIAssistant from "@/components/AIAssistant";
import { treeApi, TreeStats, NodeDetail, knowledgeApi, BuildStatus } from "@/lib/api";
import {
  isActiveSession,
  useAuthSession,
  readKnowledgeBuildTask,
  writeKnowledgeBuildTask,
  KnowledgeBuildTaskSnapshot,
} from "@/lib/session";
import UserTopbar from "@/components/UserTopbar";
import Link from "next/link";

type TreePageStatus =
  | "login"
  | "loading"
  | "building"
  | "failed"
  | "empty"
  | "indexed_no_nodes"
  | "ready";

export default function TreePage() {
  const { sessionId, scopeKey } = useAuthSession();
  const [stats, setStats] = useState<TreeStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [nodeDetail, setNodeDetail] = useState<NodeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [treeCollapsed, setTreeCollapsed] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [treeKey, setTreeKey] = useState(0);
  const [viewMode, setViewMode] = useState<"tree" | "graph3d">("tree");
  const [colorMode, setColorMode] = useState<"type" | "community">("type");
  const [buildTask, setBuildTask] = useState<KnowledgeBuildTaskSnapshot | null>(null);
  const detailRequestId = useRef(0);
  const statsRequestId = useRef(0);
  const buildPollId = useRef(0);

  const refreshStats = useCallback((activeSessionId?: string | null) => {
    const sid = activeSessionId ?? sessionId;
    if (!sid) {
      setStats(null);
      setStatsLoading(false);
      return;
    }
    const requestId = ++statsRequestId.current;
    setStatsLoading(true);
    treeApi.getStats(sid)
      .then((data) => {
        if (statsRequestId.current === requestId && isActiveSession(sid)) {
          setStats(data);
        }
      })
      .catch(() => {
        if (statsRequestId.current === requestId && isActiveSession(sid)) {
          setStats(null);
        }
      })
      .finally(() => {
        if (statsRequestId.current === requestId && isActiveSession(sid)) {
          setStatsLoading(false);
        }
      });
  }, [sessionId]);

  useEffect(() => {
    setStats(null);
    setStatsLoading(false);
    setSelectedNodeId(null);
    setNodeDetail(null);
    setDetailLoading(false);
    setBuildTask(readKnowledgeBuildTask(sessionId));
    setTreeKey((k) => k + 1);

    if (!sessionId) {
      return;
    }
    refreshStats(sessionId);
  }, [sessionId, scopeKey, refreshStats]);

  useEffect(() => {
    if (!sessionId) {
      setBuildTask(null);
      return;
    }

    const syncTask = () => setBuildTask(readKnowledgeBuildTask(sessionId));
    syncTask();
    window.addEventListener("storage", syncTask);
    window.addEventListener("bilimind:build-task-change", syncTask);
    return () => {
      window.removeEventListener("storage", syncTask);
      window.removeEventListener("bilimind:build-task-change", syncTask);
    };
  }, [sessionId, scopeKey]);

  useEffect(() => {
    if (!sessionId || !buildTask || !buildTask.taskId) {
      return;
    }
    if (buildTask.status !== "pending" && buildTask.status !== "running") {
      return;
    }

    const pollId = ++buildPollId.current;
    const activeSessionId = sessionId;
    let cancelled = false;

    const poll = async () => {
      try {
        const status: BuildStatus = await knowledgeApi.getBuildStatus(buildTask.taskId, activeSessionId);
        if (cancelled || buildPollId.current !== pollId || !isActiveSession(activeSessionId)) {
          return;
        }
        const snapshot: KnowledgeBuildTaskSnapshot = {
          taskId: status.task_id,
          status: status.status,
          message: status.message,
          progress: status.progress,
          currentStep: status.current_step,
          updatedAt: Date.now(),
        };
        writeKnowledgeBuildTask(activeSessionId, snapshot);
        setBuildTask(snapshot);

        if (status.status === "pending" || status.status === "running") {
          setTimeout(poll, 1200);
          return;
        }

        refreshStats(activeSessionId);
        setTreeKey((k) => k + 1);
      } catch {
        if (cancelled || buildPollId.current !== pollId || !isActiveSession(activeSessionId)) {
          return;
        }
        const failedTask: KnowledgeBuildTaskSnapshot = {
          taskId: buildTask.taskId,
          status: "failed",
          message: "构建状态获取失败，请稍后重试",
          progress: buildTask.progress,
          currentStep: buildTask.currentStep,
          updatedAt: Date.now(),
        };
        writeKnowledgeBuildTask(activeSessionId, failedTask);
        setBuildTask(failedTask);
      }
    };

    void poll();
    return () => {
      cancelled = true;
    };
  }, [sessionId, buildTask?.taskId, buildTask?.status, refreshStats]);

  const handleNodeSelect = useCallback((nodeId: number) => {
    setSelectedNodeId(nodeId);
    if (nodeId <= 0) {
      setNodeDetail(null);
      return;
    }
    if (!sessionId) {
      setNodeDetail(null);
      return;
    }
    const requestId = ++detailRequestId.current;
    const activeSessionId = sessionId;
    setDetailLoading(true);
    treeApi
      .getNodeDetail(nodeId)
      .then((detail) => {
        if (detailRequestId.current === requestId && isActiveSession(activeSessionId)) {
          setNodeDetail(detail);
        }
      })
      .catch(() => setNodeDetail(null))
      .finally(() => {
        if (detailRequestId.current === requestId && isActiveSession(activeSessionId)) {
          setDetailLoading(false);
        }
      });
  }, [sessionId]);

  const hasTreeData = (stats?.total_nodes || 0) > 0;
  const hasIndexedData = (stats?.total_segments || 0) > 0 || (stats?.total_videos || 0) > 0;
  let pageStatus: TreePageStatus = "login";
  if (sessionId) {
    if (statsLoading && !stats) {
      pageStatus = "loading";
    } else if (hasTreeData) {
      pageStatus = "ready";
    } else if (buildTask?.status === "pending" || buildTask?.status === "running") {
      pageStatus = "building";
    } else if (buildTask?.status === "failed") {
      pageStatus = "failed";
    } else if (hasIndexedData) {
      pageStatus = "indexed_no_nodes";
    } else {
      pageStatus = "empty";
    }
  }

  const treeStateCard = (() => {
    if (pageStatus === "loading") {
      return <div className="loading-state">正在加载当前账号的知识树状态...</div>;
    }
    if (pageStatus === "login") {
      return (
        <div className="tree-empty">
          <p>当前未登录</p>
          <p>请先扫码登录，再查看当前账号的知识树。</p>
          <p><Link href="/">回到首页登录</Link></p>
        </div>
      );
    }
    if (pageStatus === "building") {
      return (
        <div className="tree-empty">
          <p>当前账号正在构建知识图谱</p>
          <p>{buildTask?.currentStep || "正在抽取知识点和构建知识树，请稍候。"}</p>
          <p>进度 {Math.round(buildTask?.progress || 0)}%</p>
        </div>
      );
    }
    if (pageStatus === "failed") {
      return (
        <div className="tree-empty">
          <p>当前账号的知识树构建失败</p>
          <p>{buildTask?.message || "请前往知识问答页的来源面板重新发起构建。"}</p>
          <p><Link href="/chat">前往知识问答页重新构建</Link></p>
        </div>
      );
    }
    if (pageStatus === "indexed_no_nodes") {
      return (
        <div className="tree-empty">
          <p>当前账号已入库，但尚未抽取到知识节点</p>
          <p>你已有视频与片段数据；请前往知识问答页点击“更新”，重跑知识抽取。</p>
          <p><Link href="/chat">前往知识问答页更新抽取</Link></p>
        </div>
      );
    }
    return (
      <div className="tree-empty">
        <p>当前账号暂无知识树</p>
        <p>请先选择收藏夹并开始构建；在数据准备好前，不会展示旧账号内容。</p>
        <p><Link href="/chat">前往知识问答页开始构建</Link></p>
      </div>
    );
  })();

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
            <span className="brand-title">Bilimind</span>
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
            {/* 左：知识树/图谱面板 */}
            <div className={`tree-panel-left ${treeCollapsed ? "collapsed" : ""} ${viewMode === "graph3d" ? "graph3d-mode" : ""}`}
                 style={viewMode === "graph3d" && !treeCollapsed ? { flex: "1 1 0", maxWidth: "none", minWidth: 0 } : undefined}>
              <div className="tree-panel-header">
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <h3>{viewMode === "tree" ? "知识树导航" : "3D 知识图谱"}</h3>
                  <div className="view-toggle">
                    <button
                      className={`view-toggle-btn ${viewMode === "tree" ? "active" : ""}`}
                      onClick={() => setViewMode("tree")}
                    >
                      列表
                    </button>
                    <button
                      className={`view-toggle-btn ${viewMode === "graph3d" ? "active" : ""}`}
                      onClick={() => setViewMode("graph3d")}
                    >
                      3D 图谱
                    </button>
                  </div>
                  {viewMode === "graph3d" && (
                    <button
                      className="color-mode-toggle"
                      onClick={() => setColorMode(colorMode === "type" ? "community" : "type")}
                    >
                      {colorMode === "type" ? "按类型" : "按社区"}
                    </button>
                  )}
                </div>
                <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                  <button
                    className="btn-icon-mini"
                    onClick={() => setImportModalOpen(true)}
                    title="导入内容（URL）"
                    style={{ fontSize: 14 }}
                  >
                    +
                  </button>
                  <button className="btn-icon-mini" onClick={() => setTreeCollapsed(!treeCollapsed)} title={treeCollapsed ? "展开" : "折叠"}>
                    {treeCollapsed ? "→" : "←"}
                  </button>
                </div>
              </div>
              {!treeCollapsed && viewMode === "tree" && pageStatus === "ready" && (
                <KnowledgeTree
                  key={`${scopeKey}-${treeKey}`}
                  sessionId={sessionId}
                  onNodeSelect={handleNodeSelect}
                  selectedNodeId={selectedNodeId}
                />
              )}
              {!treeCollapsed && viewMode === "graph3d" && pageStatus === "ready" && (
                <KnowledgeGraph3D
                  key={`${scopeKey}-${treeKey}`}
                  sessionId={sessionId}
                  onNodeSelect={handleNodeSelect}
                  selectedNodeId={selectedNodeId}
                  colorMode={colorMode}
                />
              )}
              {!treeCollapsed && pageStatus !== "ready" && treeStateCard}
            </div>

            {/* 中：节点工作台 */}
            <div className="tree-panel-center">
              {pageStatus !== "ready" ? (
                <div className="center-placeholder">
                  <div className="placeholder-illustration">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.2">
                      <circle cx="12" cy="8" r="3" />
                      <circle cx="6" cy="18" r="2.5" />
                      <circle cx="18" cy="18" r="2.5" />
                      <path d="M12 11v3M8.5 16l2-2M15.5 16l-2-2" />
                    </svg>
                  </div>
                  <h3 className="placeholder-title">
                    {pageStatus === "building" ? "正在为当前账号构建知识树" : "当前账号暂时没有可浏览的知识树"}
                  </h3>
                  <p className="placeholder-desc">
                    {pageStatus === "building"
                      ? (buildTask?.currentStep || "正在抽取知识点、建立节点关系并整理视频证据。")
                      : pageStatus === "failed"
                        ? (buildTask?.message || "构建未成功，请重新发起构建。")
                        : pageStatus === "indexed_no_nodes"
                          ? "当前账号已有入库数据，但还未产出知识节点。请在知识问答页点击“更新”重跑抽取。"
                        : "在当前账号数据准备好之前，这里不会展示任何旧账号内容。"}
                  </p>
                </div>
              ) : detailLoading ? (
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
                {pageStatus !== "ready" ? (
                  <div className="evidence-empty">
                    <p>
                      {pageStatus === "building"
                        ? "知识树构建中，视频证据将在当前账号的数据准备好后显示"
                        : "当前账号暂无可展示的视频证据"}
                    </p>
                  </div>
                ) : nodeDetail && nodeDetail.videos.length > 0 ? (
                  <div className="evidence-list">
                    {nodeDetail.videos.map((v, vi) => (
                      <div key={v.bvid} className={`evidence-card ${vi === 0 ? "evidence-primary" : ""}`}>
                        {vi === 0 && <div className="evidence-badge">代表视频</div>}
                        <h5 className="evidence-title">
                          <Link href={`/video/${v.bvid}`}>{v.title}</Link>
                        </h5>
                        {v.owner_name && <span className="evidence-owner">UP: {v.owner_name}</span>}
                        <div className="evidence-meta" style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap" }}>
                          <span className="status-pill ok">匹配分 {Math.round((v.evidence_score || 0) * 100)}%</span>
                          {v.segments?.[0]?.confidence_level === "medium" && (
                            <span className="status-pill pending">中置信</span>
                          )}
                        </div>
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
                                title={seg.match_reason ? `${seg.match_reason} · ${seg.text?.slice(0, 100) || ""}` : seg.text ? seg.text.slice(0, 100) : undefined}
                              >
                                <span className="jump-play">▶</span>
                                <span className="jump-time">{seg.time_label}</span>
                              </a>
                            ))}
                          </div>
                        )}
                        {v.segments?.[0]?.match_reason && (
                          <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 6 }}>
                            {v.segments[0].match_reason}
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
                    <p>暂无高置信视频证据</p>
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
      <ImportUrlModal
        open={importModalOpen}
        onClose={() => setImportModalOpen(false)}
        onSuccess={() => {
          setTreeKey((k) => k + 1);
          refreshStats(sessionId);
        }}
      />
      <AIAssistant />
    </div>
  );
}
