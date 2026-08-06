#!/usr/bin/env bash
set -u

APP_DIR="$HOME/AutoRewarder"
DATA_DIR="${AUTOREWARDER_DATA_DIR:-$HOME/.local/share/AutoRewarder}"
LOG_DIR="$APP_DIR/logs"
LOCK_FILE="${LOCK_FILE:-/tmp/autorewarder.lock}"
STATE_DIR="${AUTOREWARDER_STATE_DIR:-$DATA_DIR/state}"
RUN_MARKER_FILE="$STATE_DIR/last-run-started"

START_HOUR="${START_HOUR:-4}"
END_HOUR="${END_HOUR:-23}"
END_MINUTE="${END_MINUTE:-59}"
ACCOUNT_LIMIT="${ACCOUNT_LIMIT:-}"

SEARCH_TOTAL_MIN="${SEARCH_TOTAL_MIN:-32}"
SEARCH_TOTAL_MAX="${SEARCH_TOTAL_MAX:-42}"

MIN_GAP_SECONDS="${MIN_GAP_SECONDS:-300}"
CHUNK_MIN="${CHUNK_MIN:-1}"
CHUNK_MAX="${CHUNK_MAX:-3}"
WAIT_MIN_SECONDS="${WAIT_MIN_SECONDS:-$MIN_GAP_SECONDS}"
WAIT_MAX_SECONDS="${WAIT_MAX_SECONDS:-1200}"

DRY_RUN="${DRY_RUN:-0}"
POINTS_BASELINE_FILE="${AUTOREWARDER_POINTS_BASELINE_FILE:-$LOG_DIR/points-baseline-$(date +%F).json}"
RANDOM_WAIT_MAX_SECONDS="${AUTOREWARDER_RANDOM_WAIT_MAX_SECONDS:-5800}"

declare -A REFRESHED_BALANCE_ACCOUNTS=()

mkdir -p "$LOG_DIR" "$STATE_DIR"
find "$LOG_DIR" -type f -name "autorewarder-*.log" -mtime +7 -delete 2>/dev/null || true

if [ "$DRY_RUN" = "1" ]; then
  LOG_FILE="$LOG_DIR/autorewarder-random-dryrun-$(date +%F-%H%M%S)-$$.log"
else
  LOG_FILE="$LOG_DIR/autorewarder-$(date +%F).log"
fi

rand_between() {
  local min="$1"
  local max="$2"
  if [ "$max" -lt "$min" ]; then
    max="$min"
  fi
  python3 -c "import random; print(random.randint($min, $max))"
}

random_wait_seconds() {
  if [ -n "${AUTOREWARDER_RANDOM_WAIT_SECONDS:-}" ]; then
    echo "$AUTOREWARDER_RANDOM_WAIT_SECONDS"
    return 0
  fi

  # Heavy-tailed pre-run pause: mostly 10-40 min, occasionally longer, so the
  # first search of the day does not land on a clock-aligned grid.
  python3 - <<'PY'
import random

r = random.random()
if r < 0.7:
    wait = random.uniform(600, 2400)
elif r < 0.9:
    wait = random.uniform(2400, 4200)
else:
    wait = random.uniform(4200, 5400)
print(int(wait))
PY
}

wait_random_after_updates() {
  local wait_seconds

  if [ "${AUTOREWARDER_SKIP_RANDOM_WAIT:-0}" = "1" ]; then
    echo "Random pre-run wait skipped."
    return 0
  fi

  wait_seconds="$(random_wait_seconds)"
  if ! [[ "$wait_seconds" =~ ^[0-9]+$ ]]; then
    echo "WARNING: Invalid random wait seconds: $wait_seconds. Skipping wait."
    return 0
  fi

  if [ "$wait_seconds" -le 0 ]; then
    echo "Random wait skipped (0 seconds)."
    return 0
  fi

  echo "Waiting $wait_seconds seconds before running AutoRewarder..."
  if [ "$DRY_RUN" != "1" ]; then
    sleep "$wait_seconds"
  fi
}

