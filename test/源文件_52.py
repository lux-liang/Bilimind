"""
BiliMind 单元测试 — 核心模块测试

测试覆盖:
1. GraphStore - 图存储 CRUD
2. KnowledgeExtractor - 规则 fallback 抽取
3. TreeBuilder - 图到树投影
4. ContentFetcher - 字幕合并逻辑
5. Models - 数据模型完整性
"""
import asyncio
import json
import os
import sys
import tempfile

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_models_import():
    """测试所有模型可正常导入"""
    from app.models import (
        Base, VideoCache, UserSession, FavoriteFolder, FavoriteVideo,
        Segment, KnowledgeNode, KnowledgeEdge, NodeSegmentLink,
        ContentSource, NodeType, RelationType, ReviewStatus,
        VideoInfo, VideoContent, TreeNodeInfo, NodeDetailInfo, VideoDetailInfo,
        SegmentInfo, _fmt_time,
    )
    # 验证枚举值
    assert NodeType.TOPIC.value == "topic"
    assert NodeType.CONCEPT.value == "concept"
    assert RelationType.PREREQUISITE_OF.value == "prerequisite_of"
    assert RelationType.PART_OF.value == "part_of"
    assert ReviewStatus.AUTO.value == "auto"
    assert ReviewStatus.PENDING_REVIEW.value == "pending_review"

    # 验证时间格式化
    assert _fmt_time(0) == "00:00"
    assert _fmt_time(65) == "01:05"
    assert _fmt_time(3661) == "1:01:01"

    # 验证新增字段存在
    v = VideoCache.__table__
    col_names = {c.name for c in v.columns}
    assert "tags" in col_names
    assert "summary" in col_names
    assert "extraction_status" in col_names
    assert "knowledge_node_count" in col_names

    # 验证新表字段
    s = Segment.__table__
    s_cols = {c.name for c in s.columns}
    assert "start_time" in s_cols
    assert "end_time" in s_cols
    assert "raw_text" in s_cols
    assert "source_type" in s_cols
    assert "confidence" in s_cols

    kn = KnowledgeNode.__table__
    kn_cols = {c.name for c in kn.columns}
    assert "node_type" in kn_cols
    assert "normalized_name" in kn_cols
    assert "main_topic_id" in kn_cols
    assert "review_status" in kn_cols

    print("PASS test_models_import")


def test_graph_store():
    """测试 GraphStore CRUD 操作"""
    from app.services.graph_store import GraphStore

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name

    try:
        gs = GraphStore(graph_path=tmp_path)

        # 添加节点
        gs.add_node(1, node_type="topic", name="Machine Learning", normalized_name="machine learning", confidence=0.9)
        gs.add_node(2, node_type="concept", name="Linear Regression", normalized_name="linear regression", confidence=0.8)
        gs.add_node(3, node_type="concept", name="Logistic Regression", normalized_name="logistic regression", confidence=0.7)
        gs.add_node(4, node_type="method", name="Gradient Descent", normalized_name="gradient descent", confidence=0.85)

        assert gs.node_count() == 4
        assert gs.has_node(1)
        assert not gs.has_node(99)

        # 获取节点
        n1 = gs.get_node(1)
        assert n1["name"] == "Machine Learning"
        assert n1["node_type"] == "topic"

        # 添加边
        gs.add_edge(2, 1, relation_type="part_of", confidence=0.9)
        gs.add_edge(3, 1, relation_type="part_of", confidence=0.8)
        gs.add_edge(4, 2, relation_type="supports", confidence=0.7)
        gs.add_edge(2, 3, relation_type="prerequisite_of", confidence=0.6)

        assert gs.edge_count() == 4

        # 查询邻居
        children = gs.get_children(1)
        assert len(children) == 2
        child_ids = {c["id"] for c in children}
        assert 2 in child_ids
        assert 3 in child_ids

        # 前置知识
        prereqs = gs.get_prerequisites(3)
        assert len(prereqs) == 1
        assert prereqs[0]["id"] == 2

        # 后续知识
        successors = gs.get_successors(2)
        assert len(successors) == 1
        assert successors[0]["id"] == 3

        # 按名称查找
        found = gs.find_node_by_name("linear regression")
        assert found == 2
        assert gs.find_node_by_name("nonexistent") is None

        # all_nodes 过滤
        topics = gs.all_nodes(node_type="topic")
        assert len(topics) == 1
        assert topics[0]["name"] == "Machine Learning"

        concepts = gs.all_nodes(node_type="concept")
        assert len(concepts) == 2

        # 边权重累加
        gs.add_edge(2, 1, relation_type="part_of", confidence=0.95, weight=2.0)
        edge = gs.get_edge(2, 1)
        assert edge["weight"] == 3.0  # 1.0 + 2.0
        assert edge["confidence"] == 0.95  # max(0.9, 0.95)

        # JSON 持久化
        gs.save_json()
        assert os.path.exists(tmp_path)

        gs2 = GraphStore(graph_path=tmp_path)
        loaded = gs2.load_json()
        assert loaded
        assert gs2.node_count() == 4
        assert gs2.edge_count() == 4

        n2 = gs2.get_node(2)
        assert n2["name"] == "Linear Regression"

        print("PASS test_graph_store")
    finally:
        os.unlink(tmp_path)


