"""
BiliMind 知识树学习导航系统

知识抽取服务 — LLM 结构化抽取 + 规则 fallback
"""
import json
import re
from typing import Optional
from loguru import logger
from openai import AsyncOpenAI

from app.config import settings
from app.models import NodeType, RelationType


EXTRACTION_PROMPT = """你是知识抽取专家。从以下视频文本片段中抽取知识实体和关系。

视频标题：{video_title}
文本片段：
{segment_text}

请严格输出以下JSON格式（不要输出其他内容）：
{{
  "entities": [
    {{"name": "实体名", "type": "topic|concept|method|tool|task", "definition": "一句话定义", "difficulty": 1-5, "confidence": 0.0-1.0}}
  ],
  "relations": [
    {{"source": "源实体名", "target": "目标实体名", "type": "prerequisite_of|part_of|related_to|explains|supports|recommends_next", "confidence": 0.0-1.0}}
  ]
}}

规则：
1. 只抽取文本中明确提到的知识实体
2. type 必须是 topic/concept/method/tool/task 之一
3. confidence 低于 0.3 的不要输出
4. 每个实体必须有简短的 definition
5. difficulty 表示学习难度：1=入门常识 2=基础概念 3=中级应用 4=高级原理 5=前沿/实战
6. 关系 type 必须是 prerequisite_of/part_of/related_to/explains/supports/recommends_next 之一
7. recommends_next 表示"学完 source 后推荐学 target"
8. 实体数量控制在 2-8 个，关系数量控制在 1-6 个
9. 不要抽取过于宽泛的实体（如"视频"、"学习"、"内容"）"""

VALID_NODE_TYPES = {t.value for t in NodeType}
VALID_RELATION_TYPES = {t.value for t in RelationType}


