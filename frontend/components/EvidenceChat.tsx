"use client";

import { useState, useRef, useEffect } from "react";
import EvidenceCard, { evidenceItemToCardProps } from "./EvidenceCard";
import { API_BASE_URL, EvidenceItem, evidenceApi } from "@/lib/api";
import { isActiveSession, useAuthSession } from "@/lib/session";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  evidence: EvidenceItem[];
}

interface EvidenceChatProps {
  selectedBvid?: string | null;
}

export default function EvidenceChat({ selectedBvid = null }: EvidenceChatProps) {
  const { sessionId, scopeKey } = useAuthSession();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);
  const marker = "[[EVIDENCE_JSON]]";

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    setMessages([]);
    setInput("");
    setLoading(false);
  }, [sessionId, scopeKey, selectedBvid]);

  const send = async () => {
    if (!input.trim() || loading || !sessionId) return;
    const q = input.trim();
    setInput("");
    const userId = Date.now().toString();
    const assistantId = (Date.now() + 1).toString();
    const requestId = ++requestIdRef.current;
    const activeSessionId = sessionId;
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", content: q, evidence: [] },
      { id: assistantId, role: "assistant", content: "", evidence: [] },
    ]);
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/evidence/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, session_id: activeSessionId, bvid: selectedBvid }),
      });

      if (!response.ok || !response.body) {
        throw new Error("Stream unavailable");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let done = false;
      let buffer = "";
      let evidenceJson = "";
      let inEvidence = false;

      while (!done) {
        if (requestIdRef.current !== requestId || !isActiveSession(activeSessionId)) {
          try {
            await reader.cancel();
          } catch {
            // Ignore cancel errors
          }
          return;
        }
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (value) {
          const chunk = decoder.decode(value, { stream: !done });
          if (chunk) {
            if (inEvidence) {
              evidenceJson += chunk;
            } else {
              buffer += chunk;
              const markerIndex = buffer.indexOf(marker);
              if (markerIndex !== -1) {
                const contentPart = buffer.slice(0, markerIndex);
                evidenceJson = buffer.slice(markerIndex + marker.length);
                buffer = contentPart;
                inEvidence = true;
              }
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, content: buffer } : m
                )
              );
            }
          }
        }
      }

      if (evidenceJson) {
        try {
          const parsed = JSON.parse(evidenceJson);
          if (Array.isArray(parsed) && requestIdRef.current === requestId && isActiveSession(activeSessionId)) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, evidence: parsed } : m
              )
            );
          }
        } catch {
          // Ignore parse errors
        }
      }
    } catch {
      // Fallback to non-streaming endpoint
      try {
        const res = await evidenceApi.ask(q, activeSessionId, selectedBvid);
        if (requestIdRef.current === requestId && isActiveSession(activeSessionId)) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: res.answer, evidence: res.evidence }
                : m
            )
          );
        }
      } catch (err) {
        if (requestIdRef.current === requestId && isActiveSession(activeSessionId)) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: `错误: ${err instanceof Error ? err.message : "请求失败"}` }
                : m
            )
          );
        }
      }
    }
    if (requestIdRef.current === requestId && isActiveSession(activeSessionId)) {
      setLoading(false);
    }
  };

  const suggestedPrompts = [
    "这个视频的核心观点是什么?",
    "总结主要概念之间的关系",
    "有哪些论断的置信度较低?",
    "列出最重要的3个知识点",
  ];

  return (
    <div className="evidence-chat">
      <div className="evidence-chat-header">
        证据问答
      </div>
      <div className="evidence-chat-messages">
        {messages.length === 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "24px 0" }}>
            <p style={{ fontSize: 13, color: "var(--text-tertiary)", textAlign: "center", marginBottom: 12 }}>
              {sessionId
                ? (selectedBvid
                    ? "提出问题，AI 将优先基于当前选中视频的证据回答"
                    : "提出问题，AI 会从已编译的知识中找到答案并标注证据来源")
                : "请先登录并完成当前账号内容编译"}
            </p>
            {suggestedPrompts.map((prompt, i) => (
              <button
                key={i}
                onClick={() => setInput(prompt)}
                style={{
                  padding: "8px 12px",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  background: "var(--bg-sunken)",
                  fontSize: 12,
                  color: "var(--ink-soft)",
                  cursor: "pointer",
                  textAlign: "left",
                  transition: "border-color 0.15s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--primary)")}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
              >
                {prompt}
              </button>
            ))}
          </div>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`evidence-msg ${m.role}`}>
              {m.role === "user" ? (
                m.content
              ) : (
                <>
                  <div className="evidence-msg-text">
                    {m.content || (loading && m.evidence.length === 0 ? (
                      <span style={{ display: "flex", gap: 4 }}>
                        {[0, 1, 2].map((i) => (
                          <span
                            key={i}
                            style={{
                              width: 6,
                              height: 6,
                              borderRadius: "50%",
                              background: "var(--text-tertiary)",
                              animation: `pulse 1s ease-in-out ${i * 0.15}s infinite`,
                            }}
                          />
                        ))}
                      </span>
                    ) : null)}
                  </div>
                  {m.evidence.length > 0 && (
                    <div className="evidence-msg-cards">
                      {m.evidence.map((ev, i) => (
                        <EvidenceCard key={i} {...evidenceItemToCardProps(ev)} />
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>
      <div className="evidence-chat-input">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          placeholder="输入问题..."
          disabled={loading || !sessionId}
        />
        <button onClick={send} disabled={!input.trim() || loading || !sessionId}>
          发送
        </button>
      </div>
    </div>
  );
}
