# 部署与环境配置

> 记录部署方式、环境差异和启动约定。
> 修改本文件后同步更新 [CHANGELOG.md](../CHANGELOG.md)。

## 环境变量

本项目以 `config.yaml` 为主要配置源，环境变量仅做辅助：

| 变量 | 用途 | 必填 | 备注 |
|------|------|------|------|
| `PYTHONIOENCODING` | 强制 UTF-8 输出 | ❌ | Windows BAT 脚本已默认设置为 `utf-8` |
| `PYTHONUTF8` | 强制 Python UTF-8 模式 | ❌ | 推荐在旧版 Windows 终端设置 |

## 启动方式

### 开发环境
```bash
# 单次抓取（交互式回填）
python main.py --once

# 仅启动 Web 服务
python main.py --web-only

# 默认：Web + 定时调度
python main.py
```

Windows 用户也可使用提供的 BAT 脚本：
- `scripts/run-once.bat` — 单次抓取
- `scripts/run-web.bat` — 仅启动 Web
- `scripts/run-full.bat` — Web + 定时调度

### 嵌入式 Python（无系统 Python 环境）
```powershell
scripts/setup-embed.ps1   # 初始化嵌入式环境
```

## Git 与 GitHub

### SSH 推送（Port 22 被拦截时）
若直接 `git push` 报错 `Connection closed`（Port 22 被防火墙拦截），可配置 SSH 走 HTTPS 端口：

```
# ~/.ssh/config
Host github.com
    Hostname ssh.github.com
    Port 443
    User git
    IdentityFile ~/.ssh/id_ed25519
    StrictHostKeyChecking accept-new
```

生成 key：`ssh-keygen -t ed25519 -C "备注"`，将公钥添加到 GitHub Settings → SSH keys。

## 持久化与备份

- `data/` 目录是独立的 Git 仓库，包含所有抓取内容。
- 备份只需复制 `data/` 目录或对其执行 `git clone`。
- `search-history.json`、`tag-stats.json`、`linux-do-state.json`、`linux-do-tags.json` 位于项目根目录，不纳入版本控制，丢失后可重建。
- `category-map.json` 由 Playwright 从 Discourse `/site.json` 自动生成，用于将 `category_id` 映射为中文分类名，不纳入版本控制也可重建。

## 部署陷阱

- **Windows 硬链接**：项目使用 copy 模式同步 `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`，因为 Windows 硬链接支持不稳定。
- **Playwright 状态文件**：`linux-do-state.json` 保存浏览器登录状态，若删除则 Playwright fallback 可能因未登录而被 Cloudflare 拦截。
