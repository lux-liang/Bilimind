"""
BiliMind 知识树学习导航系统

树构建引擎 — 从知识图谱投影为前端可展示的知识树
支持节点质量分级（core / normal / weak）和噪声节点过滤
"""
import re
from typing import Optional
from loguru import logger

from app.config import settings
from app.services.graph_store import GraphStore


# 节点质量等级
GRADE_CORE = "core"         # 核心节点：高置信度 + 多来源
GRADE_NORMAL = "normal"     # 普通节点
GRADE_WEAK = "weak"         # 弱关联：低置信度或单来源

# 噪声节点名称模式
NOISE_PATTERNS = [
    re.compile(r'^[a-zA-Z]{1,3}$'),           # 短英文碎片
    re.compile(r'^[\d\s\.\-\+]+$'),            # 纯数字
    re.compile(r'^[\W_]+$'),                   # 纯标点
    re.compile(r'^(someone|something|yeah|okay|well|like|just|really|'
               r'your|their|here|there|gonna|wanna|gotta|uhh|hmm|hey|'
               r'dude|guy|man|sir|bud)$', re.IGNORECASE),
]

NOISE_ZH_NAMES = {
    "大师兄", "小伙伴", "同学们", "朋友们", "大家好", "各位",
    "老铁", "兄弟们", "宝子们", "家人们", "观众", "粉丝",
    "视频", "内容", "东西", "事情",
}

TECH_ABBREVIATION_ALLOWLIST = {
    "AI", "ML", "DL", "CNN", "RNN", "GAN", "LLM", "NLP", "CV", "RL",
    "OCR", "ASR", "API", "SDK", "SQL", "GPU", "CPU", "CLI", "IDE",
    "HTTP", "HTTPS", "TCP", "UDP", "GD",
}


def _is_noise_name(name: str) -> bool:
    """判断节点名是否为噪声"""
    stripped = name.strip()
    if stripped in TECH_ABBREVIATION_ALLOWLIST:
        return False
    if re.match(r'^[A-Z][A-Z0-9]{1,4}$', stripped):
        return False
    if name in NOISE_ZH_NAMES:
        return True
    for pat in NOISE_PATTERNS:
        if pat.match(name.strip()):
            return True
    return False


def _compute_grade(node: dict) -> str:
    """计算节点质量等级"""
    confidence = node.get("confidence", 0)
    source_count = node.get("source_count", 1)

    if confidence >= 0.7 and source_count >= 2:
        return GRADE_CORE
    elif confidence < 0.45 or source_count <= 1:
        return GRADE_WEAK
    else:
        return GRADE_NORMAL


