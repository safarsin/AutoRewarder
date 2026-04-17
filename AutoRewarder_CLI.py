"""
AutoRewarder CLI runner and scheduler.

This script runs AutoRewarder in headless mode and can distribute queries
over a time window (advanced scheduling). It reads saved settings from
`SettingsManager` and accepts optional CLI overrides.

Usage examples:
  - One-off: `python AutoRewarder_CLI.py --once --count 30`
  - Scheduled: `python AutoRewarder_CLI.py --duration 3 --total-queries 30`
  - Use settings from GUI by running without args (will read saved settings)
"""

import argparse
import time
import math
import random
import sys
from datetime import datetime

from src.api import AutoRewarderAPI
from src.settings_manager import SettingsManager


def iso_now():
    return datetime.now().isoformat(timespec="seconds")

def console_log(message):
    print(f"[{iso_now()}] {message}")

def run_single(api, count):
    console_log(f"Starting single run: {count} queries")
    api.main(int(count))
    console_log("Single run finished")

def run_scheduled(api, total_queries, duration_hours, queries_per_hour):
    total_queries = int(total_queries)
    duration_hours = float(duration_hours)
    api.log(f"Scheduling {total_queries} queries over {duration_hours} hours (qph={queries_per_hour})")

    # Decide batch size to avoid creating driver for every single query.
    try:
        if queries_per_hour:
            qph_int = int(queries_per_hour)
        else:
            qph_int = 0

    except Exception:
        qph_int = 0

    if qph_int > 0:
        raw_batch = qph_int // 6  # 10-minute batches if qph specified
    else:
        raw_batch = total_queries // max(1, int(duration_hours * 2)) # Default to ~30-minute batches

    per_batch = max(1, min(10, raw_batch))

    num_batches = math.ceil(total_queries / per_batch)
    total_seconds = duration_hours * 3600

    if num_batches == 0:
        console_log("No batches to run")
        return

    interval = total_seconds / num_batches

    console_log(f"Scheduling {num_batches} batches of ~{per_batch} queries; interval ~{interval:.2f}s")

    remaining = total_queries

    for i in range(num_batches):
        batch_count = min(per_batch, remaining)
        console_log(f"Batch {i+1}/{num_batches}: running {batch_count} queries (remaining {remaining})")

        try:
            api.main(batch_count)
        except Exception as e:
            console_log(f"[ERROR] Batch {i+1} failed: {e}")

        remaining -= batch_count

        if remaining <= 0:
            break

        sleep_time = max(5, interval * random.uniform(0.75, 1.25))
        console_log(f"Sleeping {sleep_time:.2f}s until next batch")
        time.sleep(sleep_time)

    console_log("Scheduled run complete")

def create_api_headless():
    api = AutoRewarderAPI()

    # Force headless in runtime and settings
    try:
        api.set_hide_browser(True)
    except Exception:
        # Fallback: set driver manager flag directly
        api.driver_manager.hide_browser = True

    # Replace logging with console output and update components that captured the logger early
    api.log = console_log

    try:
        api.search_engine._logger = console_log
    except Exception:
        pass

    try:
        api.history._logger = console_log
    except Exception:
        pass
    
    try:
        api.daily_set.logger = console_log
    except Exception:
        pass

    return api

def main():
    parser = argparse.ArgumentParser(description="AutoRewarder CLI runner and scheduler")
    parser.add_argument("--once", action="store_true", help="Run a single immediate job")
    parser.add_argument("--count", type=int, help="Number of queries for a single run")
    parser.add_argument("--duration", type=float, help="Run duration in hours for advanced scheduling")
    parser.add_argument("--total-queries", type=int, help="Total queries for the scheduled run")
    parser.add_argument("--queries-per-hour", type=int, help="Queries per hour target for scheduling")
    args = parser.parse_args()

    settings_manager = SettingsManager()
    settings = settings_manager.get_settings()

    advanced_scheduling = settings.get("advancedScheduling", False)

    if args.duration is not None:
        run_duration = args.duration
    else:
        run_duration = settings.get("runDuration", 3)

    if args.total_queries is not None:
        total_queries = args.total_queries
    else:
        total_queries = settings.get("totalQueries", None)

    if args.queries_per_hour is not None:
        qph = args.queries_per_hour
    else:
        qph = settings.get("queriesPerHour", None)

    api = create_api_headless()

    # Single immediate run
    if args.once or (not advanced_scheduling and args.duration is None):
        count = args.count or total_queries or settings.get("totalQueries") or 30
        run_single(api, int(count))
        return

    # Advanced scheduling path
    if total_queries is None:
        if qph:
            total_queries = int(qph * float(run_duration))
        else:
            total_queries = int(settings.get("totalQueries", 30))

    run_scheduled(api, int(total_queries), float(run_duration), qph)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console_log("Interrupted by user; exiting.")
        sys.exit(0)
