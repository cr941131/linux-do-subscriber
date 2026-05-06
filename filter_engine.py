import os
import re
import yaml
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from dateutil import parser as date_parser


class FilterEngine:
    """基于元数据对帖子进行筛选和排序。"""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.data_dir = self.config.get("data_dir", "./data")
        self.rules = self.config.get("filters", {})
        self.following = set(self.config.get("following_users", []))
        self._topics_cache = None
        self._topics_cache_time = 0
        self._cache_ttl = 30
        self._user_topics_cache = {}
        self._user_topics_cache_time = {}

    def parse_frontmatter(self, filepath: str) -> Optional[Dict[str, Any]]:
        """解析 Markdown 文件的前置元数据。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return None
        if not content.startswith("---"):
            return None
        end = content.find("---", 3)
        if end == -1:
            return None
        try:
            meta = yaml.safe_load(content[3:end])
            meta["_filepath"] = filepath
            meta["_content"] = content[end + 3:].strip()
            return meta
        except Exception:
            return None

    def list_all_topics(self) -> List[Dict[str, Any]]:
        """遍历 data/categories 下的所有 .md 文件并解析元数据（带 30 秒缓存）。

        同一帖子可能因分类映射迁移同时存在于数字目录与中文目录，
        按文件名去重并优先保留非纯数字目录的副本。
        """
        import time
        now = time.time()
        if self._topics_cache is not None and (now - self._topics_cache_time) < self._cache_ttl:
            return self._topics_cache
        topics = []
        cat_dir = os.path.join(self.data_dir, "categories")
        if not os.path.exists(cat_dir):
            return topics

        seen = {}  # fname -> filepath
        for root, _dirs, files in os.walk(cat_dir):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                filepath = os.path.join(root, fname)
                if fname in seen:
                    existing_dir = os.path.basename(os.path.dirname(seen[fname]))
                    current_dir = os.path.basename(os.path.dirname(filepath))
                    # 优先保留非纯数字目录（中文 slug 目录）
                    if existing_dir.isdigit() and not current_dir.isdigit():
                        seen[fname] = filepath
                    continue
                seen[fname] = filepath

        for filepath in seen.values():
            meta = self.parse_frontmatter(filepath)
            if meta:
                topics.append(meta)
        self._topics_cache = topics
        self._topics_cache_time = now
        return topics

    def list_user_topics(self, username: str) -> List[Dict[str, Any]]:
        """获取某个用户目录下的帖子（带 30 秒缓存）。"""
        import time
        now = time.time()
        cache = self._user_topics_cache.get(username)
        cache_time = self._user_topics_cache_time.get(username, 0)
        if cache is not None and (now - cache_time) < self._cache_ttl:
            return cache
        user_dir = os.path.join(self.data_dir, "users", username)
        if not os.path.exists(user_dir):
            return []
        topics = []
        for fname in os.listdir(user_dir):
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(user_dir, fname)
            meta = self.parse_frontmatter(filepath)
            if meta:
                topics.append(meta)
        self._user_topics_cache[username] = topics
        self._user_topics_cache_time[username] = now
        return topics

    def apply(self, topics: List[Dict[str, Any]],
              min_replies: Optional[int] = None,
              max_age_days: Optional[int] = None,
              categories: Optional[List[str]] = None,
              tags: Optional[List[str]] = None,
              author: Optional[str] = None,
              sort_by: str = "bumped_at",
              descending: bool = True) -> List[Dict[str, Any]]:
        """应用筛选条件。"""
        min_replies = min_replies if min_replies is not None else self.rules.get("min_replies", 0)
        max_age = max_age_days if max_age_days is not None else self.rules.get("max_age_days")
        cats = categories if categories is not None else self.rules.get("categories", [])
        tags_filter = tags if tags is not None else self.rules.get("tags", [])

        now = datetime.now(timezone.utc)
        result = []

        for t in topics:
            if min_replies and t.get("replies_count", 0) < min_replies:
                continue
            if max_age:
                try:
                    created = date_parser.isoparse(str(t.get("created_at", "")))
                    if (now - created).days > max_age:
                        continue
                except Exception:
                    pass
            if cats:
                # 这里 category_id 是数字，实际筛选可能需要映射 slug
                # 简单处理：允许直接传 category_id 列表，或后续维护映射表
                if t.get("category_id") not in cats:
                    continue
            if tags_filter:
                raw_tags = t.get("tags") or []
                topic_tags = set(
                    (tag.get("name") or tag.get("slug") or tag if isinstance(tag, dict) else tag)
                    for tag in raw_tags if tag
                )
                if not topic_tags.intersection(set(tags_filter)):
                    continue
            if author and t.get("author") != author:
                continue
            result.append(t)

        # 排序
        reverse = descending
        if sort_by in ("created_at", "bumped_at", "last_fetched"):
            def _key(x):
                try:
                    return date_parser.isoparse(str(x.get(sort_by, "1970-01-01T00:00:00Z")))
                except Exception:
                    return datetime.min.replace(tzinfo=timezone.utc)
            result.sort(key=_key, reverse=reverse)
        elif sort_by == "replies_count":
            result.sort(key=lambda x: x.get("replies_count", 0), reverse=reverse)
        elif sort_by == "views":
            result.sort(key=lambda x: x.get("views", 0), reverse=reverse)

        return result

    def search(self, topics: List[Dict[str, Any]], query: str, search_type: str = "all") -> List[Dict[str, Any]]:
        """关键词搜索，支持全部/标签/类别三种范围。"""
        q = query.strip().lower()
        if not q:
            return topics
        result = []
        for t in topics:
            if search_type == "tag":
                raw_tags = t.get("tags") or []
                topic_tags = [
                    (tag.get("name") or tag.get("slug") or tag if isinstance(tag, dict) else tag).lower()
                    for tag in raw_tags if tag
                ]
                if any(q in tag for tag in topic_tags):
                    result.append(t)
            elif search_type == "category":
                cat = str(t.get("category_id", "")).lower()
                cat_name = str(t.get("category_name", "")).lower()
                if q in cat or q in cat_name:
                    result.append(t)
            else:
                title = str(t.get("title", "")).lower()
                content = str(t.get("_content", "")).lower()
                if q in title or q in content:
                    result.append(t)
        return result

    def get_following_updates(self) -> Dict[str, List[Dict[str, Any]]]:
        """获取所有关注用户的最新帖子，按用户分组。"""
        updates = {}
        for user in self.following:
            topics = self.list_user_topics(user)
            # 默认按 bumped_at 倒序
            updates[user] = self.apply(topics, sort_by="bumped_at")
        return updates

    def get_red_dot_items(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取最近 N 小时内新增或更新的帖子（用于前端红点）。"""
        topics = self.list_all_topics()
        now = datetime.now(timezone.utc)
        result = []
        for t in topics:
            try:
                fetched = date_parser.isoparse(str(t.get("last_fetched", "")))
                if (now - fetched).total_seconds() / 3600 <= hours:
                    result.append(t)
            except Exception:
                continue
        return sorted(result, key=lambda x: date_parser.isoparse(str(x.get("bumped_at", "1970"))), reverse=True)
