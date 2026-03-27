"use client";

import { useState } from "react";
import { TimelineSegment } from "@/lib/api";

interface KnowledgeTimelineProps {
  timeline: TimelineSegment[];
  duration: number;
  videoTitle?: string;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function KnowledgeTimeline({
  timeline,
  duration,
  videoTitle,
}: KnowledgeTimelineProps) {
  const [hoveredSegment, setHoveredSegment] = useState<TimelineSegment | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  if (!timeline || timeline.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
        暂无时间轴数据
      </div>
    );
  }

  const peakSegments = timeline.filter((s) => s.is_peak);

  return (
    <div className="timeline-container">
      {videoTitle && (
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)", marginBottom: 12 }}>
          {videoTitle}
        </div>
      )}

      {/* Stats bar */}
      <div
        style={{
          display: "flex",
          gap: 16,
          fontSize: 12,
          color: "var(--text-secondary)",
          marginBottom: 12,
        }}
      >
        <span>时长 {formatTime(duration)}</span>
        <span>
          <span
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              borderRadius: 2,
              background: "var(--primary)",
              marginRight: 4,
              verticalAlign: "middle",
            }}
          />
          知识密度
        </span>
        <span>
          <span
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "#f59e0b",
              marginRight: 4,
              verticalAlign: "middle",
            }}
          />
          知识密集段 ({peakSegments.length})
        </span>
      </div>

      {/* Timeline bar */}
      <div className="timeline-bar">
        {timeline.map((seg, i) => (
          <div
            key={i}
            className={`timeline-segment ${seg.is_peak ? "peak" : ""}`}
            style={{
              left: `${(seg.start / duration) * 100}%`,
              width: `${((seg.end - seg.start) / duration) * 100}%`,
              opacity: 0.2 + seg.density * 0.8,
            }}
            onMouseEnter={(e) => {
              setHoveredSegment(seg);
              const rect = e.currentTarget.getBoundingClientRect();
              setTooltipPos({ x: rect.left + rect.width / 2, y: rect.top });
            }}
            onMouseLeave={() => setHoveredSegment(null)}
          />
        ))}

        {/* Peak markers */}
        {peakSegments.map((seg, i) => (
          <div
            key={`peak-${i}`}
            className="timeline-peak-marker"
            style={{
              left: `${((seg.start + (seg.end - seg.start) / 2) / duration) * 100}%`,
            }}
          />
        ))}
      </div>

      {/* Time labels */}
      <div className="timeline-labels">
        <span>0:00</span>
        <span>{formatTime(duration / 4)}</span>
        <span>{formatTime(duration / 2)}</span>
        <span>{formatTime((duration * 3) / 4)}</span>
        <span>{formatTime(duration)}</span>
      </div>

      {/* Tooltip */}
      {hoveredSegment && (
        <div
          style={{
            position: "fixed",
            left: tooltipPos.x,
            top: tooltipPos.y - 8,
            transform: "translate(-50%, -100%)",
            background: "var(--ink)",
            color: "#fff",
            padding: "6px 10px",
            borderRadius: 6,
            fontSize: 11,
            whiteSpace: "nowrap",
            zIndex: 100,
            pointerEvents: "none",
            boxShadow: "0 2px 8px rgba(0,0,0,0.2)",
          }}
        >
          <div>
            {formatTime(hoveredSegment.start)} - {formatTime(hoveredSegment.end)}
          </div>
          <div>知识密度: {Math.round(hoveredSegment.density * 100)}%</div>
          {hoveredSegment.concepts && hoveredSegment.concepts.length > 0 && (
            <div style={{ marginTop: 2 }}>
              {hoveredSegment.concepts.slice(0, 3).join(", ")}
            </div>
          )}
        </div>
      )}

      {/* Peak concepts list */}
      {peakSegments.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "var(--text-secondary)",
              marginBottom: 8,
            }}
          >
            知识密集段
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {peakSegments.map((seg, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                  padding: "6px 10px",
                  background: "var(--bg-sunken)",
                  borderRadius: 6,
                  fontSize: 12,
                }}
              >
                <span
                  style={{
                    color: "#f59e0b",
                    fontWeight: 600,
                    fontFamily: "monospace",
                    minWidth: 80,
                  }}
                >
                  {formatTime(seg.start)} - {formatTime(seg.end)}
                </span>
                <span style={{ color: "var(--ink-soft)" }}>
                  {seg.concepts
                    ? seg.concepts.join(", ")
                    : `密度 ${Math.round(seg.density * 100)}%`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
