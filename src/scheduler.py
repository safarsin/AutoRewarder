"""
Per-account scheduled-run daemon for AutoRewarder.

Each account holds its own schedule in its meta.json:
    schedule: {enabled, time, queries, window_hours, last_triggered_date}

The scheduler polls every minute and, for every account whose schedule is
enabled and whose daily window is currently open, fires a run. Only one run
can execute at a time (guarded by the API run lock): other accounts whose
schedules fire while a run is in progress will simply retry on the next tick.

A single random fire-time is picked once per account per day, so the run
doesn't happen at the exact same minute every day (more natural behavior).
"""

import random
import threading
from datetime import datetime, timedelta

from .settings_manager import AccountMetaManager, default_account_schedule


class Scheduler:

    POLL_SECONDS = 60

    def __init__(self, api, account_manager, logger=None):
        self._api = api
        self._am = account_manager
        self._log = logger or (lambda m: None)

        self._thread = None
        self._stop_event = threading.Event()
        # Keyed by f"{account_id}:{today_iso}" → datetime when the run should fire.
        self._planned_starts = {}

    # ---- Lifecycle ---------------------------------------------------

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="AutoRewarderScheduler", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                self._log(f"[ERROR] Scheduler tick failed: {e}")
            self._stop_event.wait(self.POLL_SECONDS)

    # ---- Tick: iterate every account ---------------------------------

    def _tick(self):
        now = datetime.now()
        today = now.date().isoformat()

        for acc in self._am.list():
            aid = acc.get("id")
            if not aid:
                continue
            try:
                self._tick_account(aid, acc.get("label") or "Account", now, today)
            except Exception as e:
                self._log(f"[ERROR] Scheduler error for account {aid}: {e}")

    def _tick_account(self, aid, label, now, today):
        meta = AccountMetaManager(aid)
        sched = meta.get_schedule()

        if not sched.get("enabled"):
            return
        if sched.get("last_triggered_date") == today:
            return

        start = self._parse_start(sched.get("time"), now)
        if start is None:
            return

        duration_h = max(0, int(sched.get("window_hours") or 0))
        end = start + timedelta(hours=duration_h)
        # A 0-hour window means "fire exactly at start"; give it 60s of leeway.
        if duration_h == 0:
            end = start + timedelta(seconds=60)

        if now < start:
            return
        if now >= end:
            return

        planned_key = f"{aid}:{today}"
        planned = self._planned_starts.get(planned_key)
        if planned is None:
            remaining = max(0, (end - now).total_seconds())
            delay = random.uniform(0, remaining)
            planned = now + timedelta(seconds=delay)
            self._planned_starts[planned_key] = planned
            self._log(
                f"Scheduler: '{label}' will run at ~{planned.strftime('%H:%M')} "
                f"(window {start.strftime('%H:%M')}–{end.strftime('%H:%M')})."
            )

        if now >= planned:
            self._fire(aid, label, sched, meta, today)

    # ---- Trigger -----------------------------------------------------

    def _fire(self, aid, label, sched, meta, today):
        # If the bot is already running (manual or another schedule), retry later.
        if self._api.is_running():
            return

        # Switch to the target account if we're not already on it.
        if self._am.current_id() != aid:
            if not self._api.switch_account(aid):
                # Likely blocked because a run just started. Retry next tick.
                return

        # Mark as triggered BEFORE spawning so multiple ticks don't race.
        sched_copy = dict(sched)
        sched_copy["last_triggered_date"] = today
        meta.set_schedule(sched_copy)

        queries = max(1, min(99, int(sched.get("queries") or 30)))
        self._log(f"Scheduler: starting scheduled run for '{label}' ({queries} queries).")
        threading.Thread(
            target=self._api.main, args=(queries,), daemon=True
        ).start()

    # ---- Helpers -----------------------------------------------------

    def _parse_start(self, time_str, now):
        if not time_str:
            return None
        try:
            hh_s, mm_s = str(time_str).split(":", 1)
            hh = int(hh_s)
            mm = int(mm_s)
        except (ValueError, AttributeError):
            return None
        if not (0 <= hh < 24 and 0 <= mm < 60):
            return None
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


# Backwards-compat export (in case external code imported this).
default_schedule = default_account_schedule
