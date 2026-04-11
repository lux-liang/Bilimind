"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { API_BASE_URL, getSessionId } from "@/lib/api";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export default function AIAssistant() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);

  const orbRef = useRef<HTMLDivElement>(null);
  const siriWaveRef = useRef<any>(null);
  const recognitionRef = useRef<any>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Initialize SiriWave
  useEffect(() => {
    let mounted = true;
    import("siriwave").then((mod) => {
      const SiriWave = mod.default;
      if (!mounted || !orbRef.current) return;
      // Clear any existing canvas
      orbRef.current.innerHTML = "";
      siriWaveRef.current = new SiriWave({
        container: orbRef.current,
        style: "ios9",
        width: 64,
        height: 64,
        amplitude: 0.3,
        speed: 0.03,
        autostart: true,
      });
    });
    return () => {
      mounted = false;
      if (siriWaveRef.current) {
        siriWaveRef.current.dispose();
        siriWaveRef.current = null;
      }
    };
  }, []);

  // Update wave amplitude based on state
  useEffect(() => {
    if (!siriWaveRef.current) return;
    if (speaking || listening) {
      siriWaveRef.current.setAmplitude(1.5);
      siriWaveRef.current.setSpeed(0.08);
    } else if (loading) {
      siriWaveRef.current.setAmplitude(0.8);
      siriWaveRef.current.setSpeed(0.06);
    } else {
      siriWaveRef.current.setAmplitude(0.3);
      siriWaveRef.current.setSpeed(0.03);
    }
  }, [speaking, listening, loading]);

  // Auto-scroll messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Send message via SSE streaming
  const send = useCallback(async (text?: string) => {
    const q = (text || input).trim();
    if (!q || loading) return;
    setInput("");

    const userId = Date.now().toString();
    const assistantId = (Date.now() + 1).toString();
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", content: q },
      { id: assistantId, role: "assistant", content: "" },
    ]);
    setLoading(true);

    try {
      const sessionId = getSessionId();
      const response = await fetch(`${API_BASE_URL}/chat/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          session_id: sessionId,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error("Stream unavailable");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let done = false;
      let buffer = "";
      const marker = "[[SOURCES_JSON]]";
      let inSources = false;

      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (value) {
          const chunk = decoder.decode(value, { stream: !done });
          if (chunk) {
            if (inSources) {
              // skip sources for assistant
            } else {
              buffer += chunk;
              const markerIndex = buffer.indexOf(marker);
              if (markerIndex !== -1) {
                buffer = buffer.slice(0, markerIndex);
                inSources = true;
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

      // Speak the response
      speakText(buffer);
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: "抱歉，请求失败，请稍后重试。" }
            : m
        )
      );
    }
    setLoading(false);
  }, [input, loading]);

  // Voice output
  const speakText = (text: string) => {
    if (!window.speechSynthesis || !text) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text.slice(0, 500));
    utterance.lang = "zh-CN";
    utterance.rate = 1.1;
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
  };

  // Voice input
  const toggleVoice = () => {
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }

    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("当前浏览器不支持语音识别");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setInput(transcript);
      setListening(false);
      // Auto-send after recognition
      setTimeout(() => send(transcript), 100);
    };

    recognition.onerror = () => setListening(false);
    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  };

  return (
    <div className="ai-assistant">
      {open && (
        <div className="assistant-panel">
          <div className="assistant-header">
            <span>AI 知识助手</span>
            <button
              onClick={() => { setOpen(false); window.speechSynthesis?.cancel(); }}
              style={{ background: "none", border: "none", color: "#9ca3af", cursor: "pointer", fontSize: 18 }}
            >
              &times;
            </button>
          </div>
          <div className="assistant-messages">
            {messages.length === 0 && (
              <div style={{ textAlign: "center", color: "#6b7280", fontSize: 13, padding: "24px 0" }}>
                你好！我是 Bilimind AI 助手，可以回答关于你收藏视频的任何问题。
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`assistant-msg ${m.role === "user" ? "user" : "ai"}`}>
                {m.content || (m.role === "assistant" && loading ? "..." : "")}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
          <div className="assistant-input-bar">
            <button
              className={`assistant-voice-btn ${listening ? "listening" : ""}`}
              onClick={toggleVoice}
              title={listening ? "停止录音" : "语音输入"}
            >
              {listening ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" y1="19" x2="12" y2="23" />
                  <line x1="8" y1="23" x2="16" y2="23" />
                </svg>
              )}
            </button>
            <input
              className="assistant-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
              placeholder="输入问题..."
            />
            <button
              className="assistant-send-btn"
              onClick={() => send()}
              disabled={!input.trim() || loading}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </div>
        </div>
      )}
      <div className="ai-orb" onClick={() => setOpen(!open)} ref={orbRef} />
    </div>
  );
}
