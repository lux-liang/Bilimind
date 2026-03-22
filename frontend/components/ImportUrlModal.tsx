"use client";

import { useState } from "react";
import { knowledgeApi, ImportUrlResponse } from "@/lib/api";

interface ImportUrlModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: (result: ImportUrlResponse) => void;
}

const PLATFORM_INFO: Record<string, { label: string; color: string; icon: string }> = {
  bilibili: { label: "B站视频", color: "#00a1d6", icon: "▶" },
  xiaohongshu: { label: "小红书笔记", color: "#fe2c55", icon: "📕" },
  zhihu: { label: "知乎文章", color: "#0066ff", icon: "Z" },
};

function detectPlatform(url: string): string | null {
  if (url.includes("bilibili.com") || url.includes("b23.tv")) return "bilibili";
  if (url.includes("xiaohongshu.com") || url.includes("xhslink.com")) return "xiaohongshu";
  if (url.includes("zhihu.com") || url.includes("zhuanlan.zhihu.com")) return "zhihu";
  return null;
}

export default function ImportUrlModal({ open, onClose, onSuccess }: ImportUrlModalProps) {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ImportUrlResponse | null>(null);

  const platform = url.trim() ? detectPlatform(url.trim()) : null;
  const platformInfo = platform ? PLATFORM_INFO[platform] : null;

  const handleImport = async () => {
    const trimmed = url.trim();
    if (!trimmed) return;
    if (!platform) {
      setError("不支持的 URL，请粘贴 B站/知乎/小红书链接");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);

    try {
      const sessionId = typeof window !== "undefined"
        ? localStorage.getItem("bili_session") || undefined
        : undefined;
      const res = await knowledgeApi.importUrl(trimmed, sessionId);
      setResult(res);
      onSuccess?.(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "导入失败");
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setUrl("");
    setError("");
    setResult(null);
    setLoading(false);
    onClose();
  };

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div className="modal-content import-url-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>导入内容</h3>
          <button className="modal-close" onClick={handleClose}>×</button>
        </div>

        <div className="modal-body">
          <p className="import-hint">粘贴 B站/知乎/小红书链接，自动识别并提取知识</p>

          <div className="import-input-row">
            <input
              type="text"
              className="import-url-input"
              placeholder="https://www.zhihu.com/question/.../answer/..."
              value={url}
              onChange={(e) => { setUrl(e.target.value); setError(""); setResult(null); }}
              onKeyDown={(e) => e.key === "Enter" && !loading && handleImport()}
              autoFocus
            />
            {platformInfo && (
              <span
                className="platform-badge"
                style={{ backgroundColor: platformInfo.color }}
              >
                {platformInfo.icon} {platformInfo.label}
              </span>
            )}
          </div>

          {error && <div className="import-error">{error}</div>}

          {result && (
            <div className="import-result">
              <div className="import-result-icon">✓</div>
              <div className="import-result-info">
                <strong>{result.title}</strong>
                <div className="import-result-meta">
                  <span className="platform-tag" style={{ backgroundColor: PLATFORM_INFO[result.source_type]?.color || "#666" }}>
                    {PLATFORM_INFO[result.source_type]?.label || result.source_type}
                  </span>
                  <span>{result.segment_count} 段落</span>
                  <span>{result.node_count} 知识点</span>
                  <span>{Math.round(result.content_length / 1000)}k 字</span>
                </div>
              </div>
            </div>
          )}

          <div className="import-platforms">
            <span className="supported-label">支持平台：</span>
            {Object.entries(PLATFORM_INFO).map(([key, info]) => (
              <span key={key} className="platform-chip" style={{ borderColor: info.color, color: info.color }}>
                {info.icon} {info.label}
              </span>
            ))}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={handleClose}>
            {result ? "关闭" : "取消"}
          </button>
          {!result && (
            <button
              className="btn btn-primary"
              onClick={handleImport}
              disabled={loading || !url.trim() || !platform}
            >
              {loading ? "导入中..." : "导入"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
