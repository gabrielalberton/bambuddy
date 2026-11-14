#!/usr/bin/env bash
# Compila o frontend do fork e gera a imagem bambuddy-gabriel:<base>-<sha>.
# Não faz deploy nem mexe no container em execução.
#
# Uso: custom/build.sh [--no-docker]
#
# O frontend é compilado em custom/.build/static (e não em ../static, que é
# diretório versionado pelo upstream: compilar lá sujaria a árvore e geraria
# conflito no rebase).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$(tr -d '[:space:]' < "$ROOT/custom/BASE_VERSION")"   # ex.: v1.3.1
BASE_NUM="${BASE#v}"                                          # ex.: 1.3.1
SHA="$(git -C "$ROOT" rev-parse --short HEAD)"
if [ -n "$(git -C "$ROOT" status --porcelain -- frontend custom)" ]; then
  SHA="${SHA}-dirty"
fi
OUT="$ROOT/custom/.build"
TAG="bambuddy-gabriel:${BASE_NUM}-${SHA}"
CAP=(systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=1G --nice=10 --)

NO_DOCKER=0
[ "${1:-}" = "--no-docker" ] && NO_DOCKER=1

avail_kb="$(awk '/MemAvailable/ {print $2}' /proc/meminfo)"
if [ "$avail_kb" -lt 2000000 ]; then
  echo "Memória disponível baixa ($((avail_kb / 1024)) MiB < ~2 GiB): abortando. Tente mais tarde." >&2
  exit 1
fi

cd "$ROOT/frontend"
if [ ! -f node_modules/.package-lock.json ] || [ package-lock.json -nt node_modules/.package-lock.json ]; then
  echo "==> npm ci"
  "${CAP[@]}" npm ci --no-audit --no-fund
fi

echo "==> vite build -> $OUT/static"
rm -rf "$OUT/static"
mkdir -p "$OUT"
"${CAP[@]}" npx vite build --outDir "$OUT/static" --emptyOutDir
# Mesmo passo do "npm run build" do upstream (check:baseline), no diretório nosso.
node scripts/check-browser-baseline.mjs "$OUT/static/assets"

if [ "$NO_DOCKER" = 1 ]; then
  echo "Frontend em $OUT/static (sem docker build)."
  exit 0
fi

echo "==> docker build $TAG (base ghcr.io/maziggy/bambuddy:$BASE_NUM)"
docker build \
  --build-arg "BASE_VERSION=$BASE_NUM" \
  --build-arg "FORK_REVISION=$(git -C "$ROOT" rev-parse HEAD)" \
  -f "$ROOT/custom/Dockerfile" \
  -t "$TAG" -t bambuddy-gabriel:latest \
  "$OUT"
echo "Imagem: $TAG (também bambuddy-gabriel:latest)"
