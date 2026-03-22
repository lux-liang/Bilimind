"use client";

import { useState, useEffect, useCallback } from "react";
import NavSidebar from "@/components/NavSidebar";
import UserTopbar from "@/components/UserTopbar";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface NodeInfo {
  id: number;
  name: string;
  type: string;
  definition: string;
}

interface Challenge {
  node_a: NodeInfo;
  node_b: NodeInfo;
  options: string[];
  option_labels: Record<string, string>;
}

interface AnswerResult {
  correct: boolean;
  correct_answer: string;
  correct_answer_label: string;
  explanation: string;
  score: number;
  streak: number;
}

interface Stats {
  total: number;
  correct: number;
  streak: number;
  best_streak: number;
  score: number;
}

export default function GamePage() {
  const [session, setSession] = useState<string | null>(null);
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [stats, setStats] = useState<Stats>({ total: 0, correct: 0, streak: 0, best_streak: 0, score: 0 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const s = localStorage.getItem("bili_session");
    if (s) setSession(s);
  }, []);

  const fetchChallenge = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setSelected(null);
    setResult(null);
    setError(null);
    try {
      const res = await fetch(`${API}/game/challenge?session_id=${session}`);
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Failed to load challenge");
      }
      setChallenge(await res.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [session]);

  const fetchStats = useCallback(async () => {
    if (!session) return;
    try {
      const res = await fetch(`${API}/game/stats?session_id=${session}`);
      if (res.ok) setStats(await res.json());
    } catch {}
  }, [session]);

  useEffect(() => {
    if (session) {
      fetchChallenge();
      fetchStats();
    }
  }, [session, fetchChallenge, fetchStats]);

  const handleAnswer = async (answer: string) => {
    if (!session || !challenge || selected) return;
    setSelected(answer);

    try {
      const res = await fetch(`${API}/game/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: session,
          node_a_id: challenge.node_a.id,
          node_b_id: challenge.node_b.id,
          answer,
        }),
      });
      if (!res.ok) throw new Error("Submit failed");
      const data: AnswerResult = await res.json();
      setResult(data);
      setStats(prev => ({ ...prev, score: data.score, streak: data.streak }));

      // Auto-load next after 2 seconds
      setTimeout(() => {
        fetchChallenge();
        fetchStats();
      }, 2000);
    } catch {
      setError("Failed to submit answer");
    }
  };

  const getOptionClass = (option: string) => {
    if (!selected) return "game-option-btn";
    if (!result) return "game-option-btn";
    if (option === result.correct_answer) return "game-option-btn correct";
    if (option === selected && !result.correct) return "game-option-btn wrong";
    return "game-option-btn";
  };

  return (
    <div className="app-shell">
      <UserTopbar />
      <div className="app-with-nav">
        <NavSidebar />
        <main className="app-content" style={{ display: "flex", justifyContent: "center" }}>
          <div className="game-container">
            {/* Score Bar */}
            <div className="game-score-bar">
              <div className="game-score-item">
                <div className="game-score-value">{stats.score}</div>
                <div className="game-score-label">SCORE</div>
              </div>
              <div className="game-score-item">
                <div className="game-score-value game-streak">{stats.streak}</div>
                <div className="game-score-label">STREAK</div>
              </div>
              <div className="game-score-item">
                <div className="game-score-value">{stats.best_streak}</div>
                <div className="game-score-label">BEST</div>
              </div>
              <div className="game-score-item">
                <div className="game-score-value">
                  {stats.total > 0 ? Math.round((stats.correct / stats.total) * 100) : 0}%
                </div>
                <div className="game-score-label">ACCURACY</div>
              </div>
            </div>

            {error && (
              <div style={{ textAlign: "center", color: "#f87171", marginBottom: 16 }}>
                {error}
                <button className="btn btn-outline btn-sm" style={{ marginLeft: 12 }} onClick={fetchChallenge}>
                  Retry
                </button>
              </div>
            )}

            {loading && (
              <div style={{ textAlign: "center", padding: 48, color: "var(--text-tertiary)" }}>
                Loading...
              </div>
            )}

            {!loading && challenge && (
              <>
                {/* Node Cards */}
                <div className="game-challenge">
                  <div className="game-node-card">
                    <div className="game-node-name">{challenge.node_a.name}</div>
                    <div className="game-node-type">{challenge.node_a.type}</div>
                    {challenge.node_a.definition && (
                      <div className="game-node-def">
                        {challenge.node_a.definition.length > 60
                          ? challenge.node_a.definition.slice(0, 60) + "..."
                          : challenge.node_a.definition}
                      </div>
                    )}
                  </div>

                  <div className="game-question-mark">?</div>

                  <div className="game-node-card">
                    <div className="game-node-name">{challenge.node_b.name}</div>
                    <div className="game-node-type">{challenge.node_b.type}</div>
                    {challenge.node_b.definition && (
                      <div className="game-node-def">
                        {challenge.node_b.definition.length > 60
                          ? challenge.node_b.definition.slice(0, 60) + "..."
                          : challenge.node_b.definition}
                      </div>
                    )}
                  </div>
                </div>

                {/* Options */}
                <div className="game-options">
                  {challenge.options.map((opt) => (
                    <button
                      key={opt}
                      className={getOptionClass(opt)}
                      onClick={() => handleAnswer(opt)}
                      disabled={!!selected}
                    >
                      {challenge.option_labels[opt] || opt}
                    </button>
                  ))}
                </div>

                {/* Result */}
                {result && (
                  <div className={`game-result ${result.correct ? "correct" : "wrong"}`}>
                    {result.correct ? "Correct!" : "Wrong..."} {result.explanation}
                  </div>
                )}
              </>
            )}

            {!loading && !challenge && !error && (
              <div style={{ textAlign: "center", padding: 48, color: "var(--text-tertiary)" }}>
                Need to build knowledge graph first before playing.
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
