#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ $(uname -m) != x86_64 ]]; then
  echo '此预览包适用于 x86_64 Linux。'; exit 1
fi
admin() {
  if [[ $(id -u) == 0 ]]; then "$@"
  elif command -v pkexec >/dev/null; then pkexec "$@"
  else sudo "$@"; fi
}
if ! /usr/bin/python3 -c 'import tkinter, aiohttp' 2>/dev/null; then
  if command -v apt-get >/dev/null; then
    admin apt-get update
    admin apt-get install -y python3 python3-tk python3-aiohttp
  else
    echo '请通过系统包管理器安装 Python 3 和 tkinter，再重新运行。'; exit 1
  fi
fi
app_dest="$HOME/.local/opt/ai-station"
core_dest="$HOME/.local/opt/cliproxyapi"
mkdir -p "$app_dest" "$core_dest" "$HOME/.local/share/applications" "$HOME/.local/bin"
install -m 755 app.py backend.py recorder.py "$app_dest/"
mkdir -p "$app_dest/assets"
install -m 644 assets/icon.png assets/icon.svg "$app_dest/assets/"
install -m 755 install-tailscale.sh "$app_dest/install-tailscale.sh"
if [[ ! -x "$core_dest/cli-proxy-api" ]]; then
  install -m 755 core/cli-proxy-api "$core_dest/cli-proxy-api"
fi
install -m 644 core/LICENSE "$app_dest/CLIProxyAPI-LICENSE"
cat > "$HOME/.local/bin/ai-station" <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 "$HOME/.local/opt/ai-station/app.py" "$@"
EOF
chmod 755 "$HOME/.local/bin/ai-station"
python3 - <<'PY'
from pathlib import Path
home=Path.home()
# Desktop Exec uses quoted paths rather than shell expansion.
exe=str(home/'.local/bin/ai-station').replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')
text=f'''[Desktop Entry]
Type=Application
Name=轻舟 AI 中转站
Comment=配置账号授权和 AI API 中转服务
Exec="{exe}"
Icon={home}/.local/opt/ai-station/assets/icon.png
Terminal=false
Categories=Network;Utility;
'''
(home/'.local/share/applications/ai-station.desktop').write_text(text)
PY
if [[ "${1:-}" != --no-launch ]]; then
  nohup "$HOME/.local/bin/ai-station" >/dev/null 2>&1 </dev/null &
fi
printf '安装完成，可从应用菜单打开「轻舟 AI 中转站」。\n'
