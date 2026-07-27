#!/usr/bin/env bash
set -euo pipefail

for script in run-autorewarder.sh run-random-autorewarder.sh; do
  helper_code="$(
    awk '/^random_wait_seconds\(\)/,/^}/ { print }' "$script"
    awk '/^wait_random_after_updates\(\)/,/^}/ { print }' "$script"
  )"
  if [ -z "$helper_code" ]; then
    echo "$script: missing random wait helpers"
    exit 1
  fi

  output="$(
    AUTOREWARDER_SKIP_RANDOM_WAIT=1 \
    AUTOREWARDER_RANDOM_WAIT_SECONDS=12 \
    bash -c '
      sleep() {
        echo "sleep called"
      }
      eval "$1"
      wait_random_after_updates
    ' bash "$helper_code"
  )"

  if [ "$output" != "Random pre-run wait skipped." ]; then
    echo "$script: expected skip without sleeping"
    echo "$output"
    exit 1
  fi
done

echo "manual random wait skip tests passed"
