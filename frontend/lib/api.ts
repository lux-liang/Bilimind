/**
 * API 客户端
 */

import { clearAuthSession, readAuthSession } from "./session";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || (
  typeof window !== "undefined" && window.location.hostname !== "localhost"
    ? "/api/proxy"  // 外网访问时走 Next.js 代理
    : "http://localhost:8000"
);

// 获取 localStorage 中的 session_id
export function getSessionId(): string | null {
    return readAuthSession().sessionId;
}

// 通用请求函数
async function request<T>(
    endpoint: string,
    options: RequestInit = {}
): Promise<T> {
    const url = `${API_BASE_URL}${endpoint}`;

    const response = await fetch(url, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...options.headers,
        },
    });

    // 会话失效时自动清除登录状态并刷新页面
    if (response.status === 401) {
        if (typeof window !== "undefined") {
            clearAuthSession();
            window.location.href = "/";
        }
        throw new Error("会话已过期，请重新登录");
    }

    if (!response.ok) {
        const error = await response.text();
        throw new Error(error || `请求失败: ${response.status}`);
    }

    return response.json();
}

// ==================== 类型定义 ====================

export interface QRCodeResponse {
    qrcode_key: string;
    qrcode_url: string;
    qrcode_image_base64: string;
}

export interface LoginStatusResponse {
    status: "waiting" | "scanned" | "confirmed" | "expired";
    message: string;
    user_info?: UserInfo;
    session_id?: string;
}

export interface UserInfo {
    mid: number;
    uname: string;
    face: string;
    level?: number;
}

export interface FavoriteFolder {
    media_id: number;
    title: string;
    media_count: number;
    is_selected: boolean;
    is_default?: boolean;
}

export interface Video {
    bvid: string;
    title: string;
    cover?: string;
    duration?: number;
    owner?: string;
    play_count?: number;
    intro?: string;
    is_selected: boolean;
}

export interface FavoriteVideosResponse {
    folder_info: Record<string, unknown>;
    videos: Video[];
    has_more: boolean;
    page: number;
    page_size: number;
}

export interface OrganizePreviewItem {
    bvid: string;
    title: string;
    resource_id: number;
    resource_type: number;
    target_folder_id: number | null;
    target_folder_title: string;
    reason?: string;
}

export interface OrganizePreviewResponse {
    default_folder_id: number;
    default_folder_title: string;
    folders: FavoriteFolder[];
    items: OrganizePreviewItem[];
    stats: {
        total: number;
        matched: number;
        unmatched: number;
    };
}

export interface BuildRequest {
    folder_ids: number[];
    exclude_bvids?: string[];
}

export interface BuildStatus {
    task_id: string;
    status: "pending" | "running" | "completed" | "failed";
    progress: number;
    current_step: string;
    total_videos: number;
    processed_videos: number;
    message: string;
}

export interface FolderStatus {
    media_id: number;
    indexed_count: number;
    media_count?: number;
    last_sync_at?: string;
}

export interface SyncRequest {
    folder_ids?: number[];
}

export interface SyncResult {
    folder_id: number;
    total: number;
    added: number;
    removed: number;
    indexed: number;
    message: string;
    last_sync_at: string;
}

export interface KnowledgeStats {
    total_chunks: number;
    total_videos: number;
    collection_name: string;
}

export interface ChatResponse {
    answer: string;
    sources: Array<{
        bvid: string;
        title: string;
        url: string;
    }>;
}

export interface ImportUrlRequest {
    url: string;
    session_id?: string;
}

export interface ImportUrlResponse {
    source_id: string;
    source_type: string;
    title: string;
    content_length: number;
    segment_count: number;
    node_count: number;
}

// ==================== API 函数 ====================

// 认证相关
export const authApi = {
    // 获取登录二维码
    getQRCode: () => request<QRCodeResponse>("/auth/qrcode"),

    // 轮询登录状态
    pollQRCode: (qrcodeKey: string) =>
        request<LoginStatusResponse>(`/auth/qrcode/poll/${qrcodeKey}`),

    // 获取会话信息
    getSession: (sessionId: string) =>
        request<{ valid: boolean; user_info: UserInfo }>(`/auth/session/${sessionId}`),

    // 退出登录
    logout: (sessionId: string) =>
        request(`/auth/session/${sessionId}`, { method: "DELETE" }),
};

