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
    expected = ["/tree", "/search", "/learning-path/generate", "/chat/ask", "/knowledge/build"]
    for exp in expected:
        assert any(exp in p for p in route_paths), f"Route {exp} not found in {route_paths}"
    print("PASS test_all_routes_registered")


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
