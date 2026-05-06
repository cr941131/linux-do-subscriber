# 系统设计概览

> 记录系统级设计决策和架构选型理由。只写"为什么这样设计"，不写代码能直接看到的"是什么"。
> 修改本文件后同步更新 [CHANGELOG.md](../CHANGELOG.md)。

## 系统定位

本地订阅器，定期抓取 https://linux.do 内容，保存为分类 Markdown 文件，带 Git 版本管理，提供只读 Web UI。

## 架构主线

抓取器（RSS / Playwright 回退）→ Markdown 文件存储（按分类目录组织）→ Git 自动提交（`data/` 独立仓库）→ Flask Web UI 读取并展示。

关键不变量：
- `data/` 是独立 Git 仓库，每次抓取后自动 commit，确保历史可追溯。
- 所有帖子以 Markdown + YAML frontmatter 形式持久化，不依赖外部数据库。
- Web UI 为只读，不修改数据目录。

## 关键设计决策

### 为什么用 RSS 为主、Playwright 为辅
- **场景**：当前环境访问 Discourse JSON API 返回 403（Cloudflare 拦截）。
- **备选**：持续对抗 Cloudflare 的 bot 检测；或使用代理/VPS。
- **选择**：RSS 模式作为默认路径（`/latest.rss`、`/tag/{slug}.rss`），每页 30 条足够增量更新；Playwright 仅在需要 JSON API 详细字段时作为 fallback，且必须用 headed 模式（Cloudflare 能检测 headless）。
- **取舍**：RSS 字段比 JSON API 少（如 view_count 可能不准确），但稳定性高；Playwright 启动慢、资源占用高，不适合高频调用。

### 为什么用文件系统 + Git 而不是数据库
- **场景**：单机部署、数据量预期不大（文本为主）、需要离线浏览和历史回溯。
- **备选**：SQLite（查询快）、PostgreSQL（并发好）。
- **选择**：Markdown 文件按 `categories/{slug}/{topic_id}-{slug}.md` 组织，配合 Git 版本管理。零运维、可直接用任意文本编辑器查看、git blame 可追溯单帖历史。
- **取舍**：放弃了复杂查询和全文检索性能；当前通过内存索引 + Python 过滤补偿，数据量增大后可引入 SQLite 做二级索引。

### 为什么 Web UI 不做写入
- 项目定位是"订阅器"而非"客户端"，所有内容变更来自抓取端。
- 只读 UI 大幅降低状态管理和并发冲突风险。

## 不在这里记的内容

- 目录结构 → `ls` / `tree`
- 函数签名、参数默认值 → 源码
- 部署与环境变量 → [docs/deployment.md](deployment.md)
- 已知环境陷阱 → [docs/pitfalls.md](pitfalls.md)