def test_extractor_rules():
    """测试知识抽取的规则 fallback"""
    from app.services.extractor import KnowledgeExtractor

    ext = KnowledgeExtractor()
    # 强制使用规则 (没有 LLM client)
    ext.client = None

    result = ext._extract_with_rules(
        "线性回归是机器学习中最基础的算法之一，它通过 Gradient Descent 来优化 Loss Function。",
        "机器学习入门第3讲"
    )

    entities = result["entities"]
    relations = result["relations"]

    # 应该从标题抽取主题
    topic_names = [e["name"] for e in entities if e["type"] == "topic"]
    assert len(topic_names) > 0, f"Should extract topic from title, got {entities}"

    # 应该抽取英文术语
    entity_names = [e["name"] for e in entities]
    en_terms = [n for n in entity_names if n.isascii()]
    # Gradient, Descent, Loss, Function 等可能被提取
    assert len(entities) > 1, f"Should extract multiple entities, got {entities}"

    print("PASS test_extractor_rules")


def test_extractor_normalize():
    """测试实体归一化"""
    from app.services.extractor import KnowledgeExtractor

    assert KnowledgeExtractor._normalize_name("  Machine Learning  ") == "machine learning"
    assert KnowledgeExtractor._normalize_name("CNN（卷积神经网络）") == "cnn"
    assert KnowledgeExtractor._normalize_name("Linear\n  Regression") == "linear regression"

    print("PASS test_extractor_normalize")


def test_extractor_merge():
    """测试实体去重合并"""
    from app.services.extractor import KnowledgeExtractor

    ext = KnowledgeExtractor()
    ext.client = None

    entities = [
        {"name": "Linear Regression", "type": "concept", "definition": "def1", "confidence": 0.7, "_segment_id": 1},
        {"name": "linear regression", "type": "concept", "definition": "", "confidence": 0.8, "_segment_id": 2},
        {"name": "CNN", "type": "method", "definition": "conv net", "confidence": 0.6, "_segment_id": 3},
    ]
    relations = [
        {"source": "Linear Regression", "target": "CNN", "type": "related_to", "confidence": 0.5},
    ]

    result = ext._merge_and_deduplicate(entities, relations)

    # 应该合并两个 linear regression
    assert len(result["entities"]) == 2

    lr_entity = None
    for e in result["entities"]:
        if e["normalized_name"] == "linear regression":
            lr_entity = e
    assert lr_entity is not None
    assert lr_entity["source_count"] == 2
    assert lr_entity["confidence"] >= 0.8  # max confidence
    assert lr_entity["definition"] == "def1"  # 保留非空定义

    # 关系应保留
    assert len(result["relations"]) == 1
    assert result["relations"][0]["type"] == "related_to"

    print("PASS test_extractor_merge")


def test_extractor_parse_llm():
    """测试 LLM 输出解析"""
    from app.services.extractor import KnowledgeExtractor

    ext = KnowledgeExtractor()
    ext.client = None

    # 测试正常 JSON
    raw = '{"entities": [{"name": "CNN", "type": "concept", "definition": "conv net", "confidence": 0.8}], "relations": []}'
    result = ext._parse_llm_output(raw)
    assert len(result["entities"]) == 1
    assert result["entities"][0]["name"] == "CNN"

    # 测试 markdown 代码块包裹
    raw_md = '```json\n{"entities": [{"name": "RNN", "type": "method", "definition": "recurrent", "confidence": 0.7}], "relations": []}\n```'
    result2 = ext._parse_llm_output(raw_md)
    assert len(result2["entities"]) == 1
    assert result2["entities"][0]["name"] == "RNN"

    # 测试无效 JSON
    result3 = ext._parse_llm_output("This is not JSON at all")
    assert result3["entities"] == []
    assert result3["relations"] == []

    # 测试低置信度过滤
    raw_low = '{"entities": [{"name": "X", "type": "concept", "definition": "", "confidence": 0.1}], "relations": []}'
    result4 = ext._parse_llm_output(raw_low)
    assert len(result4["entities"]) == 0  # confidence 0.1 < 0.3 threshold

    print("PASS test_extractor_parse_llm")