class TreeBuilder:
    """
    将知识图谱（有向图）投影为前端可展示的知识树

    核心逻辑：
    1. 筛选出置信度达标的节点，过滤噪声
    2. 计算节点质量等级（core / normal / weak）
    3. 确定一级主题 (type=topic)
    4. 按 PART_OF 关系构建层级
    5. 弱关联节点默认折叠，噪声节点不进入主树
    6. 排序：核心优先 → 难度升序 → source_count 降序
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

        # 1. 获取所有达标节点，过滤噪声
        all_nodes = self.graph.all_nodes()
        qualified = []
        noise_count = 0
        for n in all_nodes:
            if n.get("review_status") == "rejected":
                continue
            if n.get("confidence", 0) < threshold:
                continue
            if _is_noise_name(n.get("name", "")):
                noise_count += 1
                continue
            qualified.append(n)

        if not qualified:
            return {"tree": [], "stats": self._empty_stats()}

        # 2. 计算质量等级
        for n in qualified:
            n["_grade"] = _compute_grade(n)

        node_map = {n["id"]: n for n in qualified}
        qualified_ids = set(node_map.keys())

        # 3. 确定一级主题
        topics = self._determine_topics(qualified, qualified_ids)

        # 4. 构建每个主题的子树
        assigned = set(t["id"] for t in topics)
        tree = []

        for topic in topics:
            topic_id = topic["id"]
            children = self._build_subtree(topic_id, node_map, qualified_ids, assigned)
            topic_node = self._make_tree_node(topic, children)
            tree.append(topic_node)

        # 5. 处理未归属的节点
        orphans = [node_map[nid] for nid in qualified_ids if nid not in assigned]
        if orphans:
            # 尝试按相关性归入现有主题
            remaining = self._try_assign_orphans(orphans, topics, tree, node_map)

            if remaining:
                orphan_children = []
                for orphan in sorted(remaining,
                                     key=lambda n: (self._grade_sort_key(n), n.get("difficulty", 1),
                                                    -n.get("source_count", 0), n.get("name", ""))):
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
                    "grade": GRADE_WEAK,
                    "children": orphan_children,
                })

        # 6. 排序一级主题（其他永远排最后）
        tree.sort(key=lambda t: (1 if t["id"] == -1 else 0, -t["node_count"], t["name"]))

        # 统计
        total_nodes = len(qualified)
        low_conf = sum(1 for n in all_nodes
                       if n.get("confidence", 0) < threshold
                       and n.get("review_status") != "rejected")
        core_count = sum(1 for n in qualified if n.get("_grade") == GRADE_CORE)

        return {
            "tree": tree,
            "stats": {
                "total_topics": len(topics),
                "total_nodes": total_nodes,
                "total_edges": self.graph.edge_count(),
                "low_confidence_count": low_conf,
                "core_count": core_count,
                "noise_filtered": noise_count,
            }
        }

    def _determine_topics(self, qualified: list[dict], qualified_ids: set[int]) -> list[dict]:
        """确定一级主题"""
        topics = [n for n in qualified if n.get("node_type") == "topic"]

        if not topics:
            concepts = sorted(qualified, key=lambda n: -n.get("source_count", 0))
            if concepts:
                top = concepts[0]
                top["node_type"] = "topic"
                topics = [top]

        for topic in topics:
            children = self.graph.get_children(topic["id"])
            topic["_child_count"] = len([c for c in children if c["id"] in qualified_ids])

        topics.sort(key=lambda t: -t.get("_child_count", 0))

        if len(topics) > 12:
            topics = topics[:12]

        return topics

    def _try_assign_orphans(self, orphans: list[dict], topics: list[dict],
                            tree: list[dict], node_map: dict) -> list[dict]:
        """尝试将孤儿节点归入现有主题（通过 related_to / main_topic_id）"""
        remaining = []
        topic_id_set = {t["id"] for t in topics}
        tree_map = {t["id"]: t for t in tree}

        for orphan in orphans:
            assigned = False
            # 优先通过 main_topic_id
            main_topic = orphan.get("main_topic_id")
            if main_topic and main_topic in topic_id_set and main_topic in tree_map:
                tree_map[main_topic]["children"].append(
                    self._make_tree_node(orphan, [], is_reference=False)
                )
                tree_map[main_topic]["node_count"] = len(tree_map[main_topic]["children"])
                assigned = True

            if not assigned:
                # 通过 related_to 找最相关的主题
                related = self.graph.get_related(orphan["id"])
                for r in related:
                    if r["id"] in topic_id_set and r["id"] in tree_map:
                        tree_map[r["id"]]["children"].append(
                            self._make_tree_node(orphan, [], is_reference=True)
                        )
                        tree_map[r["id"]]["node_count"] = len(tree_map[r["id"]]["children"])
                        assigned = True
                        break

            if not assigned:
                remaining.append(orphan)

        return remaining

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

            sub_children = []
            if not is_reference:
                sub_children = self._build_subtree(cid, node_map, qualified_ids, assigned)

            tree_node = self._make_tree_node(node, sub_children, is_reference=is_reference)
            children.append(tree_node)

        # 排序：核心优先 → 难度 → 来源数
        children.sort(key=lambda c: (self._grade_sort_key_from_tree(c),
                                     c["difficulty"], -c.get("node_count", 0), c["name"]))
        return children

    def _make_tree_node(self, node: dict, children: list[dict], is_reference: bool = False) -> dict:
        """创建树节点（包含质量等级）"""
        return {
            "id": node["id"],
            "name": node.get("name", ""),
            "node_type": node.get("node_type", "concept"),
            "difficulty": node.get("difficulty", 1),
            "definition": node.get("definition", ""),
            "video_count": 0,
            "node_count": len(children),
            "confidence": node.get("confidence", 0.5),
            "source_count": node.get("source_count", 1),
            "grade": node.get("_grade", GRADE_NORMAL),
            "is_reference": is_reference,
            "children": children,
        }

    @staticmethod
    def _grade_sort_key(node: dict) -> int:
        grade = node.get("_grade", GRADE_NORMAL)
        return {GRADE_CORE: 0, GRADE_NORMAL: 1, GRADE_WEAK: 2}.get(grade, 1)

    @staticmethod
    def _grade_sort_key_from_tree(tree_node: dict) -> int:
        grade = tree_node.get("grade", GRADE_NORMAL)
        return {GRADE_CORE: 0, GRADE_NORMAL: 1, GRADE_WEAK: 2}.get(grade, 1)

    def _empty_stats(self) -> dict:
        return {
            "total_topics": 0,
            "total_nodes": 0,
            "total_edges": 0,
            "low_confidence_count": 0,
            "core_count": 0,
            "noise_filtered": 0,
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
