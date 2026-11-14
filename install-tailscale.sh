#!/usr/bin/env bash
set -euo pipefail
# Run by pkexec after the user explicitly selects public access.
. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) echo '公网自动安装目前支持 Ubuntu / Debian。'; exit 1;; esac
suite="${VERSION_CODENAME:-}"
[[ "$suite" =~ ^[a-z]+$ ]] || { echo '无法确定系统版本'; exit 1; }
command -v curl >/dev/null || { apt-get update; apt-get install -y curl ca-certificates; }
mkdir -p /usr/share/keyrings
curl --fail --silent --show-error --location "https://pkgs.tailscale.com/stable/$ID/$suite.noarmor.gpg" -o /usr/share/keyrings/tailscale-archive-keyring.gpg
curl --fail --silent --show-error --location "https://pkgs.tailscale.com/stable/$ID/$suite.tailscale-keyring.list" -o /etc/apt/sources.list.d/tailscale.list
apt-get update
apt-get install -y tailscale
systemctl enable --now tailscaled
