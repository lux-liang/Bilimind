"use client";

import { EvidenceItem } from "@/lib/api";

interface EvidenceCardProps {
  ref_num: number;
  video_title: string;
  bvid: string;
  time: string;
  start_time: number;
  text: string;
  concept?: string;
}

export default function EvidenceCard({
  ref_num,
  video_title,
  bvid,
  time,
  start_time,
  text,
  concept,
}: EvidenceCardProps) {
  const jumpUrl = `https://www.bilibili.com/video/${bvid}?t=${Math.floor(start_time)}`;

  return (
    <div className="evidence-card-item">
      <div className="evidence-ref">{ref_num}</div>
      <div className="evidence-body">
        <div className="evidence-video-info">
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {video_title}
          </span>
          <span
            className="evidence-time"
            onClick={() => window.open(jumpUrl, "_blank")}
          >
            {time}
          </span>
          {concept && <span className="evidence-concept-tag">{concept}</span>}
        </div>
        <div className="evidence-text">
          {text.length > 120 ? text.slice(0, 120) + "..." : text}
        </div>
      </div>
      <a
        href={jumpUrl}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          flexShrink: 0,
          alignSelf: "center",
          padding: "4px 10px",
          fontSize: 12,
          fontWeight: 500,
          color: "var(--primary)",
          border: "1px solid var(--primary)",
          borderRadius: 6,
          textDecoration: "none",
          transition: "all 0.15s",
        }}
      >
        跳转
      </a>
    </div>
  );
}

export function evidenceItemToCardProps(item: EvidenceItem): EvidenceCardProps {
  return {
    ref_num: item.ref,
    video_title: item.video_title,
    bvid: item.bvid,
    time: item.time,
    start_time: item.start_time,
    text: item.text,
    concept: item.concept,
  };
}