// 收藏夹相关
export const favoritesApi = {
    // 获取收藏夹列表
    getList: (sessionId: string) =>
        request<FavoriteFolder[]>(`/favorites/list?session_id=${sessionId}`),

    // 获取收藏夹视频（分页）
    getVideos: (mediaId: number, sessionId: string, page = 1) =>
        request<FavoriteVideosResponse>(
            `/favorites/${mediaId}/videos?session_id=${sessionId}&page=${page}`
        ),

    // 获取收藏夹全部视频
    getAllVideos: (mediaId: number, sessionId: string) =>
        request<{ total: number; videos: Video[] }>(
            `/favorites/${mediaId}/all-videos?session_id=${sessionId}`
        ),

    // 预览整理
    organizePreview: (folderId: number, sessionId: string) =>
        request<OrganizePreviewResponse>(
            `/favorites/organize/preview?session_id=${sessionId}`,
            {
                method: "POST",
                body: JSON.stringify({ folder_id: folderId }),
            }
        ),

    // 执行整理
    organizeExecute: (
        data: {
            default_folder_id: number;
            moves: Array<{ resource_id: number; resource_type: number; target_folder_id: number }>;
        },
        sessionId: string
    ) =>
        request<{ message: string; moved: number; groups: number }>(
            `/favorites/organize/execute?session_id=${sessionId}`,
            {
                method: "POST",
                body: JSON.stringify(data),
            }
        ),

    // 清理失效内容
    cleanInvalid: (folderId: number, sessionId: string) =>
        request<{ message: string; data: Record<string, unknown> }>(
            `/favorites/organize/clean-invalid?session_id=${sessionId}`,
            {
                method: "POST",
                body: JSON.stringify({ folder_id: folderId }),
            }
        ),
};

// 知识库相关
export const knowledgeApi = {
    // 获取统计信息
    getStats: () => {
        const params = new URLSearchParams();
        const sid = getSessionId();
        if (sid) params.set("session_id", sid);
        return request<KnowledgeStats>(`/knowledge/stats?${params.toString()}`);
    },

    // 构建知识库
    build: (data: BuildRequest, sessionId: string) =>
        request<{ task_id: string; message: string }>(
            `/knowledge/build?session_id=${sessionId}`,
            {
                method: "POST",
                body: JSON.stringify(data),
            }
        ),

    // 获取构建状态
    getBuildStatus: (taskId: string, sessionId?: string) => {
        const params = new URLSearchParams();
        const sid = sessionId || getSessionId();
        if (sid) params.set("session_id", sid);
        return request<BuildStatus>(`/knowledge/build/status/${taskId}?${params.toString()}`);
    },

    // 获取收藏夹入库状态
    getFolderStatus: (sessionId: string) =>
        request<FolderStatus[]>(`/knowledge/folders/status?session_id=${sessionId}`),

    // 同步收藏夹到向量库
    syncFolders: (data: SyncRequest, sessionId: string) =>
        request<SyncResult[]>(
            `/knowledge/folders/sync?session_id=${sessionId}`,
            {
                method: "POST",
                body: JSON.stringify(data),
            }
        ),

    // 清空知识库
    clear: () => {
        const params = new URLSearchParams();
        const sid = getSessionId();
        if (sid) params.set("session_id", sid);
        return request<{ message: string }>(`/knowledge/clear?${params.toString()}`, { method: "DELETE" });
    },

    // 删除视频
    deleteVideo: (bvid: string) => {
        const params = new URLSearchParams();
        const sid = getSessionId();
        if (sid) params.set("session_id", sid);
        return request<{ message: string }>(`/knowledge/video/${bvid}?${params.toString()}`, { method: "DELETE" });
    },

    // URL 导入（跨平台）
    importUrl: (url: string, sessionId?: string) =>
        request<ImportUrlResponse>("/knowledge/import-url", {
            method: "POST",
            body: JSON.stringify({ url, session_id: sessionId }),
        }),
};

