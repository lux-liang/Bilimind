"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import NavSidebar from "@/components/NavSidebar";
import UserTopbar from "@/components/UserTopbar";
import SourcesPanel from "@/components/SourcesPanel";
import ChatPanel from "@/components/ChatPanel";
import AIAssistant from "@/components/AIAssistant";

export default function ChatPage() {
  const [session, setSession] = useState<string | null>(null);
  const [statsKey, setStatsKey] = useState(0);
  const [selectedFolderIds, setSelectedFolderIds] = useState<number[]>([]);
  const [leftWidth, setLeftWidth] = useState(280);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const s = localStorage.getItem("bili_session");
    if (s) setSession(s);
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const newWidth = e.clientX - rect.left;
    setLeftWidth(Math.max(200, Math.min(rect.width * 0.45, newWidth)));
  }, [isDragging]);

  const handleMouseUp = useCallback(() => setIsDragging(false), []);

  useEffect(() => {
    if (isDragging) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    } else {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  if (!session) {
    return (
      <div className="app-shell">
        <header className="app-topbar">
          <div className="brand"><span className="brand-title">BiliMind</span></div>
        </header>
        <main className="app-main">
          <div className="app-with-nav">
            <NavSidebar />
            <div className="app-content">
              <div className="tree-empty">
                <p>请先登录后使用知识问答</p>
                <a href="/">前往登录</a>
              </div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <span className="brand-title">BiliMind</span>
          <span className="brand-subtitle">知识问答</span>
        </div>
        <div className="topbar-actions">
          <UserTopbar />
        </div>
      </header>
      <main className="app-main">
        <div className="app-with-nav">
          <NavSidebar />
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <div className="chat-page-header">
              <h2>基于知识树的知识问答</h2>
              <p>向知识库提问，回答基于你收藏的视频内容生成，支持追溯来源片段</p>
            </div>
            <section className="workspace" ref={containerRef} style={{ flex: 1 }}>
              <aside className="panel panel-sources" style={{ width: leftWidth, flexShrink: 0 }}>
                <SourcesPanel
                  sessionId={session}
                  onBuildDone={() => setStatsKey((v) => v + 1)}
                  onSelectionChange={setSelectedFolderIds}
                />
              </aside>
              <div className="resizer" onMouseDown={handleMouseDown} style={{ cursor: "col-resize" }} />
              <section className="panel panel-chat" style={{ flex: 1 }}>
                <ChatPanel
                  statsKey={statsKey}
                  sessionId={session}
                  folderIds={selectedFolderIds}
                />
              </section>
            </section>
          </div>
        </div>
      </main>
      <AIAssistant />
    </div>
  );
}
