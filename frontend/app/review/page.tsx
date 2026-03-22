"use client";

import { useState, useEffect, useCallback } from "react";
import NavSidebar from "@/components/NavSidebar";
import UserTopbar from "@/components/UserTopbar";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface DueItem {
  node_id: number;
  name: string;
  definition: string | null;
  node_type: string;
  easiness_factor: number;
  interval_days: number;
  repetitions: number;
  next_review_date: string | null;
  implicit_review: boolean;
}

interface ImplicitNode {
  node_id: number;
  name: string;
  depth: number;
}

interface ReviewResult {
  node_id: number;
  easiness_factor: number;
  interval_days: number;
  repetitions: number;
  next_review_date: string | null;
  implicit_reviewed: ImplicitNode[];
}

interface Stats {
  total_tracked: number;
  due_today: number;
  mastered: number;
  avg_retention: number;
}

const QUALITY_BUTTONS = [
  { value: 1, label: "完全忘记" },
  { value: 2, label: "困难" },
  { value: 3, label: "一般" },
  { value: 4, label: "容易" },
  { value: 5, label: "完美" },
];

export default function ReviewPage() {
  const [session, setSession] = useState<string | null>(null);
  const [items, setItems] = useState<DueItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [stats, setStats] = useState<Stats>({ total_tracked: 0, due_today: 0, mastered: 0, avg_retention: 0 });
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const s = localStorage.getItem("bili_session");
    if (s) setSession(s);
  }, []);

  const fetchDue = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/srs/due?session_id=${session}`);
      if (res.ok) {
        const data = await res.json();
        setItems(data.items || []);
        setCurrentIndex(0);
        setResult(null);
      }
    } catch {} finally {
      setLoading(false);
    }
  }, [session]);

  const fetchStats = useCallback(async () => {
    if (!session) return;
    try {
      const res = await fetch(`${API}/srs/stats?session_id=${session}`);
      if (res.ok) setStats(await res.json());
    } catch {}
  }, [session]);

  useEffect(() => {
    if (session) {
      fetchDue();
      fetchStats();
    }
  }, [session, fetchDue, fetchStats]);

  const handleQuality = async (quality: number) => {
    if (!session || !items[currentIndex] || submitting) return;
    setSubmitting(true);
    try {
      const res = await fetch(`${API}/srs/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: session,
          node_id: items[currentIndex].node_id,
          quality,
        }),
      });
      if (res.ok) {
        const data: ReviewResult = await res.json();
        setResult(data);
        // Auto-advance after 2s
        setTimeout(() => {
          setResult(null);
          setCurrentIndex((prev) => prev + 1);
          fetchStats();
        }, 2000);
      }
    } catch {} finally {
      setSubmitting(false);
    }
  };

  const current = items[currentIndex] || null;
  const completed = currentIndex;
  const total = items.length;
  const allDone = !loading && (total === 0 || currentIndex >= total);

  return (
    <div className="app-shell">
      <UserTopbar />
      <div className="app-with-nav">
        <NavSidebar />
        <main className="app-content" style={{ display: "flex", justifyContent: "center" }}>
          <div className="review-container">
            {/* Stats Bar */}
            <div className="review-stats-bar">
              <div className="review-stat">
                <div className="review-stat-value">{stats.due_today}</div>
                <div className="review-stat-label">待复习</div>
              </div>
              <div className="review-stat">
                <div className="review-stat-value">{stats.mastered}</div>
                <div className="review-stat-label">已掌握</div>
              </div>
              <div className="review-stat">
                <div className="review-stat-value">{stats.total_tracked}</div>
                <div className="review-stat-label">总追踪</div>
              </div>
              <div className="review-stat">
                <div className="review-stat-value">{Math.round(stats.avg_retention * 100)}%</div>
                <div className="review-stat-label">记忆率</div>
              </div>
            </div>

            {/* Progress Bar */}
            {total > 0 && !allDone && (
              <div className="review-progress">
                <div
                  className="review-progress-fill"
                  style={{ width: `${(completed / total) * 100}%` }}
                />
              </div>
            )}

            {loading && (
              <div style={{ textAlign: "center", padding: 48, color: "var(--text-tertiary)" }}>
                Loading...
              </div>
            )}

            {/* All Done */}
            {allDone && !loading && (
              <div className="review-done">
                <div className="review-done-icon">&#10024;</div>
                <div>今日复习完成！</div>
                <div style={{ fontSize: 13, marginTop: 8, color: "rgba(255,255,255,0.3)" }}>
                  已掌握 {stats.mastered} 个知识点
                </div>
              </div>
            )}

            {/* Review Card */}
            {!loading && current && currentIndex < total && (
              <>
                <div className="review-card">
                  <div style={{ marginBottom: 12 }}>
                    <span className={`node-badge ${current.node_type}`}>
                      {current.node_type}
                    </span>
                  </div>
                  <div className="review-node-name">{current.name}</div>
                  {current.definition && (
                    <div className="review-node-def">{current.definition}</div>
                  )}

                  {/* Quality Buttons */}
                  {!result && (
                    <div className="review-quality-btns">
                      {QUALITY_BUTTONS.map((btn) => (
                        <button
                          key={btn.value}
                          className="review-quality-btn"
                          onClick={() => handleQuality(btn.value)}
                          disabled={submitting}
                        >
                          {btn.label}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Implicit Review Info */}
                  {result && result.implicit_reviewed.length > 0 && (
                    <div className="review-implicit">
                      你同时复习了{" "}
                      {result.implicit_reviewed.map((n) => n.name).join("、")}
                      （前置知识）
                    </div>
                  )}

                  {result && result.implicit_reviewed.length === 0 && (
                    <div className="review-implicit">
                      下次复习：{result.interval_days} 天后
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
