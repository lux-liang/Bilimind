"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import NavSidebar from "@/components/NavSidebar";
import UserTopbar from "@/components/UserTopbar";
import { OrganizerReport, organizerApi } from "@/lib/api";
import { isActiveSession, useAuthSession } from "@/lib/session";

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="organizer-stat-card">
      <div className="organizer-stat-value">{value}</div>
      <div className="organizer-stat-label">{label}</div>
    </div>
  );
}

function formatDuration(seconds?: number): string {
  if (!seconds) return "--:--";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function OrganizerPage() {
  const { sessionId, scopeKey } = useAuthSession();
  const [report, setReport] = useState<OrganizerReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [subjectFilter, setSubjectFilter] = useState("全部");
  const [typeFilter, setTypeFilter] = useState("全部");
  const [difficultyFilter, setDifficultyFilter] = useState("全部");
  const [statusFilter, setStatusFilter] = useState("全部");
  const [valueFilter, setValueFilter] = useState("全部");
  const [query, setQuery] = useState("");
  const requestIdRef = useRef(0);

  useEffect(() => {
    setReport(null);
    setLoading(!!sessionId);
    if (!sessionId) {
      setLoading(false);
      return;
    }
    const requestId = ++requestIdRef.current;
    const activeSessionId = sessionId;
    organizerApi.getReport(sessionId)
      .then((data) => {
        if (requestIdRef.current === requestId && isActiveSession(activeSessionId)) {
          setReport(data);
        }
      })
      .catch((error) => {
        if (requestIdRef.current === requestId && isActiveSession(activeSessionId)) {
          console.error("Failed to load organizer report:", error);
          setReport(null);
        }
      })
      .finally(() => {
        if (requestIdRef.current === requestId && isActiveSession(activeSessionId)) {
          setLoading(false);
        }
      });
  }, [sessionId, scopeKey]);

  const filteredVideos = useMemo(() => {
    if (!report) return [];
    return report.videos.filter((video) => {
      if (subjectFilter !== "全部" && !video.subject_tags.includes(subjectFilter)) return false;
      if (typeFilter !== "全部" && video.content_type !== typeFilter) return false;
      if (difficultyFilter !== "全部" && video.difficulty_level !== difficultyFilter) return false;
      if (statusFilter !== "全部" && video.learning_status !== statusFilter) return false;
      if (valueFilter !== "全部" && video.value_tier !== valueFilter) return false;
      if (query.trim()) {
        const haystack = `${video.title} ${video.subject_tags.join(" ")} ${video.folder_titles.join(" ")}`.toLowerCase();
        if (!haystack.includes(query.trim().toLowerCase())) return false;
      }
      return true;
    });
  }, [report, subjectFilter, typeFilter, difficultyFilter, statusFilter, valueFilter, query]);

  const facetOptions = report?.facet_counts;

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <div className="landing-logo" style={{ width: 32, height: 32 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M4 6h16" />
              <path d="M4 12h10" />
              <path d="M4 18h7" />
              <circle cx="18" cy="12" r="3" />
              <circle cx="14" cy="18" r="2" />
            </svg>
          </div>
          <div>
            <span className="brand-title">BiliMind</span>
            <span className="brand-subtitle">收藏整理分类中心</span>
          </div>
        </div>
        <div className="topbar-actions">
          <UserTopbar />
        </div>
      </header>
      <main className="app-main">
        <div className="app-with-nav">
          <NavSidebar />
          <div className="app-content organizer-page">
            <div className="organizer-hero">
              <div>
                <h2>收藏整理分类中心</h2>
                <p>自动分类、识别系列、发现重复内容，并给出学习与归档建议。</p>
              </div>
              {sessionId && (
                <div className="organizer-export-actions">
                  <a className="btn btn-outline" href={organizerApi.getExportUrl(sessionId, "json")}>导出 JSON</a>
                  <a className="btn btn-primary" href={organizerApi.getExportUrl(sessionId, "markdown")}>导出 Markdown</a>
                </div>
              )}
            </div>

            {loading && <div className="loading-state">分析收藏中...</div>}
            {!loading && !sessionId && <div className="tree-empty"><p>请先登录后查看整理中心。</p></div>}

            {!loading && sessionId && report && (
              <>
                <div className="organizer-stats-grid">
                  <StatCard label="总视频" value={report.summary.total_videos} />
                  <StatCard label="已识别系列" value={report.summary.series_count} />
                  <StatCard label="重复组" value={report.summary.duplicate_group_count} />
                  <StatCard label="主线核心" value={report.summary.core_count} />
                  <StatCard label="低价值/噪声" value={report.summary.low_value_count} />
                  <StatCard label="已编译" value={report.summary.compiled_count} />
                </div>

                <div className="organizer-filter-bar">
                  <input
                    className="input"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="搜索标题 / 标签 / 收藏夹"
                  />
                  <select className="tree-filter" value={subjectFilter} onChange={(e) => setSubjectFilter(e.target.value)}>
                    <option value="全部">全部主题</option>
                    {Object.keys(facetOptions?.subject_tags || {}).map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                  <select className="tree-filter" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                    <option value="全部">全部类型</option>
                    {Object.keys(facetOptions?.content_type || {}).map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                  <select className="tree-filter" value={difficultyFilter} onChange={(e) => setDifficultyFilter(e.target.value)}>
                    <option value="全部">全部难度</option>
                    {Object.keys(facetOptions?.difficulty_level || {}).map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                  <select className="tree-filter" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                    <option value="全部">全部学习状态</option>
                    {Object.keys(facetOptions?.learning_status || {}).map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                  <select className="tree-filter" value={valueFilter} onChange={(e) => setValueFilter(e.target.value)}>
                    <option value="全部">全部收藏价值</option>
                    {Object.keys(facetOptions?.value_tier || {}).map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </div>

                <div className="organizer-layout">
                  <div className="organizer-main">
                    <section className="organizer-section">
                      <div className="organizer-section-head">
                        <h3>视频总览</h3>
                        <span>{filteredVideos.length} 项</span>
                      </div>
                      <div className="organizer-video-list">
                        {filteredVideos.map((video) => (
                          <div key={video.bvid} className="organizer-video-card">
                            <div className="organizer-video-top">
                              <div>
                                <div className="organizer-video-title">{video.title}</div>
                                <div className="organizer-video-meta">
                                  {video.owner_name && <span>UP: {video.owner_name}</span>}
                                  <span>{formatDuration(video.duration)}</span>
                                  <span>分数 {Math.round(video.organize_score)}</span>
                                  <span>置信度 {Math.round(video.confidence * 100)}%</span>
                                  {video.is_core && <span className="organizer-pill pill-core">核心节点</span>}
                                </div>
                              </div>
                              <a className="btn btn-sm btn-outline" href={`https://www.bilibili.com/video/${video.bvid}`} target="_blank" rel="noopener noreferrer">
                                查看视频
                              </a>
                            </div>
                            <div className="organizer-tag-row">
                              {video.subject_tags.map((tag) => <span key={tag} className="organizer-chip">{tag}</span>)}
                              <span className="organizer-chip organizer-chip-ghost">{video.content_type}</span>
                              <span className="organizer-chip organizer-chip-ghost">{video.difficulty_level}</span>
                              <span className="organizer-chip organizer-chip-ghost">{video.learning_status}</span>
                              <span className={`organizer-chip ${video.value_tier === "主线核心" ? "chip-core" : video.value_tier === "低价值/噪声" ? "chip-low" : ""}`}>{video.value_tier}</span>
                            </div>
                            <div className="organizer-video-stats">
                              <span>{video.knowledge_node_count} 知识点</span>
                              <span>{video.claim_count} 论断</span>
                              <span>{video.segment_count} 片段</span>
                              <span>{video.folder_titles.join(" / ") || "未归组"}</span>
                            </div>
                            <div className="organizer-reason-list">
                              {video.reasons.slice(0, 4).map((reason) => <span key={reason} className="organizer-reason">{reason}</span>)}
                            </div>
                            {video.duplicate_candidates.length > 0 && (
                              <div className="organizer-inline-note low">
                                存在相似收藏，建议人工确认是否归档。
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </section>
                  </div>

                  <div className="organizer-side">
                    <section className="organizer-section">
                      <div className="organizer-section-head">
                        <h3>系列聚合</h3>
                        <span>{report.series_groups.length}</span>
                      </div>
                      <div className="organizer-stack">
                        {report.series_groups.length === 0 && <div className="organizer-empty">暂无明显系列内容</div>}
                        {report.series_groups.map((group) => (
                          <div key={group.series_key} className="organizer-side-card">
                            <div className="organizer-side-title">{group.series_name}</div>
                            <div className="organizer-side-meta">{group.video_count} 个视频 · 覆盖分 {Math.round(group.coverage_score)}</div>
                            <div className="organizer-reason-list">
                              {group.reasons.map((reason) => <span key={reason} className="organizer-reason">{reason}</span>)}
                            </div>
                          </div>
                        ))}
                      </div>
                    </section>

                    <section className="organizer-section">
                      <div className="organizer-section-head">
                        <h3>重复内容识别</h3>
                        <span>{report.duplicate_groups.length}</span>
                      </div>
                      <div className="organizer-stack">
                        {report.duplicate_groups.length === 0 && <div className="organizer-empty">暂无高相似重复组</div>}
                        {report.duplicate_groups.map((group) => (
                          <div key={group.group_id} className="organizer-side-card">
                            <div className="organizer-side-title">{group.group_id}</div>
                            <div className="organizer-side-meta">建议保留 {group.recommended_keep_bvid}</div>
                            <div className="organizer-dup-list">
                              {group.items.map((item) => (
                                <div key={item.bvid} className="organizer-dup-item">
                                  <span>{item.title}</span>
                                  <strong>{Math.round(item.similarity * 100)}%</strong>
                                </div>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </section>

                    <section className="organizer-section">
                      <div className="organizer-section-head">
                        <h3>整理建议</h3>
                        <span>{report.suggestions.length}</span>
                      </div>
                      <div className="organizer-stack">
                        {report.suggestions.map((item) => (
                          <div key={`${item.type}-${item.title}`} className="organizer-side-card">
                            <div className="organizer-side-title">{item.title}</div>
                            <div className="organizer-side-meta">置信度 {Math.round(item.confidence * 100)}%</div>
                            <p className="organizer-side-desc">{item.description}</p>
                            <div className="organizer-reason-list">
                              {item.evidence.map((ev) => <span key={ev} className="organizer-reason">{ev}</span>)}
                            </div>
                          </div>
                        ))}
                      </div>
                    </section>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