// 对话相关
export const chatApi = {
    // 提问
    ask: (question: string, sessionId?: string, folderIds?: number[]) =>
        request<ChatResponse>("/chat/ask", {
            method: "POST",
            body: JSON.stringify({ question, session_id: sessionId, folder_ids: folderIds }),
        }),

    // 搜索
    search: (query: string, k = 5) => {
        const params = new URLSearchParams();
        const sid = getSessionId();
        if (sid) params.set("session_id", sid);
        params.set("query", query);
        params.set("k", String(k));
        return request<{ results: Array<{ bvid: string; title: string; url: string; content_preview: string }> }>(
            `/chat/search?${params.toString()}`,
            { method: "POST" }
        );
    },
};

// ==================== 知识树类型 ====================

export interface TreeNode {
    id: number;
    name: string;
    node_type: string;
    difficulty: number;
    definition?: string;
    video_count: number;
    node_count: number;
    confidence: number;
    is_reference: boolean;
    children: TreeNode[];
}

export interface TreeResponse {
    tree: TreeNode[];
    stats: {
        total_topics: number;
        total_nodes: number;
        total_edges: number;
        low_confidence_count: number;
    };
}

// ==================== 3D 图谱类型 ====================

export interface GraphNode {
    id: number;
    name: string;
    node_type: string;
    difficulty: number;
    confidence: number;
    source_count: number;
    definition: string;
    grade: string;
    val: number;
    community_id?: number;
}

export interface GraphLink {
    source: number;
    target: number;
    relation_type: string;
    weight: number;
    confidence: number;
}

export interface GraphData {
    nodes: GraphNode[];
    links: GraphLink[];
    stats: {
        node_count: number;
        link_count: number;
    };
}

export interface SegmentRef {
    id: number;
    start_time?: number;
    end_time?: number;
    text: string;
    time_label: string;
}

export interface NodeDetail {
    id: number;
    name: string;
    node_type: string;
    definition?: string;
    difficulty: number;
    confidence: number;
    source_count: number;
    review_status: string;
    aliases: string[];
    main_topic?: { id: number; name: string };
    related_topics: Array<{ id: number; name: string }>;
    prerequisites: Array<{ id: number; name: string; difficulty: number }>;
    successors: Array<{ id: number; name: string; difficulty: number }>;
    related_nodes: Array<{ id: number; name: string; node_type: string }>;
    videos: Array<{
        bvid: string;
        title: string;
        owner_name?: string;
        pic_url?: string;
        duration?: number;
        evidence_score?: number;
        url: string;
        segments: Array<{
            start_time?: number;
            end_time?: number;
            text: string;
            time_label: string;
            match_confidence?: number;
            confidence_level?: "high" | "medium" | "low";
            match_reason?: string;
        }>;
    }>;
    tree_position: Array<{ id: number; name: string; type: string }>;
}

export interface VideoDetail {
    bvid: string;
    title: string;
    description?: string;
    owner_name?: string;
    duration?: number;
    pic_url?: string;
    summary?: string;
    tags: string[];
    url: string;
    knowledge_nodes: Array<{
        id: number;
        name: string;
        node_type: string;
        difficulty: number;
        definition?: string;
        confidence: number;
        segments: Array<{ start_time?: number; end_time?: number; time_label: string }>;
        tree_position: Array<{ id: number; name: string; type: string }>;
    }>;
    segments: Array<{
        id: number;
        segment_index: number;
        start_time?: number;
        end_time?: number;
        text: string;
        summary?: string;
        source_type?: string;
        time_label: string;
    }>;
}

export interface TreeStats {
    total_nodes: number;
    total_edges: number;
    total_segments: number;
    total_topics: number;
    total_videos: number;
    pending_review: number;
}

// ==================== 知识树 API ====================

