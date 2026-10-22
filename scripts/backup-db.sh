#!/usr/bin/env bash
# Host-side backup helper (optional). App already backs up daily inside the container.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT/backups-host}"
mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$OUT_DIR/sync-${STAMP}.db"
cd "$ROOT"
docker compose exec -T sync cat /data/sync.db > "$OUT"
echo "Wrote $OUT ($(wc -c < "$OUT") bytes)"