log_points_report() {
  local mode="$1"
  local baseline_file="$2"
  local today="$3"

  python3 - "$mode" "$baseline_file" "$today" "$DATA_DIR" <<'PY'
import json
import os
import sys

mode, baseline_file, today, data_dir = sys.argv[1:5]
accounts_path = os.path.join(data_dir, "accounts.json")

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default

def balance_for(account_id):
    stats = load_json(
        os.path.join(data_dir, "accounts", account_id, "stats.json"),
        {},
    )
    balance = stats.get("balance", {}).get("current")
    if isinstance(balance, int):
        return balance
    return None

def daily_for(account_id):
    stats = load_json(
        os.path.join(data_dir, "accounts", account_id, "stats.json"),
        {},
    )
    daily = stats.get("daily", {}).get(today, {})
    return {
        "pc": int(daily.get("pc", 0) or 0),
        "mobile": int(daily.get("mobile", 0) or 0),
        "cards": int(daily.get("cards", 0) or 0),
        "runs": int(daily.get("runs", 0) or 0),
    }

def fmt(value):
    if value is None:
        return "unknown"
    return f"{value:,}"

accounts = load_json(accounts_path, [])
if not isinstance(accounts, list):
    accounts = []

snapshot = {}
for account in accounts:
    account_id = account.get("id")
    if account_id:
        snapshot[account_id] = balance_for(account_id)

if mode == "before":
    if not os.path.exists(baseline_file):
        os.makedirs(os.path.dirname(baseline_file), exist_ok=True)
        temp_file = baseline_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(snapshot, file, indent=2, sort_keys=True)
        os.replace(temp_file, baseline_file)

    print("Points before run:")
    if not accounts:
        print("  No accounts found.")
    for account in accounts:
        account_id = account.get("id")
        name = account.get("label") or "Unknown account"
        print(f"  {name}: {fmt(snapshot.get(account_id))}")
    sys.exit(0)

baseline = load_json(baseline_file, {})
if not isinstance(baseline, dict):
    baseline = {}

print("Daily statistics:")
if not accounts:
    print("  No accounts found.")
for account in accounts:
    account_id = account.get("id")
    name = account.get("label") or "Unknown account"
    current = snapshot.get(account_id)
    start = baseline.get(account_id)
    daily = daily_for(account_id)

    if isinstance(current, int) and isinstance(start, int):
        points = f"points {current:,} ({current - start:+,} today)"
    elif isinstance(current, int):
        points = f"points {current:,} (today unknown)"
    else:
        points = "points unknown"

    print(
        f"  {name}: {points}, pc {daily['pc']}, mobile {daily['mobile']}, "
        f"cards {daily['cards']}, runs {daily['runs']}"
    )
PY
}

latest_main_release_tag() {
  git describe --tags --match "v[0-9]*" --abbrev=0 main 2>/dev/null || true
}

latest_available_release_tag() {
  git tag -l "v[0-9]*" --sort=-v:refname | head -n 1
}

has_blocking_local_changes() {
  git status --porcelain --untracked-files=no -- . ':!assets/queries.json' | grep -q .
}

restore_generated_query_changes() {
  git restore -- assets/queries.json 2>/dev/null || true
}

version_gt() {
  local newer="$1"
  local older="$2"

  [ -n "$newer" ] || return 1
  [ -n "$older" ] || return 0
  [ "$newer" != "$older" ] || return 1
  [ "$(printf "%s\n%s\n" "$newer" "$older" | sort -V | tail -n 1)" = "$newer" ]
}

