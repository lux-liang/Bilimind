"use client";

import { useState } from "react";
import Link from "next/link";
import { searchApi, SearchResults } from "@/lib/api";
import NavSidebar from "@/components/NavSidebar";
import UserTopbar from "@/components/UserTopbar";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [type, setType] = useState("all");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);

  const doSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const data = await searchApi.search(query, type);
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

  const stars = (n: number) => Array.from({ length: n }, () => "\u25CF").join("");

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
            <div style={{ maxWidth: 800 }}>
              <div className="tree-toolbar">
                <input
                  className="tree-search"
                  type="text"
                  placeholder="Search nodes, videos, segments..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                />
                <select
                  className="tree-filter"
                  value={type}
                  onChange={(e) => setType(e.target.value)}
                >
                  <option value="all">All</option>
                  <option value="nodes">Nodes</option>
                  <option value="videos">Videos</option>
                  <option value="segments">Segments</option>
                </select>
                <button className="btn btn-primary" onClick={doSearch} style={{ padding: "8px 16px" }}>
                  Search
                </button>
              </div>

              {loading && <div className="loading-state">Searching...</div>}

              {results && !loading && (
                <div>
                  {/* Nodes */}
                  {results.nodes.length > 0 && (
                    <div className="detail-section">
                      <h2>Knowledge Nodes ({results.nodes.length})</h2>
                      {results.nodes.map((n) => (
                        <div key={n.id} className="tree-node-row" style={{ padding: "8px 0", borderBottom: "1px solid rgba(0,0,0,0.06)" }}>
                          <span className={`node-badge ${n.node_type}`}>{n.node_type}</span>
                          <Link href={`/node/${n.id}`} className="tree-node-name">{n.name}</Link>
                          <span className="node-stars">{stars(n.difficulty)}</span>
                          <span className="node-meta">{n.video_count} videos</span>
                          {n.definition && (
                            <span className="node-meta" style={{ fontSize: 12 }}> - {n.definition.slice(0, 60)}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Videos */}
                  {results.videos.length > 0 && (
                    <div className="detail-section">
                      <h2>Videos ({results.videos.length})</h2>
                      {results.videos.map((v) => (
                        <div key={v.bvid} className="video-card">
                          <Link href={`/video/${v.bvid}`} className="video-card-title">{v.title}</Link>
                          <div className="video-card-meta">
                            {v.owner_name && <span>UP: {v.owner_name}</span>}
                            {v.knowledge_node_count > 0 && <span> | {v.knowledge_node_count} knowledge points</span>}
                          </div>
                          {v.description && <div style={{ fontSize: 13, color: "#6b6560", marginTop: 4 }}>{v.description}</div>}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Segments */}
                  {results.segments.length > 0 && (
                    <div className="detail-section">
                      <h2>Segments ({results.segments.length})</h2>
                      {results.segments.map((s, i) => (
                        <div key={i} className="segment-item" style={{ padding: "10px 0" }}>
                          <div>
                            <a href={s.url} target="_blank" rel="noopener noreferrer" style={{ fontWeight: 500, color: "#1b1713" }}>
                              {s.title}
                            </a>
                            <div className="segment-text" style={{ marginTop: 4 }}>{s.content_preview}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {results.nodes.length === 0 && results.videos.length === 0 && results.segments.length === 0 && (
                    <div className="tree-empty">
                      <p>No results found for &quot;{results.query}&quot;</p>
                    </div>
                  )}
                </div>
              )}

              {!results && !loading && (
                <div className="tree-empty">
                  <p>Enter a keyword to search across knowledge nodes, videos, and segments.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
