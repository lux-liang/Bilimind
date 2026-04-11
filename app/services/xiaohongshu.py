"""
BiliMind 多平台接入 — 小红书笔记内容获取
"""
import re
from typing import Optional
import httpx
from loguru import logger


class XiaohongshuService:
    """小红书公开笔记内容获取"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )

    async def close(self):
        await self.client.aclose()

    @staticmethod
    def extract_note_id(url: str) -> Optional[str]:
        """从 URL 中提取笔记 ID"""
        # https://www.xiaohongshu.com/explore/xxxxx
        # https://www.xiaohongshu.com/discovery/item/xxxxx
        # https://xhslink.com/xxx (短链接，需要跟随重定向)
        patterns = [
            r'xiaohongshu\.com/(?:explore|discovery/item)/([a-zA-Z0-9]+)',
            r'xiaohongshu\.com/note/([a-zA-Z0-9]+)',
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1)
        return None

    async def resolve_short_url(self, url: str) -> Optional[str]:
        """解析短链接 xhslink.com → 完整 URL"""
        if "xhslink.com" not in url:
            return url
        try:
            resp = await self.client.head(url)
            location = str(resp.url)
            if "xiaohongshu.com" in location:
                return location
        except Exception as e:
            logger.warning(f"小红书短链接解析失败: {e}")
        return None

    async def fetch_note(self, note_id: str) -> Optional[dict]:
        """
        获取笔记内容（通过 Web 页面解析）

        Returns:
            {title, content, author, note_id, images: [], publish_time}
        """
        page_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        try:
            resp = await self.client.get(page_url)
            if resp.status_code != 200:
                logger.warning(f"小红书笔记请求失败 [{note_id}]: HTTP {resp.status_code}")
                return None

            html = resp.text

            # 从 SSR HTML 中提取 JSON 数据
            # 小红书页面在 <script> 中嵌入 window.__INITIAL_STATE__
            import json
            state_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>', html, re.DOTALL)
            if state_match:
                try:
                    # 小红书的 JSON 可能包含 undefined，需要替换
                    raw_json = state_match.group(1)
                    raw_json = raw_json.replace('undefined', 'null')
                    state = json.loads(raw_json)
                    note_data = state.get("note", {}).get("noteDetailMap", {})
                    # 取第一个 note
                    for key, val in note_data.items():
                        note_info = val.get("note", {})
                        title = note_info.get("title", "")
                        desc = note_info.get("desc", "")
                        user = note_info.get("user", {})
                        images = [img.get("urlDefault", "") for img in note_info.get("imageList", [])]
                        return {
                            "note_id": note_id,
                            "title": title or desc[:50],
                            "content": f"{title}\n\n{desc}" if title else desc,
                            "author": user.get("nickname", ""),
                            "images": images,
                            "publish_time": note_info.get("time"),
                        }
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"解析小红书 JSON 失败 [{note_id}]: {e}")

            # 降级：从 HTML meta 标签提取
            title = _extract_meta(html, "og:title") or ""
            description = _extract_meta(html, "description") or _extract_meta(html, "og:description") or ""

            if not title and not description:
                logger.warning(f"小红书笔记无法解析内容 [{note_id}]")
                return None

            return {
                "note_id": note_id,
                "title": title,
                "content": f"{title}\n\n{description}" if title else description,
                "author": _extract_meta(html, "og:xhs:note:author") or "",
                "images": [],
                "publish_time": None,
            }

        except Exception as e:
            logger.error(f"获取小红书笔记失败 [{note_id}]: {e}")
            return None

    def to_segments(self, note: dict) -> list[dict]:
        """将笔记文本按段落切分为 Segment 列表"""
        content = note.get("content", "")
        if not content.strip():
            return []

        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
        if not paragraphs:
            return [{
                "segment_index": 0,
                "start_time": 0.0,
                "end_time": 1.0,
                "raw_text": content,
                "source_type": "text_paragraph",
                "confidence": 0.8,
            }]

        # 合并短段落
        merged = []
        buf = []
        buf_len = 0
        for p in paragraphs:
            buf.append(p)
            buf_len += len(p)
            if buf_len >= 300:
                merged.append("\n".join(buf))
                buf = []
                buf_len = 0
        if buf:
            merged.append("\n".join(buf))

        segments = []
        for i, chunk in enumerate(merged):
            segments.append({
                "segment_index": i,
                "start_time": float(i),
                "end_time": float(i + 1),
                "raw_text": chunk,
                "source_type": "text_paragraph",
                "confidence": 0.8,
            })
        return segments


def _extract_meta(html: str, name: str) -> Optional[str]:
    """从 HTML 中提取 meta 标签内容"""
    # property="name" 或 name="name"
    patterns = [
        rf'<meta[^>]+(?:property|name)="{re.escape(name)}"[^>]+content="([^"]*)"',
        rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(name)}"',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None
