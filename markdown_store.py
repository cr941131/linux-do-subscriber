import os
import re
import html
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class MarkdownStore:
    """负责将 Discourse 帖子转换为 Markdown 并存储到文件系统。"""

    def __init__(self, data_dir: str = "./data", tag_stats_path: str = "./tag-stats.json"):
        self.data_dir = data_dir
        self.tag_stats_path = tag_stats_path
        os.makedirs(data_dir, exist_ok=True)

    def _update_tag_stats(self, tags: list):
        """更新本地标签统计计数。"""
        stats = {}
        if os.path.exists(self.tag_stats_path):
            try:
                with open(self.tag_stats_path, "r", encoding="utf-8") as f:
                    stats = json.load(f)
            except Exception:
                pass
        for tag in tags:
            if not tag:
                continue
            tag_key = tag.get("name") or tag.get("slug") or tag if isinstance(tag, dict) else tag
            if not tag_key:
                continue
            if tag_key in stats:
                stats[tag_key]["count"] = stats[tag_key].get("count", 0) + 1
            else:
                slug = tag.get("slug") if isinstance(tag, dict) else tag_key
                stats[tag_key] = {"count": 1, "slug": slug}
        try:
            with open(self.tag_stats_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write tag stats: {e}")

    def _slugify(self, text: str) -> str:
        """生成文件安全的 slug。"""
        text = re.sub(r'[^\w\s-]', '', text).strip().lower()
        return re.sub(r'[-\s]+', '-', text)[:60]

    def _ensure_dir(self, path: str):
        os.makedirs(path, exist_ok=True)

    def topic_to_markdown(self, topic: Dict[str, Any], detail: Optional[Dict[str, Any]] = None) -> str:
        """将 topic + detail 转换为 Markdown 文本。"""
        title = topic.get("title", "Untitled")
        author = topic.get("last_poster_username") or topic.get("poster_usernames", ["unknown"])[0]
        category_id = topic.get("category_id", 0)
        tags = topic.get("tags", [])
        created = topic.get("created_at", "")
        bumped = topic.get("bumped_at", "")
        reply_count = topic.get("posts_count", 0) - 1  # 减去楼主
        views = topic.get("views", 0)
        tid = topic.get("id", 0)
        slug = topic.get("slug", "")
        source = f"https://linux.do/t/{slug}/{tid}"

        # 前置元数据
        frontmatter = f"""---
title: "{title}"
author: "{author}"
category_id: {category_id}
tags: {tags}
replies_count: {reply_count}
views: {views}
created_at: "{created}"
bumped_at: "{bumped}"
last_fetched: "{datetime.now(timezone.utc).isoformat()}"
source: "{source}"
---

"""

        body_parts = [frontmatter]

        if detail and "post_stream" in detail:
            posts = detail["post_stream"].get("posts", [])
            for idx, post in enumerate(posts):
                user = post.get("username", "unknown")
                cooked = post.get("cooked", "")
                post_date = post.get("created_at", "")
                post_number = post.get("post_number", idx + 1)

                # 简单 HTML -> Markdown 转换（ Discourse cooked 是 HTML）
                md_content = self._cooked_to_md(cooked)

                if post_number == 1:
                    body_parts.append(f"# {title}\n")
                else:
                    body_parts.append(f"\n---\n\n**#{post_number}** by @{user} | {post_date}\n\n")

                body_parts.append(md_content)
                body_parts.append("\n")
        elif topic.get("_description"):
            # RSS 模式：使用 description 作为正文
            md_content = self._cooked_to_md(topic["_description"])
            body_parts.append(f"# {title}\n\n")
            body_parts.append(md_content)
            body_parts.append("\n")
        else:
            # 没有详情时只存标题和链接
            body_parts.append(f"# {title}\n\n> 摘要获取失败或未展开，请查看原文：{source}\n")

        return "\n".join(body_parts)

    def _cooked_to_md(self, html_content: str) -> str:
        """极简 HTML 转 Markdown。"""
        import re

        text = html_content
        base = "https://linux.do"

        # 0. 标题：先转换 h1-h6，避免被后续通用标签清理误删
        for level in range(1, 7):
            tag = f'h{level}'
            text = re.sub(rf'<{tag}[^>]*>(.*?)</{tag}>', rf'\n{"#" * level} \1\n', text, flags=re.S)

        # 0.5 清理空锚点（Discourse 章节锚点 `<a name="..." class="anchor" href="#..."></a>`）
        # 这些空链接会被后面的 <a> 正则转成 `[](url)`，污染输出，直接删掉
        text = re.sub(r'<a[^>]*class="[^"]*anchor[^"]*"[^>]*>\s*</a>', '', text, flags=re.S)

        # 1. 补全相对路径为绝对路径（必须在标签处理之前）
        text = re.sub(r'href="/([^"]*)"', rf'href="{base}/\1"', text)
        text = re.sub(r'src="/([^"]*)"', rf'src="{base}/\1"', text)

        # 2. 代码块
        text = re.sub(r'<pre><code[^>]*>(.*?)</code></pre>', r'\n```\n\1\n```\n', text, flags=re.S)
        text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text, flags=re.S)

        # 3. 处理 lightbox 图片：<a class="lightbox" ...><img ...></a> 简化为 ![alt](src)
        # 避免生成嵌套链接 [![image](src)](href)
        def _replace_lightbox(m):
            img_src = m.group(1)
            img_alt = m.group(2) or "image"
            return f'![{img_alt}]({img_src})'
        text = re.sub(
            r'<a[^>]*class="[^"]*lightbox[^"]*"[^>]*>\s*<img[^>]+src="([^"]+)"[^>]*alt="([^"]*)"[^>]*/?>\s*</a>',
            _replace_lightbox,
            text,
            flags=re.S
        )
        # 兼容没有 alt 的 img
        text = re.sub(
            r'<a[^>]*class="[^"]*lightbox[^"]*"[^>]*>\s*<img[^>]+src="([^"]+)"[^>]*/?>\s*</a>',
            r'![image](\1)',
            text,
            flags=re.S
        )

        # 4. 列表（必须在段落之前，避免 <li><p>...</p></li> 变成空列表项）
        def _process_li(m):
            content = m.group(1)
            # 去掉 li 内部的 <p> 和 </p>，避免后续段落处理破坏列表结构
            content = re.sub(r'<p>', '', content)
            content = re.sub(r'</p>', '\n', content)
            return '- ' + content.strip() + '\n'
        text = re.sub(r'<li>(.*?)</li>', _process_li, text, flags=re.S)
        text = re.sub(r'<ul>|</ul>|<ol>|</ol>', '\n', text)

        # 5. 段落（处理不在列表内的剩余 <p>）
        text = re.sub(r'<p>', '\n\n', text)
        text = re.sub(r'</p>', '', text)

        # 6. 粗体/斜体
        text = re.sub(r'<strong>(.*?)</strong>', r'**\1**', text, flags=re.S)
        text = re.sub(r'<em>(.*?)</em>', r'*\1*', text, flags=re.S)
        # 链接
        text = re.sub(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.S)
        # 图片（非 lightbox 的剩余 img）
        text = re.sub(r'<img[^>]+src="([^"]+)"[^>]*alt="([^"]*)"[^>]*/?>', r'![\2](\1)', text)
        text = re.sub(r'<img[^>]+src="([^"]+)"[^>]*/?>', r'![image](\1)', text)
        # 引用
        text = re.sub(r'<blockquote>', '\n> ', text)
        text = re.sub(r'</blockquote>', '\n', text)
        # 清理残余标签
        text = re.sub(r'<[^>]+>', '', text)
        # 反转义
        text = html.unescape(text)
        # 合并空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def save_topic(self, topic: Dict[str, Any], detail: Optional[Dict[str, Any]] = None,
                   category_slug: str = "uncategorized") -> str:
        """保存帖子到分类目录，返回文件路径。"""
        tid = topic.get("id", 0)
        slug = self._slugify(topic.get("title", "untitled"))
        filename = f"{tid}-{slug}.md"

        cat_dir = os.path.join(self.data_dir, "categories", category_slug)
        self._ensure_dir(cat_dir)
        filepath = os.path.join(cat_dir, filename)

        md_content = self.topic_to_markdown(topic, detail)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)

        self._update_tag_stats(topic.get("tags", []))
        logger.info(f"Saved topic {tid} to {filepath}")
        return filepath

    def save_user_topic(self, topic: Dict[str, Any], detail: Optional[Dict[str, Any]] = None,
                        username: str = "unknown") -> str:
        """为关注用户单独保存副本。"""
        tid = topic.get("id", 0)
        slug = self._slugify(topic.get("title", "untitled"))
        filename = f"{tid}-{slug}.md"

        user_dir = os.path.join(self.data_dir, "users", username)
        self._ensure_dir(user_dir)
        filepath = os.path.join(user_dir, filename)

        md_content = self.topic_to_markdown(topic, detail)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)

        return filepath

    def save_user_activity(self, item: Dict[str, Any], username: str = "unknown") -> str:
        """保存用户 activity（话题或回复）到用户目录。"""
        topic_id = item.get("id", 0)
        post_id = item.get("post_id", 0)
        post_number = item.get("post_number", 1)
        title = item.get("title", "Untitled")
        author = username  # 统一使用传入的 username，避免大小写和 @ 符号不一致
        created = item.get("created_at", "")
        source = item.get("source", "")
        is_reply = item.get("_is_reply", False)
        description = item.get("_description", "")

        # 文件名区分话题和回复
        if is_reply:
            filename = f"{topic_id}-{post_number}.md"
        else:
            slug = self._slugify(title)
            filename = f"{topic_id}-{slug}.md"

        user_dir = os.path.join(self.data_dir, "users", username)
        self._ensure_dir(user_dir)
        filepath = os.path.join(user_dir, filename)

        # 避免重复写入：如果文件已存在且内容无变化，跳过
        if os.path.exists(filepath):
            existing = open(filepath, "r", encoding="utf-8").read()
            # 简单比较 source 和 post_id
            if str(post_id) in existing and source in existing:
                return filepath

        frontmatter = f"""---
title: "{title}"
author: "{author}"
topic_id: {topic_id}
post_id: {post_id}
post_number: {post_number}
is_reply: {str(is_reply).lower()}
created_at: "{created}"
bumped_at: "{created}"
last_fetched: "{datetime.now(timezone.utc).isoformat()}"
source: "{source}"
---

"""
        md_content = self._cooked_to_md(description)
        if is_reply:
            body = f"{frontmatter}**#{post_number}** by @{author}\n\n{md_content}\n"
        else:
            body = f"{frontmatter}# {title}\n\n{md_content}\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(body)

        self._update_tag_stats(item.get("tags", []))
        logger.info(f"Saved user activity {topic_id}/{post_number} for @{username}")
        return filepath
