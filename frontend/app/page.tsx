"use client";

import { useState, useEffect } from "react";
import LoginModal from "@/components/LoginModal";
import { UserInfo } from "@/lib/api";
import { readAuthSession, setAuthSession } from "@/lib/session";
import Link from "next/link";

export default function Home() {
  const [showLogin, setShowLogin] = useState(false);

  useEffect(() => {
    const { sessionId, userName } = readAuthSession();
    if (sessionId && userName) {
      window.location.href = "/workspace";
    }
  }, []);

  const onLogin = (sid: string, info: UserInfo) => {
    setShowLogin(false);
    setAuthSession(sid, info.uname);
    window.location.href = "/workspace";
  };

  return (
    <div className="zhiying-landing">
      {/* Topbar */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "16px 32px",
          borderBottom: "1px solid #f3f4f6",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              background: "#059669",
              color: "#fff",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg
              width="20"
              height="20"
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
          <span
            style={{
              fontSize: 20,
              fontWeight: 700,
              color: "#111827",
              letterSpacing: 0.5,
            }}
          >
            Bilimind
          </span>
        </div>
        <button
          onClick={() => setShowLogin(true)}
          className="btn btn-primary"
        >
          扫码登录
        </button>
      </header>

      {/* Hero */}
      <div className="zhiying-hero">
        <div
          style={{
            display: "inline-block",
            padding: "6px 16px",
            borderRadius: 20,
            background: "rgba(5, 150, 105, 0.08)",
            color: "#059669",
            fontSize: 13,
            fontWeight: 600,
            letterSpacing: 1,
            marginBottom: 20,
          }}
        >
          视频知识编译系统
        </div>
        <h1>
          把视频变成<br />
          <span className="highlight">可检索的知识库</span>
        </h1>
        <p>
          知映从你的 B 站收藏视频中自动抽取概念和论断，构建结构化知识图谱，
          让每一条观点都能追溯到视频中的具体时刻。
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
          <button
            className="zhiying-cta"
            onClick={() => setShowLogin(true)}
          >
            开始使用
          </button>
          <Link
            href="/workspace"
            style={{
              display: "inline-flex",
              padding: "12px 32px",
              border: "1px solid #e5e7eb",
              borderRadius: 10,
              fontSize: 16,
              fontWeight: 500,
              color: "#374151",
              textDecoration: "none",
              transition: "all 0.2s",
            }}
          >
            查看工作台
          </Link>
        </div>
      </div>

      {/* Feature cards */}
      <div className="zhiying-features">
        <div className="zhiying-feature-card">
          <div className="zhiying-feature-icon">
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#059669"
              strokeWidth="1.8"
            >
              <path d="M12 3L2 9l10 6 10-6-10-6z" />
              <path d="M2 17l10 6 10-6" />
              <path d="M2 13l10 6 10-6" />
            </svg>
          </div>
          <h3>知识编译</h3>
          <p>
            AI 自动从视频字幕中抽取概念、论断和证据，构建三级知识结构
          </p>
        </div>
        <div className="zhiying-feature-card">
          <div className="zhiying-feature-icon">
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#059669"
              strokeWidth="1.8"
            >
              <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
              <path d="M8 9h8M8 13h4" />
            </svg>
          </div>
          <h3>证据问答</h3>
          <p>
            提出问题，AI 回答并标注每条论据的视频来源和时间戳，可一键跳转
          </p>
        </div>
        <div className="zhiying-feature-card">
          <div className="zhiying-feature-icon">
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#059669"
              strokeWidth="1.8"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="M21 21l-4.35-4.35" />
              <path d="M8 11h6M11 8v6" />
            </svg>
          </div>
          <h3>精准补洞</h3>
          <p>
            自动检测知识缺口，推荐最相关的视频片段填补空白
          </p>
        </div>
      </div>

      {/* Steps */}
      <h2 className="zhiying-section-title">四步完成知识编译</h2>
      <div className="zhiying-steps">
        {[
          { num: "1", title: "导入视频", desc: "从 B 站收藏夹导入视频" },
          { num: "2", title: "AI 编译", desc: "自动抽取概念和论断" },
          { num: "3", title: "证据问答", desc: "带引用的智能问答" },
          { num: "4", title: "精准补洞", desc: "发现并填补知识缺口" },
        ].map((step) => (
          <div key={step.num} className="zhiying-step">
            <div className="zhiying-step-num">{step.num}</div>
            <h4>{step.title}</h4>
            <p>{step.desc}</p>
          </div>
        ))}
      </div>

      {/* Footer */}
      <footer
        style={{
          textAlign: "center",
          padding: "24px",
          fontSize: 12,
          color: "#9ca3af",
          borderTop: "1px solid #f3f4f6",
        }}
      >
        Bilimind &copy; 2026
      </footer>

      <LoginModal
        isOpen={showLogin}
        onClose={() => setShowLogin(false)}
        onSuccess={onLogin}
      />
    </div>
  );
}
