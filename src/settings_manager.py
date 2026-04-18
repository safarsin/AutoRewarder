import json
import os

from .config import APP_DIR, GLOBAL_SETTINGS_PATH, account_dir, account_meta_path

SCHEMA_VERSION = 2

DEFAULT_ACCOUNT_SCHEDULE = {
    "enabled": False,
    "time": "09:00",
    "queries": 30,
    "window_hours": 1,
    "last_triggered_date": None,
}


def default_account_schedule():
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
    """Atomically write JSON via a temp file rename."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
    os.replace(temp_path, path)


class GlobalSettingsManager:
    """
    Manages app-wide (account-agnostic) settings.
    Keys: hide_browser, current_account_id, schema_version.
    """

    def __init__(self):
        self.path = GLOBAL_SETTINGS_PATH

    def get_settings(self):
        defaults = {
            "hide_browser": False,
            "current_account_id": None,
            "schema_version": SCHEMA_VERSION,
        }

        if APP_DIR and not os.path.exists(APP_DIR):
            os.makedirs(APP_DIR)

        if not os.path.exists(self.path):
            self.save_settings(defaults)
            return defaults

        settings = _read_json(self.path, None)
        if not isinstance(settings, dict):
            self.save_settings(defaults)
            return defaults

        # Fill missing defaults without clobbering existing keys.
        merged = {**defaults, **settings}
        return merged

    def save_settings(self, settings):
        _write_json(self.path, settings)

    def set_hide_browser(self, is_hide):
        settings = self.get_settings()
        settings["hide_browser"] = bool(is_hide)
        self.save_settings(settings)

    def get_current_account_id(self):
        return self.get_settings().get("current_account_id")

    def set_current_account_id(self, account_id):
        settings = self.get_settings()
        settings["current_account_id"] = account_id
        self.save_settings(settings)


class AccountMetaManager:
    """
    Per-account metadata (currently just first_setup_done).
    Stored at accounts/<account_id>/meta.json.
    """

    def __init__(self, account_id):
        self.account_id = account_id
        self.path = account_meta_path(account_id)

    def get_meta(self):
        defaults = {"first_setup_done": False}

        if not os.path.exists(account_dir(self.account_id)):
            os.makedirs(account_dir(self.account_id), exist_ok=True)

        if not os.path.exists(self.path):
            self.save_meta(defaults)
            return defaults

        meta = _read_json(self.path, None)
        if not isinstance(meta, dict):
            self.save_meta(defaults)
            return defaults

        return {**defaults, **meta}

    def save_meta(self, meta):
        _write_json(self.path, meta)

    def is_first_setup_done(self):
        return bool(self.get_meta().get("first_setup_done"))

    def mark_up_as_done(self):
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
        """Persist this account's schedule. `sched` should be a dict."""
        meta = self.get_meta()
        meta["schedule"] = sched
        self.save_meta(meta)
