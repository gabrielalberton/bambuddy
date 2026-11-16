#!/usr/bin/env bash
# Gera os PNGs do ícone a partir de icon.svg (Chrome headless). Uso: custom/brand/render.sh
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for s in 16 32 180 192 512; do
  printf '<html><body style="margin:0"><img src="file://%s/icon.svg" width="%s" height="%s"></body></html>' "$PWD" "$s" "$s" > "$tmp/i.html"
  google-chrome --headless=new --hide-scrollbars --allow-file-access-from-files --window-size=$s,$s --screenshot="$tmp/$s.png" "file://$tmp/i.html" >/dev/null 2>&1
done
mkdir -p png
cp "$tmp/16.png" png/favicon-16x16.png; cp "$tmp/32.png" png/favicon-32x32.png
cp "$tmp/180.png" png/apple-touch-icon.png; cp "$tmp/192.png" png/android-chrome-192x192.png
cp "$tmp/512.png" png/android-chrome-512x512.png; cp "$tmp/512.png" png/favicon.png
file png/*.png
