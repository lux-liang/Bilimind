"use client";

import { useState, useEffect } from "react";
import LoginModal from "@/components/LoginModal";
import DemoFlowModal from "@/components/DemoFlowModal";
import { UserInfo, authApi } from "@/lib/api";

export default function Home() {
  const [showLogin, setShowLogin] = useState(false);
  const [showDemo, setShowDemo] = useState(false);

  useEffect(() => {
    const s = localStorage.getItem("bili_session");
    const u = localStorage.getItem("bili_user");
    if (s && u) {
      window.location.href = "/tree";
    }
  }, []);

  const onLogin = (sid: string, info: UserInfo) => {
    setShowLogin(false);
    localStorage.setItem("bili_session", sid);
    localStorage.setItem("bili_user", info.uname);
    window.location.href = "/tree";
  };

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <div className="brand-mark">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 3v18M12 7l-4 4M12 7l4 4M12 13l-6 5M12 13l6 5" />
            </svg>
          </div>
          <div>
            <span className="brand-title">BiliMind</span>
            <span className="brand-subtitle">知识导航系统</span>
          </div>
        </div>
        <div className="topbar-actions">
          <button onClick={() => setShowLogin(true)} className="btn btn-primary">
            扫码登录
          </button>
        </div>
      </header>

      <main className="app-main">
        <section className="hero">
          <div className="hero-content">
            <span className="hero-kicker">让收藏夹变成知识地图</span>
            <h1 className="hero-title">个人视频知识导航系统</h1>
            <p className="hero-desc">
              收藏了大量 B 站学习视频，却无从下手？<br />
              BiliMind 自动提取知识点、构建知识树、规划学习路径，<br />
              每个知识节点都能追溯到视频原始片段，点击即跳转。
            </p>

            <div className="hero-actions">
              <button className="btn btn-primary btn-lg" onClick={() => setShowLogin(true)}>
                扫码登录 · 开始构建
              </button>
              <button className="btn btn-outline btn-lg" onClick={() => setShowDemo(true)}>
                了解工作流程
              </button>
            </div>
          </div>

          <div className="hero-features">
            <div className="pipeline-row">
              {[
                { icon: "1", title: "同步", desc: "接入 B 站收藏夹" },
                { icon: "2", title: "抽取", desc: "识别知识实体" },
                { icon: "3", title: "构建", desc: "生成知识树" },
                { icon: "4", title: "导航", desc: "学习路径与追溯" },
              ].map((item, i) => (
                <div key={i} className="pipeline-card">
                  <span className="pipeline-icon">{item.icon}</span>
                  <div className="pipeline-text">
                    <strong>{item.title}</strong>
                    <span>{item.desc}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>

      <footer className="app-footer">
        <p>BiliMind © 2026 · 个人视频知识导航系统</p>
      </footer>

      <LoginModal isOpen={showLogin} onClose={() => setShowLogin(false)} onSuccess={onLogin} />
      <DemoFlowModal isOpen={showDemo} onClose={() => setShowDemo(false)} />
    </div>
  );
}
