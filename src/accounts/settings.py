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
            # OS-level autostart master switch. When True, the app syncs
            # per-account daily scheduled tasks (Windows Task Scheduler /
            # systemd user timers); each account's schedule.run_time
            # decides when its own task fires.
            "autoStartUp": False,
            # When True, clicking the window X hides the app to the system
            # tray instead of quitting. Default True preserves the behavior
            # introduced in v3.3; users who prefer the standard X = quit
            # can flip it off in Settings. Read once at app startup.
            "close_to_tray": True,
            # Default query counts.
            "queries_pc": 30,
            "queries_mobile": 20,
            # LLM-generated search terms (bring-your-own-key). When enabled and
            # a key is present, each phase asks the chosen provider for fresh
            # queries in the user's language; any failure falls back to the
            # static assets/queries.json. The key is stored in plain text here,
            # consistent with the rest of settings.json.
            "use_llm_queries": False,
            "llm_provider": "openai",  # openai | anthropic | gemini
            "llm_model": "",  # blank = provider default
            "llm_api_key": "",
            # Language of generated queries. "auto" resolves from
            # detected_locale (navigator.language) or OS detection.
            "search_locale": "auto",
            "detected_locale": "",  # filled by the GUI from navigator.language
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

    def set_close_to_tray(self, value):
        """Update the close_to_tray flag in settings."""
        settings = self.get_settings()
        settings["close_to_tray"] = bool(value)
        self.save_settings(settings)

    def get_current_account_id(self):
        """Return the current account id from settings."""
        return self.get_settings().get("current_account_id")

    def set_current_account_id(self, account_id):
        """Persist the current account id in settings."""
        settings = self.get_settings()
        settings["current_account_id"] = account_id
        self.save_settings(settings)

    def get_queries_pc(self):
        """Return the saved PC queries count from settings."""
        return self.get_settings().get("queries_pc", 30)

    def set_queries_pc(self, count):
        """Persist the PC queries count in settings."""
        settings = self.get_settings()
        settings["queries_pc"] = max(0, min(130, int(count)))
        self.save_settings(settings)

    def get_queries_mobile(self):
        """Return the saved mobile queries count from settings."""
        return self.get_settings().get("queries_mobile", 20)

    def set_queries_mobile(self, count):
        """Persist the mobile queries count in settings."""
        settings = self.get_settings()
        settings["queries_mobile"] = max(0, min(99, int(count)))
        self.save_settings(settings)

    # ------------------------------------------------------------------
    # LLM-generated search terms + locale
    # ------------------------------------------------------------------

    def get_llm_config(self):
        """Return the LLM query-generation config from settings."""
        s = self.get_settings()
        return {
            "use_llm_queries": bool(s.get("use_llm_queries", False)),
            "llm_provider": s.get("llm_provider", "openai"),
            "llm_model": s.get("llm_model", ""),
            "llm_api_key": s.get("llm_api_key", ""),
            "search_locale": s.get("search_locale", "auto"),
            "detected_locale": s.get("detected_locale", ""),
        }

    def set_llm_config(
        self, use_llm_queries, provider, model, api_key, search_locale="auto"
    ):
        """Persist the LLM query-generation config.

        Unknown providers fall back to "openai"; an empty locale becomes
        "auto". The API key is stored as-is (plain text) alongside the other
        settings.
        """
        from ..search.llm import SUPPORTED_PROVIDERS

        provider = str(provider or "openai").strip().lower()
        if provider not in SUPPORTED_PROVIDERS:
            provider = "openai"

        locale = str(search_locale or "").strip() or "auto"

        settings = self.get_settings()
        settings["use_llm_queries"] = bool(use_llm_queries)
        settings["llm_provider"] = provider
        settings["llm_model"] = str(model or "").strip()
        settings["llm_api_key"] = str(api_key or "").strip()
        settings["search_locale"] = locale
        self.save_settings(settings)

    def set_detected_locale(self, locale):
        """Persist the locale reported by the GUI (navigator.language)."""
        settings = self.get_settings()
        settings["detected_locale"] = str(locale or "").strip()
        self.save_settings(settings)

    def get_effective_locale(self):
        """Return the locale that query generation will actually use."""
        from ..search.locale import resolve_search_locale

        return resolve_search_locale(self.get_settings())
