"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { treeApi, VideoDetail } from "@/lib/api";
import NavSidebar from "@/components/NavSidebar";

function formatDuration(seconds?: number): string {
  if (!seconds) return "--:--";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function VideoDetailPage() {
  const params = useParams();
  const bvid = params.bvid as string;
  const [detail, setDetail] = useState<VideoDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!bvid) return;
    treeApi.getVideoDetail(bvid)
      .then(setDetail)
      .catch((e) => console.error("Failed to load video:", e))
      .finally(() => setLoading(false));
  }, [bvid]);

  if (loading) return <div className="loading-state">Loading...</div>;
  if (!detail) return <div className="loading-state">Video not found.</div>;

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

            <div className="video-header">
              {detail.pic_url && (
                <img src={detail.pic_url} alt="" className="video-thumb" />
              )}
              <div className="video-info">
                <h1>{detail.title}</h1>
                <div className="detail-meta">
                  {detail.owner_name && <span>UP: {detail.owner_name}</span>}
                  <span>Duration: {formatDuration(detail.duration)}</span>
                  <a href={detail.url} target="_blank" rel="noopener noreferrer">View on Bilibili</a>
                </div>
              </div>
            </div>

            {detail.summary && (
              <div className="detail-section">
                <h2>Summary</h2>
                <p>{detail.summary}</p>
              </div>
            )}

            {detail.description && !detail.summary && (
              <div className="detail-section">
                <h2>Description</h2>
                <p>{detail.description}</p>
              </div>
            )}

            {detail.knowledge_nodes.length > 0 && (
              <div className="detail-section">
                <h2>Knowledge Points</h2>
                {detail.knowledge_nodes.map((kn) => (
                  <div key={kn.id} className="kp-item">
                    <div style={{ flex: 1 }}>
                      <Link href={`/node/${kn.id}`} className="kp-name">{kn.name}</Link>
                      <span className={`node-badge ${kn.node_type}`} style={{ marginLeft: 8 }}>{kn.node_type}</span>
                      <span className="node-stars" style={{ marginLeft: 6 }}>
                        {Array.from({ length: kn.difficulty }, () => "\u25CF").join("")}
                      </span>
                      {kn.definition && <div style={{ fontSize: 13, color: "#6b6560", marginTop: 2 }}>{kn.definition}</div>}
                      <div className="kp-times">
                        {kn.segments.map((seg, i) => (
                          seg.time_label ? (
                            <a
                              key={i}
                              className="kp-time-badge"
                              href={`${detail.url}?t=${Math.floor(seg.start_time || 0)}`}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {seg.time_label}
                            </a>
                          ) : null
                        ))}
                      </div>
                      {kn.tree_position.length > 0 && (
                        <div className="breadcrumb" style={{ marginTop: 4 }}>
                          {kn.tree_position.map((item, i) => (
                            <span key={item.id}>
                              {i > 0 && <span className="breadcrumb-sep"> &gt; </span>}
                              <Link href={`/node/${item.id}`}>{item.name}</Link>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {detail.segments.length > 0 && (
              <div className="detail-section">
                <h2>Segments ({detail.segments.length})</h2>
                {detail.segments.map((seg) => (
                  <div key={seg.id} className="segment-item">
                    <span className="segment-time">
                      {seg.time_label ? (
                        <a href={`${detail.url}?t=${Math.floor(seg.start_time || 0)}`} target="_blank" rel="noopener noreferrer">
                          {seg.time_label}
                        </a>
                      ) : `#${seg.segment_index}`}
                    </span>
                    <span className="segment-text">{seg.text}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
