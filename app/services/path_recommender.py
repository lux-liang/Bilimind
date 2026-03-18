"""
BiliMind 知识树学习导航系统

学习路径推荐服务 — 基于图拓扑排序 + 难度 + 覆盖度
"""
from typing import Optional
from loguru import logger

try:
    import networkx as nx
except ImportError:
    nx = None

from app.services.graph_store import GraphStore


class PathRecommender:
    """
    学习路径推荐器

    支持三种路径模式:
    - beginner: 入门路径 — 从最基础的前置开始，覆盖所有前置链
    - standard: 标准路径 — 覆盖核心节点 + 重要前置
    - quick:    快速复习 — 仅目标节点 + 直接前置，跳过已知内容
    """

    def __init__(self, graph_store: GraphStore):
        self.graph = graph_store

    def recommend_path(
        self,
        target_node_id: int,
        mode: str = "standard",
        known_node_ids: Optional[list[int]] = None,
    ) -> dict:
        """
        生成学习路径

        Args:
            target_node_id: 目标知识节点
            mode: beginner / standard / quick
            known_node_ids: 用户已掌握的节点（可选）

        Returns:
            {
                "target": {...},
                "mode": str,
                "steps": [{node, videos, segments, reason, order}, ...],
                "total_steps": int,
                "estimated_videos": int,
            }
        """
        if self.graph.graph is None or not self.graph.has_node(target_node_id):
            return self._empty_result(target_node_id, mode)

        known = set(known_node_ids or [])
        target_data = self.graph.get_node(target_node_id)

        if mode == "beginner":
            steps = self._beginner_path(target_node_id, known)
        elif mode == "quick":
            steps = self._quick_path(target_node_id, known)
        else:
            steps = self._standard_path(target_node_id, known)

        return {
            "target": {
                "id": target_node_id,
                "name": target_data.get("name", ""),
                "node_type": target_data.get("node_type", ""),
                "difficulty": target_data.get("difficulty", 1),
            },
            "mode": mode,
            "steps": steps,
            "total_steps": len(steps),
            "estimated_videos": sum(1 for s in steps if s.get("has_videos")),
        }

    def _beginner_path(self, target_id: int, known: set[int]) -> list[dict]:
        """入门路径：收集所有递归前置，按拓扑排序 + 难度排序"""
        all_prereqs = self._collect_all_prerequisites(target_id)
        # 加上目标本身
        all_nodes = list(all_prereqs) + [target_id]
        # 去除已知
        all_nodes = [n for n in all_nodes if n not in known]

        return self._sort_and_build_steps(all_nodes, target_id)

    def _standard_path(self, target_id: int, known: set[int]) -> list[dict]:
        """标准路径：直接前置 + 重要间接前置 + 目标 + 后续推荐"""
        direct_prereqs = self.graph.get_prerequisites(target_id)
        direct_ids = [p["id"] for p in direct_prereqs]

        # 间接前置：只取重要的（source_count >= 2 或 difficulty <= 目标难度）
        target_data = self.graph.get_node(target_id)
        target_diff = target_data.get("difficulty", 1) if target_data else 1

        indirect = set()
        for pid in direct_ids:
            for pp in self.graph.get_prerequisites(pid):
                pp_data = self.graph.get_node(pp["id"])
                if pp_data:
                    sc = pp_data.get("source_count", 0)
                    diff = pp_data.get("difficulty", 1)
                    if sc >= 2 or diff <= target_diff:
                        indirect.add(pp["id"])

        all_nodes = list(indirect) + direct_ids + [target_id]
        all_nodes = [n for n in all_nodes if n not in known]
        # 去重保持顺序
        seen = set()
        unique = []
        for n in all_nodes:
            if n not in seen:
                seen.add(n)
                unique.append(n)

        steps = self._sort_and_build_steps(unique, target_id)

        # 追加 1-2 个后续推荐
        successors = self.graph.get_successors(target_id)
        for succ in successors[:2]:
            succ_data = self.graph.get_node(succ["id"])
            if succ_data and succ["id"] not in known:
                steps.append(self._build_step(
                    succ["id"], succ_data, len(steps) + 1,
                    reason=f"学完 {target_data.get('name', '')} 后推荐继续学习",
                    is_optional=True,
                ))

        return steps

    def _quick_path(self, target_id: int, known: set[int]) -> list[dict]:
        """快速复习：仅直接前置 + 目标"""
        direct_prereqs = self.graph.get_prerequisites(target_id)
        nodes = [p["id"] for p in direct_prereqs] + [target_id]
        nodes = [n for n in nodes if n not in known]
        return self._sort_and_build_steps(nodes, target_id)

    def _collect_all_prerequisites(self, node_id: int, max_depth: int = 8) -> list[int]:
        """递归收集所有前置知识（BFS，防止环）"""
        visited = set()
        queue = [(node_id, 0)]
        result = []

        while queue:
            nid, depth = queue.pop(0)
            if nid in visited or depth > max_depth:
                continue
            visited.add(nid)

            prereqs = self.graph.get_prerequisites(nid)
            for p in prereqs:
                pid = p["id"]
                if pid not in visited:
                    result.append(pid)
                    queue.append((pid, depth + 1))

        return result

    def _sort_and_build_steps(self, node_ids: list[int], target_id: int) -> list[dict]:
        """按拓扑顺序 + 难度排序，构建步骤列表"""
        if not node_ids:
            return []

        # 尝试拓扑排序（基于 prerequisite_of 关系）
        subgraph = self.graph.graph.subgraph(node_ids).copy() if self.graph.graph else None

        if subgraph and nx:
            try:
                # 只保留 prerequisite_of 边做拓扑排序
                topo_graph = nx.DiGraph()
                topo_graph.add_nodes_from(node_ids)
                for u, v, data in subgraph.edges(data=True):
                    if data.get("relation_type") == "prerequisite_of":
                        topo_graph.add_edge(u, v)

                sorted_ids = list(nx.topological_sort(topo_graph))
            except nx.NetworkXUnfeasible:
                # 有环，退化为按难度排序
                sorted_ids = self._sort_by_difficulty(node_ids)
        else:
            sorted_ids = self._sort_by_difficulty(node_ids)

        steps = []
        for i, nid in enumerate(sorted_ids):
            node_data = self.graph.get_node(nid)
            if not node_data:
                continue

            is_target = (nid == target_id)
            reason = self._generate_reason(nid, node_data, is_target, target_id)

            steps.append(self._build_step(nid, node_data, i + 1, reason))

        return steps

    def _sort_by_difficulty(self, node_ids: list[int]) -> list[int]:
        """按难度升序排序"""
        def sort_key(nid):
            data = self.graph.get_node(nid)
            if data:
                return (data.get("difficulty", 1), -data.get("source_count", 0))
            return (1, 0)

        return sorted(node_ids, key=sort_key)

    def _build_step(self, node_id: int, node_data: dict, order: int,
                     reason: str, is_optional: bool = False) -> dict:
        """构建单个路径步骤"""
        return {
            "order": order,
            "node_id": node_id,
            "name": node_data.get("name", ""),
            "node_type": node_data.get("node_type", ""),
            "difficulty": node_data.get("difficulty", 1),
            "definition": node_data.get("definition", ""),
            "confidence": node_data.get("confidence", 0.5),
            "reason": reason,
            "is_optional": is_optional,
            "has_videos": True,  # 将在 API 层填充实际值
        }

    def _generate_reason(self, node_id: int, node_data: dict,
                          is_target: bool, target_id: int) -> str:
        """生成推荐原因"""
        if is_target:
            return "目标知识点"

        target_data = self.graph.get_node(target_id)
        target_name = target_data.get("name", "") if target_data else ""

        # 检查是直接前置还是间接前置
        direct_prereqs = self.graph.get_prerequisites(target_id)
        direct_ids = {p["id"] for p in direct_prereqs}

        name = node_data.get("name", "")

        if node_id in direct_ids:
            return f"学习 {target_name} 的直接前置知识"

        difficulty = node_data.get("difficulty", 1)
        if difficulty <= 2:
            return f"基础知识，为后续学习 {target_name} 打基础"

        return f"深入理解 {target_name} 所需的相关知识"

    def _empty_result(self, target_id: int, mode: str) -> dict:
        return {
            "target": {"id": target_id, "name": "", "node_type": "", "difficulty": 1},
            "mode": mode,
            "steps": [],
            "total_steps": 0,
            "estimated_videos": 0,
        }
