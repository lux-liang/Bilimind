"""
BiliMind 知识树学习导航系统

学习路径推荐服务 — 基于图拓扑排序 + 难度 + 证据支撑的可解释学习导航
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
        prereq_depths = self._collect_prerequisite_depths(target_node_id)

        if mode == "beginner":
            steps = self._beginner_path(target_node_id, known, prereq_depths)
        elif mode == "quick":
            steps = self._quick_path(target_node_id, known, prereq_depths)
        else:
            steps = self._standard_path(target_node_id, known, prereq_depths)

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
            "summary": self._build_summary(steps, mode),
        }

    def _beginner_path(self, target_id: int, known: set[int], prereq_depths: dict[int, int]) -> list[dict]:
        """入门路径：收集所有递归前置，按拓扑排序 + 难度排序"""
        all_prereqs = self._collect_all_prerequisites(target_id)
        # 加上目标本身
        all_nodes = list(all_prereqs) + [target_id]
        # 去除已知
        all_nodes = [n for n in all_nodes if n not in known]

        return self._sort_and_build_steps(all_nodes, target_id, mode="beginner", prereq_depths=prereq_depths)

    def _standard_path(self, target_id: int, known: set[int], prereq_depths: dict[int, int]) -> list[dict]:
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

        steps = self._sort_and_build_steps(unique, target_id, mode="standard", prereq_depths=prereq_depths)

        # 追加 1-2 个后续推荐
        successors = self.graph.get_successors(target_id)
        for succ in successors[:2]:
            succ_data = self.graph.get_node(succ["id"])
            if succ_data and succ["id"] not in known:
                score_meta = self._score_node_for_path(
                    succ["id"],
                    succ_data,
                    target_id=target_id,
                    mode="standard",
                    prereq_depths=prereq_depths,
                    is_optional=True,
                )
                steps.append(self._build_step(
                    succ["id"], succ_data, len(steps) + 1,
                    reason=f"学完 {target_data.get('name', '')} 后推荐继续学习",
                    is_optional=True,
                    priority_score=score_meta["priority_score"],
                    support_score=score_meta["support_score"],
                    dependency_depth=score_meta["dependency_depth"],
                    dependency_role=score_meta["dependency_role"],
                    reason_tags=score_meta["reason_tags"],
                ))

        return steps

    def _quick_path(self, target_id: int, known: set[int], prereq_depths: dict[int, int]) -> list[dict]:
        """快速复习：仅直接前置 + 目标"""
        direct_prereqs = self.graph.get_prerequisites(target_id)
        nodes = [p["id"] for p in direct_prereqs] + [target_id]
        nodes = [n for n in nodes if n not in known]
        return self._sort_and_build_steps(nodes, target_id, mode="quick", prereq_depths=prereq_depths)

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

    def _collect_prerequisite_depths(self, node_id: int, max_depth: int = 8) -> dict[int, int]:
        """记录每个前置知识距离目标节点的最短深度。"""
        depths: dict[int, int] = {node_id: 0}
        visited = set()
        queue = [(node_id, 0)]

        while queue:
            nid, depth = queue.pop(0)
            if nid in visited or depth > max_depth:
                continue
            visited.add(nid)
            for prereq in self.graph.get_prerequisites(nid):
                pid = prereq["id"]
                next_depth = depth + 1
                if pid not in depths or next_depth < depths[pid]:
                    depths[pid] = next_depth
                queue.append((pid, next_depth))

        return depths

    def _sort_and_build_steps(
        self,
        node_ids: list[int],
        target_id: int,
        mode: str,
        prereq_depths: dict[int, int],
    ) -> list[dict]:
        """按拓扑顺序 + 模式评分排序，构建步骤列表"""
        if not node_ids:
            return []

        score_cache = {
            nid: self._score_node_for_path(
                nid,
                self.graph.get_node(nid) or {},
                target_id=target_id,
                mode=mode,
                prereq_depths=prereq_depths,
            )
            for nid in node_ids
        }

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

                sorted_ids = list(nx.lexicographical_topological_sort(
                    topo_graph,
                    key=lambda nid: self._step_sort_key(nid, score_cache, target_id, mode),
                ))
            except nx.NetworkXUnfeasible:
                # 有环，退化为按难度排序
                sorted_ids = self._sort_by_difficulty(node_ids, score_cache, target_id, mode)
        else:
            sorted_ids = self._sort_by_difficulty(node_ids, score_cache, target_id, mode)

        steps = []
        for i, nid in enumerate(sorted_ids):
            node_data = self.graph.get_node(nid)
            if not node_data:
                continue

            is_target = (nid == target_id)
            reason = self._generate_reason(nid, node_data, is_target, target_id)
            score_meta = score_cache.get(nid) or self._score_node_for_path(
                nid,
                node_data,
                target_id=target_id,
                mode=mode,
                prereq_depths=prereq_depths,
            )

            steps.append(self._build_step(
                nid,
                node_data,
                i + 1,
                reason,
                priority_score=score_meta["priority_score"],
                support_score=score_meta["support_score"],
                dependency_depth=score_meta["dependency_depth"],
                dependency_role=score_meta["dependency_role"],
                reason_tags=score_meta["reason_tags"],
            ))

        return steps

    def _step_sort_key(
        self,
        node_id: int,
        score_cache: dict[int, dict[str, float | int | str | list[str]]],
        target_id: int,
        mode: str,
    ) -> tuple[float, float, float, int]:
        meta = score_cache.get(node_id) or {}
        if node_id == target_id:
            return (99.0, 99.0, 99.0, node_id)
        dependency_depth = float(meta.get("dependency_depth", 99.0) or 99.0)
        difficulty = float((self.graph.get_node(node_id) or {}).get("difficulty", 1) or 1)
        priority_score = float(meta.get("priority_score", 0.0) or 0.0)
        if mode == "quick":
            return (dependency_depth, difficulty, -priority_score, node_id)
        return (-dependency_depth, difficulty, -priority_score, node_id)

    def _sort_by_difficulty(
        self,
        node_ids: list[int],
        score_cache: dict[int, dict[str, float | int | str | list[str]]],
        target_id: int,
        mode: str,
    ) -> list[int]:
        """退化排序：保留依赖深度、难度和优先级。"""
        return sorted(node_ids, key=lambda nid: self._step_sort_key(nid, score_cache, target_id, mode))

    def _build_step(
        self,
        node_id: int,
        node_data: dict,
        order: int,
        reason: str,
        is_optional: bool = False,
        priority_score: float = 0.0,
        support_score: float = 0.0,
        dependency_depth: int = 0,
        dependency_role: str = "related",
        reason_tags: Optional[list[str]] = None,
    ) -> dict:
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
            "priority_score": round(priority_score, 3),
            "support_score": round(support_score, 3),
            "dependency_depth": dependency_depth,
            "dependency_role": dependency_role,
            "reason_tags": reason_tags or [],
        }

    def _score_node_for_path(
        self,
        node_id: int,
        node_data: dict,
        target_id: int,
        mode: str,
        prereq_depths: dict[int, int],
        is_optional: bool = False,
    ) -> dict[str, float | int | str | list[str]]:
        dependency_depth = int(prereq_depths.get(node_id, 0))
        is_target = node_id == target_id
        direct_ids = {p["id"] for p in self.graph.get_prerequisites(target_id)}
        source_count = float(node_data.get("source_count", 0) or 0)
        confidence = float(node_data.get("confidence", 0.0) or 0.0)
        difficulty = int(node_data.get("difficulty", 1) or 1)

        support_score = min(1.0, source_count / 5.0) * 0.55 + min(1.0, confidence) * 0.45

        if is_target:
            dependency_role = "target"
            dependency_priority = 1.0
        elif is_optional:
            dependency_role = "recommended_next"
            dependency_priority = 0.45
        elif node_id in direct_ids:
            dependency_role = "direct_prerequisite"
            dependency_priority = 0.92
        else:
            dependency_role = "foundation"
            dependency_priority = max(0.4, min(1.0, dependency_depth / 3.0))

        if mode == "beginner":
            difficulty_score = max(0.35, 1.0 - max(0, difficulty - 1) * 0.18)
        elif mode == "quick":
            difficulty_score = 0.85 if difficulty >= 2 else 0.65
        else:
            difficulty_score = 1.0 - abs(difficulty - 2) * 0.12
            difficulty_score = max(0.55, difficulty_score)

        priority_score = dependency_priority * 0.45 + support_score * 0.35 + difficulty_score * 0.20
        if is_optional:
            priority_score -= 0.08
        priority_score = max(0.0, min(1.0, priority_score))

        reason_tags = []
        if dependency_role == "direct_prerequisite":
            reason_tags.append("直接前置")
        elif dependency_role == "foundation":
            reason_tags.append("基础铺垫")
        elif dependency_role == "recommended_next":
            reason_tags.append("延伸学习")
        elif dependency_role == "target":
            reason_tags.append("目标节点")
        if support_score >= 0.75:
            reason_tags.append("证据充分")
        if difficulty <= 2 and mode == "beginner":
            reason_tags.append("适合入门")
        if confidence >= 0.8:
            reason_tags.append("高置信")

        return {
            "priority_score": priority_score,
            "support_score": support_score,
            "dependency_depth": dependency_depth,
            "dependency_role": dependency_role,
            "reason_tags": reason_tags,
        }

    def _build_summary(self, steps: list[dict], mode: str) -> dict:
        if not steps:
            return {
                "mode_label": self._mode_label(mode),
                "avg_priority_score": 0.0,
                "avg_support_score": 0.0,
                "foundation_steps": 0,
                "direct_prerequisites": 0,
                "optional_steps": 0,
            }

        avg_priority = sum(float(step.get("priority_score", 0.0) or 0.0) for step in steps) / len(steps)
        avg_support = sum(float(step.get("support_score", 0.0) or 0.0) for step in steps) / len(steps)
        return {
            "mode_label": self._mode_label(mode),
            "avg_priority_score": round(avg_priority, 3),
            "avg_support_score": round(avg_support, 3),
            "foundation_steps": sum(1 for step in steps if step.get("dependency_role") == "foundation"),
            "direct_prerequisites": sum(1 for step in steps if step.get("dependency_role") == "direct_prerequisite"),
            "optional_steps": sum(1 for step in steps if step.get("is_optional")),
        }

    def _mode_label(self, mode: str) -> str:
        if mode == "beginner":
            return "入门路径"
        if mode == "quick":
            return "快速复习"
        return "标准路径"

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