export const treeApi = {
    getTree: (opts?: { minConfidence?: number; topicId?: number; stage?: string; sessionId?: string | null }) => {
        const params = new URLSearchParams();
        const sid = opts?.sessionId ?? getSessionId();
        if (sid) params.set("session_id", sid);
        if (opts?.minConfidence) params.set("min_confidence", String(opts.minConfidence));
        if (opts?.topicId) params.set("topic_id", String(opts.topicId));
        if (opts?.stage) params.set("stage", opts.stage);
        return request<TreeResponse>(`/tree?${params.toString()}`);
    },

    getGraph: (opts?: { topicId?: number; minConfidence?: number; sessionId?: string | null }) => {
        const params = new URLSearchParams();
        const sid = opts?.sessionId ?? getSessionId();
        if (sid) params.set("session_id", sid);
        if (opts?.topicId) params.set("topic_id", String(opts.topicId));
        if (opts?.minConfidence) params.set("min_confidence", String(opts.minConfidence));
        return request<GraphData>(`/tree/graph?${params.toString()}`);
    },

    getTopics: (sessionId?: string | null) => {
        const params = new URLSearchParams();
        const sid = sessionId ?? getSessionId();
        if (sid) params.set("session_id", sid);
        return request<Array<{ id: number; name: string; definition?: string; difficulty: number; source_count: number; confidence: number }>>(`/tree/topics?${params.toString()}`);
    },

    getNodeDetail: (nodeId: number, sessionId?: string | null) => {
        const params = new URLSearchParams();
        const sid = sessionId ?? getSessionId();
        if (sid) params.set("session_id", sid);
        return request<NodeDetail>(`/tree/node/${nodeId}?${params.toString()}`);
    },

    getVideoDetail: (bvid: string, sessionId?: string | null) => {
        const params = new URLSearchParams();
        const sid = sessionId ?? getSessionId();
        if (sid) params.set("session_id", sid);
        return request<VideoDetail>(`/tree/video/${bvid}?${params.toString()}`);
    },

    getNodeSegments: (nodeId: number, sessionId?: string | null) => {
        const params = new URLSearchParams();
        const sid = sessionId ?? getSessionId();
        if (sid) params.set("session_id", sid);
        return request<Array<SegmentRef & { video_bvid: string; url?: string }>>(`/tree/node/${nodeId}/segments?${params.toString()}`);
    },

    getStats: (sessionId?: string | null) => {
        const params = new URLSearchParams();
        const sid = sessionId ?? getSessionId();
        if (sid) params.set("session_id", sid);
        return request<TreeStats>(`/tree/stats?${params.toString()}`);
    },

    getPending: (limit = 50) => {
        const params = new URLSearchParams();
        const sid = getSessionId();
        if (sid) params.set("session_id", sid);
        params.set("limit", String(limit));
        return request<Array<{ id: number; name: string; node_type: string; definition?: string; confidence: number; source_count: number }>>(`/tree/pending?${params.toString()}`);
    },

    reviewNode: (nodeId: number, action: "approve" | "reject") => {
        const params = new URLSearchParams();
        const sid = getSessionId();
        if (sid) params.set("session_id", sid);
        params.set("action", action);
        return request<{ message: string; review_status: string }>(`/tree/node/${nodeId}/review?${params.toString()}`, { method: "POST" });
    },

    getLearningPath: (nodeId: number, mode: "beginner" | "standard" | "quick" = "standard", knownIds?: number[]) => {
        const params = new URLSearchParams({ mode });
        const sid = getSessionId();
        if (sid) params.set("session_id", sid);
        if (knownIds && knownIds.length > 0) params.set("known", knownIds.join(","));
        return request<LearningPathResponse>(`/tree/node/${nodeId}/path?${params.toString()}`);
    },
};

// ==================== 学习路径类型 ====================

export interface LearningPathStep {
    order: number;
    node_id: number;
    name: string;
    node_type: string;
    difficulty: number;
    definition?: string;
    confidence: number;
    reason: string;
    is_optional: boolean;
    has_videos: boolean;
    priority_score: number;
    support_score: number;
    dependency_depth: number;
    dependency_role: string;
    reason_tags: string[];
    video_count: number;
    segment_count: number;
    evidence_score: number;
    composite_score: number;
    support_label: "strong" | "medium" | "weak";
    videos: Array<{
        bvid: string;
        title: string;
        url: string;
        segments: Array<{ time_label: string; url?: string }>;
    }>;
}

