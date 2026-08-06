#!/usr/bin/env python3
"""Randomize per-account AutoRewarder schedules before a headless run."""

import argparse
import json
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from src.config import ACCOUNTS_DIR

SEARCH_TOTAL_MIN = 18
SEARCH_TOTAL_MAX = 22
QPH_MIN = 1
QPH_MAX = 10
QPH_JITTER = 3
DURATION_MIN_HOURS = 2.15
DURATION_MAX_HOURS = 2.8
DEFAULT_DEADLINE_HOUR = 22
DEFAULT_DEADLINE_MINUTE = 0
DEFAULT_SAFETY_BUFFER_MINUTES = 15


@dataclass
class AccountRoll:
    account_id: str
    meta_path: Path
    meta: dict
    schedule: dict
    pc: int
    mobile: int
    duration: int
    offset_minutes: int = 0

    @property
    def total_queries(self):
        return self.pc + self.mobile


def ceil_div(numerator, denominator):
    """Return integer ceiling division for positive values."""
    return int(math.ceil(float(numerator) / float(max(1, denominator))))


def app_accounts_dir():
    """Return the default AutoRewarder accounts directory for this platform."""
    return Path(ACCOUNTS_DIR)


def read_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path, data):
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
    os.replace(temp_path, path)


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, int(value)))


def random_search_split(rng):
    """Split the daily total between PC and mobile, both non-zero."""
    total = rng.randint(SEARCH_TOTAL_MIN, SEARCH_TOTAL_MAX)
    pc = rng.randint(1, max(1, total - 1))
    return pc, total - pc


def discover_ready_accounts(accounts_dir, rng):
    rolls = []
    for meta_path in sorted(Path(accounts_dir).glob("*/meta.json")):
        try:
            meta = read_json(meta_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"Skipping {meta_path}: cannot read JSON ({exc})")
            continue

        schedule = meta.get("schedule")
        if not isinstance(schedule, dict):
            continue
        if not meta.get("first_setup_done"):
            continue
        if not schedule.get("enabled"):
            continue

        pc, mobile = random_search_split(rng)
        rolls.append(
            AccountRoll(
                account_id=meta_path.parent.name,
                meta_path=meta_path,
                meta=meta,
                schedule=schedule,
                pc=pc,
                mobile=mobile,
                duration=1,
            )
        )
    return rolls


def available_duration_hours(
    now, deadline_hour, deadline_minute, safety_buffer_minutes
):
    if deadline_hour == 24 and deadline_minute == 0:
        deadline = datetime.combine(now.date() + timedelta(days=1), time(0, 0))
    else:
        deadline = datetime.combine(now.date(), time(deadline_hour, deadline_minute))
    seconds = (deadline - now).total_seconds() - (safety_buffer_minutes * 60)
    return max(0.0, seconds / 3600)


def allocate_random_durations(rolls, available_hours, rng):
    """Pick faster per-account durations while fitting inside today's budget."""
    if not rolls:
        return

    if available_hours <= len(rolls):
        for roll in rolls:
            roll.duration = 1
        return

    desired = [rng.uniform(DURATION_MIN_HOURS, DURATION_MAX_HOURS) for _ in rolls]
    desired_total = sum(desired)

    if desired_total <= available_hours:
        adjusted = desired
    elif available_hours >= len(rolls) * DURATION_MIN_HOURS:
        base = DURATION_MIN_HOURS
        desired_extra = sum(duration - base for duration in desired)
        target_extra = available_hours - (len(rolls) * base)
        scale = target_extra / desired_extra if desired_extra > 0 else 0
        adjusted = [base + ((duration - base) * scale) for duration in desired]
    else:
        base = 1.0
        desired_extra = sum(duration - base for duration in desired)
        target_extra = available_hours - len(rolls)
        scale = target_extra / desired_extra if desired_extra > 0 else 0
        adjusted = [base + ((duration - base) * scale) for duration in desired]

    for roll, duration in zip(rolls, adjusted):
        roll.duration = math.floor(max(1.0, duration) * 100) / 100