def test_tree_builder():
    """测试树构建引擎"""
    from app.services.graph_store import GraphStore
    from app.services.tree_builder import TreeBuilder

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name

    try:
        gs = GraphStore(graph_path=tmp_path)

        # 构建测试图
        gs.add_node(1, node_type="topic", name="ML", normalized_name="ml",
                     confidence=0.9, difficulty=1, source_count=5, review_status="auto")
        gs.add_node(2, node_type="topic", name="DL", normalized_name="dl",
                     confidence=0.85, difficulty=2, source_count=4, review_status="auto")
        gs.add_node(3, node_type="concept", name="Linear Reg", normalized_name="linear reg",
                     confidence=0.8, difficulty=2, source_count=3, review_status="auto")
        gs.add_node(4, node_type="concept", name="Logistic Reg", normalized_name="logistic reg",
                     confidence=0.7, difficulty=3, source_count=2, review_status="auto")
        gs.add_node(5, node_type="method", name="GD", normalized_name="gd",
                     confidence=0.6, difficulty=2, source_count=2, review_status="auto")
        gs.add_node(6, node_type="concept", name="Low Conf Node", normalized_name="low",
                     confidence=0.2, difficulty=1, source_count=1, review_status="auto")
        gs.add_node(7, node_type="concept", name="Rejected", normalized_name="rejected",
                     confidence=0.9, difficulty=1, source_count=1, review_status="rejected")

        # 关系
        gs.add_edge(3, 1, relation_type="part_of")
        gs.add_edge(4, 1, relation_type="part_of")
        gs.add_edge(5, 3, relation_type="supports")
        gs.add_edge(3, 4, relation_type="prerequisite_of")

        builder = TreeBuilder(gs)
        result = builder.build_tree(min_confidence=0.4)

        tree = result["tree"]
        stats = result["stats"]

        # 验证统计
        assert stats["total_topics"] == 2  # ML, DL
        assert stats["total_nodes"] == 5   # 排除 low conf (0.2) 和 rejected
        assert stats["low_confidence_count"] == 1  # low conf node

        # 验证树结构
        assert len(tree) >= 2  # ML 和 DL (+ 可能的"其他")

        # ML 应该有子节点
        ml_topic = None
        for t in tree:
            if t["name"] == "ML":
                ml_topic = t
                break
        assert ml_topic is not None, f"ML topic not found in tree: {[t['name'] for t in tree]}"
        assert len(ml_topic["children"]) >= 2  # Linear Reg, Logistic Reg

        # Low conf 和 rejected 不应在主树中
        all_names = []

        def collect_names(nodes):
            for n in nodes:
                all_names.append(n["name"])
                collect_names(n.get("children", []))

        collect_names(tree)
        assert "Low Conf Node" not in all_names
        assert "Rejected" not in all_names

        # 测试树位置
        pos = builder.get_node_tree_position(3)
        assert len(pos) >= 1
        assert any(p["name"] == "Linear Reg" for p in pos)

        print("PASS test_tree_builder")
    finally:
        os.unlink(tmp_path)


def test_tree_builder_empty():
    """测试空图的树构建"""
    from app.services.graph_store import GraphStore
    from app.services.tree_builder import TreeBuilder

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name

    try:
        gs = GraphStore(graph_path=tmp_path)
        builder = TreeBuilder(gs)
        result = builder.build_tree()

        assert result["tree"] == []
        assert result["stats"]["total_nodes"] == 0

        print("PASS test_tree_builder_empty")
    finally:
        os.unlink(tmp_path)


def test_content_fetcher_merge_subtitles():
    """测试字幕合并逻辑"""
    from app.services.content_fetcher import ContentFetcher

    # 创建 mock 对象
    class MockBili:
        pass

    class MockASR:
        pass

    fetcher = ContentFetcher(MockBili(), MockASR())
    fetcher.segment_merge_seconds = 30.0

    # 模拟字幕条目
    items = [
        {"content": "Hello world", "from": 0.0, "to": 2.0},
        {"content": "This is a test", "from": 2.0, "to": 4.0},
        {"content": "Of subtitle merging", "from": 4.0, "to": 6.0},
        # 大间隔 → 新片段
        {"content": "After a long pause", "from": 60.0, "to": 62.0},
        {"content": "Continues here", "from": 62.0, "to": 64.0},
    ]

    segments = fetcher._merge_subtitle_items(items)

    assert len(segments) == 2, f"Expected 2 segments, got {len(segments)}"

    # 第一个片段
    assert segments[0]["segment_index"] == 0
    assert segments[0]["start_time"] == 0.0
    assert segments[0]["end_time"] == 6.0
    assert "Hello world" in segments[0]["raw_text"]
    assert "Of subtitle merging" in segments[0]["raw_text"]
    assert segments[0]["source_type"] == "subtitle"
    assert segments[0]["confidence"] == 1.0

    # 第二个片段
    assert segments[1]["segment_index"] == 1
    assert segments[1]["start_time"] == 60.0
    assert segments[1]["end_time"] == 64.0
    assert "After a long pause" in segments[1]["raw_text"]

    print("PASS test_content_fetcher_merge_subtitles")


