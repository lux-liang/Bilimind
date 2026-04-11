"""
BiliMind 知识树学习导航系统

GraphRAG 服务 — 社区检测 + 社区摘要 + 图增强检索
基于 Microsoft GraphRAG 思想：利用知识图谱的社区结构提供高层语义上下文
"""
import json
from typing import Optional
from loguru import logger

try:
    import networkx as nx
    from networkx.algorithms.community import louvain_communities
except ImportError:
    nx = None
    louvain_communities = None

from openai import AsyncOpenAI
from app.config import settings
from app.services.graph_store import GraphStore


COMMUNITY_SUMMARY_PROMPT = """你是知识图谱分析专家。以下是一组相互关联的知识概念（来自用户收藏的学习视频）。
请用 2-3 句话概括这组知识的核心主题、涵盖内容和内在关系。

知识概念：
{entities}

它们之间的关系：
{relations}

请直接输出概括，不要加前缀。"""


class GraphRAGService:
    """
    GraphRAG 服务

    核心功能：
    1. Louvain 社区检测 — 发现知识图谱中的主题聚类
    2. 社区摘要生成 — LLM 为每个社区生成高层语义描述
    3. 上下文注入 — 在 RAG 问答时提供社区级别的结构化上下文
    """

    def __init__(self, graph_store: GraphStore):
        self.graph_store = graph_store
        self.communities: dict[int, dict] = {}  # community_id -> {node_ids, summary, entities}
        self._node_to_community: dict[int, int] = {}  # node_id -> community_id
        self._built = False

    @property
    def is_built(self) -> bool:
        return self._built and len(self.communities) > 0

    async def build_communities(self, force: bool = False) -> dict:
        """
        运行 Louvain 社区检测并生成社区摘要

        Returns:
            {"community_count": int, "node_count": int, "summaries_generated": int}
        """
        if self._built and not force:
            return {
                "community_count": len(self.communities),
                "node_count": len(self._node_to_community),
                "summaries_generated": sum(1 for c in self.communities.values() if c.get("summary")),
            }

        if nx is None or louvain_communities is None:
            logger.warning("networkx 社区检测不可用")
            return {"community_count": 0, "node_count": 0, "summaries_generated": 0}

        graph = self.graph_store.graph
        if graph is None or graph.number_of_nodes() == 0:
            logger.info("图谱为空，跳过社区检测")
            return {"community_count": 0, "node_count": 0, "summaries_generated": 0}

        # Louvain 需要无向图
        undirected = graph.to_undirected()

        try:
            communities_list = louvain_communities(undirected, resolution=1.0, seed=42)
        except Exception as e:
            logger.error(f"Louvain 社区检测失败: {e}")
            return {"community_count": 0, "node_count": 0, "summaries_generated": 0}

        # 过滤掉太小的社区（少于2个节点）
        communities_list = [c for c in communities_list if len(c) >= 2]
        logger.info(f"Louvain 检测到 {len(communities_list)} 个社区（≥2节点）")

        self.communities.clear()
        self._node_to_community.clear()

        for idx, node_set in enumerate(communities_list):
            node_ids = list(node_set)
            entities = []
            for nid in node_ids:
                node_data = self.graph_store.get_node(nid)
                if node_data:
                    entities.append({
                        "id": nid,
                        "name": node_data.get("name", ""),
                        "type": node_data.get("node_type", ""),
                        "definition": node_data.get("definition", ""),
                    })
                self._node_to_community[nid] = idx

            # 收集社区内部的关系
            internal_relations = []
            for nid in node_ids:
                for _, tgt, data in graph.out_edges(nid, data=True):
                    if tgt in node_set:
                        src_name = graph.nodes[nid].get("name", str(nid))
                        tgt_name = graph.nodes[tgt].get("name", str(tgt))
                        rel_type = data.get("relation_type", "related_to")
                        internal_relations.append(f"{src_name} --[{rel_type}]--> {tgt_name}")

            self.communities[idx] = {
                "node_ids": node_ids,
                "entities": entities,
                "relations": internal_relations,
                "summary": None,
            }

        # 写入节点属性
        for nid, cid in self._node_to_community.items():
            if nid in graph:
                graph.nodes[nid]["community_id"] = cid

        # 生成社区摘要
        summaries_generated = await self._generate_summaries()

        self._built = True

        return {
            "community_count": len(self.communities),
            "node_count": len(self._node_to_community),
            "summaries_generated": summaries_generated,
        }

    async def _generate_summaries(self) -> int:
        """为每个社区生成 LLM 摘要"""
        if not settings.openai_api_key:
            logger.info("未配置 API Key，跳过社区摘要生成")
            return 0

        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

        generated = 0
        for cid, community in self.communities.items():
            entities = community["entities"]
            relations = community["relations"]

            if not entities:
                continue

            entities_text = "\n".join(
                f"- {e['name']}（{e['type']}）: {e['definition']}"
                for e in entities[:15]  # 限制数量避免 token 过多
            )
            relations_text = "\n".join(relations[:20]) if relations else "（无明显内部关系）"

            prompt = COMMUNITY_SUMMARY_PROMPT.format(
                entities=entities_text,
                relations=relations_text,
            )

            try:
                resp = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=200,
                )
                summary = (resp.choices[0].message.content or "").strip()
                if summary:
                    community["summary"] = summary
                    generated += 1
                    logger.debug(f"社区 {cid} 摘要: {summary[:80]}...")
            except Exception as e:
                logger.warning(f"社区 {cid} 摘要生成失败: {e}")

        logger.info(f"成功生成 {generated}/{len(self.communities)} 个社区摘要")
        return generated

    def get_community_for_node(self, node_id: int) -> Optional[int]:
        """获取节点所属的社区 ID"""
        return self._node_to_community.get(node_id)

    def get_community_context(self, node_ids: list[int], max_communities: int = 3) -> str:
        """
        获取一组节点相关的社区上下文

        根据 node_ids 找到相关社区，返回社区摘要文本

        Args:
            node_ids: 查询涉及的节点 ID 列表
            max_communities: 最多返回的社区数

        Returns:
            社区上下文文本，可直接注入 LLM prompt
        """
        if not self._built:
            return ""

        # 找到涉及的社区
        community_ids = set()
        for nid in node_ids:
            cid = self._node_to_community.get(nid)
            if cid is not None:
                community_ids.add(cid)

        if not community_ids:
            return ""

        # 按社区大小排序，优先返回较大的社区
        sorted_cids = sorted(
            community_ids,
            key=lambda cid: len(self.communities.get(cid, {}).get("node_ids", [])),
            reverse=True,
        )[:max_communities]

        parts = []
        for cid in sorted_cids:
            community = self.communities.get(cid)
            if not community:
                continue

            summary = community.get("summary")
            if summary:
                entity_names = [e["name"] for e in community["entities"][:8]]
                parts.append(
                    f"【知识群组：{', '.join(entity_names)}】\n{summary}"
                )

        if not parts:
            return ""

        return "以下是相关知识群组的高层概览：\n\n" + "\n\n".join(parts)

    def get_all_community_ids(self) -> dict[int, int]:
        """返回所有节点的社区分配（用于图谱可视化）"""
        return dict(self._node_to_community)
