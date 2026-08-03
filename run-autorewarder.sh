#!/usr/bin/env bash
set -u

APP_DIR="$HOME/AutoRewarder"
DATA_DIR="${AUTOREWARDER_DATA_DIR:-$HOME/.local/share/AutoRewarder}"
LOG_DIR="$APP_DIR/logs"
LOCK_FILE="${LOCK_FILE:-/tmp/autorewarder.lock}"
STATE_DIR="${AUTOREWARDER_STATE_DIR:-$DATA_DIR/state}"
RUN_MARKER_FILE="$STATE_DIR/last-run-started"

mkdir -p "$LOG_DIR" "$STATE_DIR"

# Delete logs older than 7 days
find "$LOG_DIR" -type f -name "autorewarder-*.log" -mtime +7 -delete 2>/dev/null || true

LOG_FILE="$LOG_DIR/autorewarder-$(date +%F).log"
POINTS_BASELINE_FILE="${AUTOREWARDER_POINTS_BASELINE_FILE:-$LOG_DIR/points-baseline-$(date +%F).json}"
RANDOM_WAIT_MAX_SECONDS="${AUTOREWARDER_RANDOM_WAIT_MAX_SECONDS:-5800}"
AUTOREWARDER_SCHEDULE_DEADLINE_HOUR="${AUTOREWARDER_SCHEDULE_DEADLINE_HOUR:-22}"
AUTOREWARDER_SCHEDULE_DEADLINE_MINUTE="${AUTOREWARDER_SCHEDULE_DEADLINE_MINUTE:-0}"
AUTOREWARDER_SCHEDULE_SAFETY_BUFFER_MINUTES="${AUTOREWARDER_SCHEDULE_SAFETY_BUFFER_MINUTES:-15}"

random_wait_seconds() {
  if [ -n "${AUTOREWARDER_RANDOM_WAIT_SECONDS:-}" ]; then
    echo "$AUTOREWARDER_RANDOM_WAIT_SECONDS"
    return 0
  fi

  if ! [[ "$RANDOM_WAIT_MAX_SECONDS" =~ ^[0-9]+$ ]] || [ "$RANDOM_WAIT_MAX_SECONDS" -le 0 ]; then
    echo 0
    return 0
  fi

  echo $((RANDOM % RANDOM_WAIT_MAX_SECONDS))
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
  sleep "$wait_seconds"
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

{
  echo "===== Started $(date) PID $$ ====="

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

    sync_fork_if_new_release || {
      echo "ERROR: Upstream release sync failed. Not running AutoRewarder."
      exit 1
    }

    echo "Updating search queries from Google Trends..."
    if ! python3 -u update_queries.py update --mode replace --timeout 60; then
      echo "WARNING: Query update failed. Continuing with existing queries."
    fi

    wait_random_after_updates

    echo "Randomizing account schedules..."
    python3 -u schedule_randomizer.py \
      --deadline-hour "$AUTOREWARDER_SCHEDULE_DEADLINE_HOUR" \
      --deadline-minute "$AUTOREWARDER_SCHEDULE_DEADLINE_MINUTE" \
      --safety-buffer-minutes "$AUTOREWARDER_SCHEDULE_SAFETY_BUFFER_MINUTES"

    log_points_report before "$POINTS_BASELINE_FILE" "$(date +%F)"

    echo "Running AutoRewarder..."
    AUTOREWARDER_REFRESH_BALANCE_ON_SWITCH=1 python3 -u AutoRewarder.py --headless
    exit_code="$?"

    log_points_report after "$POINTS_BASELINE_FILE" "$(date +%F)"

    echo "AutoRewarder exited with code $exit_code"
    exit "$exit_code"
  ) 9>"$LOCK_FILE"

  echo "===== Finished $(date) ====="
  echo
} >> "$LOG_FILE" 2>&1
