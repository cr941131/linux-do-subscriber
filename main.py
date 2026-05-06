import os
import sys
import time
import logging
import argparse
from threading import Thread

# 兼容嵌入式 Python：确保项目根目录在 sys.path 中
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import schedule
import yaml

from fetcher import LinuxDoFetcher
from markdown_store import MarkdownStore
from git_snapshot import GitSnapshot
from filter_engine import FilterEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def job_once(config: dict, interactive: bool = False):
    """单次抓取任务。"""
    fetcher = LinuxDoFetcher()
    store = MarkdownStore(
        data_dir=config["data_dir"],
        tag_stats_path=os.path.join(_project_root, "tag-stats.json"),
    )
    git = GitSnapshot(repo_dir=config["data_dir"])
    engine = FilterEngine()

    try:
        topics, is_backfill = fetcher.run(interactive=interactive)
        if not topics:
            logger.info("No new topics.")
            git.commit_changes(message=f"fetch: no new topics ({'backfill' if is_backfill else 'poll'})")
            return

        # 拉取详情并保存
        for t in topics:
            tid = t.get("id", 0)
            detail = fetcher.fetch_topic_detail(tid)

            # 尝试获取分类 slug
            cat_slug = "uncategorized"
            if detail and "category_slug" in detail:
                cat_slug = detail["category_slug"]
            elif t.get("category_name"):
                # RSS 模式下 category_name 是字符串名称
                cat_slug = t["category_name"]
            elif "category_id" in t:
                cat_slug = str(t["category_id"])

            # 保存到分类目录
            store.save_topic(t, detail=detail, category_slug=cat_slug)

            # 如果是关注用户，额外保存到用户目录
            author = t.get("last_poster_username") or t.get("poster_usernames", [""])[0]
            following = set(config.get("following_users", []))
            if author in following:
                store.save_user_topic(t, detail=detail, username=author)

        # ---------- 抓取关注用户的 activity RSS（包含评论/回复） ----------
        following_users = config.get("following_users", [])
        user_activity_total = 0
        for username in following_users:
            logger.info(f"Fetching activity for @{username}...")
            activities = fetcher.fetch_user_activity_rss(username)
            if not activities:
                continue
            saved = 0
            for act in activities:
                store.save_user_activity(act, username=username)
                saved += 1
            logger.info(f"Saved {saved} activities for @{username}.")
            user_activity_total += saved

        # Git 快照
        git.commit_changes(
            message=f"fetch: {len(topics)} topics ({'backfill' if is_backfill else 'poll'}), {user_activity_total} user activities"
        )
        logger.info(f"Job done. New topics: {len(topics)}, user activities: {user_activity_total}")
    finally:
        fetcher.close()


def run_scheduler(config: dict):
    """启动定时调度（阻塞）。"""
    interval = config["fetch"]["interval_minutes"]
    logger.info(f"Scheduler started. Interval: {interval} minutes.")

    # 立即执行一次（后台调度不交互，避免阻塞）
    job_once(config, interactive=False)

    schedule.every(interval).minutes.do(job_once, config, False)
    while True:
        schedule.run_pending()
        time.sleep(1)


def run_web_server(config: dict):
    """在后台线程启动 Flask。"""
    from web.app import run_web
    host = config.get("web_host", "127.0.0.1")
    port = config.get("web_port", 5000)
    thread = Thread(target=run_web, kwargs={"host": host, "port": port, "debug": False}, daemon=True)
    thread.start()
    logger.info(f"Web server started at http://{host}:{port}")


def main():
    parser = argparse.ArgumentParser(description="Linux.do 订阅器")
    parser.add_argument("--once", action="store_true", help="仅运行一次抓取并退出")
    parser.add_argument("--web-only", action="store_true", help="仅启动 Web 服务")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.once:
        job_once(config, interactive=True)
        return

    if args.web_only:
        from web.app import run_web
        host = config.get("web_host", "127.0.0.1")
        port = config.get("web_port", 5000)
        run_web(host=host, port=port, debug=True)
        return

    # 默认：启动 Web + 定时调度
    # 预检提示：如果 state 显示很久没抓，提醒用户先 --once
    from fetcher import LinuxDoFetcher
    pre_fetcher = LinuxDoFetcher()
    try:
        if pre_fetcher._is_backfill_needed():
            logger.warning(
                "检测到需要回填（可能已离线较长时间）。"
                "建议先运行 'python main.py --once' 进行交互式完整回填，"
                "否则后台调度将只抓取安全限制内的 %s 页。",
                config["fetch"].get("backfill_safe_limit", 20)
            )
    finally:
        pre_fetcher.close()

    run_web_server(config)
    run_scheduler(config)


if __name__ == "__main__":
    main()
