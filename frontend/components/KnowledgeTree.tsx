"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { treeApi, TreeNode, TreeResponse } from "@/lib/api";

interface TreeNodeItemProps {
  node: TreeNode;
  searchTerm: string;
  difficultyFilter: number;
  onNodeSelect?: (nodeId: number) => void;
  selectedNodeId?: number | null;
}

function TreeNodeItem({ node, searchTerm, difficultyFilter, onNodeSelect, selectedNodeId }: TreeNodeItemProps) {
  const [expanded, setExpanded] = useState(node.node_type === "topic");
  const hasChildren = node.children && node.children.length > 0;

  const matchesSearch = !searchTerm || node.name.toLowerCase().includes(searchTerm.toLowerCase());
  const matchesDifficulty = difficultyFilter === 0 || node.difficulty === difficultyFilter;

  const childMatchesFilter = (n: TreeNode): boolean => {
    const selfMatch = (!searchTerm || n.name.toLowerCase().includes(searchTerm.toLowerCase()))
      && (difficultyFilter === 0 || n.difficulty === difficultyFilter);
    if (selfMatch) return true;
    return (n.children || []).some(childMatchesFilter);
  };

  const visible = (matchesSearch && matchesDifficulty) || childMatchesFilter(node);
  if (!visible) return null;

  const stars = Array.from({ length: node.difficulty }, () => "\u25CF").join("");
  const isSelected = selectedNodeId === node.id;

  return (
    <div className="tree-node">
      <div className={`tree-node-row${isSelected ? " tree-node-selected" : ""}`}>
        <span
          className="tree-toggle"
          onClick={() => hasChildren && setExpanded(!expanded)}
        >
          {hasChildren ? (expanded ? "\u25BC" : "\u25B6") : "\u00A0\u00A0"}
        </span>
        <span className={`node-badge ${node.node_type}`}>{node.node_type}</span>
        <span
          className="tree-node-name clickable"
          onClick={() => onNodeSelect?.(node.id)}
        >
          {node.name}
        </span>
        {node.difficulty > 0 && <span className="node-stars">{stars}</span>}
        {node.video_count > 0 && <span className="node-meta">{node.video_count} 视频</span>}
        {node.is_reference && <span className="node-meta">(ref)</span>}
      </div>
      {expanded && hasChildren && (
        <div className="tree-children">
          {node.children.map((child) => (
            <TreeNodeItem
              key={child.id}
              node={child}
              searchTerm={searchTerm}
              difficultyFilter={difficultyFilter}
              onNodeSelect={onNodeSelect}
              selectedNodeId={selectedNodeId}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface KnowledgeTreeProps {
  onNodeSelect?: (nodeId: number) => void;
  selectedNodeId?: number | null;
}

export default function KnowledgeTree({ onNodeSelect, selectedNodeId }: KnowledgeTreeProps) {
  const [data, setData] = useState<TreeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [difficultyFilter, setDifficultyFilter] = useState(0);
  const [stageFilter, setStageFilter] = useState("");
  const [topicFilter, setTopicFilter] = useState<number | undefined>(undefined);

  useEffect(() => {
    setLoading(true);
    treeApi.getTree({
      stage: stageFilter || undefined,
      topicId: topicFilter,
    })
      .then(setData)
      .catch((e) => console.error("Failed to load tree:", e))
      .finally(() => setLoading(false));
  }, [stageFilter, topicFilter]);

  if (loading) return <div className="loading-state">加载知识树中...</div>;
  if (!data || data.tree.length === 0) {
    return (
      <div className="tree-empty">
        <p>暂无知识树数据</p>
        <p>请先在 <Link href="/">首页</Link> 登录并构建知识库。</p>
      </div>
    );
  }

  // 提取主题列表供筛选
  const topics = data.tree.filter(n => n.node_type === "topic" && n.id > 0);

  return (
    <div className="tree-container">
      <div className="tree-toolbar">
        <input
          className="tree-search"
          type="text"
          placeholder="搜索知识点..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
        <select
          className="tree-filter"
          value={stageFilter}
          onChange={(e) => setStageFilter(e.target.value)}
        >
          <option value="">全部阶段</option>
          <option value="beginner">入门 (1-2)</option>
          <option value="intermediate">进阶 (3-4)</option>
          <option value="advanced">实战 (5)</option>
        </select>
        {topics.length > 1 && (
          <select
            className="tree-filter"
            value={topicFilter ?? ""}
            onChange={(e) => setTopicFilter(e.target.value ? Number(e.target.value) : undefined)}
          >
            <option value="">全部主题</option>
            {topics.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        )}
        <select
          className="tree-filter"
          value={difficultyFilter}
          onChange={(e) => setDifficultyFilter(Number(e.target.value))}
        >
          <option value={0}>全部难度</option>
          <option value={1}>★ 入门</option>
          <option value={2}>★★ 基础</option>
          <option value={3}>★★★ 中级</option>
          <option value={4}>★★★★ 高级</option>
          <option value={5}>★★★★★ 专家</option>
        </select>
      </div>

      {data.tree.map((node) => (
        <TreeNodeItem
          key={node.id}
          node={node}
          searchTerm={searchTerm}
          difficultyFilter={difficultyFilter}
          onNodeSelect={onNodeSelect}
          selectedNodeId={selectedNodeId}
        />
      ))}

      <div className="tree-stats">
        <span>{data.stats.total_topics} 主题</span>
        <span>{data.stats.total_nodes} 知识点</span>
        <span>{data.stats.total_edges} 关系</span>
        {data.stats.low_confidence_count > 0 && (
          <span>{data.stats.low_confidence_count} 待审核</span>
        )}
      </div>
    </div>
  );
}
