# CHANGELOG

## 2026-05-06

### 初始化文档体系

- 创建 agent-first 文档结构：AGENTS.md（含 copy 同步 CLAUDE.md / GEMINI.md）+ STRUCTURE.md + docs/ 层级
- 配置 scripts/changelog.py 与 scripts/agent_links.py，脚本化维护日志和硬链接
- 迁移原 CLAUDE.md 中的项目概述、部署说明、环境陷阱至 docs/overview.md、docs/deployment.md、docs/pitfalls.md
- 设计哲学：仓库即事实源，只记代码读不出来的东西，计划作为跨上下文交接协议

<!--
说明：
- 日期节倒序，最新在前。同一天的多次修改合并到同一个日期节，用 ### 区分主题。
- 写入前不要读全文，用 `python scripts/changelog.py titles/show/add` 查看标题树、局部读取和追加。
- 当前工作状态写在 docs/CURRENT.md；CHANGELOG 只记录历史变更。
-->

### 完善 Agent 协作触发机制

#### 变更内容
- AGENTS.md 默认偏好中新增两条规则：1) 任务启动时先读 CURRENT.md，确认是否有未完成的上下文；2) 明确复杂任务的判定标准（跨模块、超 5 个文件、跨会话），单会话小任务不必建计划。同步更新 docs/ 使用边界中的计划规则描述。

### fix: 修复 Discourse HTML 转 Markdown 标题与列表项格式错误

#### 变更内容
- 修复 _cooked_to_md() 中 h 标签未提前处理、空锚点未清理、li/p 处理顺序错误的问题；新增 fix_markdown.py 批量修复存量数据。共修复 72 个文件、537 处格式错误。

### feat: 点击红点可查看更新内容下拉面板

#### 变更内容
- 新增 /api/red-dot/items 接口与 red-dot-dropdown 前端面板。点击红点展示最近更新帖子列表（标题、分类、相对时间），查看后仍标记已读。支持关闭按钮、点击外部关闭、列表项跳转。

### fix: 修复 tag 为 dict 类型时 _update_tag_stats 崩溃

#### 变更内容
- Discourse API 返回的 tags 有时是 dict 列表（含 name/slug），原代码直接用 dict 作 dict 键导致 TypeError: unhashable type: 'dict'。现提取 name 或 slug 作为字符串键。

### fix: 修复 tags 为 dict 列表时多处崩溃

#### 变更内容
- web/app.py 的 all_tags.add、filter_engine.py 的 set() 交集与 .lower() 搜索均因 tag 为 dict 而崩溃。统一提取 name/slug 作字符串键。

### chore: 重命名数字分类目录为中文名

#### 变更内容
- 将 category_id 作为目录名的历史数据迁移到中文分类名：11→搞七捻三、2→运营反馈、4→开发调优。

### feat: Playwright 浏览器窗口彻底隐藏（任务栏无图标）

#### 变更内容
- 启动后通过 EnumWindows + GetWindowThreadProcessId + ShowWindow(SW_HIDE) 精确隐藏当前新启动的 Chromium 窗口，避免与用户已有 Chrome 冲突。

### feat: 彻底修复数字分类目录问题

#### 变更内容
- 新增 category-map.json 维护 id→名称映射，main.py 保存帖子时优先查表。迁移全部剩余数字目录（11/14/27/34/4/94）。
