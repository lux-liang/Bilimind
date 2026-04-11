"""
BiliMind 多平台接入 — 知乎文章/回答内容获取
"""
import re
from typing import Optional
import httpx
from loguru import logger


class ZhihuService:
    """知乎公开内容获取（回答 + 专栏文章）"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/html",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )

    async def close(self):
        await self.client.aclose()

    @staticmethod
    def parse_url(url: str) -> Optional[dict]:
        """
        解析知乎 URL，返回类型和 ID

        支持:
        - https://www.zhihu.com/question/123/answer/456
        - https://zhuanlan.zhihu.com/p/789
        - https://www.zhihu.com/question/123 (问题页，取第一个回答)
        """
        # 回答
        m = re.search(r'zhihu\.com/question/(\d+)/answer/(\d+)', url)
        if m:
            return {"type": "answer", "question_id": m.group(1), "answer_id": m.group(2)}

        # 专栏文章
        m = re.search(r'zhuanlan\.zhihu\.com/p/(\d+)', url)
        if m:
            return {"type": "article", "article_id": m.group(1)}

        # 问题页
        m = re.search(r'zhihu\.com/question/(\d+)', url)
        if m:
            return {"type": "question", "question_id": m.group(1)}

        return None

    async def fetch_answer(self, answer_id: str) -> Optional[dict]:
        """获取知乎回答"""
        api_url = f"https://www.zhihu.com/api/v4/answers/{answer_id}"
        params = {"include": "content,voteup_count,comment_count,question"}
        try:
            resp = await self.client.get(api_url, params=params)
            if resp.status_code != 200:
                logger.warning(f"知乎回答API返回 {resp.status_code}")
                return await self._fetch_answer_from_html(answer_id)

            data = resp.json()
            question = data.get("question", {})
            content_html = data.get("content", "")
            text = _html_to_text(content_html)

            return {
                "source_id": answer_id,
                "title": question.get("title", f"知乎回答 {answer_id}"),
                "content": text,
                "content_html": content_html,
                "author": data.get("author", {}).get("name", ""),
                "voteup_count": data.get("voteup_count", 0),
                "comment_count": data.get("comment_count", 0),
                "question_id": str(question.get("id", "")),
            }
        except Exception as e:
            logger.warning(f"知乎回答API失败 [{answer_id}]: {e}")
            return await self._fetch_answer_from_html(answer_id)

    async def _fetch_answer_from_html(self, answer_id: str) -> Optional[dict]:
        """降级：从 HTML 页面提取回答内容"""
        # 尝试通过搜索引擎缓存或直接访问页面
        try:
            url = f"https://www.zhihu.com/question/0/answer/{answer_id}"
            resp = await self.client.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text
            title = _extract_meta(html, "og:title") or f"知乎回答 {answer_id}"
            description = _extract_meta(html, "og:description") or ""
            if description:
                return {
                    "source_id": answer_id,
                    "title": title,
                    "content": description,
                    "content_html": "",
                    "author": "",
                    "voteup_count": 0,
                    "comment_count": 0,
                    "question_id": "",
                }
        except Exception as e:
            logger.warning(f"知乎回答HTML降级失败 [{answer_id}]: {e}")
        return None

    async def fetch_article(self, article_id: str) -> Optional[dict]:
        """获取知乎专栏文章"""
        api_url = f"https://zhuanlan.zhihu.com/api/articles/{article_id}"
        try:
            resp = await self.client.get(api_url)
            if resp.status_code != 200:
                logger.warning(f"知乎专栏API返回 {resp.status_code}")
                return await self._fetch_article_from_html(article_id)

            data = resp.json()
            content_html = data.get("content", "")
            text = _html_to_text(content_html)

            return {
                "source_id": article_id,
                "title": data.get("title", f"知乎专栏 {article_id}"),
                "content": text,
                "content_html": content_html,
                "author": data.get("author", {}).get("name", ""),
                "voteup_count": data.get("voteup_count", 0),
                "comment_count": data.get("comment_count", 0),
            }
        except Exception as e:
            logger.warning(f"知乎专栏API失败 [{article_id}]: {e}")
            return await self._fetch_article_from_html(article_id)

    async def _fetch_article_from_html(self, article_id: str) -> Optional[dict]:
        """降级：从 HTML 页面提取文章"""
        try:
            url = f"https://zhuanlan.zhihu.com/p/{article_id}"
            resp = await self.client.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text
            title = _extract_meta(html, "og:title") or f"知乎专栏 {article_id}"
            description = _extract_meta(html, "og:description") or ""
            if description:
                return {
                    "source_id": article_id,
                    "title": title,
                    "content": description,
                    "content_html": "",
                    "author": "",
                    "voteup_count": 0,
                    "comment_count": 0,
                }
        except Exception as e:
            logger.warning(f"知乎专栏HTML降级失败 [{article_id}]: {e}")
        return None

    async def fetch_question_top_answer(self, question_id: str) -> Optional[dict]:
        """获取问题的最高赞回答"""
        api_url = f"https://www.zhihu.com/api/v4/questions/{question_id}/answers"
        params = {"include": "content,voteup_count,comment_count", "limit": 1, "sort_by": "default"}
        try:
            resp = await self.client.get(api_url, params=params)
            if resp.status_code != 200:
                return None
            data = resp.json()
            answers = data.get("data", [])
            if not answers:
                return None
            answer = answers[0]
            answer_id = str(answer.get("id", ""))
            return await self.fetch_answer(answer_id)
        except Exception as e:
            logger.warning(f"知乎问题回答获取失败 [{question_id}]: {e}")
            return None

    def to_segments(self, content_html: str, plain_text: str = "") -> list[dict]:
        """将知乎内容按标题/段落切分为 Segment 列表"""
        text = plain_text or _html_to_text(content_html)
        if not text.strip():
            return []

        # 尝试按 HTML 标题切分
        sections = _split_by_headings(content_html)
        if sections and len(sections) > 1:
            segments = []
            for i, section in enumerate(sections):
                section_text = _html_to_text(section).strip()
                if not section_text:
                    continue
                segments.append({
                    "segment_index": len(segments),
                    "start_time": float(len(segments)),
                    "end_time": float(len(segments) + 1),
                    "raw_text": section_text,
                    "source_type": "text_paragraph",
                    "confidence": 0.8,
                })
            if segments:
                return segments

        # 降级：按段落切分
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        if not paragraphs:
            return [{
                "segment_index": 0,
                "start_time": 0.0,
                "end_time": 1.0,
                "raw_text": text,
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
            if buf_len >= 500:
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


def _html_to_text(html: str) -> str:
    """简单 HTML → 纯文本转换"""
    if not html:
        return ""
    text = html
    # 替换常见块级标签为换行
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(?:p|div|h[1-6]|li|blockquote)>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<(?:p|div|h[1-6]|li|blockquote)[^>]*>', '\n', text, flags=re.IGNORECASE)
    # 去掉所有 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # HTML entities
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"')
    # 合并多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _split_by_headings(html: str) -> list[str]:
    """按 <h2>/<h3> 标签切分 HTML 为段落"""
    if not html:
        return []
    parts = re.split(r'(?=<h[23][^>]*>)', html, flags=re.IGNORECASE)
    return [p for p in parts if p.strip()]


def _extract_meta(html: str, name: str) -> Optional[str]:
    """从 HTML 中提取 meta 标签内容"""
    patterns = [
        rf'<meta[^>]+(?:property|name)="{re.escape(name)}"[^>]+content="([^"]*)"',
        rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(name)}"',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None