sync_fork_if_new_release() {
  local current_tag
  local latest_tag
  local original_branch

  echo "Checking upstream release tags..."
  current_tag="$(latest_main_release_tag)"
  if [ -n "$current_tag" ]; then
    echo "Current main release: $current_tag"
  else
    echo "Current main release: none"
  fi

  git fetch upstream --tags || return 1

  latest_tag="$(latest_available_release_tag)"
  if [ -z "$latest_tag" ]; then
    echo "No upstream release tags found. Skipping fork sync."
    return 0
  fi

  echo "Latest available release: $latest_tag"
  if ! version_gt "$latest_tag" "$current_tag"; then
    echo "No newer upstream release found. Skipping fork sync."
    return 0
  fi

  if has_blocking_local_changes; then
    echo "ERROR: Working tree has local changes. Resolve them before syncing."
    return 1
  fi
  restore_generated_query_changes

  original_branch="$(git branch --show-current)"
  if [ "$original_branch" != "autorun" ]; then
    echo "ERROR: Expected to run from autorun branch, found '$original_branch'."
    return 1
  fi

  echo "New upstream release found: $latest_tag"
  echo "Fast-forwarding main from upstream/main..."
  git checkout main || return 1
  git merge --ff-only upstream/main || return 1
  git push origin main || return 1

  echo "Rebasing autorun on updated main..."
  git checkout autorun || return 1
  git rebase main || return 1
  git push --force-with-lease origin autorun || return 1

  echo "Fork synced to upstream release $latest_tag."
}

today_epoch() {
  local hour="$1"
  local minute="$2"
  date -d "$(date +%F) ${hour}:${minute}:00" +%s
}

load_accounts() {
  if [ -n "${ACCOUNT_LIST:-}" ]; then
    printf "%s\n" "$ACCOUNT_LIST" | sed '/^[[:space:]]*$/d'
    return
  fi

  python3 - <<'PY'
from src.accounts import AccountManager, GlobalSettingsManager

manager = AccountManager(GlobalSettingsManager())
manager.migrate_legacy()
for account in manager.list():
    if account.get("first_setup_done"):
        print(account["label"])
PY
}

shuffle_and_limit_accounts() {
  python3 -c '
import random
import sys

limit = int(sys.argv[1]) if sys.argv[1] else None
accounts = [line.rstrip("\n") for line in sys.stdin if line.strip()]
random.shuffle(accounts)
for account in accounts[:limit] if limit else accounts:
    print(account)
' "$ACCOUNT_LIMIT"
}

shuffle_indices() {
  python3 -c '
import random
import sys

indices = [line.rstrip("\n") for line in sys.stdin if line.strip()]
random.shuffle(indices)
for index in indices:
    print(index)
'
}

run_account() {
  local account="$1"
  local pc="$2"
  local mobile="$3"
  local run_env=(AUTOREWARDER_DISABLE_ADVANCED_SCHEDULING=1)

  if [ -z "${REFRESHED_BALANCE_ACCOUNTS[$account]+x}" ]; then
    REFRESHED_BALANCE_ACCOUNTS["$account"]=1
    run_env+=(AUTOREWARDER_REFRESH_BALANCE_ON_SWITCH=1)
  fi

  if [ "$DRY_RUN" = "1" ]; then
    echo "DRY RUN: ${run_env[*]} python3 -u AutoRewarder.py --headless --account \"$account\" --pc $pc --mobile $mobile"
    return 0
  fi

  env "${run_env[@]}" python3 -u AutoRewarder.py --headless --account "$account" --pc "$pc" --mobile "$mobile"
}

active_indices() {
  local index
  for index in "${!accounts[@]}"; do
    if [ $((pc_left[index] + mobile_left[index])) -gt 0 ]; then
      echo "$index"
    fi
  done
}

run_account_chunk() {
  local index="$1"
  local account="${accounts[$index]}"
  local remaining=$((pc_left[index] + mobile_left[index]))
  local max_chunk="$CHUNK_MAX"
  local min_chunk="$CHUNK_MIN"
  local chunk_total
  local pc_min
  local pc_max
  local pc_chunk
  local mobile_chunk
  local chunk_exit_code

  if [ "$max_chunk" -gt "$remaining" ]; then
    max_chunk="$remaining"
  fi
  if [ "$min_chunk" -gt "$max_chunk" ]; then
    min_chunk="$max_chunk"
  fi

  chunk_total="$(rand_between "$min_chunk" "$max_chunk")"
  pc_min=0
  if [ "$chunk_total" -gt "${mobile_left[$index]}" ]; then
    pc_min=$((chunk_total - mobile_left[index]))
  fi
  pc_max="${pc_left[$index]}"
  if [ "$pc_max" -gt "$chunk_total" ]; then
    pc_max="$chunk_total"
  fi
  pc_chunk="$(rand_between "$pc_min" "$pc_max")"
  mobile_chunk=$((chunk_total - pc_chunk))

  echo "Running chunk: $account --pc $pc_chunk --mobile $mobile_chunk (left before: pc ${pc_left[$index]}, mobile ${mobile_left[$index]})"
  run_account "$account" "$pc_chunk" "$mobile_chunk"
  chunk_exit_code="$?"
  echo "Chunk for '$account' exited with code $chunk_exit_code"
  if [ "$chunk_exit_code" -ne 0 ] && [ "${exit_code:-0}" -eq 0 ]; then
    exit_code="$chunk_exit_code"
  fi

  pc_left[index]=$((pc_left[index] - pc_chunk))
  mobile_left[index]=$((mobile_left[index] - mobile_chunk))
  echo "Remaining for '$account': pc ${pc_left[$index]}, mobile ${mobile_left[$index]}"
}

