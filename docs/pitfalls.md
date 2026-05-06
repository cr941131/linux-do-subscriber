# 已知环境陷阱

> 记录开发和部署中遇到的坑。每条记录包括：现象、原因、解决方案。
> 修改本文件后同步更新 [CHANGELOG.md](../CHANGELOG.md)。

## UTF-8 编码

### 文件编码
**现象**：中文注释或字符串在某些环境下显示为乱码，或读取文件时抛出 UnicodeDecodeError / GBK codec 错误。
**原因**：Windows 默认使用 GBK/CP936 编码，而非 UTF-8。新建文件可能继承系统默认编码。
**解决**：
- 所有源码文件和文档统一使用 UTF-8（无 BOM）编码
- Python 读写文件时显式指定 `encoding='utf-8'`，不依赖系统默认编码
- 在 `.editorconfig` 中设置 `charset = utf-8`（如项目使用 EditorConfig）
- VS Code 用户在 settings.json 中设置 `"files.encoding": "utf-8"`

### 终端与 Shell
**现象**：脚本输出中文时终端显示乱码，或 `print()` 抛出编码错误。
**原因**：终端代码页不是 UTF-8（Windows 默认 CP936）。
**解决**：
- Windows Terminal 默认已支持 UTF-8，推荐使用
- 旧版 cmd 可执行 `chcp 65001` 切换到 UTF-8 代码页
- Python 脚本开头可设置 `PYTHONUTF8=1` 环境变量强制 UTF-8 模式

## Cloudflare 与抓取

### JSON API 403
**现象**：直接请求 `/latest.json` 返回 403 Forbidden。
**原因**：Cloudflare bot 检测拦截了非浏览器请求。
**解决**：已自动回退到 RSS 模式；如需 JSON 字段，使用 Playwright headed 模式（`linux-do-state.json` 带登录状态）绕过检测。不要试图用 headless Playwright —— Cloudflare 能检测并返回空内容。

### 所有帖子保存到 uncategorized
**现象**：抓取后所有帖子都在 `data/categories/uncategorized/` 下。
**原因**：RSS 解析未正确读取 `category_name` 字段，或字段缺失。
**解决**：检查 `fetcher.py` 的 `_parse_rss` 是否正确提取了 `category_name`，并确认 `main.py` 将其传给了 `MarkdownStore.save_topic()`。

### 标签太少
**现象**：界面上几乎看不到标签。
**原因**：`/latest.rss` 每页只有 30 条，且很多帖子本身不带标签。
**解决**：在 `config.yaml` 的 `following_tags` 中配置关注的标签，系统会额外抓取对应标签的 RSS feed，从而积累更多标签数据。
