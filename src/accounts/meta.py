"""Per-account metadata persistence (first_setup_done, schedule)."""

import json
import os

from ..config import account_dir, account_meta_path

DEFAULT_ACCOUNT_SCHEDULE = {
    # Master toggle for this account's scheduled headless run.
    "enabled": False,
    # False = single burst when the headless runner fires.
    # True  = drip-feed the total across runDuration at queriesPerHour.
    "advancedScheduling": False,
    "runDuration": 3,  # hours, 1..24
    "queriesPerHour": 10,  # 1..99
    "queries_pc": 30,  # 0..130
    "queries_mobile": 20,  # 0..99
    "last_triggered_date": None,
}


def default_account_schedule():
    """Return a fresh copy of the default per-account schedule."""
    return dict(DEFAULT_ACCOUNT_SCHEDULE)


def _read_json(path, default):
    """Read a JSON file. On any parse/IO failure, back it up as .backup and return default."""
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError):
        backup_path = path + ".backup"
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError:
                pass
        try:
            os.replace(path, backup_path)
        except OSError:
            pass
        return default


def _write_json(path, data):
    """
    Atomically write JSON via a temp file rename, with a retry loop that
    tolerates transient Windows locks (Defender, indexer, another instance
    briefly holding the file). A stale `.tmp` from a previous crashed write
    is removed before the write so its file attributes don't block us.

    Args:
        path: target file path to write
        data: JSON-serializable data to write

    Raises:
        OSError: If the file cannot be written.
    """
    import time as _time

    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"

    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass

    last_err = None
    for attempt in range(4):
        try:
            with open(temp_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
            os.replace(temp_path, path)
            return
        except PermissionError as e:
            last_err = e
            _time.sleep(0.15 * (attempt + 1))
        except OSError as e:
            last_err = e
            _time.sleep(0.1)
    raise last_err if last_err else OSError(f"Could not write {path}")


class AccountMetaManager:
    """
    Per-account metadata (currently just first_setup_done).
    Stored at accounts/<account_id>/meta.json.
    """

    def __init__(self, account_id):
        """
        Args:
            account_id: the ID of the account this manager handles (string)
        """
        self.account_id = account_id
        self.path = account_meta_path(account_id)

    def get_meta(self):
        """Return per-account meta merged with defaults."""
        defaults = {"first_setup_done": False}

        if not os.path.exists(account_dir(self.account_id)):
            try:
                os.makedirs(account_dir(self.account_id), exist_ok=True)
            except OSError:
                pass

        if not os.path.exists(self.path):
            try:
                self.save_meta(defaults)
            except OSError:
                pass
            return defaults

        meta = _read_json(self.path, None)
        if not isinstance(meta, dict):
            try:
                self.save_meta(defaults)
            except OSError:
                pass
            return defaults

        return {**defaults, **meta}

    def save_meta(self, meta):
        """Persist per-account meta to disk."""
        _write_json(self.path, meta)

    def is_first_setup_done(self):
        """Return True if first setup is marked complete."""
        return bool(self.get_meta().get("first_setup_done"))

    def mark_up_as_done(self):
        """Mark first setup as completed."""
        meta = self.get_meta()
        meta["first_setup_done"] = True
        self.save_meta(meta)

    def get_schedule(self):
        """Return this account's schedule, with defaults for missing keys."""
        meta = self.get_meta()
        sched = meta.get("schedule") if isinstance(meta, dict) else None
        merged = default_account_schedule()
        if isinstance(sched, dict):
            merged.update({k: sched.get(k, v) for k, v in merged.items()})
        return merged

    def set_schedule(self, sched):
        """
        Persist this account's schedule. `sched` should be a dict.

        Args:
            sched: dict with keys matching default_account_schedule.
                Missing keys will fall back to default values.
                Example: {"enabled": True, "queriesPerHour": 15}
        """
        meta = self.get_meta()
        meta["schedule"] = sched
        self.save_meta(meta)
