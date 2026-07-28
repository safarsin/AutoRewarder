#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${1:-run-random-autorewarder.sh}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

output="$(
  mkdir -p "$WORK_DIR/AutoRewarder"
  HOME="$WORK_DIR" \
  LOCK_FILE="$WORK_DIR/autorewarder.lock" \
  DRY_RUN=1 \
  ACCOUNT_LIST=$'Alpha\nBeta' \
  ACCOUNT_LIMIT=2 \
  SEARCH_TOTAL_MIN=3 \
  SEARCH_TOTAL_MAX=3 \
  CHUNK_MIN=1 \
  CHUNK_MAX=1 \
  WAIT_MIN_SECONDS=0 \
  WAIT_MAX_SECONDS=0 \
  bash "$SCRIPT_PATH"
)"

commands="$(printf '%s\n' "$output" | grep 'python3 -u AutoRewarder.py')"

if printf '%s\n' "$commands" | grep -v 'AUTOREWARDER_DISABLE_ADVANCED_SCHEDULING=1' >/dev/null; then
  echo "random chunks should disable advanced scheduling"
  echo "$output"
  exit 1
fi

for account in Alpha Beta; do
  count="$(printf '%s\n' "$commands" | grep -c -- "--account \"$account\"")"
  if [ "$count" -lt 3 ]; then
    echo "$account should run in multiple one-search chunks"
    echo "$output"
    exit 1
  fi
done

printf '%s\n' "$commands" | awk '
{
  pc = mobile = -1
  for (i = 1; i <= NF; i++) {
    if ($i == "--pc") pc = $(i + 1)
    if ($i == "--mobile") mobile = $(i + 1)
  }
  if (pc < 0 || mobile < 0 || pc + mobile != 1) {
    print "chunk is not exactly one search: " $0
    exit 1
  }
}
'

echo "random account mixing tests passed"