def test_content_fetcher_split_text():
    """测试无时间戳文本按等时分段"""
    from app.services.content_fetcher import ContentFetcher

    class MockBili:
        pass

    class MockASR:
        pass

    fetcher = ContentFetcher(MockBili(), MockASR())

    # 生成较长文本
    text = "\n".join([f"Paragraph {i}: " + "x" * 200 for i in range(5)])
    segments = fetcher._split_text_to_segments(text, duration=300, source_type="asr")

    assert len(segments) >= 2
    # 检查时间分布
    for seg in segments:
        assert seg["start_time"] is not None
        assert seg["end_time"] is not None
        assert seg["source_type"] == "asr"
        assert seg["confidence"] == 0.5

    # 最后一个片段的结束时间应接近 300
    assert segments[-1]["end_time"] <= 300.0 + 1

    # 无 duration 的情况
    segments_no_dur = fetcher._split_text_to_segments("short text", duration=None)
    assert len(segments_no_dur) == 1
    assert segments_no_dur[0]["start_time"] is None
    assert segments_no_dur[0]["confidence"] == 0.3

    print("PASS test_content_fetcher_split_text")


def test_bilibili_subtitle_compat():
    """测试 bilibili download_subtitle 兼容性"""
    # 只验证方法存在性和签名
    from app.services.bilibili import BilibiliService

    svc = BilibiliService()
    assert hasattr(svc, "download_subtitle")
    assert hasattr(svc, "download_subtitle_with_timestamps")

    print("PASS test_bilibili_subtitle_compat")


def test_config_new_fields():
    """测试新增配置项"""
    from app.config import Settings

    s = Settings()
    assert hasattr(s, "graph_persist_path")
    assert hasattr(s, "extraction_min_confidence")
    assert hasattr(s, "tree_min_confidence")
    assert hasattr(s, "extraction_segment_merge_seconds")
    assert hasattr(s, "ml_artifact_dir")
    assert hasattr(s, "evidence_ranker_model_path")
    assert hasattr(s, "organizer_classifier_model_path")
    assert s.extraction_min_confidence == 0.3
    assert s.tree_min_confidence == 0.4

    print("PASS test_config_new_fields")


def test_router_import():
    """测试路由可正常导入"""
    from app.routers import tree
    assert hasattr(tree, "router")
    assert tree.router.prefix == "/tree"

    # 检查端点数量
    routes = [r for r in tree.router.routes if hasattr(r, "methods")]
    assert len(routes) >= 8, f"Expected >= 8 routes, got {len(routes)}"

    print("PASS test_router_import")


def test_main_app_import():
    """测试主应用可正常导入"""
    from app.main import app

    route_paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/tree" in str(route_paths) or any("/tree" in p for p in route_paths), \
        f"Tree routes not registered: {route_paths}"

    print("PASS test_main_app_import")


# ==================== Phase 2 新增测试 ====================

def test_new_relation_types():
    """测试新增关系类型"""
    from app.models import RelationType
    assert RelationType.RECOMMENDS_NEXT.value == "recommends_next"
    assert RelationType.VIDEO_FOR.value == "video_for"
    assert len(RelationType) == 8
    print("PASS test_new_relation_types")


def test_difficulty_stage():
    """测试难度阶段枚举"""
    from app.models import DifficultyStage
    assert DifficultyStage.difficulty_range(DifficultyStage.BEGINNER) == (1, 2)
    assert DifficultyStage.difficulty_range(DifficultyStage.INTERMEDIATE) == (3, 4)
    assert DifficultyStage.difficulty_range(DifficultyStage.ADVANCED) == (5, 5)
    print("PASS test_difficulty_stage")


def test_query_router_classify():
    """测试问答路由器分类"""
    from app.services.query_router import QueryRouter
    qr = QueryRouter()

    assert qr.classify_question("你好") == "direct"
    assert qr.classify_question("Transformer和RNN有什么关系") == "graph"
    assert qr.classify_question("怎么学机器学习") == "path"
    assert qr.classify_question("学习路径推荐") == "path"
    assert qr.classify_question("有哪些视频") == "db_list"
    assert qr.classify_question("总结一下内容") == "db_content"
    assert qr.classify_question("什么是深度学习") == "vector"
    print("PASS test_query_router_classify")


