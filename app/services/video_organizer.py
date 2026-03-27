"""
Video Organizer service.

基于现有收藏、缓存和知识抽取结果，生成收藏整理报告。
第一版以规则 + 统计特征为主，不依赖额外持久化表。
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Claim, FavoriteFolder, FavoriteVideo, KnowledgeNode, NodeSegmentLink, Segment, VideoCache
from app.services.video_classifier import OrganizerClassifierService, OrganizerVideoSample


SUBJECT_KEYWORDS: dict[str, list[str]] = {
    "AI": ["ai", "llm", "agent", "大模型", "机器学习", "深度学习", "神经网络", "transformer", "nlp", "cv"],
    "算法": ["算法", "数据结构", "刷题", "leetcode", "动态规划", "图论", "二叉树", "dp", "dfs", "bfs"],
    "前端": ["前端", "react", "vue", "next.js", "typescript", "javascript", "css", "html", "node"],
    "英语": ["英语", "单词", "语法", "听力", "口语", "雅思", "托福", "四六级"],
    "考研": ["考研", "408", "政治", "数学一", "数学二", "专业课", "复试"],
    "科研": ["科研", "论文", "实验", "文献", "研究", "academic", "paper", "review"],
    "工具": ["工具", "效率", "obsidian", "notion", "cursor", "vscode", "git", "docker", "linux"],
}

CONTENT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "概念讲解": ["是什么", "原理", "理解", "概念", "本质", "详解", "入门"],
    "教程实战": ["教程", "实战", "项目", "从零", "手把手", "开发", "搭建", "案例"],
    "刷题训练": ["刷题", "题解", "习题", "真题", "练习", "训练营", "leetcode"],
    "经验分享": ["经验", "分享", "心得", "建议", "避坑", "规划", "路线"],
    "资讯解读": ["资讯", "新闻", "解读", "速递", "发布会", "更新", "趋势"],
    "工具演示": ["工具", "插件", "工作流", "效率", "配置", "演示", "测评"],
}

LOW_VALUE_KEYWORDS = ["资讯", "热点", "搬运", "合集", "广告", "抽奖", "发布会", "直播回放", "reaction"]
CORE_VALUE_KEYWORDS = ["系统", "入门", "基础", "实战", "路线", "教程", "原理", "课程", "训练营"]
DUPLICATE_THRESHOLD = 0.64

SERIES_PATTERNS = [
    r"第\s*\d+\s*[讲课集期章篇季]",
    r"\b[pP]\s*\d+\b",
    r"\bpart\s*\d+\b",
    r"\blesson\s*\d+\b",
    r"\bchapter\s*\d+\b",
    r"\bep(?:isode)?\s*\d+\b",
]


@dataclass
class VideoFeatures:
    bvid: str
    title: str
    description: str
    summary: str
    owner_name: str
    duration: int
    pic_url: Optional[str]
    folder_ids: list[int]
    folder_titles: list[str]
    segment_count: int
    claim_count: int
    concept_count: int
    knowledge_node_count: int
    avg_node_difficulty: float
    node_names: list[str]
    node_types: list[str]
    node_confidence_avg: float
    tags: list[str]


class VideoOrganizerService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.classifier = OrganizerClassifierService()

    async def build_report(self, session_id: str, folder_ids: Optional[list[int]] = None) -> dict[str, Any]:
        folder_map = await self._load_folders(session_id, folder_ids)
        video_folder_map = await self._load_video_folders(session_id, folder_map)
        bvids = sorted(video_folder_map.keys())
        if not bvids:
            return self._empty_report()

        features = await self._load_video_features(session_id, bvids, video_folder_map)
        videos = [self._analyze_video(item) for item in features]

        series_groups = self._detect_series_groups(videos)
        series_map = {
            video["bvid"]: {"series_key": group["series_key"], "series_name": group["series_name"]}
            for group in series_groups
            for video in group["videos"]
        }
        for video in videos:
            series_info = series_map.get(video["bvid"])
            if series_info:
                video.update(series_info)
                video["reasons"].append(f"识别为系列内容：{series_info['series_name']}")

        duplicate_groups = self._detect_duplicate_groups(videos)
        duplicate_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        archived_bvids: set[str] = set()
        for group in duplicate_groups:
            keep_bvid = group["recommended_keep_bvid"]
            for item in group["items"]:
                duplicate_map[item["bvid"]].append({
                    "group_id": group["group_id"],
                    "similarity": item["similarity"],
                    "recommended_keep": item["bvid"] == keep_bvid,
                })
                if item["bvid"] != keep_bvid:
                    archived_bvids.add(item["bvid"])

        for video in videos:
            if duplicate_map.get(video["bvid"]):
                video["duplicate_candidates"] = duplicate_map[video["bvid"]]
                max_similarity = max(item["similarity"] for item in duplicate_map[video["bvid"]])
                video["reasons"].append(f"存在高度相似收藏，最高相似度 {round(max_similarity * 100)}%")
                if video["bvid"] in archived_bvids:
                    video["value_tier"] = "低价值/噪声"

        suggestions = self._generate_suggestions(videos, series_groups, duplicate_groups)
        facet_counts = self._build_facet_counts(videos)
        summary = {
            "total_videos": len(videos),
            "series_count": len(series_groups),
            "duplicate_group_count": len(duplicate_groups),
            "core_count": sum(1 for v in videos if v["value_tier"] == "主线核心"),
            "low_value_count": sum(1 for v in videos if v["value_tier"] == "低价值/噪声"),
            "compiled_count": sum(1 for v in videos if v["segment_count"] > 0 or v["claim_count"] > 0),
        }

        videos.sort(key=lambda item: (-item["organize_score"], item["title"]))
        return {
            "summary": summary,
            "videos": videos,
            "series_groups": series_groups,
            "duplicate_groups": duplicate_groups,
            "suggestions": suggestions,
            "facet_counts": facet_counts,
            "export_generated_at": datetime.utcnow().isoformat(),
        }

    async def export_report(self, session_id: str, format_name: str = "json") -> tuple[str, str, str]:
        report = await self.build_report(session_id=session_id)
        if format_name == "markdown":
            body = self._render_markdown(report)
            return body, "text/markdown; charset=utf-8", "organizer-report.md"
        if format_name == "json":
            import json
            body = json.dumps(report, ensure_ascii=False, indent=2)
            return body, "application/json; charset=utf-8", "organizer-report.json"
        raise ValueError(f"unsupported format: {format_name}")

    async def _load_folders(self, session_id: str, folder_ids: Optional[list[int]]) -> dict[int, FavoriteFolder]:
        query = select(FavoriteFolder).where(FavoriteFolder.session_id == session_id)
        if folder_ids:
            query = query.where(FavoriteFolder.media_id.in_(folder_ids))
        rows = await self.db.execute(query)
        folders = rows.scalars().all()
        return {folder.id: folder for folder in folders}

    async def _load_video_folders(
        self,
        session_id: str,
        folder_map: dict[int, FavoriteFolder],
    ) -> dict[str, list[FavoriteFolder]]:
        if not folder_map:
            return {}
        rows = await self.db.execute(
            select(FavoriteVideo.bvid, FavoriteVideo.folder_id)
            .join(FavoriteFolder, FavoriteVideo.folder_id == FavoriteFolder.id)
            .where(
                FavoriteFolder.session_id == session_id,
                FavoriteVideo.folder_id.in_(list(folder_map.keys())),
            )
        )
        grouped: dict[str, list[FavoriteFolder]] = defaultdict(list)
        for bvid, folder_id in rows.all():
            folder = folder_map.get(folder_id)
            if folder and folder not in grouped[bvid]:
                grouped[bvid].append(folder)
        return grouped

    async def _load_video_features(
        self,
        session_id: str,
        bvids: list[str],
        video_folder_map: dict[str, list[FavoriteFolder]],
    ) -> list[VideoFeatures]:
        cache_rows = await self.db.execute(select(VideoCache).where(VideoCache.bvid.in_(bvids)))
        cache_map = {item.bvid: item for item in cache_rows.scalars().all()}

        claim_rows = await self.db.execute(
            select(
                Claim.video_bvid,
                func.count(Claim.id),
                func.count(func.distinct(Claim.concept_id)),
            )
            .where(
                Claim.session_id == session_id,
                Claim.video_bvid.in_(bvids),
            )
            .group_by(Claim.video_bvid)
        )
        claim_map = {
            row[0]: {"claim_count": int(row[1] or 0), "concept_count": int(row[2] or 0)}
            for row in claim_rows.all()
        }

        segment_rows = await self.db.execute(
            select(Segment.video_bvid, func.count(Segment.id))
            .where(
                Segment.session_id == session_id,
                Segment.video_bvid.in_(bvids),
            )
            .group_by(Segment.video_bvid)
        )
        segment_map = {row[0]: int(row[1] or 0) for row in segment_rows.all()}

        node_rows = await self.db.execute(
            select(
                NodeSegmentLink.video_bvid,
                KnowledgeNode.name,
                KnowledgeNode.node_type,
                KnowledgeNode.difficulty,
                KnowledgeNode.confidence,
            )
            .join(KnowledgeNode, KnowledgeNode.id == NodeSegmentLink.node_id)
            .where(
                NodeSegmentLink.session_id == session_id,
                KnowledgeNode.session_id == session_id,
                NodeSegmentLink.video_bvid.in_(bvids),
            )
        )
        node_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in node_rows.all():
            node_map[row[0]].append({
                "name": row[1],
                "node_type": row[2],
                "difficulty": int(row[3] or 1),
                "confidence": float(row[4] or 0.5),
            })

        features: list[VideoFeatures] = []
        for bvid in bvids:
            cache = cache_map.get(bvid)
            folders = video_folder_map.get(bvid, [])
            node_items = node_map.get(bvid, [])
            difficulties = [item["difficulty"] for item in node_items]
            confidences = [item["confidence"] for item in node_items]
            tags = cache.tags if cache and isinstance(cache.tags, list) else []
            features.append(VideoFeatures(
                bvid=bvid,
                title=(cache.title if cache else bvid) or bvid,
                description=(cache.description if cache and cache.description else "") or "",
                summary=(cache.summary if cache and cache.summary else "") or "",
                owner_name=(cache.owner_name if cache and cache.owner_name else "") or "",
                duration=int(cache.duration or 0) if cache else 0,
                pic_url=cache.pic_url if cache else None,
                folder_ids=[folder.media_id for folder in folders],
                folder_titles=[folder.title for folder in folders],
                segment_count=segment_map.get(bvid, 0),
                claim_count=claim_map.get(bvid, {}).get("claim_count", 0),
                concept_count=claim_map.get(bvid, {}).get("concept_count", 0),
                knowledge_node_count=len({item["name"] for item in node_items}),
                avg_node_difficulty=(sum(difficulties) / len(difficulties)) if difficulties else 0.0,
                node_names=list({item["name"] for item in node_items}),
                node_types=[item["node_type"] for item in node_items],
                node_confidence_avg=(sum(confidences) / len(confidences)) if confidences else 0.0,
                tags=[str(tag) for tag in tags],
            ))
        return features

    def _analyze_video(self, item: VideoFeatures) -> dict[str, Any]:
        full_text = self._build_text(item)
        subject_tags, subject_reasons = self._classify_subjects(full_text)
        content_type, content_reason = self._classify_content_type(full_text)
        difficulty_level, difficulty_reason = self._classify_difficulty(item, full_text)
        learning_status = self._classify_learning_status(item)
        organize_score, value_tier, value_reasons = self._score_value(item, subject_tags, content_type, learning_status, full_text)

        ml_predictions = self._predict_with_model(item)
        if ml_predictions:
            primary_subject = ml_predictions.get("primary_subject")
            if primary_subject and primary_subject["confidence"] >= 0.62:
                predicted_subject = primary_subject["label"]
                if predicted_subject not in subject_tags:
                    subject_tags = [predicted_subject, *subject_tags][:3]
                subject_reasons.append(f"轻量模型识别主题：{predicted_subject}")

            content_pred = ml_predictions.get("content_type")
            if content_pred and content_pred["confidence"] >= 0.6:
                content_type = content_pred["label"]
                content_reason = [f"轻量模型判定内容类型：{content_type}"]

            difficulty_pred = ml_predictions.get("difficulty_level")
            if difficulty_pred and difficulty_pred["confidence"] >= 0.58:
                difficulty_level = difficulty_pred["label"]
                difficulty_reason = f"轻量模型判定难度：{difficulty_level}"

            value_pred = ml_predictions.get("value_tier")
            if value_pred and value_pred["confidence"] >= 0.64:
                value_tier = value_pred["label"]
                value_reasons.append(f"轻量模型判定收藏价值：{value_tier}")

        reasons = [*subject_reasons, *content_reason, difficulty_reason, *value_reasons]
        if item.knowledge_node_count:
            reasons.append(f"关联 {item.knowledge_node_count} 个知识节点")
        if item.claim_count:
            reasons.append(f"抽取到 {item.claim_count} 条论断")

        is_core = value_tier == "主线核心"
        return {
            "bvid": item.bvid,
            "title": item.title,
            "owner_name": item.owner_name,
            "duration": item.duration,
            "pic_url": item.pic_url,
            "folder_ids": item.folder_ids,
            "folder_titles": item.folder_titles,
            "subject_tags": subject_tags or ["未分类"],
            "content_type": content_type,
            "difficulty_level": difficulty_level,
            "learning_status": learning_status,
            "value_tier": value_tier,
            "organize_score": round(organize_score, 1),
            "segment_count": item.segment_count,
            "claim_count": item.claim_count,
            "concept_count": item.concept_count,
            "knowledge_node_count": item.knowledge_node_count,
            "confidence": round(item.node_confidence_avg or min(0.95, 0.4 + item.claim_count * 0.05), 2),
            "is_core": is_core,
            "reasons": list(dict.fromkeys([reason for reason in reasons if reason])),
            "ml_predictions": ml_predictions,
            "series_key": None,
            "series_name": None,
            "duplicate_candidates": [],
        }

    def _predict_with_model(self, item: VideoFeatures) -> dict[str, dict]:
        if not self.classifier.is_enabled:
            return {}
        sample = OrganizerVideoSample(
            title=item.title,
            description=item.description,
            summary=item.summary,
            folder_titles=item.folder_titles,
            tags=item.tags,
            knowledge_node_count=item.knowledge_node_count,
            claim_count=item.claim_count,
            segment_count=item.segment_count,
            avg_node_difficulty=item.avg_node_difficulty,
            node_confidence_avg=item.node_confidence_avg,
            duration=item.duration,
        )
        return self.classifier.predict(sample)

    def _build_text(self, item: VideoFeatures) -> str:
        blob = " ".join([
            item.title,
            item.description,
            item.summary,
            " ".join(item.node_names),
            " ".join(item.tags),
            " ".join(item.folder_titles),
        ])
        return re.sub(r"\s+", " ", blob.lower())

    def _classify_subjects(self, text: str) -> tuple[list[str], list[str]]:
        scores: dict[str, int] = {}
        reasons: list[str] = []
        for subject, keywords in SUBJECT_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw.lower() in text)
            if count > 0:
                scores[subject] = count
                reasons.append(f"标题/简介命中主题词：{subject}")
        ordered = [name for name, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]
        return ordered[:3], reasons[:2]

    def _classify_content_type(self, text: str) -> tuple[str, list[str]]:
        scores: dict[str, int] = {}
        for kind, keywords in CONTENT_TYPE_KEYWORDS.items():
            scores[kind] = sum(1 for kw in keywords if kw.lower() in text)
        best_kind = max(scores.items(), key=lambda item: item[1])[0]
        if scores[best_kind] <= 0:
            return "概念讲解", []
        return best_kind, [f"标题模式更接近：{best_kind}"]

    def _classify_difficulty(self, item: VideoFeatures, text: str) -> tuple[str, str]:
        if any(word in text for word in ["高阶", "源码", "底层", "优化", "论文"]):
            return "高阶", "难度由标题关键词判定为高阶"
        if any(word in text for word in ["进阶", "提高", "系统", "项目", "实战"]):
            return "进阶", "难度由标题关键词判定为进阶"
        if any(word in text for word in ["入门", "基础", "零基础", "新手"]):
            return "入门", "难度由标题关键词判定为入门"
        if item.avg_node_difficulty >= 4:
            return "高阶", "关联知识节点平均难度偏高"
        if item.avg_node_difficulty >= 2.5:
            return "进阶", "关联知识节点平均难度中等"
        return "入门", "缺少复杂知识节点，默认视为入门"

    def _classify_learning_status(self, item: VideoFeatures) -> str:
        if item.segment_count == 0 and item.claim_count == 0 and item.knowledge_node_count == 0:
            return "未看"
        if item.claim_count >= 8 and item.concept_count >= 4:
            return "待复习"
        if item.claim_count >= 4 or item.knowledge_node_count >= 5:
            return "已学"
        return "在学"

    def _score_value(
        self,
        item: VideoFeatures,
        subject_tags: list[str],
        content_type: str,
        learning_status: str,
        text: str,
    ) -> tuple[float, str, list[str]]:
        score = 35.0
        reasons: list[str] = []

        if subject_tags:
            score += min(15, 5 * len(subject_tags))
            reasons.append("主题较明确")
        if content_type in {"教程实战", "概念讲解", "刷题训练"}:
            score += 12
            reasons.append(f"{content_type}更适合作为主线学习材料")
        if item.knowledge_node_count >= 5:
            score += 10
        elif item.knowledge_node_count >= 2:
            score += 6
        if item.claim_count >= 5:
            score += 8
        if item.node_confidence_avg >= 0.75:
            score += 5
        if any(word.lower() in text for word in CORE_VALUE_KEYWORDS):
            score += 8
        if learning_status == "待复习":
            score += 4
        if any(word.lower() in text for word in LOW_VALUE_KEYWORDS):
            score -= 14
            reasons.append("存在资讯/泛内容词，优先级下调")
        if item.duration and item.duration < 180 and item.knowledge_node_count <= 1:
            score -= 6

        score = max(0.0, min(100.0, score))
        if score >= 72:
            tier = "主线核心"
        elif score >= 45:
            tier = "补充材料"
        else:
            tier = "低价值/噪声"
        return score, tier, reasons

    def _series_base_name(self, title: str) -> Optional[str]:
        lowered = title.lower()
        if not any(re.search(pattern, lowered) for pattern in SERIES_PATTERNS):
            return None
        base = lowered
        for pattern in SERIES_PATTERNS:
            base = re.sub(pattern, " ", base, flags=re.IGNORECASE)
        base = re.sub(r"[\[\]()（）【】\-_:：·|]+", " ", base)
        base = re.sub(r"\s+", " ", base).strip()
        if len(base) < 4:
            return None
        return base

    def _detect_series_groups(self, videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for video in videos:
            base = self._series_base_name(video["title"])
            if base:
                groups[base].append(video)

        results: list[dict[str, Any]] = []
        for series_key, items in groups.items():
            if len(items) < 2:
                continue
            ordered = sorted(items, key=lambda item: item["title"])
            results.append({
                "series_key": series_key,
                "series_name": ordered[0]["title"][:36],
                "video_count": len(ordered),
                "coverage_score": round(sum(item["organize_score"] for item in ordered) / len(ordered), 1),
                "reasons": ["标题存在连续讲次/分集模式", f"系列下共 {len(ordered)} 个视频"],
                "videos": [{
                    "bvid": item["bvid"],
                    "title": item["title"],
                    "organize_score": item["organize_score"],
                    "difficulty_level": item["difficulty_level"],
                } for item in ordered],
            })
        results.sort(key=lambda item: (-item["video_count"], -item["coverage_score"], item["series_name"]))
        return results

    def _detect_duplicate_groups(self, videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        parent = {video["bvid"]: video["bvid"] for video in videos}
        video_map = {video["bvid"]: video for video in videos}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        similarities: dict[tuple[str, str], float] = {}
        for left, right in combinations(videos, 2):
            if left.get("series_key") and left.get("series_key") == right.get("series_key"):
                continue
            similarity = self._similarity(left, right)
            if similarity >= DUPLICATE_THRESHOLD:
                similarities[(left["bvid"], right["bvid"])] = similarity
                union(left["bvid"], right["bvid"])

        groups: dict[str, list[str]] = defaultdict(list)
        for bvid in parent:
            groups[find(bvid)].append(bvid)

        results: list[dict[str, Any]] = []
        group_index = 1
        for _, members in groups.items():
            if len(members) < 2:
                continue
            items = []
            ranked = sorted((video_map[bvid] for bvid in members), key=lambda item: (-item["organize_score"], -item["knowledge_node_count"], item["title"]))
            keep_bvid = ranked[0]["bvid"]
            for bvid in members:
                peer_scores = [
                    score
                    for (a, b), score in similarities.items()
                    if a == bvid or b == bvid
                ]
                items.append({
                    "bvid": bvid,
                    "title": video_map[bvid]["title"],
                    "similarity": round(max(peer_scores) if peer_scores else DUPLICATE_THRESHOLD, 2),
                    "organize_score": video_map[bvid]["organize_score"],
                })
            results.append({
                "group_id": f"dup-{group_index}",
                "reason": "标题语义与知识节点重合度较高",
                "recommended_keep_bvid": keep_bvid,
                "archive_candidates": [item["bvid"] for item in items if item["bvid"] != keep_bvid],
                "items": sorted(items, key=lambda item: (-item["similarity"], -item["organize_score"])),
            })
            group_index += 1
        return results

    def _similarity(self, left: dict[str, Any], right: dict[str, Any]) -> float:
        title_sim = self._jaccard(self._tokenize(left["title"]), self._tokenize(right["title"]))
        subject_sim = self._jaccard(left["subject_tags"], right["subject_tags"])
        folder_sim = self._jaccard(left["folder_titles"], right["folder_titles"])
        node_strength = min(left["knowledge_node_count"], right["knowledge_node_count"]) / max(
            max(left["knowledge_node_count"], right["knowledge_node_count"]), 1
        )
        duration_gap = abs((left["duration"] or 0) - (right["duration"] or 0))
        duration_sim = 1.0 if duration_gap <= 120 else max(0.0, 1.0 - duration_gap / 2400.0)
        score = (
            title_sim * 0.45 +
            subject_sim * 0.2 +
            node_strength * 0.2 +
            duration_sim * 0.1 +
            folder_sim * 0.05
        )
        return round(score, 3)

    def _tokenize(self, text: str) -> list[str]:
        lowered = text.lower()
        tokens = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", lowered)
        stopwords = {"视频", "教程", "合集", "一集", "第", "讲", "课", "版", "的", "了"}
        cleaned = [token for token in tokens if token not in stopwords and len(token) > 1]
        expanded: list[str] = []
        for token in cleaned:
            expanded.append(token)
            if re.search(r"[\u4e00-\u9fff]", token):
                expanded.extend(token[idx:idx + 2] for idx in range(len(token) - 1))
        return expanded

    def _jaccard(self, left: Iterable[str], right: Iterable[str]) -> float:
        a, b = set(left), set(right)
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def _generate_suggestions(
        self,
        videos: list[dict[str, Any]],
        series_groups: list[dict[str, Any]],
        duplicate_groups: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []

        subject_counter = Counter(tag for video in videos for tag in video["subject_tags"] if tag != "未分类")
        for subject, count in subject_counter.most_common(3):
            if count < 3:
                continue
            targets = [video["bvid"] for video in videos if subject in video["subject_tags"]][:6]
            suggestions.append({
                "type": "create_topic",
                "title": f"建议建立「{subject}」主题分类",
                "description": f"当前收藏中有 {count} 个与 {subject} 强相关的视频，适合单独归组管理。",
                "targets": targets,
                "confidence": 0.82,
                "evidence": [f"{count} 个视频命中同一主题词", "标题/知识节点均出现稳定主题特征"],
            })

            move_targets = [
                video["bvid"]
                for video in videos
                if subject in video["subject_tags"] and not any(subject in title for title in video["folder_titles"])
            ][:6]
            if move_targets:
                suggestions.append({
                    "type": "move_folder",
                    "title": f"建议将相关视频归入「{subject}」主题",
                    "description": f"有一批 {subject} 视频当前不在同主题收藏夹中，适合单独整理归类。",
                    "targets": move_targets,
                    "confidence": 0.78,
                    "evidence": ["当前收藏夹命名与主题标签不一致", f"{subject} 标签稳定出现"],
                })

        for group in duplicate_groups[:3]:
            keep_bvid = group["recommended_keep_bvid"]
            suggestions.append({
                "type": "dedupe",
                "title": "建议处理重复/相似收藏",
                "description": f"重复组 {group['group_id']} 建议保留 {keep_bvid}，其余内容可归档或降权。",
                "targets": [item["bvid"] for item in group["items"]],
                "confidence": 0.88,
                "evidence": [group["reason"], f"最高相似度 {max(item['similarity'] for item in group['items']) * 100:.0f}%"],
            })

        core_videos = [video for video in videos if video["value_tier"] == "主线核心"]
        if core_videos:
            core_targets = [video["bvid"] for video in sorted(core_videos, key=lambda item: -item["organize_score"])[:5]]
            suggestions.append({
                "type": "prioritize",
                "title": "建议将高价值视频纳入主学习路径",
                "description": "这些视频主题清晰、知识节点密度高，更适合作为主线学习材料。",
                "targets": core_targets,
                "confidence": 0.9,
                "evidence": ["知识节点密度较高", "内容类型偏教程/概念讲解"],
            })

        low_value = [video for video in videos if video["value_tier"] == "低价值/噪声"][:6]
        if low_value:
            suggestions.append({
                "type": "archive",
                "title": "建议归档低价值或弱相关内容",
                "description": "这些视频偏资讯、噪声或与主线学习关系较弱，可放入归档区。",
                "targets": [video["bvid"] for video in low_value],
                "confidence": 0.76,
                "evidence": ["泛资讯/弱知识密度特征明显", "重复或主题不聚焦"],
            })

        if series_groups:
            best_group = series_groups[0]
            suggestions.append({
                "type": "series",
                "title": "建议按系列聚合连续课程",
                "description": f"系列「{best_group['series_name']}」包含 {best_group['video_count']} 个视频，适合按课程进度跟踪。",
                "targets": [video["bvid"] for video in best_group["videos"]],
                "confidence": 0.84,
                "evidence": best_group["reasons"],
            })

        return suggestions[:8]

    def _build_facet_counts(self, videos: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        return {
            "subject_tags": dict(Counter(tag for video in videos for tag in video["subject_tags"])),
            "content_type": dict(Counter(video["content_type"] for video in videos)),
            "difficulty_level": dict(Counter(video["difficulty_level"] for video in videos)),
            "learning_status": dict(Counter(video["learning_status"] for video in videos)),
            "value_tier": dict(Counter(video["value_tier"] for video in videos)),
        }

    def _render_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# 收藏整理分类中心报告",
            "",
            "## 概览",
            f"- 总视频数：{report['summary']['total_videos']}",
            f"- 系列数：{report['summary']['series_count']}",
            f"- 重复组数：{report['summary']['duplicate_group_count']}",
            f"- 主线核心：{report['summary']['core_count']}",
            f"- 低价值/噪声：{report['summary']['low_value_count']}",
            "",
            "## 整理建议",
        ]
        for suggestion in report["suggestions"]:
            lines.extend([
                f"### {suggestion['title']}",
                suggestion["description"],
                f"- 置信度：{round(suggestion['confidence'] * 100)}%",
                f"- 目标：{', '.join(suggestion['targets'])}",
                f"- 依据：{'；'.join(suggestion['evidence'])}",
                "",
            ])

        lines.append("## 视频清单")
        for video in report["videos"][:30]:
            lines.extend([
                f"### {video['title']}",
                f"- BV：{video['bvid']}",
                f"- 主题：{', '.join(video['subject_tags'])}",
                f"- 类型：{video['content_type']}",
                f"- 难度：{video['difficulty_level']}",
                f"- 学习状态：{video['learning_status']}",
                f"- 价值：{video['value_tier']}",
                f"- 理由：{'；'.join(video['reasons'][:4])}",
                "",
            ])
        return "\n".join(lines)

    def _empty_report(self) -> dict[str, Any]:
        return {
            "summary": {
                "total_videos": 0,
                "series_count": 0,
                "duplicate_group_count": 0,
                "core_count": 0,
                "low_value_count": 0,
                "compiled_count": 0,
            },
            "videos": [],
            "series_groups": [],
            "duplicate_groups": [],
            "suggestions": [],
            "facet_counts": {
                "subject_tags": {},
                "content_type": {},
                "difficulty_level": {},
                "learning_status": {},
                "value_tier": {},
            },
            "export_generated_at": "",
        }
