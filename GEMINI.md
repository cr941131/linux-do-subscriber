# AI 协作规范

> 本文件会被 AI 框架自动加载并始终驻留在上下文中，因此必须保持精简。
> 只放行为规则和信息指针，不放可从代码或其他文档获取的事实描述。

## 硬链接声明

`AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 内容必须保持一致；读取时选择其一即可。**只编辑 AGENTS.md**，另两个由脚本同步。

- 检查：`python scripts/agent_links.py check --verbose`
- 修复：`python scripts/agent_links.py repair`
- 强制覆盖：`python scripts/agent_links.py repair --force`

本项目使用 copy 模式（Windows 环境硬链接支持不稳定）。

## 信息导航

- 文档总索引：[STRUCTURE.md](STRUCTURE.md)
- 系统主线与设计决策：[docs/overview.md](docs/overview.md)
- 部署与同步：[docs/deployment.md](docs/deployment.md)
- 环境陷阱：[docs/pitfalls.md](docs/pitfalls.md)
- 复杂任务计划：[docs/plans/](docs/plans/)
- 当前任务状态：[docs/CURRENT.md](docs/CURRENT.md)
- 变更记录：[CHANGELOG.md](CHANGELOG.md)

## 行为规则

### 硬约束（不可违反）
- **不碰构建产物**：`data/`（独立 Git 仓库）、`python/`（嵌入式环境）属于生成物，除非任务明确要求，否则不要修改。
- **Playwright 必须用 headed 模式**：headless 会被 Cloudflare 检测并返回空内容；绕过 JSON API 403 依赖 `linux-do-state.json` 中的登录状态。
- **Windows 编码**：所有 BAT 脚本和 Python 文件需保证 UTF-8；读写文件显式指定 `encoding='utf-8'`。
- **不绕过 hook**：项目启用了 `.githooks/pre-commit` 时，lint 失败先修复再提交，不要用 `--no-verify` 跳过。
- **完工必检**：任务完成后必须执行末尾的"完工检查清单"，不可跳过，不可先回复用户再补。

### 默认偏好（有充分理由可偏离）
- **先读后改**：修改任何文件前先读取，理解现有逻辑再动手。
- **风格跟随**：Python `snake_case`，4 空格缩进；Flask 路由和 Jinja2 模板跟随已有风格。
- **Occam**：如无必要，勿增实体；新增文件、字段、脚本、规则或流程前，先确认它解决的具体问题。
- **Bitter Lesson**：通用方法优于硬编码先验；优先复用模型能力、语义检索、结构化工具和默认流程。
- **模式匹配复杂度**：单会话能完成的小任务用直接执行模式；涉及跨模块、预计改动超过 5 个文件、或可能跨会话完成的任务，先在 `docs/plans/active/` 建计划。
- **任务启动先读 CURRENT.md**：接到新任务时，先读取 `docs/CURRENT.md`。若存在未完成的上下文（任务状态非"无"），向用户确认是继续还是覆盖。
- **验证尽量换视角**：高风险改动优先由新上下文或 reviewer 视角复查。

## 测试要求

无自动化测试套件。改动后至少验证：
- Web 服务能启动（`python main.py --web-only` 或访问 `http://127.0.0.1:5000`）
- 前端改动在浏览器确认无白屏、无控制台报错
- 抓取脚本能运行（`python main.py --once`）

## 提交规范

使用 Conventional Commit 风格：`feat:` / `fix:` / `chore:` 等。PR 需说明影响范围。

**及时提交**：完成一个功能阶段后主动暂存源码文件并提交，避免 diff 膨胀导致上下文压力。排除二进制生成物。

## 文档维护原则

**核心理念：只记代码里读不出来的东西。** 目录结构、模块职责、技术栈、函数签名等可从代码直接获取的内容不写入文档。文档只记设计原因、协作约束和不能从代码推导的信息。

1. **不重复**：同一信息只在最合适的位置出现一次。
2. **不展开实现细节**：CSS 断点、具体字段列表等可从代码直接获取的内容，一句话概括 + 指向源文件即可。
3. **可从代码/git 推导的不写**：文件路径、函数签名、参数默认值等会随代码变化的细节，优先让读者查看源码，文档只记"为什么这样设计"。

**`docs/` 的使用边界**

4. 新增设计决策写入 [docs/overview.md](docs/overview.md)；部署或环境约束更新 [docs/deployment.md](docs/deployment.md)；环境陷阱写入 [docs/pitfalls.md](docs/pitfalls.md)。
5. 先更新对应 `docs/*.md`，再写 [CHANGELOG.md](CHANGELOG.md)。CHANGELOG 只记变更摘要，不重复架构文档正文。
6. 单个架构文档接近 300 行时按主题拆分，并在 [STRUCTURE.md](STRUCTURE.md) 里补索引。
7. 涉及跨模块、预计改动超过 5 个文件、或可能跨会话完成的任务，先在 `docs/plans/active/` 落一份轻量计划，再开始实施；完成后移到 `docs/plans/completed/`。单会话能完成的小任务不必建计划。

**CHANGELOG 规则**

8. 日期节倒序排列，最新在前；同一天的多次修改合并到同一个日期节，用 `###` 区分主题。
9. 写入 [CHANGELOG.md](CHANGELOG.md) 前**不要读全文**；使用 `python scripts/changelog.py titles --limit 5` 查看标题树，`python scripts/changelog.py show --date YYYY-MM-DD` 或 `--match 关键词` 读取局部内容，`python scripts/changelog.py add --title "..." --body "..."` 追加条目。
10. 当前任务状态写入 [docs/CURRENT.md](docs/CURRENT.md)，不要写进 CHANGELOG。
11. 只写"改了什么、为什么改、有什么迁移影响"，不贴代码，不重复 `docs/` 中已经存在的设计说明。

## 完工检查清单（硬约束）

文档是跨会话协作的唯一记忆。代码改了但文档没跟上，下一次对话会基于过时信息做决策，产生连锁错误。**每次编辑任务完成后，必须逐项走完以下清单，再向用户报告完成。**

- [ ] **验证**：改动涉及的功能是否仍能正常工作？前端改动至少在浏览器确认无白屏/控制台无报错；后端改动至少确认服务能启动。
- [ ] **复查视角**：如果这是高风险或跨模块任务，是否至少经过一次新的 reviewer 视角复查（新上下文窗口优先）？没有做到时，在计划或回复中明确说明。
- [ ] **架构文档（docs/）**：是否涉及架构变更（新模块、新接口、流程变化、新配置、端口/环境变化）？如是，更新 `docs/` 下对应文件。
- [ ] **CHANGELOG.md**：是否值得记录？如是，用 `python scripts/changelog.py add ...` 插入到当天日期节。
- [ ] **硬链接**：本文件若被编辑，运行 `python scripts/agent_links.py check --verbose`；只有断开时才用 `python scripts/agent_links.py repair` 重建。
- [ ] **跳过条件**：纯格式修改、注释修改、同一会话内已记录的变更，可跳过文档更新步骤（但验证步骤不可跳过）。
