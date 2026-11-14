<p align="center"><img src="assets/icon.png" width="112" alt="轻舟图标"></p>
<h1 align="center">轻舟 AI 中转站 · Qingzhou AI Station</h1>
<p align="center">自己的账号 · 清晰的连接 · 本机掌控</p>

Linux / Windows 桌面 App，把 CLIProxyAPI 配置、ChatGPT 浏览器授权、API 连接信息和可选的本机对话记录放进一个界面。无需把账号密码交给 App。

## 下载

在本仓库的 **Releases** 页面下载 `v0.2.0` 预览版：

| 系统 | 文件 | 使用方式 |
| --- | --- | --- |
| Ubuntu / Debian x86_64 | `qingzhou-ai-station_0.2.0_amd64.deb` | 双击，通过系统软件安装器安装 |
| Linux x86_64 便携包 | `qingzhou-ai-station-0.2.0-linux-x64.tar.gz` | 解压后运行 `./install.sh` |
| Windows 10 / 11 x64 安装包 | `qingzhou-ai-station-0.2.0-windows-x64-setup.exe` | 双击，按向导安装 |
| Windows x64 便携包 | `qingzhou-ai-station-0.2.0-windows-x64.zip` | 完整解压文件夹，双击 `QingzhouAIStation.exe` |

Windows 包含 Python 运行时，不需要另装 Python。预览版未进行商业代码签名。Linux 安装包通过系统包管理器安装 Python / tkinter / aiohttp 依赖。

## 使用

1. 打开 App，点击「一键配置 / 启动」。
2. 点击「登录 ChatGPT」，在浏览器完成本人账号授权。
3. 点击「测试连接」。测试会消耗一次很短的模型调用。
4. 复制 Base URL 和 API Key 到需要连接的应用。
5. 需要从其他设备调用时，点击「开启公网」，按提示完成系统权限、Tailscale 设备登录和 Funnel 授权。公网功能是可选的。

不能连通上游时，可在「网络代理」填写可用的 HTTP / SOCKS5 代理地址。App 不会提供或搭建网络代理。

关闭窗口后服务继续运行。Linux 使用 systemd 用户服务，在用户登录后自动启动；Windows 使用本机后台进程，注销或重启后需重新打开 App 并点击启动。

## 对话记录

**默认关闭。请先告知使用者并取得同意，再点击「开启记录（已告知使用者）」。** 界面提供可复制的使用告知：

> 本中转站开启对话记录时，管理员可以查看并保存你发送的内容和 AI 回复。请勿发送不愿被管理员查看的信息。

- 保存通过本中转站的文本请求、客户端携带的历史上下文，以及 AI 的文本回复。
- 支持 Chat Completions、Responses、SSE 流式文本和 Responses WebSocket 文本。
- 默认只保留最近 500 次成功授权的请求，每次请求或回复最多约 2 MiB 字符/采集字节；超过上限会显示截断提示。
- API Key 仅显示 SHA-256 指纹，不保存请求头、OAuth 凭据、图片或音频。**同一个 Key 无法区分具体使用者**。
- 记录只保存在本机 SQLite 文件中，公网入口不提供历史查询接口。界面支持关闭记录、清空记录。
- 开启功能时自动把核心迁移到另一个本机端口，原本的 URL、API Key 和 Tailscale 公网地址保持可用。迁移期间服务会短暂重启。
- 客户端断开时可能只保留部分回复；未提取的工具调用、非文本内容不会显示。已有的上游错误日志策略独立于本功能。
- 关闭记录后已经保存的历史仍保留；清空记录用于删除历史。清空不是磁盘级取证擦除。

## 数据位置

| 内容 | Linux | Windows |
| --- | --- | --- |
| 核心配置 | `~/.config/cliproxyapi/config.yaml` | `%LOCALAPPDATA%\QingzhouAIStation\config.yaml` |
| 账号授权 | `~/.local/share/cliproxyapi/auth/` | `%LOCALAPPDATA%\QingzhouAIStation\auth\` |
| 记录与录制配置 | `~/.local/share/ai-station/` | `%LOCALAPPDATA%\QingzhouAIStation\` |

安装包与仓库均不包含使用者账号、API Key、OAuth 文件或聊天数据。请勿将上述目录提交到 Git。

## 本地开发与构建

Python 3.10+，Linux 需要 tkinter：

```bash
python -m pip install -r requirements.txt
python scripts/download_core.py
python -m unittest discover -p 'test_*.py'
python app.py
```

Linux：`bash build.sh`，生成 `.deb` 和便携 `.tar.gz`。

Windows：PowerShell 运行 `./scripts/build_windows.ps1`，使用 PyInstaller 和 Inno Setup 生成便携 `.zip` 与安装 `.exe`。构建脚本自动下载并校验固定版本的核心。

GitHub Actions 在发布 `v*` 标签时分别使用 Linux / Windows runner 测试和构建，通过后创建包含 SHA256 校验文件的预览 Release。

## 验证范围

Linux：本机 Ubuntu 桌面与现有真实上游连接验证；自动测试覆盖普通回复、SSE、WebSocket、未授权请求、关闭记录、清空记录与密钥不落盘。
Windows：原生 Windows runner 构建、自动测试及启动检查；实际用户的首次 OAuth 登录、系统权限提示和公网授权仍需在目标电脑验收。

## 上游与许可

- [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) 8.0.61，MIT 许可，见 `THIRD_PARTY_LICENSES.txt`。
- [aiohttp](https://docs.aiohttp.org/)，Apache-2.0 许可。
- 公网功能使用 [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel)，需本人完成相应账号和设备授权。
- 图标为本项目绘制的 SVG 帆船与连接节点，同时提供 PNG / ICO。

本项目与 OpenAI、CLIProxyAPI、Tailscale 无官方隶属关系。第三方软件与服务按各自许可和账号条件使用。