def allocate_random_offsets(rolls, available_hours, now):
    """
    Stagger account start times inside the leftover daily budget.

    Each account gets `offset_minutes`: minutes after the headless run begins.
    Offsets are derived from a per-day seed, so the ordering shifts daily but
    stays deterministic for tests, and they never consume the caller's RNG.
    """
    if not rolls:
        return
    total_duration = sum(roll.duration for roll in rolls)
    slack = max(0.0, available_hours - total_duration)
    if slack <= 0:
        for roll in rolls:
            roll.offset_minutes = 0
        return
    seeded = random.Random(int(now.strftime("%Y%m%d")))
    points = sorted(seeded.random() for _ in rolls)
    for roll, fraction in zip(rolls, points):
        roll.offset_minutes = int(fraction * slack * 60)


def randomized_queries_per_hour(roll, rng):
    """Choose a bounded QPH that varies batch size without changing query totals."""
    effective_qph = roll.total_queries / max(1.0, float(roll.duration))
    jitter = rng.randint(-QPH_JITTER, QPH_JITTER)
    return clamp(round(effective_qph) + jitter, QPH_MIN, QPH_MAX)


def randomize_account_schedules(
    accounts_dir=None,
    rng=None,
    now=None,
    deadline_hour=DEFAULT_DEADLINE_HOUR,
    deadline_minute=DEFAULT_DEADLINE_MINUTE,
    safety_buffer_minutes=DEFAULT_SAFETY_BUFFER_MINUTES,
):
    """Randomize schedule fields for enabled, ready accounts."""
    accounts_dir = (
        Path(accounts_dir) if accounts_dir is not None else app_accounts_dir()
    )
    rng = rng if rng is not None else random.SystemRandom()
    now = now if now is not None else datetime.now()

    rolls = discover_ready_accounts(accounts_dir, rng)
    budget = available_duration_hours(
        now, deadline_hour, deadline_minute, safety_buffer_minutes
    )
    allocate_random_durations(rolls, budget, rng)
    allocate_random_offsets(rolls, budget, now)

    changes = []
    for roll in rolls:
        old = {
            "runDuration": roll.schedule.get("runDuration"),
            "queriesPerHour": roll.schedule.get("queriesPerHour"),
            "queries_pc": roll.schedule.get("queries_pc"),
            "queries_mobile": roll.schedule.get("queries_mobile"),
            "startOffsetMinutes": roll.schedule.get("startOffsetMinutes", 0),
        }

        qph = randomized_queries_per_hour(roll, rng)
        roll.schedule["queries_pc"] = roll.pc
        roll.schedule["queries_mobile"] = roll.mobile
        roll.schedule["runDuration"] = roll.duration
        roll.schedule["queriesPerHour"] = qph
        roll.schedule["startOffsetMinutes"] = roll.offset_minutes
        roll.meta["schedule"] = roll.schedule
        write_json(roll.meta_path, roll.meta)

        new = {
            "runDuration": roll.duration,
            "queriesPerHour": qph,
            "queries_pc": roll.pc,
            "queries_mobile": roll.mobile,
            "startOffsetMinutes": roll.offset_minutes,
            "effectiveQueriesPerHour": round(
                roll.total_queries / max(1, roll.duration), 2
            ),
        }
        changes.append({"account_id": roll.account_id, "old": old, "new": new})

    return changes


def main():
    parser = argparse.ArgumentParser(
        description="Randomize AutoRewarder per-account schedules."
    )
    parser.add_argument("--accounts-dir", default=str(app_accounts_dir()))
    parser.add_argument("--deadline-hour", type=int, default=DEFAULT_DEADLINE_HOUR)
    parser.add_argument("--deadline-minute", type=int, default=DEFAULT_DEADLINE_MINUTE)
    parser.add_argument(
        "--safety-buffer-minutes", type=int, default=DEFAULT_SAFETY_BUFFER_MINUTES
    )
    args = parser.parse_args()

    changes = randomize_account_schedules(
        accounts_dir=args.accounts_dir,
        deadline_hour=args.deadline_hour,
        deadline_minute=args.deadline_minute,
        safety_buffer_minutes=args.safety_buffer_minutes,
    )

    if not changes:
        print("No enabled ready account schedules found to randomize.")
        return 0

    for change in changes:
        old = change["old"]
        new = change["new"]
        print(
            f"{change['account_id']}: "
            f"PC {old['queries_pc']} -> {new['queries_pc']}, "
            f"mobile {old['queries_mobile']} -> {new['queries_mobile']}, "
            f"duration {old['runDuration']}h -> {new['runDuration']}h, "
            f"QPH {old['queriesPerHour']} -> {new['queriesPerHour']} "
            f"(effective {new['effectiveQueriesPerHour']}/h), "
            f"offset {new['startOffsetMinutes']}min"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