export interface LearningPathResponse {
    target: { id: number; name: string; node_type: string; difficulty: number };
    mode: string;
    steps: LearningPathStep[];
    total_steps: number;
    estimated_videos: number;
    summary?: {
        mode_label: string;
        avg_priority_score: number;
        avg_support_score: number;
        avg_evidence_score?: number;
        avg_composite_score?: number;
        foundation_steps: number;
        direct_prerequisites: number;
        optional_steps: number;
        strong_support_steps?: number;
    };
}

// ==================== 搜索 API ====================

export interface SearchResults {
    query: string;
    type: string;
    nodes: Array<{
        id: number;
        name: string;
        node_type: string;
        difficulty: number;
        definition?: string;
        confidence: number;
        source_count: number;
        video_count: number;
    }>;
    videos: Array<{
        bvid: string;
        title: string;
        description?: string;
        owner_name?: string;
        duration?: number;
        pic_url?: string;
        knowledge_node_count: number;
        url: string;
    }>;
    segments: Array<{
        bvid: string;
        title: string;
        content_preview: string;
        chunk_index?: number;
        url: string;
    }>;
}

export const searchApi = {
    search: (q: string, type: string = "all", limit: number = 20, sessionId?: string | null) => {
        const params = new URLSearchParams();
        const sid = sessionId ?? getSessionId();
        if (sid) params.set("session_id", sid);
        params.set("q", q);
        params.set("type", type);
        params.set("limit", String(limit));
        return request<SearchResults>(`/search?${params.toString()}`);
    },
};

// ==================== 知映编译类型 ====================

export interface CompileConcept {
  id: number;
  name: string;
  definition: string;
  difficulty: number;
  claims: CompileClaim[];
}

export interface CompileClaim {
  id: number;
  statement: string;
  type: string;
  confidence: number;
  time: string;
  start_time: number;
  end_time: number;
  raw_text: string;
}

export interface TimelineSegment {
  start: number;
  end: number;
  density: number;
  is_peak: boolean;
  concepts?: string[];
}

export interface CompileResult {
  video: { bvid: string; title: string; duration: number };
  concepts: CompileConcept[];
  timeline: TimelineSegment[];
  prerequisites: Array<{ source: string; target: string; type: string }>;
  stats: { concept_count: number; claim_count: number; peak_count: number };
}

export interface EvidenceItem {
  ref: number;
  video_title: string;
  bvid: string;
  time: string;
  start_time: number;
  end_time?: number;
  text: string;
  concept?: string;
  claim?: string;
}

export interface EvidenceAnswer {
  answer: string;
  evidence: EvidenceItem[];
  concept_count: number;
}

export interface OrganizerVideoItem {
  bvid: string;
  title: string;
  owner_name?: string;
  duration?: number;
  pic_url?: string;
  folder_ids: number[];
  folder_titles: string[];
  subject_tags: string[];
  content_type: string;
  difficulty_level: string;
  learning_status: string;
  value_tier: string;
  organize_score: number;
  segment_count: number;
  claim_count: number;
  concept_count: number;
  knowledge_node_count: number;
  confidence: number;
  is_core: boolean;
  reasons: string[];
  series_key?: string | null;
  series_name?: string | null;
  duplicate_candidates: Array<{
    group_id: string;
    similarity: number;
    recommended_keep: boolean;
  }>;
}

export interface OrganizerSeriesGroup {
  series_key: string;
  series_name: string;
  video_count: number;
  coverage_score: number;
  reasons: string[];
  videos: Array<{
    bvid: string;
    title: string;
    organize_score: number;
    difficulty_level: string;
  }>;
}

export interface OrganizerDuplicateGroup {
  group_id: string;
  reason: string;
  recommended_keep_bvid: string;
  archive_candidates: string[];
  items: Array<{
    bvid: string;
    title: string;
    similarity: number;
    organize_score: number;
  }>;
}

