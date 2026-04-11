"""
BiliMind 知识树学习导航系统

视频内容获取服务 — 三级降级策略 + Segment 输出
"""
from typing import Optional
from urllib.parse import urlparse
import asyncio
import math
import os
import shutil
import subprocess
import time
import httpx
from loguru import logger
from app.models import VideoContent, ContentSource, SourceType
from app.config import settings
from app.services.bilibili import BilibiliService
from app.services.asr import ASRService


def identify_platform(url: str) -> tuple[str, dict]:
    """
    识别 URL 对应的平台和关键参数

    Returns:
        (platform, params) — platform: "bilibili"/"xiaohongshu"/"zhihu", params: 解析出的ID等
    """
    import re
    if "bilibili.com" in url or "b23.tv" in url:
        m = re.search(r'/(BV[a-zA-Z0-9]+)', url)
        bvid = m.group(1) if m else None
        return "bilibili", {"bvid": bvid}
    elif "xiaohongshu.com" in url or "xhslink.com" in url:
        from app.services.xiaohongshu import XiaohongshuService
        note_id = XiaohongshuService.extract_note_id(url)
        return "xiaohongshu", {"note_id": note_id, "url": url}
    elif "zhihu.com" in url or "zhuanlan.zhihu.com" in url:
        from app.services.zhihu import ZhihuService
        parsed = ZhihuService.parse_url(url)
        return "zhihu", parsed or {}
    return "unknown", {}


