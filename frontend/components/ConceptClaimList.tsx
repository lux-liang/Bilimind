"use client";

import { useState } from "react";
import { CompileConcept } from "@/lib/api";

interface ConceptClaimListProps {
  concepts: CompileConcept[];
}

const CLAIM_TYPE_CLASSES: Record<string, string> = {
  definition: "claim-type-definition",
  explanation: "claim-type-explanation",
  example: "claim-type-example",
  comparison: "claim-type-comparison",
  warning: "claim-type-warning",
};

const CLAIM_TYPE_LABELS: Record<string, string> = {
  definition: "定义",
  explanation: "解释",
  example: "示例",
  comparison: "对比",
  warning: "注意",
  opinion: "观点",
  fact: "事实",
  step: "步骤",
};

export default function ConceptClaimList({ concepts }: ConceptClaimListProps) {
  const [expandedConcepts, setExpandedConcepts] = useState<Set<number>>(
    new Set(concepts.slice(0, 3).map((c) => c.id))
  );
  const [expandedClaims, setExpandedClaims] = useState<Set<number>>(new Set());

  const toggleConcept = (id: number) => {
    setExpandedConcepts((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleClaim = (id: number) => {
    setExpandedClaims((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (concepts.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
        暂无编译结果，请先选择视频并编译
      </div>
    );
  }

  return (
    <div>
      {concepts.map((concept) => (
        <div key={concept.id} className="concept-item">
          <div className="concept-header" onClick={() => toggleConcept(concept.id)}>
            <span style={{ fontSize: 12, color: "var(--text-tertiary)", width: 16 }}>
              {expandedConcepts.has(concept.id) ? "v" : ">"}
            </span>
            <span className="concept-name">{concept.name}</span>
            {concept.review_status && (
              <span className={`review-pill ${concept.review_status === "verified" ? "ok" : "warn"}`}>
                {concept.review_status === "verified" ? "已验证" : "待确认"}
              </span>
            )}
            {concept.definition && (
              <span className="concept-def">
                {concept.definition.length > 40
                  ? concept.definition.slice(0, 40) + "..."
                  : concept.definition}
              </span>
            )}
            <span className="concept-difficulty" style={{ marginLeft: "auto" }}>
              {"*".repeat(concept.difficulty)}
            </span>
          </div>

          {expandedConcepts.has(concept.id) && (
            <div>
              {concept.claims.map((claim) => (
                <div key={claim.id}>
                  <div
                    className="claim-item"
                    style={{ cursor: "pointer" }}
                    onClick={() => toggleClaim(claim.id)}
                  >
                    <div className="claim-statement">{claim.statement}</div>
                    <div className="claim-meta">
                      <span
                        className={`claim-type-badge ${
                          CLAIM_TYPE_CLASSES[claim.type] || ""
                        }`}
                      >
                        {CLAIM_TYPE_LABELS[claim.type] || claim.type}
                      </span>
                      <span>置信度 {Math.round(claim.confidence * 100)}%</span>
                      {claim.review_status && (
                        <span className={`review-pill tiny ${claim.review_status === "verified" ? "ok" : "warn"}`}>
                          {claim.review_status === "verified" ? "已验证" : "低置信"}
                        </span>
                      )}
                      <span
                        className="evidence-time"
                        onClick={(e) => {
                          e.stopPropagation();
                        }}
                      >
                        {claim.time}
                      </span>
                    </div>
                  </div>

                  {expandedClaims.has(claim.id) && claim.raw_text && (
                    <div
                      style={{
                        marginLeft: 32,
                        padding: "8px 12px",
                        background: "var(--bg-sunken)",
                        borderRadius: 6,
                        fontSize: 12,
                        color: "var(--text-secondary)",
                        lineHeight: 1.5,
                        borderLeft: "2px solid var(--border)",
                        marginBottom: 8,
                      }}
                    >
                      <div
                        style={{
                          fontSize: 10,
                          color: "var(--text-tertiary)",
                          marginBottom: 4,
                          fontWeight: 600,
                        }}
                      >
                        原文片段
                      </div>
                      {claim.raw_text}
                      <div style={{ marginTop: 6 }}>
                        <a
                          href={`#t=${Math.floor(claim.start_time)}`}
                          style={{
                            fontSize: 11,
                            color: "var(--primary)",
                            fontWeight: 500,
                          }}
                        >
                          {claim.time}
                          {claim.end_time > 0
                            ? ` - ${Math.floor(claim.end_time / 60)}:${String(Math.floor(claim.end_time % 60)).padStart(2, "0")}`
                            : ""}
                        </a>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