export interface OrganizerSuggestion {
  type: string;
  title: string;
  description: string;
  targets: string[];
  confidence: number;
  evidence: string[];
}

export interface OrganizerReport {
  summary: {
    total_videos: number;
    series_count: number;
    duplicate_group_count: number;
    core_count: number;
    low_value_count: number;
    compiled_count: number;
  };
  videos: OrganizerVideoItem[];
  series_groups: OrganizerSeriesGroup[];
  duplicate_groups: OrganizerDuplicateGroup[];
  suggestions: OrganizerSuggestion[];
  facet_counts: {
    subject_tags: Record<string, number>;
    content_type: Record<string, number>;
    difficulty_level: Record<string, number>;
    learning_status: Record<string, number>;
    value_tier: Record<string, number>;
  };
  export_generated_at: string;
}

// ==================== 知映编译 API ====================

export const compileApi = {
  compileVideo: (bvid: string, sessionId: string) =>
    request<{ task_id: string; message: string }>("/compile/video", {
      method: "POST",
      body: JSON.stringify({ bvid, session_id: sessionId }),
    }),
  getStatus: (taskId: string, sessionId?: string) => {
    const params = new URLSearchParams();
    const sid = sessionId || getSessionId();
    if (sid) params.set("session_id", sid);
    return request<{ status: string; progress: number; message: string }>(`/compile/status/${taskId}?${params.toString()}`);
  },
  getResult: (bvid: string) => {
    const params = new URLSearchParams();
    const sid = getSessionId();
    if (sid) params.set("session_id", sid);
    return request<CompileResult>(`/compile/result/${bvid}?${params.toString()}`);
  },
};

export const evidenceApi = {
  ask: (question: string, sessionId?: string | null) =>
    request<EvidenceAnswer>("/evidence/ask", {
      method: "POST",
      body: JSON.stringify({ question, session_id: sessionId }),
    }),
};

export const organizerApi = {
  getReport: (sessionId: string, folderIds?: number[]) => {
    const params = new URLSearchParams({ session_id: sessionId });
    if (folderIds && folderIds.length > 0) {
      params.set("folder_ids", folderIds.join(","));
    }
    return request<OrganizerReport>(`/organizer/report?${params.toString()}`);
  },
  getExportUrl: (sessionId: string, format: "json" | "markdown" = "json") => {
    const params = new URLSearchParams({ session_id: sessionId, format });
    return `${API_BASE_URL}/organizer/export?${params.toString()}`;
  },
};

// ==================== 学习路径独立 API ====================

export interface PopularTopic {
    id: number;
    name: string;
    node_type: string;
    difficulty: number;
    definition?: string;
    source_count: number;
    video_count: number;
}

export const learningPathApi = {
    // 搜索学习目标
    searchTargets: (q: string, limit = 10) => {
        const params = new URLSearchParams();
        const sid = getSessionId();
        if (sid) params.set("session_id", sid);
        params.set("q", q);
        params.set("limit", String(limit));
        return request<Array<{ id: number; name: string; node_type: string; difficulty: number; definition?: string; confidence: number; source_count: number }>>(
            `/learning-path/search?${params.toString()}`
        );
    },

    // 生成学习路径
    generate: (opts: { target?: string; nodeId?: number; mode?: string; known?: number[] }) => {
        const params = new URLSearchParams();
        const sid = getSessionId();
        if (sid) params.set("session_id", sid);
        if (opts.target) params.set("target", opts.target);
        if (opts.nodeId) params.set("node_id", String(opts.nodeId));
        if (opts.mode) params.set("mode", opts.mode);
        if (opts.known && opts.known.length > 0) params.set("known", opts.known.join(","));
        return request<LearningPathResponse>(`/learning-path/generate?${params.toString()}`);
    },

    // 获取热门学习目标
    getPopularTopics: (limit = 20) => {
        const params = new URLSearchParams();
        const sid = getSessionId();
        if (sid) params.set("session_id", sid);
        params.set("limit", String(limit));
        return request<PopularTopic[]>(`/learning-path/topics?${params.toString()}`);
    },
};