wait_between_chunks() {
  local remaining_count="$1"
  local now
  local seconds_left
  local total_remaining
  local expected_chunks
  local target_interval
  local max_wait
  local wait_seconds

  if [ "$remaining_count" -le 0 ]; then
    return
  fi

  now="$(date +%s)"
  seconds_left=$((end_epoch - now))
  
  # If we're running out of time, continue without delay
  if [ "$seconds_left" -le "$WAIT_MIN_SECONDS" ]; then
    echo "Run window nearly closed; continuing without delay."
    return
  fi

  # Estimate how many more chunks we'll run (including current one)
  total_remaining=$((remaining_count + 1))
  
  # Calculate expected chunks based on average chunk size
  local avg_chunk=$(( (CHUNK_MIN + CHUNK_MAX) / 2 ))
  if [ "$avg_chunk" -le 0 ]; then
    avg_chunk=1
  fi
  expected_chunks=$(( (total_remaining + avg_chunk - 1) / avg_chunk ))
  
  # Target interval = remaining time / expected chunks (with 25% jitter)
  target_interval=$(( seconds_left / expected_chunks ))
  
  # Clamp to reasonable bounds
  if [ "$target_interval" -lt "$WAIT_MIN_SECONDS" ]; then
    target_interval="$WAIT_MIN_SECONDS"
  fi
  if [ "$target_interval" -gt "$WAIT_MAX_SECONDS" ]; then
    target_interval="$WAIT_MAX_SECONDS"
  fi
  
  # Add jitter: 75% to 125% of target
  local jitter_low=$(( target_interval * 75 / 100 ))
  local jitter_high=$(( target_interval * 125 / 100 ))
  
  # Don't exceed configured max wait or time left
  max_wait="$seconds_left"
  if [ "$max_wait" -gt "$WAIT_MAX_SECONDS" ]; then
    max_wait="$WAIT_MAX_SECONDS"
  fi
  if [ "$jitter_high" -gt "$max_wait" ]; then
    jitter_high="$max_wait"
  fi
  if [ "$jitter_low" -lt "$WAIT_MIN_SECONDS" ]; then
    jitter_low="$WAIT_MIN_SECONDS"
  fi

  wait_seconds="$(rand_between "$jitter_low" "$jitter_high")"
  if [ "$wait_seconds" -le 0 ]; then
    echo "Continuing immediately before the next chunk."
    return
  fi

  echo "Waiting $wait_seconds seconds (target interval ~${target_interval}s) before next chunk."
  if [ "$DRY_RUN" != "1" ]; then
    sleep "$wait_seconds"
  fi
}

