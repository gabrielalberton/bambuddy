#!/usr/bin/env bash
# Build da imagem do fork + troca da imagem no compose + up + espera healthy. Uso: custom/deploy.sh
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
compose="/home/gabriel/Área de trabalho/compose-migration"
systemd-run --user --scope -q -p MemoryMax=3G -p MemorySwapMax=1G --nice=10 -- "$repo/custom/build.sh" | tail -1
new="$(git -C "$repo" rev-parse --short=9 HEAD)"
cd "$compose"
old="$(grep -oP 'image: bambuddy-gabriel:\K[^ ]+' 23-bambuddy.yml)"
sed -i -E "s|image: bambuddy-gabriel:[^ ]+|image: bambuddy-gabriel:1.3.1-$new|; s|# Versão anterior do fork: bambuddy-gabriel:[^ .]+(\.[0-9]+\.[0-9]+-[0-9a-f]+)?\.|# Versão anterior do fork: bambuddy-gabriel:$old.|" 23-bambuddy.yml
./up-stack.sh bambuddy 2>&1 | tail -1
for _ in $(seq 1 60); do s=$(docker inspect -f '{{.State.Health.Status}}' bambuddy); [ "$s" = healthy ] && break; sleep 3; done
echo "deploy: $old -> 1.3.1-$new ($s)"
