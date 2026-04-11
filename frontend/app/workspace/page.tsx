"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import NavSidebar from "@/components/NavSidebar";
import UserTopbar from "@/components/UserTopbar";
import KnowledgeTimeline from "@/components/KnowledgeTimeline";
import ConceptClaimList from "@/components/ConceptClaimList";
import EvidenceChat from "@/components/EvidenceChat";
import {
  favoritesApi,
  compileApi,
  FavoriteFolder,
  CompileResult,
} from "@/lib/api";
import { isActiveSession, useAuthSession } from "@/lib/session";
import dynamic from "next/dynamic";
import Link from "next/link";

const KnowledgeMap = dynamic(() => import("@/components/KnowledgeMap"), {
  ssr: false,
  loading: () => (
    <div style={{ padding: 24, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
      加载思维导图组件...
    </div>
  ),
});

type TabKey = "timeline" | "map" | "claims";

interface VideoItem {
  bvid: string;
  title: string;
  duration?: number;
  owner?: string;
  compiled?: boolean;
}

function getErrorMessage(err: unknown): string {
  if (!(err instanceof Error)) return "请求失败";
  const raw = err.message || "请求失败";
  try {
    const parsed = JSON.parse(raw) as { detail?: string };
    if (parsed && typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail;
    }
  } catch {
    // message is not JSON text
  }
  return raw;
}

export default function WorkspacePage() {
  const { sessionId, scopeKey } = useAuthSession();
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [selectedBvid, setSelectedBvid] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("timeline");
  const [compileResult, setCompileResult] = useState<CompileResult | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [compileStatusMessage, setCompileStatusMessage] = useState<string | null>(null);
  const [compiling, setCompiling] = useState<string | null>(null);
  const [compileProgress, setCompileProgress] = useState(0);
  const [loadingResult, setLoadingResult] = useState(false);
  const [loadingVideos, setLoadingVideos] = useState(true);
  const listRequestIdRef = useRef(0);
  const resultRequestIdRef = useRef(0);
  const compilePollIdRef = useRef(0);

  useEffect(() => {
    setVideos([]);
    setSelectedBvid(null);
    setCompileResult(null);
    setCompileError(null);
    setCompileStatusMessage(null);
    setCompiling(null);
    setCompileProgress(0);
    setLoadingResult(false);
    setLoadingVideos(!!sessionId);
  }, [sessionId, scopeKey]);

  // Load videos from favorites
  useEffect(() => {
    if (!sessionId) {
      setLoadingVideos(false);
      return;
    }
    const requestId = ++listRequestIdRef.current;
    const activeSessionId = sessionId;

    favoritesApi
      .getList(sessionId)
      .then(async (folders: FavoriteFolder[]) => {
        const allVideos: VideoItem[] = [];
        // Load from first 3 selected folders or default folder
        const targetFolders = folders
          .filter((f) => f.is_selected || f.is_default)
          .slice(0, 3);

        for (const folder of targetFolders) {
          try {
            const resp = await favoritesApi.getVideos(folder.media_id, sessionId, 1);
            for (const v of resp.videos) {
              if (!allVideos.find((av) => av.bvid === v.bvid)) {
                allVideos.push({
                  bvid: v.bvid,
                  title: v.title,
                  duration: v.duration,
                  owner: v.owner,
                });
              }
            }
          } catch {
            // Skip failed folders
          }
        }
        if (listRequestIdRef.current === requestId && isActiveSession(activeSessionId)) {
          setVideos(allVideos);
        }
      })
      .catch(() => {
        if (listRequestIdRef.current === requestId && isActiveSession(activeSessionId)) {
          setVideos([]);
        }
      })
      .finally(() => {
        if (listRequestIdRef.current === requestId && isActiveSession(activeSessionId)) {
          setLoadingVideos(false);
        }
      });
  }, [sessionId, scopeKey]);

  // Fetch compile result when video selected
  const fetchResult = useCallback(async (bvid: string, activeSessionId?: string | null) => {
    const sid = activeSessionId || sessionId;
    if (!sid) {
      setCompileResult(null);
      setLoadingResult(false);
      return;
    }
    const requestId = ++resultRequestIdRef.current;
    setLoadingResult(true);
    try {
      const result = await compileApi.getResult(bvid, sid);
      if (resultRequestIdRef.current === requestId && isActiveSession(sid)) {
        setCompileResult(result);
        if ((result.stats?.concept_count ?? 0) === 0 && (result.stats?.claim_count ?? 0) === 0) {
          setCompileError("编译完成但未提取到知识点。请检查后端 LLM 配置（DASHSCOPE_API_KEY/OPENAI_API_KEY）和字幕可用性。");
        } else {
          setCompileError(null);
        }
      }
    } catch (e: unknown) {
      if (resultRequestIdRef.current === requestId && isActiveSession(sid)) {
        setCompileResult(null);
        const msg = getErrorMessage(e);
        // "视频未找到/未编译" usually means this video is not compiled yet, not a fatal error.
        if (msg.includes("视频未找到") || msg.includes("视频未编译")) {
          setCompileError(null);
        } else {
          setCompileError(msg);
        }
      }
    }
    if (resultRequestIdRef.current === requestId && isActiveSession(sid)) {
      setLoadingResult(false);
    }
  }, [sessionId]);

  const handleSelectVideo = (bvid: string) => {
    setSelectedBvid(bvid);
    setCompileResult(null);
    setCompileError(null);
    setCompileStatusMessage(null);
    void fetchResult(bvid, sessionId);
  };

  // Compile video
  const handleCompile = async (bvid: string) => {
    if (!sessionId) return;

    setCompiling(bvid);
    setCompileProgress(0);
    setCompileError(null);
    setCompileStatusMessage("正在初始化编译任务...");
    try {
      const { task_id } = await compileApi.compileVideo(bvid, sessionId);
      const pollId = ++compilePollIdRef.current;
      const activeSessionId = sessionId;

      // Poll for status
      const poll = async () => {
        try {
          const status = await compileApi.getStatus(task_id, activeSessionId);
          if (compilePollIdRef.current !== pollId || !isActiveSession(activeSessionId)) {
            return;
          }
          setCompileProgress(status.progress);
          setCompileStatusMessage(status.message || null);

          if (status.status === "completed") {
            setCompiling(null);
            if (selectedBvid === bvid) {
              void fetchResult(bvid, activeSessionId);
            }
          } else if (status.status === "failed") {
            setCompiling(null);
            setCompileError(status.message || "编译失败，请检查后端日志");
            setCompileStatusMessage(null);
          } else {
            setTimeout(poll, 2000);
          }
        } catch (e: unknown) {
          if (compilePollIdRef.current === pollId && isActiveSession(activeSessionId)) {
            setCompiling(null);
            setCompileError(getErrorMessage(e));
            setCompileStatusMessage(null);
          }
        }
      };
      setTimeout(poll, 2000);
    } catch (e: unknown) {
      setCompiling(null);
      setCompileError(getErrorMessage(e));
      setCompileStatusMessage(null);
    }
  };

  const hasCompiledKnowledge = !!compileResult && (
    (compileResult.stats?.concept_count ?? 0) > 0 || (compileResult.stats?.claim_count ?? 0) > 0
  );

  const formatDuration = (d?: number) => {
    if (!d) return "";
    const m = Math.floor(d / 60);
    const s = d % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  const tabs: { key: TabKey; label: string }[] = [
    { key: "timeline", label: "时间轴" },
    { key: "map", label: "知识图" },
    { key: "claims", label: "论断" },
  ];

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <div
            className="landing-logo"
            style={{ width: 32, height: 32 }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
            >
              <path d="M12 3L2 9l10 6 10-6-10-6z" />
              <path d="M2 17l10 6 10-6" />
              <path d="M2 13l10 6 10-6" />
            </svg>
          </div>
          <div>
            <span className="brand-title">Bilimind</span>
            <span className="brand-subtitle">知识工作台</span>
          </div>
        </div>
        <div className="topbar-actions">
          <Link className="btn btn-outline" href="/chat">
            构建知识树
          </Link>
          {compileResult && (
            <div className="topbar-stats">
              <span className="topbar-stat">
                <strong>{compileResult.stats.concept_count}</strong> 概念
              </span>
              <span className="topbar-stat">
                <strong>{compileResult.stats.claim_count}</strong> 论断
              </span>
              <span className="topbar-stat">
                <strong>{compileResult.stats.peak_count}</strong> 密集段
              </span>
            </div>
          )}
          <UserTopbar />
        </div>
      </header>

      <main className="app-main">
        <div className="app-with-nav">
          <NavSidebar />
          <div className="workspace-layout">
            {/* Left: Video sidebar */}
            <div className="workspace-sidebar">
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: "var(--text-secondary)",
                  textTransform: "uppercase",
                  letterSpacing: 1,
                  marginBottom: 12,
                  padding: "0 4px",
                }}
              >
                视频列表
              </div>

              {loadingVideos ? (
                <div style={{ textAlign: "center", padding: 20, color: "var(--text-tertiary)", fontSize: 13 }}>
                  <div className="placeholder-spinner" style={{ margin: "0 auto 8px" }} />
                  加载中...
                </div>
              ) : videos.length === 0 ? (
                <div style={{ textAlign: "center", padding: 20, color: "var(--text-tertiary)", fontSize: 13 }}>
                  <p>暂无视频</p>
                  <p style={{ marginTop: 4, fontSize: 12 }}>请先在收藏夹中添加视频</p>
                </div>
              ) : (
                videos.map((v) => (
                  <div key={v.bvid}>
                    <div
                      className={`video-sidebar-item ${selectedBvid === v.bvid ? "selected" : ""}`}
                      onClick={() => handleSelectVideo(v.bvid)}
                    >
                      <div className="video-sidebar-title">{v.title}</div>
                      <div className="video-sidebar-meta">
                        {v.owner && <span>{v.owner}</span>}
                        {v.duration && (
                          <span style={{ marginLeft: 6 }}>{formatDuration(v.duration)}</span>
                        )}
                      </div>
                    </div>
                    {selectedBvid === v.bvid && !loadingResult && (
                      <div style={{ padding: "4px 12px 8px" }}>
                        <button
                          className="compile-btn"
                          onClick={() => handleCompile(v.bvid)}
                          disabled={compiling === v.bvid}
                        >
                          {compiling === v.bvid
                            ? `编译中... ${Math.round(compileProgress * 100)}%`
                            : (hasCompiledKnowledge ? "重新编译此视频" : "编译此视频")}
                        </button>
                        {compiling === v.bvid && (
                          <div className="progress" style={{ marginTop: 6 }}>
                            <div
                              className="progress-bar"
                              style={{ width: `${compileProgress * 100}%` }}
                            />
                          </div>
                        )}
                        {compiling === v.bvid && compileStatusMessage && (
                          <div style={{ marginTop: 6, fontSize: 12, color: "var(--text-secondary)" }}>
                            {compileStatusMessage}
                          </div>
                        )}
                        {compileError && (
                          <div style={{ marginTop: 8, fontSize: 12, color: "var(--danger)" }}>
                            {compileError}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>

            {/* Center: Main panel with tabs */}
            <div className="workspace-main">
              <div className="workspace-tabs">
                {tabs.map((tab) => (
                  <button
                    key={tab.key}
                    className={`workspace-tab ${activeTab === tab.key ? "active" : ""}`}
                    onClick={() => setActiveTab(tab.key)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              <div className="workspace-content">
                {compileError && (
                  <div
                    style={{
                      marginBottom: 12,
                      padding: "10px 12px",
                      borderRadius: 10,
                      border: "1px solid rgba(220,38,38,0.25)",
                      background: "rgba(220,38,38,0.08)",
                      color: "var(--danger)",
                      fontSize: 13,
                    }}
                  >
                    {compileError}
                  </div>
                )}
                {loadingResult ? (
                  <div className="center-placeholder">
                    <div className="placeholder-spinner" />
                    <span style={{ fontSize: 13, color: "var(--text-tertiary)" }}>
                      加载编译结果...
                    </span>
                  </div>
                ) : !selectedBvid ? (
                  <div className="center-placeholder">
                    <div className="placeholder-illustration">
                      <svg
                        width="48"
                        height="48"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="var(--text-tertiary)"
                        strokeWidth="1.2"
                      >
                        <path d="M12 3L2 9l10 6 10-6-10-6z" />
                        <path d="M2 17l10 6 10-6" />
                        <path d="M2 13l10 6 10-6" />
                      </svg>
                    </div>
                    <h3 className="placeholder-title">选择一个视频</h3>
                    <p className="placeholder-desc">
                      在左侧视频列表中选择视频，编译后查看知识结构
                    </p>
                  </div>
                ) : !compileResult ? (
                  <div className="center-placeholder">
                    <div className="placeholder-illustration">
                      <svg
                        width="48"
                        height="48"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="var(--text-tertiary)"
                        strokeWidth="1.2"
                      >
                        <rect x="3" y="3" width="18" height="14" rx="2" />
                        <polygon points="10,7 10,13 15,10" />
                        <path d="M7 21h10M12 17v4" />
                      </svg>
                    </div>
                    <h3 className="placeholder-title">视频尚未编译</h3>
                    <p className="placeholder-desc">
                      点击左侧的"编译此视频"按钮，AI 将自动提取知识结构
                    </p>
                  </div>
                ) : (
                  <>
                    {activeTab === "timeline" && (
                      <KnowledgeTimeline
                        timeline={compileResult.timeline}
                        duration={compileResult.video.duration}
                        videoTitle={compileResult.video.title}
                      />
                    )}
                    {activeTab === "map" && (
                      <KnowledgeMap compileResult={compileResult} />
                    )}
                    {activeTab === "claims" && (
                      <ConceptClaimList concepts={compileResult.concepts} />
                    )}
                  </>
                )}
              </div>
            </div>

            {/* Right: Evidence chat */}
            <div className="workspace-chat">
              <EvidenceChat selectedBvid={selectedBvid} />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
