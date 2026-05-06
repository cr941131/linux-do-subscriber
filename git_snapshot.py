import os
import logging
import subprocess
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


class GitSnapshot:
    """管理 data 目录的 git 快照，保留每次抓取的 diff 历史。"""

    def __init__(self, repo_dir: str = "./data"):
        self.repo_dir = repo_dir
        self._ensure_repo()

    def _run(self, cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
        """在 repo_dir 中运行 git 命令。"""
        result = subprocess.run(
            cmd,
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if check and result.returncode != 0:
            logger.warning(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")
        return result

    def _ensure_repo(self):
        git_dir = os.path.join(self.repo_dir, ".git")
        if not os.path.exists(git_dir):
            logger.info("Initializing git repository in data/")
            self._run(["git", "init"], check=False)
            self._run(["git", "config", "user.email", "subscriber@linux.do.local"], check=False)
            self._run(["git", "config", "user.name", "LinuxDo Subscriber"], check=False)
            # 初始提交
            self._run(["git", "add", "."], check=False)
            self._run(["git", "commit", "-m", "Initial commit: empty data directory"], check=False)

    def commit_changes(self, message: Optional[str] = None) -> bool:
        """如果有变更则提交，返回是否实际发生了提交。"""
        # 检查是否有变更
        status_result = self._run(["git", "status", "--porcelain"], check=False)
        if not status_result.stdout.strip():
            logger.info("No changes to commit.")
            return False

        self._run(["git", "add", "."], check=False)
        msg = message or f"Snapshot at {datetime.now(timezone.utc).isoformat()}"
        commit_result = self._run(["git", "commit", "-m", msg], check=False)
        if commit_result.returncode == 0:
            logger.info(f"Git snapshot committed: {msg}")
            return True
        return False

    def get_history(self, filepath: str = "", max_count: int = 10) -> List[dict]:
        """获取某个文件的最近提交历史。"""
        args = ["git", "log", f"-{max_count}", "--pretty=format:%H|%ci|%s"]
        if filepath:
            args.append(filepath)
        result = self._run(args, check=False)
        history = []
        for line in result.stdout.strip().split("\n"):
            if "|" not in line:
                continue
            parts = line.split("|", 2)
            history.append({
                "hash": parts[0],
                "date": parts[1],
                "message": parts[2],
            })
        return history

    def diff_last(self, filepath: str) -> str:
        """获取文件最近一次提交的 diff。"""
        result = self._run(["git", "diff", "HEAD~1", "HEAD", "--", filepath], check=False)
        return result.stdout
