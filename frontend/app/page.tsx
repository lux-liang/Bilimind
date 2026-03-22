"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import LoginModal from "@/components/LoginModal";
import DemoFlowModal from "@/components/DemoFlowModal";
import { UserInfo } from "@/lib/api";
import dynamic from "next/dynamic";

// 动态导入 ForceGraph3D（避免 SSR）
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
  loading: () => null,
});

// 示例图谱数据（供未登录用户展示）
const DEMO_GRAPH = {
  nodes: [
    { id: 1, name: "机器学习", node_type: "topic", val: 6 },
    { id: 2, name: "深度学习", node_type: "concept", val: 5 },
    { id: 3, name: "神经网络", node_type: "concept", val: 4 },
    { id: 4, name: "CNN", node_type: "method", val: 3 },
    { id: 5, name: "RNN", node_type: "method", val: 3 },
    { id: 6, name: "Transformer", node_type: "method", val: 5 },
    { id: 7, name: "注意力机制", node_type: "concept", val: 4 },
    { id: 8, name: "PyTorch", node_type: "tool", val: 3 },
    { id: 9, name: "TensorFlow", node_type: "tool", val: 3 },
    { id: 10, name: "自然语言处理", node_type: "topic", val: 4 },
    { id: 11, name: "计算机视觉", node_type: "topic", val: 4 },
    { id: 12, name: "强化学习", node_type: "concept", val: 3 },
    { id: 13, name: "监督学习", node_type: "concept", val: 3 },
    { id: 14, name: "无监督学习", node_type: "concept", val: 3 },
    { id: 15, name: "大语言模型", node_type: "concept", val: 5 },
    { id: 16, name: "GPT", node_type: "tool", val: 4 },
    { id: 17, name: "BERT", node_type: "method", val: 3 },
    { id: 18, name: "图像分类", node_type: "task", val: 2 },
    { id: 19, name: "目标检测", node_type: "task", val: 2 },
    { id: 20, name: "文本生成", node_type: "task", val: 3 },
  ],
  links: [
    { source: 1, target: 2 }, { source: 1, target: 12 }, { source: 1, target: 13 },
    { source: 1, target: 14 }, { source: 2, target: 3 }, { source: 3, target: 4 },
    { source: 3, target: 5 }, { source: 3, target: 6 }, { source: 6, target: 7 },
    { source: 2, target: 8 }, { source: 2, target: 9 }, { source: 1, target: 10 },
    { source: 1, target: 11 }, { source: 6, target: 15 }, { source: 15, target: 16 },
    { source: 10, target: 17 }, { source: 10, target: 20 }, { source: 11, target: 4 },
    { source: 11, target: 18 }, { source: 11, target: 19 }, { source: 15, target: 20 },
  ],
};

