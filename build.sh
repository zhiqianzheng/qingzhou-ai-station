#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
mkdir -p dist
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/DEBIAN" "$stage/opt/ai-station/core" "$stage/opt/ai-station/assets" "$stage/usr/share/applications" "$stage/usr/share/icons/hicolor/512x512/apps" "$stage/usr/bin"
cat > "$stage/DEBIAN/control" <<'EOF'
Package: qingzhou-ai-station
Version: 0.2.1
Architecture: amd64
Maintainer: zhiqianzheng <133075010+zhiqianzheng@users.noreply.github.com>
Depends: python3 (>= 3.10), python3-tk, python3-aiohttp, policykit-1
Section: net
Priority: optional
Description: AI gateway desktop app with opt-in local conversation history
 Browser account authorization, API connection details and streaming conversation history.
EOF
install -m755 app.py backend.py recorder.py install-tailscale.sh "$stage/opt/ai-station/"
install -m755 core/cli-proxy-api "$stage/opt/ai-station/core/"
install -m644 core/LICENSE "$stage/opt/ai-station/core/"
install -m644 README.md THIRD_PARTY_LICENSES.txt "$stage/opt/ai-station/"
install -m644 assets/icon.png assets/icon.svg "$stage/opt/ai-station/assets/"
install -m644 assets/icon.png "$stage/usr/share/icons/hicolor/512x512/apps/qingzhou-ai-station.png"
cat > "$stage/usr/bin/qingzhou-ai-station" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /opt/ai-station/app.py "$@"
EOF
chmod 755 "$stage/usr/bin/qingzhou-ai-station"
cat > "$stage/usr/share/applications/qingzhou-ai-station.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=轻舟 AI 中转站
Exec=qingzhou-ai-station
Icon=qingzhou-ai-station
Terminal=false
Categories=Network;Utility;
EOF
find "$stage" -type d -exec chmod 755 {} +
chmod 644 "$stage/DEBIAN/control" "$stage/usr/share/applications/qingzhou-ai-station.desktop"
dpkg-deb --root-owner-group -Zxz -z4 --build "$stage" dist/qingzhou-ai-station_0.2.1_amd64.deb
portable="$stage/portable/qingzhou-ai-station"
mkdir -p "$portable/core" "$portable/assets"
cp app.py backend.py recorder.py install.sh install-tailscale.sh README.md THIRD_PARTY_LICENSES.txt "$portable/"
cp core/cli-proxy-api core/LICENSE "$portable/core/"
cp assets/icon.png assets/icon.svg "$portable/assets/"
tar -C "$stage/portable" -czf dist/qingzhou-ai-station-0.2.1-linux-x64.tar.gz qingzhou-ai-station