class ContentFetcher:
    """
    视频内容获取器

    降级策略：
    1. 字幕（带时间戳，优先）
    2. ASR 音频转写
    3. 视频基本信息（兜底）

    新增能力：fetch_segments() 输出带时间戳的 Segment 列表
    """

    def __init__(self, bilibili_service: BilibiliService, asr_service: ASRService):
        self.bili = bilibili_service
        self.asr = asr_service
        self.segment_merge_seconds = settings.extraction_segment_merge_seconds

    async def fetch_from_url(self, url: str) -> tuple[VideoContent, list[dict]]:
        """
        统一 URL 入口：自动识别平台，获取内容和 segments

        Returns:
            (VideoContent, segments_list)
        """
        platform, params = identify_platform(url)

        if platform == "bilibili":
            bvid = params.get("bvid")
            if not bvid:
                raise ValueError(f"无法从 URL 解析 B站 bvid: {url}")
            content = await self.fetch_content(bvid)
            segments = await self.fetch_segments(bvid)
            return content, segments

        elif platform == "xiaohongshu":
            from app.services.xiaohongshu import XiaohongshuService
            xhs = XiaohongshuService()
            try:
                note_id = params.get("note_id")
                if not note_id and "xhslink.com" in url:
                    resolved = await xhs.resolve_short_url(url)
                    if resolved:
                        note_id = XiaohongshuService.extract_note_id(resolved)
                if not note_id:
                    raise ValueError(f"无法从 URL 解析小红书 note_id: {url}")

                note = await xhs.fetch_note(note_id)
                if not note:
                    raise ValueError(f"获取小红书笔记失败: {note_id}")

                segments = xhs.to_segments(note)
                content = VideoContent(
                    bvid=note_id,
                    title=note.get("title", ""),
                    content=note.get("content", ""),
                    source=ContentSource.SUBTITLE,
                    source_type=SourceType.XIAOHONGSHU,
                )
                return content, segments
            finally:
                await xhs.close()

        elif platform == "zhihu":
            from app.services.zhihu import ZhihuService
            zhihu = ZhihuService()
            try:
                content_type = params.get("type")
                data = None

                if content_type == "article":
                    data = await zhihu.fetch_article(params["article_id"])
                    source_id = params["article_id"]
                elif content_type == "answer":
                    data = await zhihu.fetch_answer(params["answer_id"])
                    source_id = params["answer_id"]
                elif content_type == "question":
                    data = await zhihu.fetch_question_top_answer(params["question_id"])
                    source_id = params["question_id"]
                else:
                    raise ValueError(f"无法解析知乎 URL: {url}")

                if not data:
                    raise ValueError(f"获取知乎内容失败: {url}")

                source_id = data.get("source_id", source_id)
                segments = zhihu.to_segments(
                    data.get("content_html", ""),
                    data.get("content", ""),
                )
                content = VideoContent(
                    bvid=source_id,
                    title=data.get("title", ""),
                    content=data.get("content", ""),
                    source=ContentSource.SUBTITLE,
                    source_type=SourceType.ZHIHU,
                )
                return content, segments
            finally:
                await zhihu.close()

        else:
            raise ValueError(f"不支持的平台 URL: {url}")

    async def fetch_content(self, bvid: str, cid: int = None, title: str = None) -> VideoContent:
        """获取视频内容（兼容旧接口），自动降级"""
        video_info = None
        if not cid or not title:
            try:
                video_info = await self.bili.get_video_info(bvid)
                if not cid:
                    cid = video_info.get("cid")
                if not title:
                    title = video_info.get("title", "未知标题")
            except Exception as e:
                logger.error(f"获取视频信息失败 [{bvid}]: {e}")
                return VideoContent(
                    bvid=bvid,
                    title=title or "未知标题",
                    content="无法获取视频信息",
                    source=ContentSource.BASIC_INFO
                )

        description = video_info.get("desc", "") if video_info else ""

        # Level 1: 尝试字幕
        subtitle_text = await self._try_subtitle(bvid, cid, video_info)
        if subtitle_text:
            logger.info(f"[{bvid}] 使用字幕文本")
            return VideoContent(
                bvid=bvid,
                title=title,
                content=subtitle_text,
                source=ContentSource.SUBTITLE
            )

        # Level 2: 尝试 ASR
        asr_text = await self._try_asr(bvid, cid)
        if asr_text:
            logger.info(f"[{bvid}] 使用 ASR 文本")
            return VideoContent(
                bvid=bvid,
                title=title,
                content=asr_text,
                source=ContentSource.ASR
            )

        # ASR 失败时，补齐基础信息
        if not video_info:
            try:
                video_info = await self.bili.get_video_info(bvid)
            except Exception as e:
                logger.debug(f"[{bvid}] 获取视频信息失败(兜底): {e}")

        if video_info and not description:
            description = video_info.get("desc", "") or description

        # Level 3: 使用基本信息兜底
        logger.info(f"[{bvid}] 使用基本信息")
        basic_content = f"视频标题：{title}"
        if description:
            basic_content += f"\n\n视频简介：{description}"

        return VideoContent(
            bvid=bvid,
            title=title,
            content=basic_content,
            source=ContentSource.BASIC_INFO
        )

    async def fetch_segments(self, bvid: str, cid: int = None, title: str = None, duration: int = None) -> list[dict]:
        """
        获取视频片段列表（带时间戳）

        Returns:
            [{"segment_index": int, "start_time": float, "end_time": float,
              "raw_text": str, "source_type": str, "confidence": float}]
        """
        video_info = None
        if not cid or not title:
            try:
                video_info = await self.bili.get_video_info(bvid)
                if not cid:
                    cid = video_info.get("cid")
                if not title:
                    title = video_info.get("title", "未知标题")
                if not duration:
                    duration = video_info.get("duration")
            except Exception as e:
                logger.error(f"获取视频信息失败 [{bvid}]: {e}")
                return []

        # 优先尝试字幕（有精确时间戳）
        subtitle_segments = await self._try_subtitle_segments(bvid, cid, video_info)
        if subtitle_segments:
            return subtitle_segments

        # 尝试 ASR（无精确时间戳，按等时分段）
        asr_text = await self._try_asr(bvid, cid)
        if asr_text:
            return self._split_text_to_segments(asr_text, duration, source_type="asr")

        # 兜底：基本信息作为单个 segment
        description = (video_info or {}).get("desc", "")
        basic_text = f"视频标题：{title}"
        if description:
            basic_text += f"\n\n视频简介：{description}"

        if basic_text.strip():
            return [{
                "segment_index": 0,
                "start_time": 0.0,
                "end_time": float(duration) if duration else None,
                "raw_text": basic_text,
                "source_type": "basic",
                "confidence": 0.3,
            }]
        return []

    async def _try_subtitle(self, bvid: str, cid: int, video_info: Optional[dict] = None) -> Optional[str]:
        """尝试获取字幕纯文本（兼容旧接口）"""
        try:
            items = await self._get_subtitle_items(bvid, cid, video_info)
            if not items:
                return None
            text = "\n".join(item["content"] for item in items if item.get("content"))
            if len(text) < 50:
                return None
            return text
        except Exception as e:
            logger.warning(f"[{bvid}] 字幕获取失败: {e}")
            return None

    async def _try_subtitle_segments(self, bvid: str, cid: int, video_info: Optional[dict] = None) -> list[dict]:
        """尝试获取字幕并合并为 Segment 列表"""
        try:
            subtitle_items = await self._get_subtitle_items(bvid, cid, video_info)
            if not subtitle_items:
                return []

            # 合并相邻字幕条目为语义片段
            return self._merge_subtitle_items(subtitle_items)

        except Exception as e:
            logger.warning(f"[{bvid}] 字幕片段获取失败: {e}")
            return []

    async def _get_subtitle_items(self, bvid: str, cid: int, video_info: Optional[dict] = None) -> list[dict]:
        """获取原始字幕条目（带时间戳）"""
        def pick_subtitle(subtitles: list) -> Optional[dict]:
            if not subtitles:
                return None
            def is_zh(sub):
                lan = sub.get("lan", "") or ""
                return "zh" in lan.lower() or "cn" in lan.lower()
            for sub in subtitles:
                if is_zh(sub) and str(sub.get("ai_status", "0")) == "0":
                    return sub
            for sub in subtitles:
                if is_zh(sub):
                    return sub
            return subtitles[0]

        def extract_subtitles(data: dict) -> list:
            subtitle_block = (data or {}).get("subtitle", {}) or {}
            return subtitle_block.get("subtitles") or subtitle_block.get("list") or []

        def extract_url(sub: dict) -> str:
            return sub.get("subtitle_url") or sub.get("url") or ""

        aid = video_info.get("aid") if video_info else None

        # 第一次尝试：播放器接口
        player_info = await self.bili.get_player_info(bvid, cid, aid=aid)
        subtitles = extract_subtitles(player_info or {})
        if subtitles:
            selected = pick_subtitle(subtitles)
            url = extract_url(selected or {})
            if url:
                items = await self.bili.download_subtitle_with_timestamps(url)
                if items and len(items) >= 3:
                    logger.info(f"[{bvid}] 字幕获取成功，{len(items)} 条")
                    return items

        # 第二次：带 aid 重试
        if video_info and not aid:
            aid = video_info.get("aid")
            if aid:
                player_info = await self.bili.get_player_info(bvid, cid, aid=aid)
                subtitles = extract_subtitles(player_info or {})
                if subtitles:
                    selected = pick_subtitle(subtitles)
                    url = extract_url(selected or {})
                    if url:
                        items = await self.bili.download_subtitle_with_timestamps(url)
                        if items and len(items) >= 3:
                            logger.info(f"[{bvid}] 字幕获取成功(补aid)，{len(items)} 条")
                            return items

        # 最后兜底：view 接口字幕列表
        view_subtitles = (video_info or {}).get("subtitle", {}).get("list") or []
        if view_subtitles:
            selected = pick_subtitle(view_subtitles)
            url = extract_url(selected or {})
            if url:
                items = await self.bili.download_subtitle_with_timestamps(url)
                if items and len(items) >= 3:
                    logger.info(f"[{bvid}] 字幕获取成功(view兜底)，{len(items)} 条")
                    return items

        logger.info(f"[{bvid}] 无可用字幕")
        return []

    def _merge_subtitle_items(self, items: list[dict]) -> list[dict]:
        """将字幕条目按时间窗口合并为语义片段"""
        if not items:
            return []

        segments = []
        current_texts = []
        current_start = items[0].get("from", 0.0)
        current_end = items[0].get("to", 0.0)

        for item in items:
            item_start = item.get("from", 0.0)
            item_end = item.get("to", 0.0)
            content = item.get("content", "")

            if not content.strip():
                continue

            # 如果与当前片段间隔超过阈值，开新片段
            if current_texts and (item_start - current_end) > self.segment_merge_seconds:
                segments.append({
                    "segment_index": len(segments),
                    "start_time": current_start,
                    "end_time": current_end,
                    "raw_text": "\n".join(current_texts),
                    "source_type": "subtitle",
                    "confidence": 1.0,
                })
                current_texts = []
                current_start = item_start

            current_texts.append(content)
            current_end = item_end

            # 如果积累的文本超过 800 字，也切分
            total_len = sum(len(t) for t in current_texts)
            if total_len >= 800:
                segments.append({
                    "segment_index": len(segments),
                    "start_time": current_start,
                    "end_time": current_end,
                    "raw_text": "\n".join(current_texts),
                    "source_type": "subtitle",
                    "confidence": 1.0,
                })
                current_texts = []
                current_start = item_end

        if current_texts:
            segments.append({
                "segment_index": len(segments),
                "start_time": current_start,
                "end_time": current_end,
                "raw_text": "\n".join(current_texts),
                "source_type": "subtitle",
                "confidence": 1.0,
            })

        return segments

    def _split_text_to_segments(self, text: str, duration: Optional[int] = None, source_type: str = "asr") -> list[dict]:
        """将无时间戳的文本按等时分段"""
        if not text.strip():
            return []

        # 按自然段落或固定长度切分
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        if not paragraphs:
            paragraphs = [text]

        # 合并短段落
        merged = []
        buf = []
        buf_len = 0
        for p in paragraphs:
            buf.append(p)
            buf_len += len(p)
            if buf_len >= 500:
                merged.append("\n".join(buf))
                buf = []
                buf_len = 0
        if buf:
            merged.append("\n".join(buf))

        total = len(merged)
        seg_duration = (float(duration) / total) if duration and total > 0 else None

        segments = []
        for i, chunk in enumerate(merged):
            start = (seg_duration * i) if seg_duration else None
            end = (seg_duration * (i + 1)) if seg_duration else None
            segments.append({
                "segment_index": i,
                "start_time": start,
                "end_time": end,
                "raw_text": chunk,
                "source_type": source_type,
                "confidence": 0.5 if seg_duration else 0.3,
            })

        return segments

    async def _try_asr(self, bvid: str, cid: int) -> Optional[str]:
        """尝试进行音频转写"""
        try:
            audio_url = await self.bili.get_audio_url(bvid, cid)
            if not audio_url:
                logger.info(f"[{bvid}] 未获取到音频 URL")
                return None
            status = await self._probe_audio_url(bvid, audio_url)
            if status is not None and status < 400:
                logger.info(f"[{bvid}] 音频 URL 可达，使用 Transcription")
                text = await self.asr.transcribe_url(audio_url)
            else:
                logger.info(f"[{bvid}] 音频 URL 不可达，使用 Recognition 兜底")
                text = await self._try_asr_with_local_audio(bvid, cid, audio_url)

            if not text or len(text) < 50:
                logger.info(f"[{bvid}] ASR 内容过少")
                return None
            preview = text[:120].replace("\n", " ").strip()
            logger.info(f"[{bvid}] ASR 成功，长度={len(text)}，预览：{preview}")
            return text
        except Exception as e:
            logger.warning(f"[{bvid}] ASR 失败: {e}")
            return None

    async def _probe_audio_url(self, bvid: str, audio_url: str) -> Optional[int]:
        """探测音频 URL 可达性（不带 Cookie，模拟 ASR 服务拉取）"""
        try:
            parsed = urlparse(audio_url)
            safe_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        except Exception:
            safe_url = "unknown"

        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            status = None
            try:
                head = await client.head(audio_url)
                status = head.status_code
            except Exception as e:
                logger.info(f"[{bvid}] 音频 URL HEAD 失败: {e}")

            if status is None or status >= 400:
                try:
                    headers = {"Range": "bytes=0-0"}
                    get = await client.get(audio_url, headers=headers)
                    status = get.status_code
                except Exception as e:
                    logger.info(f"[{bvid}] 音频 URL GET 失败: {e}")

        if status is None:
            logger.info(f"[{bvid}] 音频 URL 不可达: {safe_url}")
        else:
            logger.info(f"[{bvid}] 音频 URL 可达性: {status} - {safe_url}")
        return status

    async def _try_asr_with_local_audio(
        self, bvid: str, cid: int, audio_url: str
    ) -> Optional[str]:
        """本地下载后使用 Recognition 直传"""
        tmp_dir = os.path.join("data", "asr_tmp")
        os.makedirs(tmp_dir, exist_ok=True)

        try:
            parsed = urlparse(audio_url)
            ext = os.path.splitext(parsed.path)[1] or ".m4s"
        except Exception:
            ext = ".m4s"

        filename = f"{bvid}_{cid}_{int(time.time())}{ext}"
        file_path = os.path.join(tmp_dir, filename)

        ok = await self.bili.download_audio_to_file(audio_url, file_path)
        if not ok:
            logger.info(f"[{bvid}] 本地下载音频失败")
            return None

        if os.path.exists(file_path) and os.path.getsize(file_path) < 1024:
            logger.info(f"[{bvid}] 本地音频文件过小，跳过上传")
            try:
                os.remove(file_path)
            except Exception:
                logger.debug(f"[{bvid}] 清理过小音频失败: {file_path}")
            return None

        text = await self.asr.transcribe_local_file(file_path)
        if text:
            preview = text[:120].replace("\n", " ").strip()
            logger.info(f"[{bvid}] Recognition ASR 成功，长度={len(text)}，预览：{preview}")
        return text