def test_graph_store_new_methods():
    """测试图存储新增方法"""
    from app.services.graph_store import GraphStore

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name

    try:
        gs = GraphStore(graph_path=tmp_path)
        gs.add_node(1, node_type="topic", name="AI", normalized_name="ai",
                     main_topic_id=None, confidence=0.9)
        gs.add_node(2, node_type="concept", name="ML", normalized_name="ml",
                     main_topic_id=1, confidence=0.8)
        gs.add_node(3, node_type="concept", name="DL", normalized_name="dl",
                     main_topic_id=1, confidence=0.7)
        gs.add_edge(2, 1, relation_type="part_of")
        gs.add_edge(3, 1, relation_type="part_of")
        gs.add_edge(2, 3, relation_type="prerequisite_of")

        # 测试 search_nodes_by_name
        results = gs.search_nodes_by_name("M", limit=5)
        assert len(results) == 1
        assert results[0]["name"] == "ML"

        # 测试 find_shortest_path
        path = gs.find_shortest_path(2, 3)
        assert len(path) >= 2

        # 测试 get_topic_subgraph_ids
        ids = gs.get_topic_subgraph_ids(1)
        assert 1 in ids
        assert 2 in ids
        assert 3 in ids

        # 测试 get_related_by_type
        related = gs.get_related_by_type(2, ["part_of", "prerequisite_of"])
        assert len(related) >= 1

        print("PASS test_graph_store_new_methods")
    finally:
        os.unlink(tmp_path)


def test_extractor_difficulty():
    """测试抽取器难度推断"""
    from app.services.extractor import KnowledgeExtractor
    ext = KnowledgeExtractor()

    # 测试 difficulty 在验证中被保留
    raw = '{"entities": [{"name": "CNN", "type": "concept", "definition": "卷积神经网络", "difficulty": 3, "confidence": 0.8}], "relations": []}'
    result = ext._parse_llm_output(raw)
    assert len(result["entities"]) == 1
    assert result["entities"][0]["difficulty"] == 3

    # 测试 difficulty 边界
    raw2 = '{"entities": [{"name": "CNN", "type": "concept", "definition": "", "difficulty": 10, "confidence": 0.8}], "relations": []}'
    result2 = ext._parse_llm_output(raw2)
    assert result2["entities"][0]["difficulty"] == 5  # clamped

    raw3 = '{"entities": [{"name": "RNN", "type": "concept", "definition": "", "difficulty": -1, "confidence": 0.8}], "relations": []}'
    result3 = ext._parse_llm_output(raw3)
    assert result3["entities"][0]["difficulty"] == 1  # clamped

    print("PASS test_extractor_difficulty")


def test_learning_path_router_import():
    """测试学习路径路由可正常导入"""
    from app.routers.learning_path import router
    assert router.prefix == "/learning-path"
    routes = [r for r in router.routes if hasattr(r, "methods")]
    assert len(routes) >= 3  # search, generate, topics
    print("PASS test_learning_path_router_import")


def test_all_routes_registered():
    """测试所有路由在 app 中正确注册"""
    from app.main import app
    route_paths = [r.path for r in app.routes if hasattr(r, "path")]
    expected = ["/tree", "/search", "/learning-path/generate", "/chat/ask", "/knowledge/build", "/organizer/report"]
    for exp in expected:
        assert any(exp in p for p in route_paths), f"Route {exp} not found in {route_paths}"
    print("PASS test_all_routes_registered")


def test_video_organizer_classification():
    """测试 Organizer 分类规则"""
    from app.services.video_organizer import VideoFeatures, VideoOrganizerService

    service = VideoOrganizerService(db=None)  # 仅测试纯规则逻辑
    item = VideoFeatures(
        bvid="BV1demo",
        title="AI Agent 从入门到实战 第1讲",
        description="大模型 agent 项目教程，手把手搭建工作流",
        summary="讲解 Agent 原理、工作流和实战案例",
        owner_name="tester",
        duration=1800,
        pic_url=None,
        folder_ids=[1],
        folder_titles=["AI 主线"],
        segment_count=12,
        claim_count=8,
        concept_count=5,
        knowledge_node_count=7,
        avg_node_difficulty=3.6,
        node_names=["Agent", "Workflow", "Prompt"],
        node_types=["concept", "method"],
        node_confidence_avg=0.82,
        tags=["AI", "Agent"],
    )

    result = service._analyze_video(item)
    assert "AI" in result["subject_tags"]
    assert result["content_type"] == "教程实战"
    assert result["difficulty_level"] in {"进阶", "高阶"}
    assert result["value_tier"] == "主线核心"
    assert result["organize_score"] >= 70
    print("PASS test_video_organizer_classification")


def test_video_organizer_series_detection():
    """测试 Organizer 系列识别"""
    from app.services.video_organizer import VideoOrganizerService

    service = VideoOrganizerService(db=None)
    videos = [
        {"bvid": "BV1", "title": "AI Agent 从入门到实战 第1讲", "organize_score": 82, "difficulty_level": "进阶"},
        {"bvid": "BV2", "title": "AI Agent 从入门到实战 第2讲", "organize_score": 80, "difficulty_level": "进阶"},
        {"bvid": "BV3", "title": "前端工程化速查", "organize_score": 60, "difficulty_level": "入门"},
    ]
    groups = service._detect_series_groups(videos)
    assert len(groups) == 1
    assert groups[0]["video_count"] == 2
    assert {item["bvid"] for item in groups[0]["videos"]} == {"BV1", "BV2"}
    print("PASS test_video_organizer_series_detection")


