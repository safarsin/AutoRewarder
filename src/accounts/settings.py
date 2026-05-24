"""App-wide global settings persistence."""

import json
import os

from ..config import APP_DIR, GLOBAL_SETTINGS_PATH

SCHEMA_VERSION = 3


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


class GlobalSettingsManager:
    """
    Manages app-wide (account-agnostic) settings.
    Keys: hide_browser, current_account_id, schema_version.
    """

    def __init__(self):
        self.path = GLOBAL_SETTINGS_PATH

    def get_settings(self):
        """Return settings merged with defaults."""
        defaults = {
            "hide_browser": False,
            "current_account_id": None,
            "schema_version": SCHEMA_VERSION,
            # OS-level autostart. When True, the app registers a Run entry
            # (Windows registry) or a .desktop autostart file (Linux).
            "autoStartUp": False,
        }

        if APP_DIR and not os.path.exists(APP_DIR):
            try:
                os.makedirs(APP_DIR)
            except OSError:
                pass

        if not os.path.exists(self.path):
            # First-launch init. If we can't write (locked/denied), still
            # return defaults so reads don't blow up — the next successful
            # write (via save_settings from a user action) will create it.
            try:
                self.save_settings(defaults)
            except OSError:
                pass
            return defaults

        settings = _read_json(self.path, None)
        if not isinstance(settings, dict):
            # Recovery path: recreate defaults. If the write fails (e.g.
            # transient Windows lock), don't crash the read — caller still
            # gets a valid default dict.
            try:
                self.save_settings(defaults)
            except OSError:
                pass
            return defaults

        # Fill missing defaults without clobbering existing keys.
        merged = {**defaults, **settings}
        return merged

    def save_settings(self, settings):
        """Persist settings to disk."""
        _write_json(self.path, settings)

    def set_hide_browser(self, is_hide):
        """Update the hide_browser flag in settings."""
        settings = self.get_settings()
        settings["hide_browser"] = bool(is_hide)
        self.save_settings(settings)

    def get_current_account_id(self):
        """Return the current account id from settings."""
        return self.get_settings().get("current_account_id")

    def set_current_account_id(self, account_id):
        """Persist the current account id in settings."""
        settings = self.get_settings()
        settings["current_account_id"] = account_id
        self.save_settings(settings)