{
  echo "===== Started $(date) PID $$ ====="
  echo "Window: ${START_HOUR}:00 through ${END_HOUR}:${END_MINUTE}"
  echo "Counts: total searches ${SEARCH_TOTAL_MIN}-${SEARCH_TOTAL_MAX}"
  echo "Chunks: ${CHUNK_MIN}-${CHUNK_MAX}; waits: ${WAIT_MIN_SECONDS}-${WAIT_MAX_SECONDS}s"
  echo "Advanced scheduling: disabled for random chunk runs"

  cd "$APP_DIR" || {
    echo "ERROR: Cannot cd to $APP_DIR"
    exit 1
  }

  date +%F > "$RUN_MARKER_FILE"

  (
  flock -n 9 || {
    echo "Could not acquire lock: $LOCK_FILE"
    exit 1
  }

  if [ "$DRY_RUN" = "1" ]; then
    echo "DRY RUN: skipping query update, random pre-run wait, and points report."
  else
    # Upstream release sync removed: done manually by the operator.

    echo "Updating search queries from Google Trends..."
    if ! python3 -u update_queries.py update --mode combine --timeout 60; then
      echo "WARNING: Query update failed. Continuing with existing queries."
    fi

    wait_random_after_updates
    log_points_report before "$POINTS_BASELINE_FILE" "$(date +%F)"
  fi

  now="$(date +%s)"
  start_epoch="$(today_epoch "$START_HOUR" 0)"
  end_epoch="$(today_epoch "$END_HOUR" "$END_MINUTE")"
  exit_code=0

  # Fail-safe: If run window is too short (less than 2 hours),
  # reduce search targets and prioritize daily tasks
  window_seconds=$((end_epoch - start_epoch))
  window_hours=$((window_seconds / 3600))
  
  if [ "$window_hours" -lt 2 ]; then
    echo "WARNING: Run window is very short (${window_hours}h). Reducing search targets."
    
    # Reduce to minimums and focus on daily tasks
    SEARCH_TOTAL_MIN=5
    SEARCH_TOTAL_MAX=10
    CHUNK_MIN=1
    CHUNK_MAX=1
    
    # Set minimum wait to avoid rapid execution
    WAIT_MIN_SECONDS=60
    WAIT_MAX_SECONDS=180
    
    echo "Adjusted: counts ${SEARCH_TOTAL_MIN}-${SEARCH_TOTAL_MAX}, chunks ${CHUNK_MIN}-${CHUNK_MAX}"
  fi

  if [ "$now" -gt "$end_epoch" ]; then
    echo "Current time is after today's run window. Nothing to run."
    exit 0
  fi

  if [ "$now" -lt "$start_epoch" ]; then
    wait_seconds=$((start_epoch - now))
    echo "Waiting $wait_seconds seconds for the run window to open."
    if [ "$DRY_RUN" != "1" ]; then
      sleep "$wait_seconds"
    fi
    now="$start_epoch"
  fi

  mapfile -t accounts < <(load_accounts | shuffle_and_limit_accounts)
  if [ "${#accounts[@]}" -eq 0 ]; then
    echo "No ready accounts found."
    exit 0
  fi

  echo "Randomized account order:"
  for account in "${accounts[@]}"; do
    echo "  - $account"
  done

  pc_left=()
  mobile_left=()
  for index in "${!accounts[@]}"; do
    search_total="$(rand_between "$SEARCH_TOTAL_MIN" "$SEARCH_TOTAL_MAX")"
    pc="$search_total"
    mobile=0
    pc_left+=("$pc")
    mobile_left+=("$mobile")

    echo "Planned total for ${accounts[$index]}: pc $pc, mobile $mobile (total $search_total)"
  done

  while mapfile -t active < <(active_indices) && [ "${#active[@]}" -gt 0 ]; do
    mapfile -t round < <(printf '%s\n' "${active[@]}" | shuffle_indices)
    for index in "${round[@]}"; do
      if [ $((pc_left[index] + mobile_left[index])) -le 0 ]; then
        continue
      fi
      run_account_chunk "$index"
      mapfile -t active < <(active_indices)
      wait_between_chunks "${#active[@]}"
    done
  done

  if [ "$DRY_RUN" != "1" ]; then
    log_points_report after "$POINTS_BASELINE_FILE" "$(date +%F)"
  fi
  echo "AutoRewarder exited with code $exit_code"
  exit "$exit_code"
  ) 9>"$LOCK_FILE"

  echo "===== Finished $(date) ====="
  echo
} >> "$LOG_FILE" 2>&1

if [ "$DRY_RUN" = "1" ]; then
  cat "$LOG_FILE"
fi
