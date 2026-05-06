import os
import time
import json
import logging
import random
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin
from typing import List, Dict, Any, Optional, Tuple

import requests
import yaml
from dateutil import parser as date_parser

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class LinuxDoFetcher:
    """基于 Discourse API 或 RSS 的内容获取器，支持正常轮询和断点回填。"""

    def __init__(self, config_path: str = "config.yaml", state_path: str = "state.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.state_path = state_path
        self.state = self._load_state()
        self.base_url = self.config["site"]["base_url"].rstrip("/")
        self.page_size = self.config["site"]["page_size"]
        self.delay = self.config["fetch"]["request_delay"]
        self.jitter = self.config["fetch"].get("request_jitter", 0.5)
        self.safe_limit = self.config["fetch"].get("backfill_safe_limit", 20)
        self.confirm = self.config["fetch"].get("backfill_confirm", True)
        self._delay_factor = 1.0  # 动态延迟系数：回填=1.0，增量=0.2

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config["fetch"].get("user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        # Playwright 后备（用于绕过 Cloudflare）
        self._pw = None
        self._pw_browser = None
        self._pw_context = None
        self._pw_page = None
        self._use_playwright = False

        # 运行时检测数据源（requests 不行会尝试 Playwright）
        self._use_rss = not self._check_api_available()
        if self._use_rss:
            logger.warning("Discourse JSON API 不可用（403），已自动切换到 RSS 模式。")
            self.session.headers["Accept"] = "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"

    def _load_state(self) -> dict:
        if os.path.exists(self.state_path):
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"last_fetch_time": None, "last_topic_id": 0, "known_topic_ids": []}

    def _save_state(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _sleep(self):
        """带抖动的延迟（回填模式用完整延迟，增量模式加速）。"""
        sleep_time = self.delay * self._delay_factor + random.uniform(0, self.jitter * self._delay_factor)
        time.sleep(sleep_time)

    def _get_chrome_pids(self):
        """获取当前所有 chrome.exe / chromium.exe 的 PID（Windows tasklist）。"""
        pids = set()
        try:
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        pids.add(int(parts[1].strip('"')))
                    except ValueError:
                        pass
        except Exception:
            pass
        return pids

    def _hide_browser_windows(self, target_pids):
        """使用 Windows API 隐藏指定 PID 的 Chromium 窗口（任务栏也不显示图标）。"""
        if not target_pids:
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            EnumWindowsProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )
            SW_HIDE = 0

            def enum_callback(hwnd, _):
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in target_pids:
                    user32.ShowWindow(hwnd, SW_HIDE)
                return True

            user32.EnumWindows(EnumWindowsProc(enum_callback), 0)
        except Exception:
            pass

    def _init_playwright(self):
        """初始化 Playwright headed 浏览器（用于绕过 Cloudflare）。"""
        if self._pw_browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
            before_pids = self._get_chrome_pids()
            self._pw = sync_playwright().start()
            # 必须用 headed 模式，headless 会被 Cloudflare 检测
            # 窗口移出屏幕 + 启动后通过 WinAPI 隐藏，确保任务栏无图标
            self._pw_browser = self._pw.chromium.launch(
                headless=False,
                args=["--window-position=-10000,-10000"]
            )
            state_file = "linux-do-state.json"
            if os.path.exists(state_file):
                self._pw_context = self._pw_browser.new_context(storage_state=state_file)
            else:
                self._pw_context = self._pw_browser.new_context()
            self._pw_page = self._pw_context.new_page()
            # 等待窗口创建完成后隐藏
            time.sleep(0.5)
            after_pids = self._get_chrome_pids()
            self._hide_browser_windows(after_pids - before_pids)
            logger.info("Playwright headed browser initialized for Cloudflare bypass.")
        except Exception as e:
            logger.error(f"Failed to init Playwright: {e}")

    def _playwright_get(self, url: str) -> Optional[str]:
        """通过 Playwright 浏览器获取页面文本（JSON 响应会作为 body text 返回）。"""
        if self._pw_browser is None:
            self._init_playwright()
        if self._pw_page is None:
            return None
        try:
            self._pw_page.goto(url, wait_until="domcontentloaded", timeout=30000)
            text = self._pw_page.evaluate("() => document.body.innerText")
            return text
        except Exception as e:
            logger.error(f"Playwright request failed: {url} | {e}")
            return None

    def _get(self, endpoint: str, params: Optional[dict] = None, json_resp: bool = True) -> Optional[Any]:
        url = urljoin(self.base_url + "/", endpoint.lstrip("/"))
        query = ""
        if params:
            query = "?" + requests.compat.urlencode(params)
        full_url = url + query

        # 若已确认 Playwright 模式，直接走浏览器
        if self._use_playwright:
            text = self._playwright_get(full_url)
            if text is not None:
                self._sleep()
                if json_resp:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        logger.error(f"Playwright returned non-JSON: {text[:200]}")
                        return None
                return text
            return None

        # 先尝试 requests
        try:
            resp = self.session.get(url, params=params or {}, timeout=30)
            resp.raise_for_status()
            self._sleep()
            if json_resp:
                return resp.json()
            return resp.text
        except requests.RequestException as e:
            logger.warning(f"requests failed: {full_url} | {e}")

        # requests 失败时，尝试 Playwright 后备（仅一次）
        if not self._use_playwright:
            self._init_playwright()
            text = self._playwright_get(full_url)
            if text is not None:
                logger.info("Playwright fallback succeeded, switching to Playwright mode.")
                self._use_playwright = True
                if json_resp:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        logger.error(f"Playwright returned non-JSON: {text[:200]}")
                        return None
                return text
        return None

    def _check_api_available(self) -> bool:
        """探测 JSON API 是否可用（requests -> Playwright）。"""
        data = self._get("/latest.json", params={"page": 0, "per_page": 5})
        if data is not None and "topic_list" in data:
            return True
        # requests 失败，尝试 Playwright 探测
        self._init_playwright()
        text = self._playwright_get(urljoin(self.base_url, "/latest.json?page=0&per_page=5"))
        if text:
            try:
                data = json.loads(text)
                if "topic_list" in data:
                    logger.info("JSON API accessible via Playwright headed browser.")
                    self._use_playwright = True
                    return True
            except json.JSONDecodeError:
                pass
        return False

    def _is_backfill_needed(self) -> bool:
        """判断是否需要回填（超过正常轮询间隔 2 倍视为需要）。"""
        last = self.state.get("last_fetch_time")
        if not last:
            return True
        last_dt = datetime.fromisoformat(last)
        interval = self.config["fetch"]["interval_minutes"]
        elapsed_minutes = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
        return elapsed_minutes > interval * 2

    def _ask_backfill_limit(self, current_page: int) -> int:
        """交互式询问用户需要追加多少页。返回新的最大允许页数。"""
        print(f"\n[!] 回填已进行 {current_page} 页，仍未追上上次已知内容。")
        print(f"    安全限制为 {self.safe_limit} 页，可能已遗漏较早期的帖子。")
        try:
            extra = input(
                f"    请输入额外追溯页数（直接回车 = 停止在 {current_page} 页）："
            ).strip()
            if extra == "":
                return current_page
            return current_page + int(extra)
        except (EOFError, KeyboardInterrupt, ValueError):
            logger.info("用户取消交互，使用当前已抓取页数。")
            return current_page

    # ---------- JSON API 模式 ----------

    def fetch_latest_topics(self, page: int = 0) -> List[Dict[str, Any]]:
        """获取最新帖子列表（JSON API）。"""
        data = self._get("/latest.json", params={"page": page, "per_page": self.page_size})
        if not data or "topic_list" not in data:
            return []
        return data["topic_list"].get("topics", [])

    def fetch_topic_detail(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """获取单帖详情（JSON API）。"""
        return self._get(f"/t/{topic_id}.json")

    def fetch_user_activity(self, username: str) -> List[Dict[str, Any]]:
        """获取指定用户的最近帖子（JSON API）。"""
        data = self._get(f"/topics/created-by/{username}.json")
        if not data or "topic_list" not in data:
            return []
        return data["topic_list"].get("topics", [])

    def fetch_categories(self) -> List[Dict[str, Any]]:
        """获取分类列表（JSON API）。"""
        data = self._get("/categories.json")
        if not data or "category_list" not in data:
            return []
        return data["category_list"].get("categories", [])

    def fetch_tag_json(self, tag_slug: str, page: int = 0) -> List[Dict[str, Any]]:
        """获取指定标签下的最新帖子（JSON API）。"""
        data = self._get(f"/tag/{tag_slug}.json", params={"page": page})
        if not data or "topic_list" not in data:
            return []
        return data["topic_list"].get("topics", [])

    # ---------- RSS 模式 ----------

    def _fetch_rss_page(self, page: int = 0) -> List[Dict[str, Any]]:
        """获取 RSS 单页并解析为统一 topic 格式。"""
        xml_text = self._get("/latest.rss", params={"page": page}, json_resp=False)
        if not xml_text:
            return []
        return self._parse_rss(xml_text)

    def _parse_rss(self, xml_text: str) -> List[Dict[str, Any]]:
        """解析 RSS XML，返回与 JSON API 结构兼容的 topic 列表。"""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"RSS parse error: {e}")
            return []

        ns = {
            'dc': 'http://purl.org/dc/elements/1.1/',
            'discourse': 'http://www.discourse.org/',
        }
        items = []
        for item in root.findall('.//item'):
            title = item.findtext('title', default='') or ''
            link = item.findtext('link', default='') or ''
            creator = item.findtext('dc:creator', default='', namespaces=ns) or ''
            category = item.findtext('category', default='') or ''
            pub_date = item.findtext('pubDate', default='') or ''
            description = item.findtext('description', default='') or ''

            # 提取 topic ID: https://linux.do/t/topic/2112366
            tid = 0
            if link:
                parts = link.rstrip('/').split('/')
                if parts and parts[-1].isdigit():
                    tid = int(parts[-1])

            # 解析回复数（description 底部小字）
            replies_count = 0
            m = re.search(r'(\d+)\s*个帖子', description)
            if m:
                total_posts = int(m.group(1))
                replies_count = max(0, total_posts - 1)

            # 转换日期为 ISO 格式
            created_at = bumped_at = ''
            try:
                dt = date_parser.parse(pub_date)
                dt_utc = dt.astimezone(timezone.utc)
                created_at = bumped_at = dt_utc.isoformat()
            except Exception:
                pass

            # 从 description HTML 中提取标签（去重保序）
            tags = []
            seen_tags = set()
            for tag_m in re.finditer(r'data-type="tag"\s+data-slug="([^"]+)"', description):
                slug = tag_m.group(1)
                if slug not in seen_tags:
                    seen_tags.add(slug)
                    tags.append(slug)

            # 清理 description：移除底部统计和"阅读完整话题"链接
            clean_desc = description
            footer_match = re.search(
                r'<p><small>.*?</small></p>\s*<p><a href=".*?">阅读完整话题</a></p>',
                description, re.S
            )
            if footer_match:
                clean_desc = description[:footer_match.start()]

            items.append({
                "id": tid,
                "title": title,
                "slug": "topic",
                "created_at": created_at,
                "bumped_at": bumped_at,
                "last_poster_username": creator,
                "poster_usernames": [creator] if creator else [],
                "category_id": category,      # RSS 下用名称代替数字 ID
                "category_name": category,
                "tags": tags,
                "posts_count": replies_count + 1,
                "replies_count": replies_count,
                "views": 0,
                "source": link,
                "_description": clean_desc.strip(),
                "_is_rss": True,
            })
        return items

    def fetch_tag_rss(self, tag_slug: str, page: int = 0) -> List[Dict[str, Any]]:
        """获取指定标签的 RSS 帖子列表。"""
        xml_text = self._get(f"/tag/{tag_slug}.rss", params={"page": page}, json_resp=False)
        if not xml_text:
            return []
        return self._parse_rss(xml_text)

    def fetch_user_activity_rss(self, username: str, page: int = 0) -> List[Dict[str, Any]]:
        """获取指定用户的 activity RSS（包含话题和回复）。"""
        xml_text = self._get(f"/u/{username}/activity.rss", params={"page": page}, json_resp=False)
        if not xml_text:
            return []
        return self._parse_activity_rss(xml_text, username)

    def _parse_activity_rss(self, xml_text: str, username: str) -> List[Dict[str, Any]]:
        """解析用户 activity RSS，返回包含回复内容的条目列表。"""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"Activity RSS parse error for {username}: {e}")
            return []

        ns = {'dc': 'http://purl.org/dc/elements/1.1/'}
        items = []
        for item in root.findall('.//item'):
            title = item.findtext('title', default='') or ''
            link = item.findtext('link', default='') or ''
            creator = item.findtext('dc:creator', default='', namespaces=ns) or ''
            pub_date = item.findtext('pubDate', default='') or ''
            description = item.findtext('description', default='') or ''
            guid = item.findtext('guid', default='') or ''

            # 提取 topic_id 和 post_number
            # link: https://linux.do/t/topic/1381609/266
            topic_id = 0
            post_number = 1
            if link:
                parts = link.rstrip('/').split('/')
                if len(parts) >= 2 and parts[-2].isdigit():
                    topic_id = int(parts[-2])
                    if parts[-1].isdigit():
                        post_number = int(parts[-1])
                elif parts and parts[-1].isdigit():
                    topic_id = int(parts[-1])

            # 提取 post_id: linux.do-post-17268542
            post_id = 0
            m = re.search(r'linux\.do-post-(\d+)', guid)
            if m:
                post_id = int(m.group(1))

            created_at = bumped_at = ''
            try:
                dt = date_parser.parse(pub_date)
                dt_utc = dt.astimezone(timezone.utc)
                created_at = bumped_at = dt_utc.isoformat()
            except Exception:
                pass

            items.append({
                "id": topic_id,
                "title": title,
                "post_id": post_id,
                "post_number": post_number,
                "created_at": created_at,
                "bumped_at": bumped_at,
                "last_poster_username": creator or username,
                "poster_usernames": [creator or username],
                "category_id": "",
                "category_name": "",
                "tags": [],
                "posts_count": 1,
                "replies_count": 0,
                "views": 0,
                "source": link,
                "_description": description.strip(),
                "_is_rss": True,
                "_is_reply": post_number > 1,
            })
        return items

    # ---------- 统一入口 ----------

    def run(self, interactive: bool = False) -> Tuple[List[Dict[str, Any]], bool]:
        """
        执行一次抓取任务。
        interactive: 是否允许命令行交互询问（后台服务应传 False）。
        返回: (topics列表, 是否是回填模式)
        """
        is_backfill = self._is_backfill_needed()
        # 增量模式加速（0.2 倍延迟），回填模式保持正常（1.0 倍）
        self._delay_factor = 1.0 if is_backfill else 0.2
        logger.info(f"Delay factor set to {self._delay_factor} (backfill={is_backfill})")
        all_topics: List[Dict[str, Any]] = []
        seen_ids = set(self.state.get("known_topic_ids", []))
        max_id = self.state.get("last_topic_id", 0)

        page = 0
        max_pages = self.safe_limit if is_backfill else 1
        asked_user = False

        while page < max_pages:
            logger.info(f"Fetching page {page} (backfill={is_backfill}, rss={self._use_rss})...")

            if self._use_rss:
                topics = self._fetch_rss_page(page=page)
            else:
                topics = self.fetch_latest_topics(page=page)

            if not topics:
                logger.warning(f"Page {page} returned empty, stopping.")
                break

            new_count = 0
            for t in topics:
                tid = t.get("id", 0)
                if tid and tid not in seen_ids:
                    all_topics.append(t)
                    seen_ids.add(tid)
                    new_count += 1
                if tid > max_id:
                    max_id = tid

            logger.info(f"Page {page}: {len(topics)} topics, {new_count} new.")

            # 非回填模式下，如果整页都是已知的，说明没有新内容，停止
            if not is_backfill and new_count == 0:
                break

            # 回填模式下，如果整页都是已知的，说明已经追上了，停止
            if is_backfill and new_count == 0:
                logger.info("Backfill caught up with known topics.")
                break

            page += 1

            # 安全阀：达到安全限制仍未追上
            if is_backfill and page >= self.safe_limit and not asked_user:
                if interactive and self.confirm:
                    max_pages = self._ask_backfill_limit(page)
                    asked_user = True
                    if max_pages <= page:
                        logger.warning("User chose to stop backfill early. Some topics may be missed.")
                        break
                else:
                    logger.warning(
                        f"Backfill reached safe limit ({self.safe_limit} pages) without catching up. "
                        f"Run with '--once' or increase backfill_safe_limit in config.yaml to retrieve older topics."
                    )
                    break

        # ---------- 抓取配置的额外标签 feed ----------
        following_tags = self.config.get("following_tags", [])
        if following_tags:
            tag_max_pages = self.safe_limit if is_backfill else 3
            for tag in following_tags:
                tag_page = 0
                while tag_page < tag_max_pages:
                    logger.info(f"Fetching tag '{tag}' page {tag_page}...")
                    if self._use_rss:
                        tag_topics = self.fetch_tag_rss(tag, page=tag_page)
                    else:
                        tag_topics = self.fetch_tag_json(tag, page=tag_page)
                    if not tag_topics:
                        break
                    new_count = 0
                    for t in tag_topics:
                        tid = t.get("id", 0)
                        if tid and tid not in seen_ids:
                            all_topics.append(t)
                            seen_ids.add(tid)
                            new_count += 1
                        if tid > max_id:
                            max_id = tid
                    logger.info(f"Tag '{tag}' page {tag_page}: {len(tag_topics)} topics, {new_count} new.")
                    if new_count == 0:
                        break
                    tag_page += 1

        # 更新状态
        self.state["last_fetch_time"] = datetime.now(timezone.utc).isoformat()
        self.state["last_topic_id"] = max_id
        self.state["known_topic_ids"] = list(seen_ids)
        self._save_state()

        logger.info(f"Fetch complete. Total new topics: {len(all_topics)}, backfill={is_backfill}, rss={self._use_rss}, pw={self._use_playwright}")
        return all_topics, is_backfill

    def close(self):
        """关闭 Playwright 浏览器进程。"""
        if self._pw_browser:
            try:
                self._pw_browser.close()
            except Exception as e:
                logger.warning(f"Browser close error: {e}")
        if self._pw:
            try:
                self._pw.stop()
            except Exception as e:
                logger.warning(f"Playwright stop error: {e}")


if __name__ == "__main__":
    fetcher = LinuxDoFetcher()
    topics, backfill = fetcher.run(interactive=True)
    print(f"Fetched {len(topics)} topics. Backfill mode: {backfill}")