def test_video_organizer_duplicate_detection():
    """测试 Organizer 重复识别"""
    from app.services.video_organizer import VideoOrganizerService

    service = VideoOrganizerService(db=None)
    videos = [
        {
            "bvid": "BVkeep",
            "title": "React 项目实战教程",
            "subject_tags": ["前端"],
            "folder_titles": ["前端"],
            "duration": 1200,
            "knowledge_node_count": 6,
            "organize_score": 86,
            "series_key": None,
        },
        {
            "bvid": "BVarc",
            "title": "React 实战项目教程",
            "subject_tags": ["前端"],
            "folder_titles": ["前端收藏"],
            "duration": 1260,
            "knowledge_node_count": 5,
            "organize_score": 62,
            "series_key": None,
        },
        {
            "bvid": "BVother",
            "title": "算法基础入门",
            "subject_tags": ["算法"],
            "folder_titles": ["算法"],
            "duration": 900,
            "knowledge_node_count": 2,
            "organize_score": 58,
            "series_key": None,
        },
    ]

    groups = service._detect_duplicate_groups(videos)
    assert len(groups) == 1
    assert groups[0]["recommended_keep_bvid"] == "BVkeep"
    assert "BVarc" in groups[0]["archive_candidates"]
    print("PASS test_video_organizer_duplicate_detection")


def test_lightweight_binary_model():
    """测试轻量二分类模型可训练并分离简单样本"""
    from app.services.lightweight_models import HashedBinaryLogisticModel, SparseSample

    samples = [
        SparseSample(label=1.0, numeric_features={"overlap": 2.0, "confidence": 0.9}, token_features=["node::cnn", "overlap::cnn"]),
        SparseSample(label=1.0, numeric_features={"overlap": 1.5, "confidence": 0.8}, token_features=["node::agent"]),
        SparseSample(label=0.0, numeric_features={"overlap": 0.0, "confidence": 0.2}, token_features=["noise::random"]),
        SparseSample(label=0.0, numeric_features={"overlap": 0.1, "confidence": 0.1}, token_features=["noise::other"]),
    ]
    model = HashedBinaryLogisticModel(buckets=256)
    model.fit(samples, epochs=12, lr=0.1)
    pos = model.predict_proba({"overlap": 2.0, "confidence": 0.9}, ["node::cnn"])
    neg = model.predict_proba({"overlap": 0.0, "confidence": 0.1}, ["noise::random"])
    assert pos > neg
    assert pos > 0.5
    assert neg < 0.5
    print("PASS test_lightweight_binary_model")


def test_lightweight_multiclass_model():
    """测试轻量多分类模型可训练并输出类别"""
    from app.services.lightweight_models import HashedMulticlassOVRModel

    dataset = [
        ("教程实战", {"duration": 5.0, "claims": 6.0}, ["tok::项目", "tok::实战"]),
        ("教程实战", {"duration": 4.5, "claims": 5.5}, ["tok::教程", "tok::搭建"]),
        ("概念讲解", {"duration": 2.0, "claims": 2.0}, ["tok::原理", "tok::概念"]),
        ("概念讲解", {"duration": 2.5, "claims": 1.5}, ["tok::本质", "tok::理解"]),
    ]
    model = HashedMulticlassOVRModel(labels=["教程实战", "概念讲解"], buckets=256)
    model.fit(dataset, epochs=10, lr=0.1)
    label, confidence, _ = model.predict({"duration": 5.0, "claims": 6.0}, ["tok::项目", "tok::实战"])
    assert label == "教程实战"
    assert confidence > 0.5
    print("PASS test_lightweight_multiclass_model")


def test_evidence_ranker_metrics():
    """测试证据判别器评估指标计算"""
    from app.services.evidence_ranker_metrics import compute_auc, compute_classification_metrics, compute_query_metrics

    labels = [1, 1, 0, 0]
    scores = [0.91, 0.77, 0.42, 0.18]
    metrics = compute_classification_metrics(labels, scores, threshold=0.6)
    assert metrics["accuracy"] >= 0.99
    assert metrics["precision"] >= 0.99
    assert metrics["recall"] >= 0.99
    assert compute_auc(labels, scores) >= 0.99

    query_metrics = compute_query_metrics([
        {"query_id": "q1", "label": 1, "relevance_score": 0.92, "rule_score": 0.8, "segment_id": 1},
        {"query_id": "q1", "label": 0, "relevance_score": 0.30, "rule_score": 0.5, "segment_id": 2},
        {"query_id": "q2", "label": 0, "relevance_score": 0.40, "rule_score": 0.7, "segment_id": 3},
        {"query_id": "q2", "label": 1, "relevance_score": 0.20, "rule_score": 0.3, "segment_id": 4},
    ], score_key="relevance_score", threshold=0.6)
    assert query_metrics["queries"] == 2
    assert query_metrics["displayed_queries"] == 1
    assert query_metrics["top1_precision"] == 1.0
    assert query_metrics["empty_state_rate"] == 0.5
    print("PASS test_evidence_ranker_metrics")