const NODE_COLORS: Record<string, string> = {
  topic: "#059669", concept: "#3b82f6", method: "#8b5cf6", tool: "#f59e0b", task: "#ef4444",
};

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
    <div className="landing-page">
      {/* 3D 图谱背景 */}
      <div className="graph3d-bg">
        <ForceGraph3D
          graphData={DEMO_GRAPH}
          nodeColor={(node: any) => NODE_COLORS[node.node_type] || "#6b7280"}
          nodeVal={(node: any) => node.val}
          nodeRelSize={4}
          nodeOpacity={0.7}
          linkColor={() => "rgba(148, 163, 184, 0.2)"}
          linkWidth={0.5}
          linkOpacity={0.3}
          backgroundColor="rgba(0,0,0,0)"
          showNavInfo={false}
          enableNavigationControls={false}
          enableNodeDrag={false}
          cooldownTicks={100}
          width={typeof window !== "undefined" ? window.innerWidth : 1200}
          height={typeof window !== "undefined" ? window.innerHeight : 800}
        />
      </div>

      {/* 顶栏 */}
      <header className="landing-topbar" style={{ position: "relative", zIndex: 10 }}>
        <div className="landing-brand">
          <div className="landing-logo">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <circle cx="12" cy="8" r="3" />
              <circle cx="6" cy="18" r="2.5" />
              <circle cx="18" cy="18" r="2.5" />
              <path d="M12 11v3M8.5 16l2-2M15.5 16l-2-2" />
            </svg>
          </div>
          <span className="landing-brand-text">BiliMind</span>
        </div>
        <button onClick={() => setShowLogin(true)} className="btn btn-primary">
          扫码登录
        </button>
      </header>

      {/* 主视觉区 */}
      <main className="landing-main" style={{ position: "relative", zIndex: 10 }}>
        <div className="landing-hero">
          <div className="landing-hero-badge">个人视频知识导航系统</div>
          <h1 className="landing-hero-title">
            收藏的视频，<br />
            <span className="landing-highlight">终于有了知识地图</span>
          </h1>
          <p className="landing-hero-desc">
            BiliMind 从你的 B 站收藏夹中自动抽取知识点，构建可浏览的知识树，
            生成学习路径，并让每个知识节点都能追溯到视频中的具体时间点。
          </p>
          <div className="landing-cta">
            <button className="btn btn-primary btn-lg" onClick={() => setShowLogin(true)}>
              开始构建我的知识树
            </button>
            <button className="btn btn-glass btn-lg" onClick={() => setShowDemo(true)}>
              了解工作流程
            </button>
          </div>
        </div>

        {/* 三大核心能力卡片 — 完全不同于原项目的 pipeline */}
        <div className="landing-capabilities">
          <div className="cap-card cap-tree">
            <div className="cap-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                <circle cx="12" cy="5" r="2.5" />
                <circle cx="6" cy="14" r="2" />
                <circle cx="18" cy="14" r="2" />
                <circle cx="4" cy="21" r="1.5" />
                <circle cx="9" cy="21" r="1.5" />
                <circle cx="18" cy="21" r="1.5" />
                <path d="M12 7.5V10M8 14l-2.5 5.5M7 16l1.5 3.5M18 16v3.5M10.5 10.5l-3 2M13.5 10.5l3 2" />
              </svg>
            </div>
            <h3>知识树浏览</h3>
            <p>从视频内容中自动抽取实体与关系，构建层级化的知识树。核心节点优先展示，噪声自动过滤。</p>
            <div className="cap-tag">主入口</div>
          </div>
          <div className="cap-card cap-path">
            <div className="cap-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                <path d="M4 4v4h4" />
                <path d="M4 8c2-3 5-5 8-5s6 2 8 5" />
                <path d="M20 20v-4h-4" />
                <path d="M20 16c-2 3-5 5-8 5s-6-2-8-5" />
                <circle cx="12" cy="12" r="2" />
              </svg>
            </div>
            <h3>学习路径规划</h3>
            <p>输入目标知识点，自动生成从基础到进阶的学习路线，每一步标注推荐理由和代表视频。</p>
            <div className="cap-tag">路线图</div>
          </div>
          <div className="cap-card cap-evidence">
            <div className="cap-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                <rect x="3" y="3" width="18" height="14" rx="2" />
                <polygon points="10,7 10,13 15,10" fill="currentColor" opacity="0.3" />
                <polygon points="10,7 10,13 15,10" />
                <path d="M7 21h10M12 17v4" />
              </svg>
            </div>
            <h3>视频证据追溯</h3>
            <p>每个知识节点关联到具体视频的具体时间片段，点击即跳转到 B 站对应时刻——这是核心卖点。</p>
            <div className="cap-tag cap-tag-hot">核心亮点</div>
          </div>
        </div>

        {/* 工作流可视化 — 独特的阶梯式展示 */}
        <div className="landing-flow">
          <h2 className="landing-section-title">四步构建你的知识体系</h2>
          <div className="flow-steps">
            {[
              { num: "01", title: "同步收藏夹", desc: "扫码登录 B 站，选择收藏夹自动拉取视频内容", color: "#3b82f6" },
              { num: "02", title: "知识抽取", desc: "AI 识别知识实体和关系，自动过滤口语噪声和无效碎片", color: "#8b5cf6" },
              { num: "03", title: "构建知识树", desc: "实体去重归一化，构建层级化知识图谱并投影为可浏览的树", color: "#06b6d4" },
              { num: "04", title: "导航与学习", desc: "浏览知识树、生成学习路径、追溯视频片段证据", color: "var(--primary)" },
            ].map((step, i) => (
              <div key={i} className="flow-step">
                <div className="flow-num" style={{ background: step.color }}>{step.num}</div>
                <div className="flow-body">
                  <h4>{step.title}</h4>
                  <p>{step.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </main>

      <footer className="landing-footer" style={{ position: "relative", zIndex: 10 }}>
        <p>BiliMind © 2026 · 个人视频知识导航系统</p>
      </footer>

      <LoginModal isOpen={showLogin} onClose={() => setShowLogin(false)} onSuccess={onLogin} />
      <DemoFlowModal isOpen={showDemo} onClose={() => setShowDemo(false)} />
    </div>
  );
}
