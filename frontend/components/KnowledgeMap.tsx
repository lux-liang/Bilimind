"use client";

import { useEffect, useRef, useState } from "react";
import { CompileResult } from "@/lib/api";

interface KnowledgeMapProps {
  compileResult: CompileResult;
}

export default function KnowledgeMap({ compileResult }: KnowledgeMapProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!svgRef.current || !compileResult) return;

    let cancelled = false;

    const renderMap = async () => {
      try {
        const { Transformer } = await import("markmap-lib");
        const { Markmap } = await import("markmap-view");

        if (cancelled) return;

        // Build markdown from compile result
        const lines: string[] = [];
        lines.push(`# ${compileResult.video.title}`);

        for (const concept of compileResult.concepts) {
          lines.push(`## ${concept.name}`);
          if (concept.definition) {
            lines.push(`- _${concept.definition}_`);
          }
          for (const claim of concept.claims) {
            lines.push(`- ${claim.statement} [${claim.time}]`);
          }
        }

        const markdown = lines.join("\n");
        const transformer = new Transformer();
        const { root } = transformer.transform(markdown);

        // Clear existing content
        while (svgRef.current && svgRef.current.firstChild) {
          svgRef.current.removeChild(svgRef.current.firstChild);
        }

        if (svgRef.current) {
          Markmap.create(svgRef.current, {
            color: (node: any) => {
              const depth = node.depth || 0;
              const colors = ["#059669", "#3b82f6", "#8b5cf6", "#f59e0b", "#ef4444"];
              return colors[depth % colors.length];
            },
            paddingX: 16,
            autoFit: true,
          }, root);
          setLoaded(true);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to render mind map");
        }
      }
    };

    renderMap();

    return () => {
      cancelled = true;
    };
  }, [compileResult]);

  if (error) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "var(--text-tertiary)" }}>
        <p>思维导图加载失败: {error}</p>
      </div>
    );
  }

  return (
    <div className="markmap-container">
      {!loaded && (
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          color: "var(--text-tertiary)",
          fontSize: 13,
        }}>
          加载思维导图...
        </div>
      )}
      <svg
        ref={svgRef}
        style={{ width: "100%", height: "100%", display: loaded ? "block" : "none" }}
      />
    </div>
  );
}
