"use client";

import { useState } from "react";
import Link from "next/link";
import { searchApi, SearchResults } from "@/lib/api";
import NavSidebar from "@/components/NavSidebar";
import UserTopbar from "@/components/UserTopbar";

type TabType = "all" | "nodes" | "videos" | "segments";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<TabType>("all");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);

  const doSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const data = await searchApi.search(query, tab);
      setResults(data);
    } catch (e) {
      console.error("Search failed:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") doSearch();
  };

  const tabs: { key: TabType; label: string }[] = [
    { key: "all", label: "全部" },
    { key: "nodes", label: "知识节点" },
    { key: "videos", label: "视频" },
    { key: "segments", label: "片段" },
  ];

  const nodeCount = results?.nodes?.length ?? 0;
  const videoCount = results?.videos?.length ?? 0;
  const segmentCount = results?.segments?.length ?? 0;
  const totalCount = nodeCount + videoCount + segmentCount;

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <span className="brand-title">BiliMind</span>
          <span className="brand-subtitle">搜索</span>
        </div>
        <div className="topbar-actions">
          <UserTopbar />
        </div>
      </header>
      <main className="app-main">
        <div className="app-with-nav">
          <NavSidebar />
          <div className="app-content">
            <div className="search-hero">
              <h2>知识搜索</h2>
              <p>搜索知识节点、视频和时间片段，快速定位学习内容</p>
            </div>

            {/* 搜索栏 */}
            <div className="search-bar">
              <input
                className="search-input"
                type="text"
                placeholder="输入关键词搜索知识点、视频或片段..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
              />
              <button className="btn btn-primary" onClick={doSearch} disabled={loading || !query.trim()}>
                {loading ? "搜索中..." : "搜索"}
              </button>
            </div>

            {/* Tab 切换 */}
            <div className="search-tabs">
              {tabs.map((t) => (
                <button
                  key={t.key}
                  className={`search-tab ${tab === t.key ? "active" : ""}`}
                  onClick={() => { setTab(t.key); if (results) doSearch(); }}
                >
                  {t.label}
                  {results && t.key === "nodes" && nodeCount > 0 && ` (${nodeCount})`}
                  {results && t.key === "videos" && videoCount > 0 && ` (${videoCount})`}
                  {results && t.key === "segments" && segmentCount > 0 && ` (${segmentCount})`}
                  {results && t.key === "all" && totalCount > 0 && ` (${totalCount})`}
                </button>
              ))}
            </div>

            {/* 搜索结果 */}
            <div className="search-results">
              {loading && <div className="loading-state">搜索中...</div>}

              {results && !loading && (
                <>
                  {/* 知识节点 */}
                  {(tab === "all" || tab === "nodes") && results.nodes.length > 0 && (
                    <div style={{ marginBottom: 24 }}>
                      {tab === "all" && <h3 style={{ fontSize: 14, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 8 }}>知识节点 ({results.nodes.length})</h3>}
                      {results.nodes.map((n) => (
                        <div key={n.id} className="search-result-card">
                          <div className="search-result-name">
                            <span className={`node-badge ${n.node_type}`} style={{ marginRight: 8 }}>{n.node_type}</span>
                            <Link href={`/node/${n.id}`}>{n.name}</Link>
                          </div>
                          <div className="search-result-meta">
                            <span>难度 {"●".repeat(n.difficulty)}</span>
                            <span>置信度 {Math.round(n.confidence * 100)}%</span>
                            <span>{n.video_count} 视频</span>
                            <span>{n.source_count} 来源</span>
                          </div>
                          {n.definition && <div className="search-result-desc">{n.definition}</div>}
                          <div className="search-result-actions">
                            <Link href={`/node/${n.id}`} className="btn btn-sm btn-ghost">查看详情</Link>
                            <Link href={`/learning-path?target=${encodeURIComponent(n.name)}`} className="btn btn-sm btn-outline">生成路径</Link>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 视频 */}
                  {(tab === "all" || tab === "videos") && results.videos.length > 0 && (
                    <div style={{ marginBottom: 24 }}>
                      {tab === "all" && <h3 style={{ fontSize: 14, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 8 }}>视频 ({results.videos.length})</h3>}
                      {results.videos.map((v) => (
                        <div key={v.bvid} className="search-result-card">
                          <div className="search-result-name">
                            <Link href={`/video/${v.bvid}`}>{v.title}</Link>
                          </div>
                          <div className="search-result-meta">
                            {v.owner_name && <span>UP: {v.owner_name}</span>}
                            {v.knowledge_node_count > 0 && <span>{v.knowledge_node_count} 个知识点</span>}
                          </div>
                          {v.description && <div className="search-result-desc">{v.description.slice(0, 120)}</div>}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 片段 */}
                  {(tab === "all" || tab === "segments") && results.segments.length > 0 && (
                    <div style={{ marginBottom: 24 }}>
                      {tab === "all" && <h3 style={{ fontSize: 14, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 8 }}>时间片段 ({results.segments.length})</h3>}
                      {results.segments.map((s, i) => (
                        <div key={i} className="search-result-card">
                          <div className="search-result-name">
                            <a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a>
                          </div>
                          <div className="search-result-desc" style={{ marginTop: 4 }}>{s.content_preview}</div>
                          <div className="search-result-actions">
                            <a href={s.url} target="_blank" rel="noopener noreferrer" className="jump-bilibili-btn">
                              ▶ 跳转到 B 站
                            </a>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {totalCount === 0 && (
                    <div className="tree-empty">
                      <p>未找到与「{results.query}」相关的结果</p>
                      <p style={{ fontSize: 13, color: "var(--text-tertiary)" }}>尝试使用不同的关键词，或减少筛选条件</p>
                    </div>
                  )}
                </>
              )}

              {!results && !loading && (
                <div className="tree-empty">
                  <p>输入关键词搜索知识节点、视频和时间片段</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
