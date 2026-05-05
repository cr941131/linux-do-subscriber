#!/usr/bin/env python3
"""批量修复 data/ 目录下 Markdown 文件的格式问题。

修复内容：
1. `[](url#anchor)**text**` → `## text`（Discourse 标题被误解析为空链接+加粗）
2. `- \n\n**text**` → `- **text**`（空列表项后紧跟加粗文本）
"""

import os
import re
import sys


def fix_file(filepath: str) -> tuple:
    """修复单个文件，返回 (是否修改, 修复计数)."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    count = 0

    # 1. 修复标题：空链接 + 加粗 → Markdown 标题
    # 匹配 [](url#anchor)**text**
    heading_pattern = re.compile(
        r'^\[\]\([^)]+\)\*\*([^*\n]+)\*\*$',
        re.MULTILINE
    )

    def heading_repl(m):
        nonlocal count
        count += 1
        return f"## {m.group(1)}"

    content = heading_pattern.sub(heading_repl, content)

    # 2. 修复空列表项：`- `（仅含空白）后紧跟加粗文本
    # 匹配 `- ` 或 `-` 后面只有空白，然后空行，然后 `**text**`
    # 去掉末尾 $，允许 `**text**` 后面还跟有内容（如 `**优点**：...`）
    list_pattern = re.compile(
        r'^-\s*\n\n(\*\*[^*\n]+\*\*)',
        re.MULTILINE
    )

    def list_repl(m):
        nonlocal count
        count += 1
        return f"- {m.group(1)}"

    content = list_pattern.sub(list_repl, content)

    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True, count
    return False, 0


def main():
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    if not os.path.exists(data_dir):
        print(f"data/ 目录不存在: {data_dir}")
        sys.exit(1)

    fixed_files = 0
    total_fixes = 0

    for root, _, files in os.walk(data_dir):
        for fname in files:
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(root, fname)
            modified, fixes = fix_file(filepath)
            if modified:
                fixed_files += 1
                total_fixes += fixes
                print(f"  修复 {fixes} 处: {filepath}")

    print(f"\n总计: {fixed_files} 个文件, {total_fixes} 处修复")


if __name__ == "__main__":
    main()