class KnowledgeExtractor:
    """
    知识抽取器

    主路径：LLM 结构化输出
    Fallback：规则 + 关键词提取
    """

    def __init__(self):
        self.client = None
        if settings.openai_api_key:
            self.client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
        self.min_confidence = settings.extraction_min_confidence

    async def extract_from_segment(
        self,
        segment_text: str,
        video_title: str,
    ) -> dict:
        """
        从文本片段抽取知识实体和关系

        Returns:
            {"entities": [...], "relations": [...]}
        """
        if not segment_text or len(segment_text.strip()) < 20:
            return {"entities": [], "relations": []}

        if self.client:
            try:
                result = await self._extract_with_llm(segment_text, video_title)
                if result["entities"]:
                    return result
            except Exception as e:
                logger.warning(f"LLM extraction failed, falling back to rules: {e}")

        return self._extract_with_rules(segment_text, video_title)

    async def extract_from_segments(
        self,
        segments: list[dict],
        video_title: str,
    ) -> dict:
        """
        从多个片段批量抽取，合并结果

        Args:
            segments: [{"text": str, "segment_id": int, "video_bvid": str}]
        """
        all_entities = []
        all_relations = []

        for seg in segments:
            text = seg.get("text", "")
            result = await self.extract_from_segment(text, video_title)

            for entity in result.get("entities", []):
                entity["_segment_id"] = seg.get("segment_id")
                entity["_video_bvid"] = seg.get("video_bvid")
                all_entities.append(entity)

            for relation in result.get("relations", []):
                relation["_segment_id"] = seg.get("segment_id")
                relation["_video_bvid"] = seg.get("video_bvid")
                all_relations.append(relation)

        merged = self._merge_and_deduplicate(all_entities, all_relations)
        return merged

    # ==================== LLM 抽取 ====================

    async def _extract_with_llm(self, segment_text: str, video_title: str) -> dict:
        """使用 LLM 抽取"""
        prompt = EXTRACTION_PROMPT.format(
            video_title=video_title,
            segment_text=segment_text[:3000],
        )

        response = await self.client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
        )

        raw = response.choices[0].message.content.strip()
        parsed = self._parse_llm_output(raw)
        return parsed

    def _parse_llm_output(self, raw: str) -> dict:
        """解析 LLM JSON 输出"""
        # 尝试从 markdown 代码块中提取
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(1)

        # 尝试直接找 JSON 对象
        brace_start = raw.find("{")
        brace_end = raw.rfind("}")
        if brace_start != -1 and brace_end != -1:
            raw = raw[brace_start:brace_end + 1]

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM output as JSON")
            return {"entities": [], "relations": []}

        entities = self._validate_entities(data.get("entities", []))
        relations = self._validate_relations(data.get("relations", []))
        return {"entities": entities, "relations": relations}

    def _validate_entities(self, entities: list) -> list:
        """验证实体列表"""
        valid = []
        for e in entities:
            if not isinstance(e, dict):
                continue
            name = (e.get("name") or "").strip()
            if not name or len(name) < 2:
                continue
            node_type = e.get("type", "concept")
            if node_type not in VALID_NODE_TYPES:
                node_type = "concept"
            confidence = float(e.get("confidence", 0.5))
            if confidence < self.min_confidence:
                continue
            difficulty = int(e.get("difficulty", 1))
            difficulty = max(1, min(5, difficulty))
            valid.append({
                "name": name,
                "type": node_type,
                "definition": (e.get("definition") or "").strip(),
                "difficulty": difficulty,
                "confidence": confidence,
            })
        return valid

    def _validate_relations(self, relations: list) -> list:
        """验证关系列表"""
        valid = []
        for r in relations:
            if not isinstance(r, dict):
                continue
            source = (r.get("source") or "").strip()
            target = (r.get("target") or "").strip()
            if not source or not target:
                continue
            rel_type = r.get("type", "related_to")
            if rel_type not in VALID_RELATION_TYPES:
                rel_type = "related_to"
            confidence = float(r.get("confidence", 0.5))
            if confidence < self.min_confidence:
                continue
            valid.append({
                "source": source,
                "target": target,
                "type": rel_type,
                "confidence": confidence,
            })
        return valid

    # ==================== 规则 Fallback ====================

    def _extract_with_rules(self, segment_text: str, video_title: str) -> dict:
        """规则 + 关键词提取 fallback"""
        entities = []
        relations = []

        # 从标题提取主题
        title_topic = self._clean_title_for_topic(video_title)
        if title_topic:
            entities.append({
                "name": title_topic,
                "type": "topic",
                "definition": f"来自视频《{video_title}》的主题",
                "confidence": 0.6,
            })

        # 简单关键词提取
        keywords = self._extract_keywords(segment_text)
        for kw in keywords[:5]:
            entities.append({
                "name": kw,
                "type": "concept",
                "definition": f"在视频《{video_title}》中被提及的概念",
                "confidence": 0.4,
            })
            if title_topic:
                relations.append({
                    "source": kw,
                    "target": title_topic,
                    "type": "part_of",
                    "confidence": 0.3,
                })

        return {"entities": entities, "relations": relations}

    def _clean_title_for_topic(self, title: str) -> str:
        """从视频标题提取主题"""
        # 去除常见无用前缀/后缀
        title = re.sub(r"【.*?】", "", title)
        title = re.sub(r"\[.*?\]", "", title)
        title = re.sub(r"[第]?\d+[集讲期章节课p]", "", title, flags=re.IGNORECASE)
        title = re.sub(r"[|｜\-—·].*$", "", title)
        title = title.strip()
        return title if len(title) >= 2 else ""

    def _extract_keywords(self, text: str) -> list[str]:
        """简单关键词提取"""
        # 提取英文术语（2+ 字母，可能包含连字符）
        en_terms = re.findall(r"\b[A-Za-z][A-Za-z\-]{2,}\b", text)
        # 提取中文术语（引号或书名号内的内容）
        zh_quoted = re.findall(r"[\u300c\u201c\u300a](.+?)[\u300d\u201d\u300b]", text)
        # 提取"XX是XX"模式中的主语
        zh_is = re.findall(r"([\u4e00-\u9fff]{2,6})(?:是|指|即|为)", text)

        all_terms = []
        seen = set()
        for term in en_terms + zh_quoted + zh_is:
            term = term.strip()
            lower = term.lower()
            if lower in seen or len(term) < 2:
                continue
            # 过滤常见停用词
            if lower in {"the", "this", "that", "and", "for", "with", "from",
                          "are", "was", "were", "have", "has", "been", "not",
                          "our", "their", "其中", "这个", "那个", "可以", "进行",
                          "使用", "通过", "如果", "因为", "所以", "但是"}:
                continue
            seen.add(lower)
            all_terms.append(term)

        return all_terms[:10]

    # ==================== 去重/归一化 ====================

    def _merge_and_deduplicate(self, entities: list, relations: list) -> dict:
        """合并和去重实体与关系"""
        name_map: dict[str, dict] = {}  # normalized_name -> best entity

        for e in entities:
            normalized = self._normalize_name(e["name"])
            if normalized in name_map:
                existing = name_map[normalized]
                existing["confidence"] = max(existing["confidence"], e.get("confidence", 0.5))
                existing["source_count"] = existing.get("source_count", 1) + 1
                existing["difficulty"] = max(existing.get("difficulty", 1), e.get("difficulty", 1))
                if e.get("definition") and not existing.get("definition"):
                    existing["definition"] = e["definition"]
                # 保留 segment 追踪
                if "_segment_id" in e:
                    existing.setdefault("_segment_ids", []).append(e["_segment_id"])
                if "_video_bvid" in e:
                    existing.setdefault("_video_bvids", []).append(e["_video_bvid"])
            else:
                entry = dict(e)
                entry["normalized_name"] = normalized
                entry["source_count"] = 1
                if "_segment_id" in e:
                    entry["_segment_ids"] = [e["_segment_id"]]
                if "_video_bvid" in e:
                    entry["_video_bvids"] = [e["_video_bvid"]]
                # 保留 difficulty（取最大值策略）
                entry.setdefault("difficulty", 1)
                name_map[normalized] = entry

        # 调整置信度：被多个片段提及的节点更可信
        for entry in name_map.values():
            sc = entry.get("source_count", 1)
            entry["confidence"] = min(1.0, entry["confidence"] * min(1.0, sc / 3.0 + 0.5))

        # 去重关系
        edge_key_set = set()
        merged_relations = []
        for r in relations:
            src_norm = self._normalize_name(r["source"])
            tgt_norm = self._normalize_name(r["target"])
            key = (src_norm, tgt_norm, r["type"])
            if key in edge_key_set:
                continue
            # 确保源和目标实体都存在
            if src_norm not in name_map or tgt_norm not in name_map:
                continue
            edge_key_set.add(key)
            merged_relations.append({
                "source": r["source"],
                "target": r["target"],
                "source_normalized": src_norm,
                "target_normalized": tgt_norm,
                "type": r["type"],
                "confidence": r.get("confidence", 0.5),
                "_segment_id": r.get("_segment_id"),
                "_video_bvid": r.get("_video_bvid"),
            })

        return {
            "entities": list(name_map.values()),
            "relations": merged_relations,
        }

    @staticmethod
    def _normalize_name(name: str) -> str:
        """归一化实体名称"""
        name = name.strip().lower()
        name = re.sub(r"\s+", " ", name)
        # 去除括号内的说明文字
        name = re.sub(r"[（(].*?[）)]", "", name).strip()
        return name
