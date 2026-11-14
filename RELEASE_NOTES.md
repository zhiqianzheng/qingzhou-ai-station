Linux / Windows 首个跨平台预览版本。

- 新增轻舟帆船图标，包含 SVG、PNG 和 Windows ICO。
- ChatGPT 浏览器授权、服务启停、URL / Key 复制、连接测试及网络代理。
- 可选 Tailscale 公网安装和登录向导。
- 新增默认关闭的本机对话记录：普通文本、SSE、Responses WebSocket；最近 500 次请求，支持查看与清空。
- 记录仅保存对话文字和 Key 指纹，不打包账号、密钥或用户数据。

Linux：选择 `.deb` 安装包或 `.tar.gz` 便携包。
Windows：选择 `-setup.exe` 安装包或 `.zip` 便携包，均已包含 Python 运行时。

开启记录前请先告知使用者并取得同意。共用同一个 Key 无法区分具体使用者。
Windows 在原生 runner 完成构建、自动测试和启动检查，首次账号登录与公网授权需要在实际电脑验收。