def test_evidence_ranker_score_record_prefers_precomputed_features():
    """测试离线推理优先复用样本自带特征，避免口径漂移"""
    from app.services.evidence_ranker import EvidenceRanker
    from app.services.lightweight_models import HashedBinaryLogisticModel, SparseSample

    model = HashedBinaryLogisticModel(buckets=128)
    samples = [
        SparseSample(label=1.0, numeric_features={"overlap": 2.0, "rule_score": 0.7}, token_features=["node::cnn", "overlap::cnn"]),
        SparseSample(label=0.0, numeric_features={"overlap": 0.0, "rule_score": 0.1}, token_features=["noise::other"]),
    ]
    model.fit(samples, epochs=12, lr=0.1)

    ranker = EvidenceRanker(model_path="/tmp/nonexistent-evidence-ranker.json")
    ranker.model = model
    result = ranker.score_record({
        "label": 1,
        "rule_score": 0.7,
        "numeric_features": {"overlap": 2.0, "rule_score": 0.7},
        "token_features": ["node::cnn", "overlap::cnn"],
    })
    assert result.model_score > 0.5
    assert result.relevance_score > 0.6
    assert result.is_relevant
    print("PASS test_evidence_ranker_score_record_prefers_precomputed_features")


def test_evidence_ranker_loads_saved_model():
    """训练产物必须能被 EvidenceRanker 真正加载，避免评估静默退回规则基线"""
    from app.services.evidence_ranker import EvidenceRanker
    from app.services.lightweight_models import HashedBinaryLogisticModel, SparseSample

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        model_path = handle.name

    try:
        model = HashedBinaryLogisticModel(buckets=64, metadata={"task": "test_evidence_ranker"})
        samples = [
            SparseSample(
                label=1.0,
                numeric_features={"overlap_ratio": 0.9, "rule_score": 0.62},
                token_features=["node::梯度下降", "seg::梯度下降"],
            ),
            SparseSample(
                label=0.0,
                numeric_features={"overlap_ratio": 0.0, "rule_score": 0.12},
                token_features=["node::梯度下降", "seg::音乐"],
            ),
        ]
        model.fit(samples, epochs=8, lr=0.1)
        model.save(model_path)

        ranker = EvidenceRanker(model_path=model_path)
        assert ranker.is_enabled is True
        assert ranker.disabled_reason is None
        assert ranker.load_error is None

        result = ranker.score_record({
            "label": 1,
            "rule_score": 0.62,
            "numeric_features": {"overlap_ratio": 0.9, "rule_score": 0.62},
            "token_features": ["node::梯度下降", "seg::梯度下降"],
        })
        assert result.used_model is True
        assert result.relevance_score >= 0.62
        print("PASS test_evidence_ranker_loads_saved_model")
    finally:
        os.unlink(model_path)


def test_evidence_ranker_penalizes_generic_basic_segments():
    """泛主题节点 + basic 片段不应轻易作为高置信证据"""
    from app.models import KnowledgeNode, NodeSegmentLink, Segment, VideoCache
    from app.services.evidence_ranker import EvidenceRanker

    node = KnowledgeNode(
        id=1,
        name="机器学习",
        node_type="topic",
        aliases=["ML"],
        definition="一种让模型从数据中学习规律的方法",
        confidence=0.9,
        source_count=5,
    )
    link = NodeSegmentLink(node_id=1, segment_id=1, relation="mentions", confidence=0.62)
    segment = Segment(
        id=1,
        video_bvid="BV1",
        segment_index=0,
        raw_text="视频标题：AI 学习路线与经验分享。视频简介：介绍学习规划和一些建议。",
        cleaned_text="视频标题：AI 学习路线与经验分享。视频简介：介绍学习规划和一些建议。",
        source_type="basic",
        confidence=0.3,
        knowledge_density=0.05,
        is_peak=False,
    )
    video = VideoCache(bvid="BV1", title="AI 学习路线与经验分享")

    ranker = EvidenceRanker(model_path="/tmp/nonexistent-evidence-model.json")
    result = ranker.score(node, link, segment, video)

    assert result["confidence_level"] == "low"
    assert result["is_relevant"] is False
    print("PASS test_evidence_ranker_penalizes_generic_basic_segments")


