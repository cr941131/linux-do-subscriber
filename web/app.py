import os
import sys
import json

# 确保能 import 上级目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from urllib.parse import urlencode
from flask import Flask, render_template, jsonify, request, send_from_directory
import markdown as md_lib
from dateutil import parser as date_parser

from filter_engine import FilterEngine
from git_snapshot import GitSnapshot

app = Flask(__name__, template_folder="templates", static_folder="static")

# Markdown 转换器（支持表格、代码高亮等扩展）
_md_converter = md_lib.Markdown(extensions=['tables', 'fenced_code'])

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
engine = FilterEngine()
git_snap = GitSnapshot(repo_dir=DATA_DIR)

# 红点已读时间（进程级，重启后重置）
_last_read_time = datetime.min.replace(tzinfo=timezone.utc)

# 搜索历史持久化
_SEARCH_HISTORY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "search-history.json")
_SEARCH_HISTORY_MAX = 10


def _load_search_history() -> list:
    if os.path.exists(_SEARCH_HISTORY_PATH):
        try:
            with open(_SEARCH_HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("history", [])
        except Exception:
            pass
    return []


def _record_search(q: str, search_type: str):
    if not q.strip():
        return
    history = _load_search_history()
    # 去重：同样的 query+type 只保留最新一条
    history = [
        h for h in history
        if not (h.get("query") == q and h.get("search_type") == search_type)
    ]
    history.insert(0, {
        "query": q,
        "search_type": search_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    history = history[:_SEARCH_HISTORY_MAX]
    try:
        with open(_SEARCH_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump({"history": history}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _topic_url_path(filepath: str) -> str:
    """将本地文件路径转换为 URL 路径（统一用 /）。"""
    rel = os.path.relpath(filepath, DATA_DIR)
    return rel.replace("\\", "/")


@app.context_processor
def inject_globals():
    return {"data_dir": DATA_DIR, "topic_url": _topic_url_path}


@app.template_global()
def build_url(base: str = "/", **overrides) -> str:
    """基于当前请求参数构造新 URL，支持覆盖或删除指定参数。"""
    args = request.args.copy()
    for k, v in overrides.items():
        if v is None:
            args.pop(k, None)
        else:
            args[k] = v
    query = urlencode(args)
    return f"{base}?{query}" if query else base


def _format_relative(dt_str: str) -> str:
    """人性化时间显示。"""
    try:
        from dateutil import parser as date_parser
        dt = date_parser.isoparse(dt_str)
        now = datetime.now(timezone.utc)
        delta = now - dt
        if delta.days > 365:
            return f"{delta.days // 365}年前"
        if delta.days > 30:
            return f"{delta.days // 30}月前"
        if delta.days > 0:
            return f"{delta.days}天前"
        if delta.seconds >= 3600:
            return f"{delta.seconds // 3600}小时前"
        if delta.seconds >= 60:
            return f"{delta.seconds // 60}分钟前"
        return "刚刚"
    except Exception:
        return dt_str


def _deduplicate_topics(topics: list) -> list:
    """按话题 ID 去重，优先保留首帖（非回复），其次是 bumped_at 最新的一条。"""
    seen = {}
    for t in topics:
        tid = t.get("id") or t.get("topic_id")
        if tid is None:
            continue
        if tid not in seen:
            seen[tid] = t
        else:
            existing_is_reply = seen[tid].get("is_reply", False) or seen[tid].get("_is_reply", False)
            new_is_reply = t.get("is_reply", False) or t.get("_is_reply", False)
            # 优先保留首帖
            if existing_is_reply and not new_is_reply:
                seen[tid] = t
            # 如果都是回复或都是首帖，保留更新的
            elif t.get("bumped_at", "") > seen[tid].get("bumped_at", ""):
                seen[tid] = t
    return sorted(seen.values(), key=lambda x: x.get("bumped_at", ""), reverse=True)


@app.template_filter("relative_time")
def relative_time_filter(dt_str: str) -> str:
    return _format_relative(dt_str)


@app.template_filter("markdown")
def markdown_filter(text: str) -> str:
    """将 Markdown 文本转为 HTML。"""
    return _md_converter.convert(text)


@app.route("/")
def index():
    """首页：最新帖子列表，支持筛选参数与搜索。"""
    min_replies = request.args.get("min_replies", type=int)
    max_age_days = request.args.get("max_age_days", type=int)
    sort_by = request.args.get("sort_by", "bumped_at")
    category = request.args.get("category", "")
    tag = request.args.get("tag", "")
    author = request.args.get("author", "")
    q = request.args.get("q", "")
    search_type = request.args.get("search_type", "all")

    categories = [category] if category else None
    tags = [tag] if tag else None

    topics = engine.list_all_topics()

    # 搜索过滤与记录
    if q:
        topics = engine.search(topics, q, search_type)
        _record_search(q, search_type)

    search_history = _load_search_history()

    filtered = engine.apply(
        topics,
        min_replies=min_replies,
        max_age_days=max_age_days,
        categories=categories,
        tags=tags,
        author=author or None,
        sort_by=sort_by,
        descending=True,
    )

    # 为模板准备简洁数据
    for t in filtered:
        t["relative_bumped"] = _format_relative(t.get("bumped_at", ""))
        t["relative_created"] = _format_relative(t.get("created_at", ""))

    # 获取分类列表（从目录结构推断）
    cat_dir = os.path.join(DATA_DIR, "categories")
    category_slugs = []
    if os.path.exists(cat_dir):
        category_slugs = [d for d in os.listdir(cat_dir) if os.path.isdir(os.path.join(cat_dir, d))]

    # 收集所有出现过的标签（去重排序）
    all_tags = set()
    for t in topics:
        for tag in t.get("tags", []):
            if tag:
                all_tags.add(tag)
    all_tags = sorted(all_tags)

    # 红点标记：last_fetched 晚于已读时间的内容
    red_dot_ids = {
        t["source"].split("/")[-1]
        for t in engine.get_red_dot_items(hours=24)
        if _last_read_time == datetime.min.replace(tzinfo=timezone.utc)
        or date_parser.isoparse(str(t.get("last_fetched", "1970-01-01T00:00:00Z"))) > _last_read_time
    }
    for t in filtered:
        tid = t.get("source", "").split("/")[-1]
        t["is_new"] = tid in red_dot_ids

    return render_template(
        "index.html",
        topics=filtered,
        categories=category_slugs,
        all_tags=all_tags,
        following=engine.following,
        request_args=request.args,
        q=q,
        search_type=search_type,
        search_history=search_history,
    )


@app.route("/topic/<path:filepath>")
def topic_detail(filepath):
    """查看单帖内容。"""
    # filepath 为相对路径，如 categories/xxx/123-slug.md
    safe_path = os.path.normpath(filepath).lstrip(".\\/")
    full_path = os.path.join(DATA_DIR, safe_path)
    if not full_path.startswith(os.path.abspath(DATA_DIR)):
        return "Invalid path", 400

    if not os.path.exists(full_path):
        return "Not found", 404

    meta = engine.parse_frontmatter(full_path)
    if not meta:
        return "Failed to parse", 500

    # 获取 git 历史
    history = git_snap.get_history(filepath=safe_path, max_count=5)
    meta["history"] = history

    # 找到同分类的上下帖
    cat_dir = os.path.dirname(full_path)
    siblings = []
    if os.path.exists(cat_dir):
        siblings = [f for f in os.listdir(cat_dir) if f.endswith(".md")]
    siblings.sort()
    fname = os.path.basename(full_path)
    idx = siblings.index(fname) if fname in siblings else -1
    prev_topic = siblings[idx - 1] if idx > 0 else None
    next_topic = siblings[idx + 1] if idx >= 0 and idx < len(siblings) - 1 else None

    return render_template(
        "topic.html",
        topic=meta,
        prev_topic=prev_topic,
        next_topic=next_topic,
        category_dir=os.path.basename(cat_dir),
    )


@app.route("/following")
def following_page():
    """关注用户汇总页。"""
    updates = engine.get_following_updates()
    for user_topics in updates.values():
        for t in user_topics:
            t["relative_bumped"] = _format_relative(t.get("bumped_at", ""))
            t["relative_created"] = _format_relative(t.get("created_at", ""))

    # 去重：同一话题只保留最新一条，避免同一话题的多个回复重复显示
    for username, user_topics in updates.items():
        updates[username] = _deduplicate_topics(user_topics)

    return render_template("following.html", updates=updates)


@app.route("/user/<username>")
def user_page(username):
    """关注用户的主页。"""
    topics = engine.list_user_topics(username)
    filtered = engine.apply(topics, sort_by="bumped_at")
    # 按话题去重：同一话题只保留最新一条
    filtered = _deduplicate_topics(filtered)
    for t in filtered:
        t["relative_bumped"] = _format_relative(t.get("bumped_at", ""))
        t["relative_created"] = _format_relative(t.get("created_at", ""))
    return render_template("user.html", username=username, topics=filtered)


@app.route("/api/topics")
def api_topics():
    """JSON API：供前端 AJAX 调用。"""
    min_replies = request.args.get("min_replies", type=int)
    max_age_days = request.args.get("max_age_days", type=int)
    sort_by = request.args.get("sort_by", "bumped_at")
    topics = engine.list_all_topics()
    filtered = engine.apply(topics, min_replies=min_replies, max_age_days=max_age_days, sort_by=sort_by)
    return jsonify(filtered)


@app.route("/api/red-dot")
def api_red_dot():
    """返回需要红点标记的 topic id 列表（仅包含已读时间之后的新内容）。"""
    items = engine.get_red_dot_items(hours=24)
    # 过滤出 last_fetched 晚于 _last_read_time 的条目
    new_items = [
        t for t in items
        if _last_read_time == datetime.min.replace(tzinfo=timezone.utc)
        or date_parser.isoparse(str(t.get("last_fetched", "1970-01-01T00:00:00Z"))) > _last_read_time
    ]
    ids = [t.get("source", "").split("/")[-1] for t in new_items]
    return jsonify({"ids": ids, "count": len(ids)})


@app.route("/api/red-dot/items")
def api_red_dot_items():
    """返回红点对应的更新内容列表（用于下拉面板展示）。"""
    items = engine.get_red_dot_items(hours=24)
    new_items = [
        t for t in items
        if _last_read_time == datetime.min.replace(tzinfo=timezone.utc)
        or date_parser.isoparse(str(t.get("last_fetched", "1970-01-01T00:00:00Z"))) > _last_read_time
    ]
    result = []
    for t in new_items:
        fp = t.get("_filepath", "")
        rel = _topic_url_path(fp) if fp else ""
        result.append({
            "id": t.get("source", "").split("/")[-1],
            "title": t.get("title", "Untitled"),
            "source": t.get("source", ""),
            "category": t.get("category_id", ""),
            "bumped_at": t.get("bumped_at", ""),
            "relative_bumped": _format_relative(t.get("bumped_at", "")),
            "filepath": rel,
        })
    return jsonify({"items": result, "count": len(result)})


@app.route("/api/tags")
def api_tags():
    """返回所有标签及本地计数，按数量降序。"""
    tag_stats_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tag-stats.json")
    stats = {}
    if os.path.exists(tag_stats_path):
        try:
            with open(tag_stats_path, "r", encoding="utf-8") as f:
                stats = json.load(f)
        except Exception:
            pass
    tags = []
    for name, info in stats.items():
        tags.append({"name": name, "count": info.get("count", 0), "slug": info.get("slug", name)})
    tags.sort(key=lambda x: x["count"], reverse=True)
    return jsonify({"tags": tags})


@app.route("/api/mark-read", methods=["POST"])
def api_mark_read():
    """标记当前时间为已读，清空红点。"""
    global _last_read_time
    _last_read_time = datetime.now(timezone.utc)
    return jsonify({"ok": True})


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(os.path.join(app.root_path, "static"), filename)


def run_web(host: str = "127.0.0.1", port: int = 5000, debug: bool = True):
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_web()
