"""
BiliMind 知识树学习导航系统

树构建引擎 — 从知识图谱投影为前端可展示的知识树
"""
from typing import Optional
from loguru import logger

from app.config import settings
from app.services.graph_store import GraphStore


class TreeBuilder:
    """
    将知识图谱（有向图）投影为前端可展示的知识树

    核心逻辑：
    1. 筛选出置信度达标的节点
    2. 确定一级主题 (type=topic)
    3. 按 PART_OF 关系构建层级
    4. 处理多归属（主归属 vs 引用节点）
    5. 排序：难度升序 → source_count 降序 → 名称字典序
    """

    def __init__(self, graph_store: GraphStore):
        self.graph = graph_store
        self.min_confidence = settings.tree_min_confidence

    def build_tree(self, min_confidence: Optional[float] = None) -> dict:
        """
        构建完整知识树

        Returns:
            {"tree": [...], "stats": {...}}
        """
        threshold = min_confidence or self.min_confidence

        # 1. 获取所有达标节点
        all_nodes = self.graph.all_nodes()
        qualified = [n for n in all_nodes if n.get("confidence", 0) >= threshold
                     and n.get("review_status") != "rejected"]

        if not qualified:
            return {"tree": [], "stats": self._empty_stats()}

        node_map = {n["id"]: n for n in qualified}
        qualified_ids = set(node_map.keys())

        # 2. 确定一级主题
        topics = self._determine_topics(qualified, qualified_ids)

        # 3. 构建每个主题的子树
        assigned = set(t["id"] for t in topics)
        tree = []

        for topic in topics:
            topic_id = topic["id"]
            children = self._build_subtree(topic_id, node_map, qualified_ids, assigned)
            topic_node = self._make_tree_node(topic, children)
            tree.append(topic_node)

        # 4. 处理未归属的节点 → 放入"其他"主题
        orphans = [node_map[nid] for nid in qualified_ids if nid not in assigned]
        if orphans:
            orphan_children = []
            for orphan in sorted(orphans, key=lambda n: (n.get("difficulty", 1), -n.get("source_count", 0), n.get("name", ""))):
                orphan_children.append(self._make_tree_node(orphan, []))
            tree.append({
                "id": -1,
                "name": "其他",
                "node_type": "topic",
                "difficulty": 5,
                "definition": "未归类到明确主题的知识点",
                "video_count": 0,
                "node_count": len(orphan_children),
                "confidence": 0.5,
                "is_reference": False,
                "children": orphan_children,
            })

        # 5. 排序一级主题
        tree.sort(key=lambda t: (-t["node_count"], t["name"]))

        # 统计
        total_nodes = sum(1 for _ in qualified)
        low_conf = sum(1 for n in all_nodes
                       if n.get("confidence", 0) < threshold
                       and n.get("review_status") != "rejected")

        return {
            "tree": tree,
            "stats": {
                "total_topics": len(topics),
                "total_nodes": total_nodes,
                "total_edges": self.graph.edge_count(),
                "low_confidence_count": low_conf,
            }
        }

    def _determine_topics(self, qualified: list[dict], qualified_ids: set[int]) -> list[dict]:
        """确定一级主题"""
        topics = [n for n in qualified if n.get("node_type") == "topic"]

        if not topics:
            # 没有 topic 类型的节点 → 从 concept 中提升出现频次最高的
            concepts = sorted(qualified, key=lambda n: -n.get("source_count", 0))
            if concepts:
                top = concepts[0]
                top["node_type"] = "topic"
                topics = [top]

        # 按被 PART_OF 引用的子节点数降序
        for topic in topics:
            children = self.graph.get_children(topic["id"])
            topic["_child_count"] = len([c for c in children if c["id"] in qualified_ids])

        topics.sort(key=lambda t: -t.get("_child_count", 0))

        # 如果主题过多(>12)，只保留前12个
        if len(topics) > 12:
            topics = topics[:12]

        return topics

    def _build_subtree(self, parent_id: int, node_map: dict, qualified_ids: set, assigned: set) -> list[dict]:
        """递归构建子树"""
        children_raw = self.graph.get_children(parent_id)
        children = []

        for child in children_raw:
            cid = child["id"]
            if cid not in qualified_ids or cid == parent_id:
                continue

            node = node_map.get(cid)
            if not node:
                continue

            is_reference = cid in assigned
            assigned.add(cid)

            # 递归获取子子节点（限制深度3层）
            sub_children = []
            if not is_reference:
                sub_children = self._build_subtree(cid, node_map, qualified_ids, assigned)

            tree_node = self._make_tree_node(node, sub_children, is_reference=is_reference)
            children.append(tree_node)

        # 排序
        children.sort(key=lambda c: (c["difficulty"], -c.get("node_count", 0), c["name"]))
        return children

    def _make_tree_node(self, node: dict, children: list[dict], is_reference: bool = False) -> dict:
        """创建树节点"""
        return {
            "id": node["id"],
            "name": node.get("name", ""),
            "node_type": node.get("node_type", "concept"),
            "difficulty": node.get("difficulty", 1),
            "definition": node.get("definition", ""),
            "video_count": 0,  # 将在 API 层填充
            "node_count": len(children),
            "confidence": node.get("confidence", 0.5),
            "is_reference": is_reference,
            "children": children,
        }

    def _empty_stats(self) -> dict:
        return {
            "total_topics": 0,
            "total_nodes": 0,
            "total_edges": 0,
            "low_confidence_count": 0,
        }

    def get_node_tree_position(self, node_id: int) -> list[dict]:
        """获取节点在知识树中的位置路径"""
        path = []
        current = node_id
        visited = set()

        while current is not None and current not in visited:
            visited.add(current)
            node = self.graph.get_node(current)
            if node:
                path.insert(0, {"id": current, "name": node.get("name", ""), "type": node.get("node_type", "")})
            parent = self.graph.get_parent(current)
            current = parent["id"] if parent else None

        return path
