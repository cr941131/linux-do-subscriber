# 初始化：Agent-first 文档体系

## 状态

✅ completed

## 目标

为 Linux.do 订阅器项目建立面向 AI Agent 的文档体系，确保跨会话协作有统一的事实源。

## 执行步骤

1. 分析项目画像（技术栈、硬约束、已有文档）
2. 创建 AGENTS.md（硬约束 + 默认偏好 + 完工检查清单）
3. 复制 scripts/changelog.py 与 scripts/agent_links.py
4. 同步 CLAUDE.md / GEMINI.md（copy 模式，Windows 硬链接不稳定）
5. 创建 STRUCTURE.md（文档索引）
6. 创建 docs/ 层级：CURRENT.md、overview.md、deployment.md、pitfalls.md
7. 创建 CHANGELOG.md（初始化条目）
8. 建立 docs/plans/active/ 与 docs/plans/completed/ 目录
9. 迁移原 CLAUDE.md 内容至 docs/overview.md、docs/deployment.md、docs/pitfalls.md
10. 配置 .githooks/pre-commit（AGENTS.md 同步检查）
11. 静态自检与 reviewer 视角测试

## 关键决策

- **Copy 模式**：Windows 环境硬链接支持不稳定，采用 copy 模式同步三文件。
- **不建 api.md**：项目为只读 Web UI，无对外 API，故省略 api.md。
- **不保留旧 CLAUDE.md**：内容已拆分迁移至 docs/，旧文件由 AGENTS.md 取代。

## 出生档案（第 0 步 intent 结果）

1. **项目做什么**：本地订阅器，抓取 https://linux.do 内容，保存为分类 Markdown，提供只读 Web UI。
2. **技术栈**：Python 3.11 + Flask + Jinja2，Schedule 定时，GitPython 快照，RSS/Playwright 双模式抓取。
3. **硬约束**：不碰 `data/` 和 `python/`（生成物）；Playwright 必须用 headed；Windows UTF-8；不绕过 hook。
4. **已有文档**：原 CLAUDE.md 有项目概述，需迁移。
5. **使用 Agent**：Claude Code、可能 future 使用 Gemini CLI。
6. **构建产物**：`data/`（独立 Git 仓库）、`python/`（嵌入式环境）。
7. **自动化测试**：无测试套件，改动后手动验证 Web 服务和抓取脚本。
8. **默认协作倾向**：单 Agent 顺序推进，小修改直接执行，复杂任务建计划。
9. **常见任务类型**：小修改（UI、过滤逻辑）和中等复杂度功能迭代。
10. **文档语言**：中文。

## 完成记录

- 2026-05-06：所有文件创建完毕，agent_links.py / changelog.py 工作正常，pre-commit hook 配置完成。
- Reviewer 视角测试：新上下文仅读 AGENTS.md 后，能正确回答"项目做什么、不能改哪些文件、任务完成要做什么、复杂任务先去哪里"。
