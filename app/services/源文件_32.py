"""
BiliMind 知识树学习导航系统

问答路由器 — 将用户问题分发到不同检索策略

路由类型:
- vector:    事实检索类问题 → 走向量检索
- graph:     关系理解类问题 → 走图谱查询
- path:      学习路径类问题 → 走知识树/路径推荐
- hybrid:    综合问题 → 走混合检索
- db_list:   列表类问题 → 走数据库标题列表
- db_content:总结类问题 → 走数据库全文
- direct:    闲聊/无关 → 直接回答
"""
import re
from typing import Optional
from loguru import logger
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    KnowledgeNode, NodeSegmentLink, Segment, VideoCache,
    FavoriteFolder, FavoriteVideo, _fmt_time,
)
from app.services.graph_store import GraphStore
from app.services.rag import RAGService
from app.config import settings


class QueryRouter:
    """
    问答路由器

    分析用户问题 → 选择检索策略 → 执行检索 → 返回 context + evidence
    """

    # 关系/图谱类关键词
    GRAPH_KEYWORDS = [
        "前置", "前提", "先学", "后学", "依赖", "关系", "关联",
        "属于", "包含", "从属", "上级", "下级", "子类", "父类",
        "相关", "类似", "相似", "区别", "对比", "差异",
        "prerequisite", "related", "depends",
    ]

    # 路径/学习类关键词
    PATH_KEYWORDS = [
        "学习路径", "学习路线", "学习顺序", "怎么学", "学习计划",
        "入门", "进阶", "从哪里开始", "先学什么", "学完之后",
        "推荐顺序", "学习建议", "roadmap", "learning path",
    ]

    def classify_question(self, question: str) -> str:
        """
        分类用户问题

        Returns:
            路由类型: vector / graph / path / hybrid / db_list / db_content / direct
        """
        q = question.lower().strip()

        # 闲聊
        if self._is_general(q):
            return "direct"

        # 学习路径类
        if any(kw in q for kw in self.PATH_KEYWORDS):
            return "path"

        # 关系理解类
        if any(kw in q for kw in self.GRAPH_KEYWORDS):
            return "graph"

        # 列表类
        if self._is_list_question(q):
            return "db_list"

        # 总结类
        if self._is_summary_question(q):
            return "db_content"

        # 默认走向量检索
        return "vector"

    async def execute_graph_search(
        self,
        question: str,
        graph: GraphStore,
        db: AsyncSession,
        limit: int = 10,
    ) -> dict:
        """
        图谱检索：从问题中提取实体名，在图中查找相关节点和关系

        Returns:
            {
                "nodes": [{id, name, node_type, definition, ...}],
                "relations": [{source, target, type, ...}],
                "segments": [{id, video_bvid, text, time_label, ...}],
                "context": str (供 LLM 使用的文本)
            }
        """
        if graph.graph is None or graph.node_count() == 0:
            await graph.load_from_db(db)

        # 提取关键词并在图中搜索
        keywords = self._extract_keywords(question)
        matched_nodes = []

        for kw in keywords:
            results = graph.search_nodes_by_name(kw, limit=5)
            matched_nodes.extend(results)

        # 去重
        seen_ids = set()
        unique_nodes = []
        for n in matched_nodes:
            if n["id"] not in seen_ids:
                seen_ids.add(n["id"])
                unique_nodes.append(n)

        if not unique_nodes:
            return {"nodes": [], "relations": [], "segments": [], "context": ""}

        # 收集关系
        relations = []
        expanded_nodes = list(unique_nodes)  # 副本
        for node in unique_nodes:
            nid = node["id"]
            # 前置
            for p in graph.get_prerequisites(nid):
                relations.append({
                    "source": p.get("name", ""), "target": node.get("name", ""),
                    "type": "prerequisite_of", "source_id": p["id"], "target_id": nid,
                })
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    expanded_nodes.append(p)
            # 后续
            for s in graph.get_successors(nid):
                relations.append({
                    "source": node.get("name", ""), "target": s.get("name", ""),
                    "type": "prerequisite_of", "source_id": nid, "target_id": s["id"],
                })
                if s["id"] not in seen_ids:
                    seen_ids.add(s["id"])
                    expanded_nodes.append(s)
            # 相关
            for r in graph.get_related(nid):
                relations.append({
                    "source": node.get("name", ""), "target": r.get("name", ""),
                    "type": "related_to", "source_id": nid, "target_id": r["id"],
                })

        # 获取相关片段
        node_ids = [n["id"] for n in expanded_nodes[:limit]]
        segments = await self._get_segments_for_nodes(node_ids, db)

        # 构建 LLM context
        context = self._build_graph_context(expanded_nodes[:limit], relations[:20], segments[:10])

        return {
            "nodes": [
                {"id": n["id"], "name": n.get("name", ""), "node_type": n.get("node_type", ""),
                 "definition": n.get("definition", ""), "difficulty": n.get("difficulty", 1)}
                for n in expanded_nodes[:limit]
            ],
            "relations": relations[:20],
            "segments": segments[:10],
            "context": context,
        }

    async def _get_segments_for_nodes(
        self, node_ids: list[int], db: AsyncSession, limit: int = 10
    ) -> list[dict]:
        """获取节点关联的视频片段"""
        if not node_ids:
            return []

        links_result = await db.execute(
            select(NodeSegmentLink)
            .where(NodeSegmentLink.node_id.in_(node_ids))
            .limit(limit * 2)
        )
        links = links_result.scalars().all()
        if not links:
            return []

        seg_ids = list(set(link.segment_id for link in links))[:limit]
        seg_result = await db.execute(
            select(Segment).where(Segment.id.in_(seg_ids))
            .order_by(Segment.start_time)
        )

        segments = []
        for seg in seg_result.scalars().all():
            time_label = ""
            if seg.start_time is not None and seg.end_time is not None:
                time_label = f"{_fmt_time(seg.start_time)}-{_fmt_time(seg.end_time)}"
            segments.append({
                "id": seg.id,
                "video_bvid": seg.video_bvid,
                "text": (seg.cleaned_text or seg.raw_text or "")[:300],
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "time_label": time_label,
                "url": f"https://www.bilibili.com/video/{seg.video_bvid}?t={int(seg.start_time)}"
                       if seg.start_time is not None else None,
            })
        return segments

    def _build_graph_context(
        self, nodes: list[dict], relations: list[dict], segments: list[dict]
    ) -> str:
        """构建供 LLM 使用的图谱上下文"""
        parts = []

        if nodes:
            parts.append("## 相关知识点")
            for n in nodes:
                name = n.get("name", "")
                ntype = n.get("node_type", "")
                definition = n.get("definition", "")
                difficulty = n.get("difficulty", 1)
                parts.append(f"- [{ntype}] {name} (难度{difficulty}): {definition}")

        if relations:
            parts.append("\n## 知识关系")
            for r in relations:
                rtype = r.get("type", "related_to")
                type_labels = {
                    "prerequisite_of": "是...的前置",
                    "part_of": "属于",
                    "related_to": "相关于",
                    "explains": "解释",
                    "supports": "支持",
                    "recommends_next": "推荐接下来学",
                }
                label = type_labels.get(rtype, rtype)
                parts.append(f"- {r['source']} {label} {r['target']}")

        if segments:
            parts.append("\n## 相关视频片段")
            for s in segments:
                time_label = s.get("time_label", "")
                bvid = s.get("video_bvid", "")
                text = s.get("text", "")[:200]
                if time_label:
                    parts.append(f"- [{bvid} {time_label}] {text}")
                else:
                    parts.append(f"- [{bvid}] {text}")

        return "\n".join(parts)

    # ==================== 辅助方法 ====================

    @staticmethod
    def _is_general(question: str) -> bool:
        general_terms = [
            "你好", "嗨", "哈喽", "hello", "hi", "在吗", "你是谁",
            "你能做什么", "谢谢", "晚安", "早安", "早上好",
        ]
        cleaned = re.sub(r"[\W_]+", "", question, flags=re.UNICODE)
        residual = cleaned.lower()
        for term in general_terms:
            residual = residual.replace(term.lower(), "")
        return residual == ""

    @staticmethod
    def _is_list_question(question: str) -> bool:
        terms = ["有哪些", "有什么", "列表", "清单", "目录", "列出", "罗列", "多少个", "几个"]
        return any(t in question for t in terms)

    @staticmethod
    def _is_summary_question(question: str) -> bool:
        terms = ["总结", "概述", "概括", "分析", "梳理", "提炼", "回顾", "要点", "重点", "讲了什么"]
        return any(t in question for t in terms)

    @staticmethod
    def _extract_keywords(question: str) -> list[str]:
        """提取关键词用于图谱搜索"""
        stopwords = {
            "什么", "怎么", "如何", "是否", "可以", "哪个", "哪些", "请问", "一下",
            "为什么", "有没有", "能不能", "是不是", "是什么", "多少", "哪里",
            "讲讲", "介绍", "总结", "概括", "分析", "解释", "说明", "内容", "视频",
            "学习", "路径", "路线", "关系", "区别", "对比",
        }
        keywords = []
        for kw in re.findall(r"[\u4e00-\u9fff]{2,}", question):
            if kw not in stopwords and kw not in keywords:
                keywords.append(kw)
        for kw in re.findall(r"[A-Za-z0-9]{2,}", question):
            if kw.lower() not in keywords:
                keywords.append(kw)
        return keywords