def test_evidence_ranker_keeps_exact_subtitle_match():
    """准确命中节点名的字幕片段应保留为相关证据"""
    from app.models import KnowledgeNode, NodeSegmentLink, Segment, VideoCache
    from app.services.evidence_ranker import EvidenceRanker

    node = KnowledgeNode(
        id=2,
        name="梯度下降",
        node_type="method",
        aliases=["Gradient Descent", "GD"],
        definition="沿负梯度方向迭代优化目标函数",
        confidence=0.88,
        source_count=4,
    )
    link = NodeSegmentLink(node_id=2, segment_id=2, relation="explains", confidence=0.74)
    segment = Segment(
        id=2,
        video_bvid="BV2",
        segment_index=3,
        raw_text="梯度下降的核心思想是沿着损失函数的负梯度方向更新参数，从而逐步逼近最优解。",
        cleaned_text="梯度下降的核心思想是沿着损失函数的负梯度方向更新参数，从而逐步逼近最优解。",
        source_type="subtitle",
        confidence=1.0,
        knowledge_density=0.72,
        is_peak=True,
    )
    video = VideoCache(bvid="BV2", title="机器学习基础：梯度下降详解")

    ranker = EvidenceRanker(model_path="/tmp/nonexistent-evidence-model.json")
    result = ranker.score(node, link, segment, video)

    assert result["confidence_level"] in {"medium", "high"}
    assert result["is_relevant"] is True
    print("PASS test_evidence_ranker_keeps_exact_subtitle_match")


def test_learning_path_router_accepts_session_id():
    """学习路径接口必须显式接收 session_id，避免前端传参被静默忽略"""
    import inspect
    from app.routers import learning_path

    assert "session_id" in inspect.signature(learning_path.search_target_topics).parameters
    assert "session_id" in inspect.signature(learning_path.generate_learning_path).parameters
    assert "session_id" in inspect.signature(learning_path.get_popular_topics).parameters
    print("PASS test_learning_path_router_accepts_session_id")


def test_path_recommender_scores_and_roles():
    from app.services.graph_store import GraphStore
    from app.services.path_recommender import PathRecommender

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        graph_path = handle.name

    try:
        gs = GraphStore(graph_path=graph_path)
        gs.add_node(1, node_type="concept", name="线性代数基础", difficulty=1, confidence=0.82, source_count=4)
        gs.add_node(2, node_type="concept", name="梯度下降", difficulty=2, confidence=0.88, source_count=5)
        gs.add_node(3, node_type="topic", name="机器学习", difficulty=3, confidence=0.9, source_count=6)
        gs.add_edge(1, 2, relation_type="prerequisite_of", confidence=0.9)
        gs.add_edge(2, 3, relation_type="prerequisite_of", confidence=0.9)

        recommender = PathRecommender(gs)
        result = recommender.recommend_path(3, mode="beginner")

        assert result["summary"]["mode_label"] == "入门路径"
        assert result["summary"]["direct_prerequisites"] == 1
        assert len(result["steps"]) == 3

        step_names = [step["name"] for step in result["steps"]]
        assert step_names == ["线性代数基础", "梯度下降", "机器学习"]

        foundation_step = result["steps"][0]
        direct_step = result["steps"][1]
        target_step = result["steps"][2]

        assert foundation_step["dependency_role"] == "foundation"
        assert direct_step["dependency_role"] == "direct_prerequisite"
        assert target_step["dependency_role"] == "target"
        assert direct_step["priority_score"] > 0
        assert "直接前置" in direct_step["reason_tags"]
        assert target_step["dependency_depth"] == 0
        print("PASS test_path_recommender_scores_and_roles")
    finally:
        os.unlink(graph_path)


if __name__ == "__main__":
    tests = [
        test_models_import,
        test_graph_store,
        test_extractor_rules,
        test_extractor_normalize,
        test_extractor_merge,
        test_extractor_parse_llm,
        test_tree_builder,
        test_tree_builder_empty,
        test_content_fetcher_merge_subtitles,
        test_content_fetcher_split_text,
        test_bilibili_subtitle_compat,
        test_config_new_fields,
        test_router_import,
        test_main_app_import,
        # Phase 2 新增
        test_new_relation_types,
        test_difficulty_stage,
        test_query_router_classify,
        test_graph_store_new_methods,
        test_extractor_difficulty,
        test_learning_path_router_import,
        test_all_routes_registered,
        test_video_organizer_classification,
        test_video_organizer_series_detection,
        test_video_organizer_duplicate_detection,
        test_lightweight_binary_model,
        test_lightweight_multiclass_model,
        test_evidence_ranker_metrics,
        test_evidence_ranker_score_record_prefers_precomputed_features,
        test_evidence_ranker_loads_saved_model,
        test_evidence_ranker_penalizes_generic_basic_segments,
        test_evidence_ranker_keeps_exact_subtitle_match,
        test_learning_path_router_accepts_session_id,
        test_path_recommender_scores_and_roles,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"FAIL {test.__name__}: {e}")

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  - {name}: {err}")
        sys.exit(1)
    else:
        print("All tests passed!")
