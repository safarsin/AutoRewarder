"""Core API for bridging the GUI and automation routines."""

import os
import re
import sys
import time
import json
import math
import random
import platform
import subprocess
import threading
import webbrowser

# `webview` (pywebview) is imported lazily inside `open_history_window` — the
# only method that needs it — so AutoRewarder_CLI.py can import
# AutoRewarderAPI and run headless without dragging in pywebview or its
# display-layer requirements.

from .config import (
    GUI_DIR,
    REPO,
    CURRENT_VERSION,
    JSON_FILE_PATH,
    BASE_DIR,
    edge_profile_path,
    history_path,
    status_path,
)
from .utils import check_for_updates
from .accounts import (
    AccountManager,
    AccountMetaManager,
    GlobalSettingsManager,
)
from .emulator import DriverManager, HumanBehavior, edge_policy
from .search import HistoryManager, SearchEngine
from .dailytasks import DailySet

# Default wall-clock fire time (24h "HH:MM") if an account schedule does
# not yet have a `run_time` value. Each account stores its own time in
# meta.json; this constant is only the fallback default for fresh accounts.
AUTOSTART_TIME = "09:00"

# Naming prefix for the OS-level scheduled task / systemd unit. Each
# account gets its own task: AutoRewarder.<account_id> on Windows,
# autorewarder-<account_id>.{service,timer} on Linux. The unsuffixed
# names (without account_id) are reserved as legacy markers from the
# previous single-task design and only cleaned up, never created.
_AUTOSTART_TASK_NAME = "AutoRewarder"
_SYSTEMD_UNIT_NAME = "autorewarder"

# HH:MM validator — accepts 00:00..23:59.
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _normalize_run_time(value):
    """Return a valid HH:MM string, falling back to AUTOSTART_TIME."""
    if isinstance(value, str) and _TIME_RE.match(value.strip()):
        return value.strip()
    return AUTOSTART_TIME


class AutoRewarderAPI:
    """
    Core API class for AutoRewarder.

    Bridges the pywebview GUI and the Selenium automation. Multi-account aware:
    the driver, history, daily-set, and meta managers are rebuilt whenever the
    currently-selected account changes.
    """

    def __init__(self):
        self._webview_window = None
        self._driver_loader_thread_started = False
        self._update_check_started = False
        self._driver = None
        self.is_driver_loading = False
        self._run_lock = threading.Lock()
        # Set when the user clicks Stop. Long loops in search_engine and
        # daily_set poll this between iterations and bail out cleanly.
        self._stop_event = threading.Event()

        # Global (app-wide) settings. Per-account data is handled below.
        self.global_settings = GlobalSettingsManager()
        self.hide_browser = bool(
            self.global_settings.get_settings().get("hide_browser", False)
        )

        # Account layer: migration runs here. `account_manager` is the source of
        # truth for the dropdown.
        self.account_manager = AccountManager(
            self.global_settings, logger=self._safe_log
        )
        self.account_manager.migrate_legacy()

        # Per-account managers: rebuilt each time the active account changes.
        self.driver_manager = None
        self.history = None
        self.daily_set = None
        self.account_meta = None
        self.search_engine = None

        self._rebuild_account_context()

        # One-shot migration: lift any pre-existing global schedule (v1 feature)
        # into the per-account meta.json it referenced.
        self._migrate_legacy_global_schedule()

        # One-shot migration: lift any pre-existing fire-on-login autostart
        # (HKCU Run / .desktop) into the new daily scheduled task / systemd
        # timer. Otherwise a previously-enabled autostart would keep opening
        # a visible GUI at every login until the user manually toggles.
        self._migrate_legacy_autostart()

        # Scheduled runs are driven by the OS autostart entry which launches
        # `AutoRewarder.py --headless` → `AutoRewarder_CLI.main()`. No in-app
        # daemon thread.

    # ------------------------------------------------------------------
    # Context lifecycle
    # ------------------------------------------------------------------

    def _rebuild_account_context(self):
        """(Re)build the per-account managers based on the currently-selected account."""
        current_id = self.account_manager.current_id()

        if current_id:
            profile = edge_profile_path(current_id)
            self.account_meta = AccountMetaManager(current_id)
            self.history = HistoryManager(history_path(current_id), logger=self.log)
            self.daily_set = DailySet(status_path(current_id), logger=self.log)
            self.driver_manager = DriverManager(
                profile_path=profile, hide_browser=self.hide_browser
            )
            self.search_engine = SearchEngine(logger=self.log, history=self.history)
        else:
            self.account_meta = None
            self.history = None
            self.daily_set = None
            self.driver_manager = DriverManager(
                profile_path=None, hide_browser=self.hide_browser
            )
            self.search_engine = SearchEngine(logger=self.log, history=None)

    # ------------------------------------------------------------------
    # Webview plumbing
    # ------------------------------------------------------------------

    def set_window(self, window):
        """
        Attach the webview window and start background tasks.

        Args:
            window: The webview window to attach.
        """
        self._webview_window = window
        self.start_update_check()

        if not self._driver_loader_thread_started:
            self._driver_loader_thread_started = True
            threading.Thread(target=self.load_driver_in_background, daemon=True).start()

    def _safe_log(self, message):
        """
        Log wrapper usable before the webview window is attached.

        Args:
            message (str): The message to log.
        """
        if self._webview_window:
            self.log(message)
        else:
            print(message)

    def open_history_window(self):
        """Open the history viewer window."""
        # Local import: pywebview is a GUI-only dependency, kept out of the
        # headless CLI import chain (see comment at top of this module).
        import webview

        webview.create_window(
            title="Query History",
            url=os.path.join(GUI_DIR, "history.html"),
            js_api=self,
            width=700,
            height=500,
            resizable=True,
            background_color="#0d1117",
            text_select=True,
        )

    def start_update_check(self):
        """Start a one-time background update check."""
        if self._update_check_started:
            return
        self._update_check_started = True
        threading.Thread(target=self.run_update_check, daemon=True).start()

    def run_update_check(self):
        """Check for updates and notify the UI when a newer version exists."""
        try:
            needs_update, latest_version = check_for_updates(logger=self.log)
        except Exception as e:
            self.log(f"[ERROR] Error checking for updates: {e}")
            return

        if not needs_update or not latest_version:
            return
        if not self._webview_window:
            return

        url = f"https://github.com/{REPO}/releases/latest"
        msg = (
            f"Update available: {latest_version} (current {CURRENT_VERSION}).\n"
            f"Link added to the log area. "
            f"Please download the latest version for better performance and "
            f"to avoid potential issues due to Microsoft updates."
        )

        # Structured call into JS: the text, the link label and the URL are
        # each passed as plain arguments (via json.dumps), and update_log_link
        # builds the <a> element with createElement/textContent — no HTML
        # parsing, so nothing user-controllable can inject markup.
        try:
            self._webview_window.evaluate_js(
                "update_log_link("
                f"{json.dumps(f'New version {latest_version} available.')}, "
                f"{json.dumps('Click here to download')}, "
                f"{json.dumps(url)})"
            )
        except Exception as e:
            self.log(f"[ERROR] Error displaying update link: {e}")

        try:
            self._webview_window.evaluate_js(f"alert({json.dumps(msg)})")
        except Exception as e:
            self.log(f"[ERROR] Error displaying update alert: {e}")

    def open_link(self, url):
        """Open a URL in the system default browser."""
        webbrowser.open(url)

    def load_driver_in_background(self):
        """Warmup the WebDriver download, only if an account is selected."""
        if self.account_manager.current_id() is None:
            # Nothing to warm up; empty state.
            if self._webview_window:
                self._webview_window.evaluate_js("stop_loader()")
            return

        self.is_driver_loading = True
        try:
            warmup_driver = self.driver_manager.setup_driver(headless=True)
            warmup_driver.quit()
        except Exception as e:
            self.log(f"[ERROR] Error loading WebDriver: {e}")
        finally:
            self.is_driver_loading = False
            if self._webview_window:
                self._webview_window.evaluate_js("stop_loader()")

    def check_driver_status(self):
        """Return True while the driver warmup thread is active."""
        return self.is_driver_loading

    # ------------------------------------------------------------------
    # Exposed to JS: global settings
    # ------------------------------------------------------------------

    def get_settings(self):
        """Return global settings (hide_browser, current_account_id, schema_version)."""
        return self.global_settings.get_settings()

    def set_hide_browser(self, is_hide):
        """
        Persist and apply the hide-browser setting.

        Args:
            is_hide (bool): True to hide the browser, False to show it.

        Returns:
            bool: True if the setting was successfully updated, False otherwise.
        """
        self.hide_browser = bool(is_hide)
        if self.driver_manager is not None:
            self.driver_manager.hide_browser = bool(is_hide)
        self.global_settings.set_hide_browser(is_hide)
        self.log(f"Browser hidden mode: {'ON' if is_hide else 'OFF'}")

    def get_close_to_tray(self):
        """Return whether the window X-close should minimize to tray."""
        return bool(self.global_settings.get_settings().get("close_to_tray", True))

    def set_close_to_tray(self, value):
        """
        Persist the close-to-tray setting. Reads at app startup, so a
        change only takes effect on the next launch.

        Args:
            value (bool): True to hide the window on X (close-to-tray),
                False to quit the app entirely on X.
        """
        self.global_settings.set_close_to_tray(value)
        state = "ON (X → tray)" if value else "OFF (X → quit)"
        self.log(f"Close-to-tray: {state}. Restart to apply.")

    def get_queries_counts(self):
        """
        Return the saved PC and Mobile query counts from global settings.

        Returns:
            dict: {"queries_pc": int, "queries_mobile": int}
        """
        return {
            "queries_pc": self.global_settings.get_queries_pc(),
            "queries_mobile": self.global_settings.get_queries_mobile(),
        }

    def set_queries_counts(self, queries_pc, queries_mobile):
        """
        Save PC and Mobile query counts to global settings.

        Args:
            queries_pc (int): Number of PC searches.
            queries_mobile (int): Number of mobile searches.

        Returns:
            bool: True if successfully saved, False otherwise.
        """
        try:
            before = (
                self.global_settings.get_queries_pc(),
                self.global_settings.get_queries_mobile(),
            )

            self.global_settings.set_queries_pc(queries_pc)
            self.global_settings.set_queries_mobile(queries_mobile)

            after = (
                self.global_settings.get_queries_pc(),
                self.global_settings.get_queries_mobile(),
            )

            if after != before:
                self.log(f"Search counts saved: PC={after[0]}, Mobile={after[1]}")
            return True
        except Exception as e:
            self.log(f"[WARNING] Failed to save search counts: {e}")
            return False

    # ------------------------------------------------------------------
    # Exposed to JS: per-account schedule + startup
    # ------------------------------------------------------------------

    def is_running(self):
        """True when the bot is mid-run. Used by the headless runner to avoid overlap."""
        return self._run_lock.locked()

    def stop(self):
        """
        User-initiated graceful stop.

        Sets the stop flag so cooperating loops (searches, daily set) bail at
        the next checkpoint, and force-quits the active driver to break any
        in-progress Selenium call. The current run thread will exit through
        its normal `finally` cleanup, which re-enables the Start button.
        """
        if not self._run_lock.locked():
            return False

        self.log("Stop requested. Closing browser…")
        self._stop_event.set()

        try:
            if self._driver is not None:
                self._driver.quit()
        except Exception:
            pass
        return True

    def get_schedule(self, account_id):
        """Return a specific account's schedule (defaults merged in)."""
        if not account_id or not self.account_manager.exists(account_id):
            return None
        return AccountMetaManager(account_id).get_schedule()

    def get_all_schedules(self):
        """Return [{id, label, first_setup_done, schedule}] for the settings modal."""
        result = []
        for acc in self.account_manager.list():
            result.append(
                {
                    "id": acc["id"],
                    "label": acc["label"],
                    "first_setup_done": acc["first_setup_done"],
                    "schedule": AccountMetaManager(acc["id"]).get_schedule(),
                }
            )
        return result

    def set_schedule(self, account_id, payload):
        """
        Persist the schedule for a specific account.
        `payload` accepts: enabled, advancedScheduling, runDuration (1..24),
        queriesPerHour (1..99), queries_pc (0..130), queries_mobile (0..99),
        run_time (HH:MM 24h). Unknown keys are ignored.

        After persisting, if the global "Start with Windows/Linux" toggle
        is on, the account's OS-level scheduled task is (re)created or
        removed to match the new state.

        Args:
            account_id (str): The ID of the account to set the schedule for.
            payload (dict): The schedule settings to persist.

        Returns:
            bool: True if the schedule was successfully updated, False otherwise.
        """
        if not account_id or not self.account_manager.exists(account_id):
            return False
        if not isinstance(payload, dict):
            return False

        meta = AccountMetaManager(account_id)
        current = meta.get_schedule()

        def _pick(key, default):
            return payload[key] if key in payload else default

        new = {
            "enabled": bool(_pick("enabled", current["enabled"])),
            "advancedScheduling": bool(
                _pick("advancedScheduling", current["advancedScheduling"])
            ),
            "runDuration": max(
                1, min(24, int(_pick("runDuration", current["runDuration"])))
            ),
            "queriesPerHour": max(
                1, min(99, int(_pick("queriesPerHour", current["queriesPerHour"])))
            ),
            "queries_pc": max(
                0, min(130, int(_pick("queries_pc", current["queries_pc"])))
            ),
            "queries_mobile": max(
                0, min(99, int(_pick("queries_mobile", current["queries_mobile"])))
            ),
            "run_time": _normalize_run_time(_pick("run_time", current.get("run_time"))),
            # Reset the daily-dedup marker so the edited schedule can still fire today.
            "last_triggered_date": None,
        }
        meta.set_schedule(new)

        label = self.account_manager.get(account_id)
        label = label["label"] if label else account_id
        if new["enabled"]:
            mode = "advanced" if new["advancedScheduling"] else "simple"
            self.log(
                f"Schedule '{label}' ({mode}) @ {new['run_time']}: "
                f"PC={new['queries_pc']}, Mobile={new['queries_mobile']}, "
                f"{new['runDuration']}h @ {new['queriesPerHour']}/h"
            )
        else:
            self.log(f"Schedule '{label}' disabled.")

        # Re-sync the OS-level scheduled task. _sync_account_autostart
        # itself respects the global Start-with-Windows toggle and the
        # new schedule.enabled value, so it correctly creates / updates
        # / removes the task in any state.
        try:
            self._sync_account_autostart(account_id)
        except Exception as e:
            self.log(f"[WARNING] Failed to sync autostart for '{label}': {e}")

        return True

    def _migrate_legacy_global_schedule(self):
        """
        Clean up any pre-existing global `schedule` key left over from an
        earlier version of this branch. The schedule now lives in each
        account's meta.json, so we just drop the global one. Anything
        valuable was already migrated during a previous upgrade cycle.
        """
        settings = self.global_settings.get_settings()
        if "schedule" in settings:
            settings.pop("schedule", None)
            self.global_settings.save_settings(settings)

    def _detect_legacy_autostart(self):
        """
        Return True if any pre-per-account autostart artifact exists on
        this system. Used both by the migration path and by every
        startup so stale legacy entries get cleaned up even when the
        user has already moved to the per-account model.

        Recognised sources:
          * Fire-on-login: HKCU Run (Windows) / .desktop (Linux)
          * Single-task daily scheduler: schtasks `AutoRewarder` /
            systemd `autorewarder.timer` (v3.3 single-task design)
        """
        system = platform.system()
        if system == "Windows":
            try:
                import winreg

                run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_READ
                ) as key:
                    winreg.QueryValueEx(key, _AUTOSTART_TASK_NAME)
                    return True
            except Exception:
                pass
            try:
                result = subprocess.run(
                    ["schtasks", "/Query", "/TN", _AUTOSTART_TASK_NAME],
                    capture_output=True,
                    creationflags=0x08000000,
                )
                if result.returncode == 0:
                    return True
            except Exception:
                pass
        elif system == "Linux":
            try:
                if os.path.exists(self._legacy_linux_autostart_path()):
                    return True
            except Exception:
                pass
            try:
                timer_path = os.path.join(
                    self._systemd_user_dir(),
                    f"{_SYSTEMD_UNIT_NAME}.timer",
                )
                if os.path.exists(timer_path):
                    return True
            except Exception:
                pass
        return False

    # Bumped whenever the format of registered scheduled tasks changes in
    # a way that requires re-creating existing tasks on disk:
    #   * v1 switched dev-mode commands from python.exe to pythonw.exe
    #     to avoid the console-window flash.
    #   * v2 switched Windows registration from `schtasks /Create /SC DAILY
    #     /ST HH:MM` (flag form) to `schtasks /Create /XML <file>` so the
    #     resulting task carries StartWhenAvailable=true — without it,
    #     Windows silently skips daily triggers that fired while the
    #     machine was off, unlike systemd's Persistent=true on Linux.
    # Stored in global_settings as `autostart_schema_version`. Users on
    # autoStartUp=True with a lower version get all their tasks re-
    # registered on next launch.
    _AUTOSTART_SCHEMA_VERSION = 2

    def _migrate_legacy_autostart(self):
        """
        Two cleanup paths on every app launch:

        1. Legacy artifact exists → idempotent cleanup. Never auto-
           enables autostart, even if the user previously had it on
           under the old model: their explicit intent is whatever
           `autoStartUp` says today. If they want per-account
           autostart back, they re-toggle Start-with-Windows in
           Settings.
        2. User is on per-account model (autoStartUp=True) AND
           `autostart_schema_version` is below current → re-register
           every task so format changes (e.g. python.exe → pythonw.exe)
           take effect without the user having to toggle anything.

        Failures are logged but swallowed — a stale legacy entry is
        not worth crashing app startup.
        """
        legacy = self._detect_legacy_autostart()
        try:
            settings = self.global_settings.get_settings()
            autostartup = bool(settings.get("autoStartUp", False))
            schema_v = int(settings.get("autostart_schema_version", 0))
        except Exception:
            return

        needs_resync = autostartup and schema_v < self._AUTOSTART_SCHEMA_VERSION

        if not legacy and not needs_resync:
            return

        if legacy:
            self._safe_log("Cleaning up stale legacy autostart entries...")
            try:
                self._cleanup_legacy_autostart()
            except Exception as e:
                self._safe_log(f"[WARNING] Legacy cleanup failed: {e}")

        if needs_resync:
            self._safe_log(
                f"Refreshing per-account scheduled tasks "
                f"(schema v{self._AUTOSTART_SCHEMA_VERSION})..."
            )
            try:
                self._sync_all_autostart()
            except Exception as e:
                self._safe_log(f"[WARNING] Autostart refresh failed: {e}")

        # Mark current schema applied so we don't re-run unnecessarily.
        try:
            settings = self.global_settings.get_settings()
            settings["autostart_schema_version"] = self._AUTOSTART_SCHEMA_VERSION
            self.global_settings.save_settings(settings)
        except Exception:
            pass

    # ---- Autostart (OS-level) — ported from v3.1 main -----------------

    def _autostart_command(self, account_id):
        """
        Command string registered for an account's daily scheduled run.

        Args:
            account_id (str): the account this scheduled task targets.
                Passed to the CLI as `--account <id>` so the headless run
                only processes that account, regardless of which other
                accounts are enabled.

        Returns:
            str: The command to execute for autostart, which varies based on
                whether the app is frozen (packaged) or running in development mode.
        """
        # Frozen build: call the bundled exe with --headless --account <id>.
        # PyInstaller's `console=False` in AutoRewarder.spec means the exe
        # itself has no console, so this fires silently.
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --headless --account {account_id}'

        # Dev mode: prefer pythonw.exe on Windows. python.exe is the console
        # variant, so when Task Scheduler fires it Windows allocates a
        # console window — visible flash at every trigger. pythonw.exe is
        # the same interpreter without that console. Falls back to whatever
        # sys.executable is if pythonw isn't there (custom layout).
        python_exe = sys.executable
        if platform.system() == "Windows":
            candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if os.path.exists(candidate):
                python_exe = candidate
        entry = os.path.join(BASE_DIR, "AutoRewarder.py")
        return f'"{python_exe}" "{entry}" --headless --account {account_id}'

    # ---- Per-account OS-task naming -----------------------------------

    def _windows_task_name(self, account_id):
        """schtasks task name for a specific account."""
        return f"{_AUTOSTART_TASK_NAME}.{account_id}"

    def _systemd_unit_base(self, account_id):
        """Base name for the systemd service + timer of a specific account."""
        return f"{_SYSTEMD_UNIT_NAME}-{account_id}"

    # ------------------------------------------------------------------
    # Autostart — daily scheduled task (Windows Task Scheduler / systemd
    # user timer). Replaces the previous "fire on login" model so a daily
    # run still happens even when the machine stays logged in for days.
    # ------------------------------------------------------------------

    def _systemd_user_dir(self):
        return os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")

    def _legacy_linux_autostart_path(self):
        """Old .desktop autostart path — kept only for migration cleanup."""
        return os.path.join(
            os.path.expanduser("~"), ".config", "autostart", "AutoRewarder.desktop"
        )

    def _cleanup_legacy_autostart(self):
        """
        Remove pre-per-account autostart entries:
          * HKCU Run / .desktop (the original fire-on-login mechanism)
          * Single-task `AutoRewarder` schtasks / `autorewarder.timer`
            systemd unit (the v3.3 single-task daily scheduler)

        Idempotent — safe to call on every startup. Outcomes are logged
        so that a silent failure can be diagnosed instead of leaving a
        stale task to fire alongside the new per-account ones.
        """
        system = platform.system()
        if system == "Windows":
            # HKCU Run value.
            try:
                import winreg

                run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE
                ) as key:
                    try:
                        winreg.DeleteValue(key, _AUTOSTART_TASK_NAME)
                        self.log("Removed legacy HKCU Run autostart entry")
                    except FileNotFoundError:
                        pass
            except Exception:
                pass
            # Single-task daily scheduler from the v3.3 design.
            # Only attempt delete if it actually exists, so failures are
            # always meaningful (don't log "delete failed" for tasks
            # that were never there).
            try:
                q = subprocess.run(
                    ["schtasks", "/Query", "/TN", _AUTOSTART_TASK_NAME],
                    capture_output=True,
                    text=True,
                    creationflags=0x08000000,
                )
                if q.returncode == 0:
                    d = subprocess.run(
                        [
                            "schtasks",
                            "/Delete",
                            "/TN",
                            _AUTOSTART_TASK_NAME,
                            "/F",
                        ],
                        capture_output=True,
                        text=True,
                        creationflags=0x08000000,
                    )
                    if d.returncode == 0:
                        self.log("Removed legacy single-task scheduler")
                    else:
                        msg = (d.stderr or d.stdout or "").strip()
                        self.log(
                            f"[WARNING] Could not delete legacy task "
                            f"'{_AUTOSTART_TASK_NAME}': {msg}"
                        )
            except FileNotFoundError:
                # schtasks not on PATH — nothing we can do.
                pass
            except Exception as e:
                self.log(f"[WARNING] Legacy schtasks cleanup error: {e}")
        elif system == "Linux":
            old_desktop = self._legacy_linux_autostart_path()
            if os.path.exists(old_desktop):
                try:
                    os.remove(old_desktop)
                    self.log("Removed legacy .desktop autostart entry")
                except OSError as e:
                    self.log(f"[WARNING] Could not remove .desktop: {e}")
            # Single-task systemd timer from the v3.3 design.
            base = self._systemd_user_dir()
            old_service = os.path.join(base, f"{_SYSTEMD_UNIT_NAME}.service")
            old_timer = os.path.join(base, f"{_SYSTEMD_UNIT_NAME}.timer")
            if os.path.exists(old_timer) or os.path.exists(old_service):
                try:
                    subprocess.run(
                        [
                            "systemctl",
                            "--user",
                            "disable",
                            "--now",
                            f"{_SYSTEMD_UNIT_NAME}.timer",
                        ],
                        capture_output=True,
                    )
                except Exception:
                    pass
                removed = False
                for path in (old_service, old_timer):
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                            removed = True
                        except OSError as e:
                            self.log(f"[WARNING] Could not remove {path}: {e}")
                if removed:
                    self.log("Removed legacy single-task systemd timer")
                try:
                    subprocess.run(
                        ["systemctl", "--user", "daemon-reload"],
                        capture_output=True,
                    )
                except Exception:
                    pass

    # ---- Per-account OS-task management -------------------------------

    def _autostart_exec_and_args(self, account_id):
        """
        Split the autostart command into (executable, arguments) for the
        Task Scheduler XML Action element, which expects them separately.
        Mirrors the same dev-vs-frozen logic as _autostart_command.
        """
        if getattr(sys, "frozen", False):
            return sys.executable, f"--headless --account {account_id}"

        python_exe = sys.executable
        candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(candidate):
            python_exe = candidate
        entry = os.path.join(BASE_DIR, "AutoRewarder.py")
        return python_exe, f'"{entry}" --headless --account {account_id}'

    def _build_windows_task_xml(self, account_id, run_time, label):
        """
        Build a Task Scheduler 1.2 XML for a daily run.

        Key setting: <StartWhenAvailable>true</StartWhenAvailable>. Without
        it, Windows silently skips a trigger that fired while the machine
        was off (unlike systemd's Persistent=true). With it, the task
        runs as soon as possible after the missed time at the next boot —
        matching the Linux behavior.

        Also: <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
        so laptop users on battery still get their run.
        """
        executable, arguments = self._autostart_exec_and_args(account_id)

        def esc(s):
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;")
            )

        description = f"AutoRewarder daily run ({label})"
        # Past anchor date — only the HH:MM portion of StartBoundary
        # matters for DaysInterval=1 recurrence.
        start_boundary = f"2025-01-01T{run_time}:00"

        return (
            '<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
            "  <RegistrationInfo>\n"
            f"    <Description>{esc(description)}</Description>\n"
            "  </RegistrationInfo>\n"
            "  <Triggers>\n"
            "    <CalendarTrigger>\n"
            f"      <StartBoundary>{start_boundary}</StartBoundary>\n"
            "      <Enabled>true</Enabled>\n"
            "      <ScheduleByDay>\n"
            "        <DaysInterval>1</DaysInterval>\n"
            "      </ScheduleByDay>\n"
            "    </CalendarTrigger>\n"
            "  </Triggers>\n"
            "  <Principals>\n"
            '    <Principal id="Author">\n'
            "      <LogonType>InteractiveToken</LogonType>\n"
            "      <RunLevel>LeastPrivilege</RunLevel>\n"
            "    </Principal>\n"
            "  </Principals>\n"
            "  <Settings>\n"
            "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
            "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
            "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
            "    <AllowHardTerminate>true</AllowHardTerminate>\n"
            "    <StartWhenAvailable>true</StartWhenAvailable>\n"
            "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
            "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
            "    <Enabled>true</Enabled>\n"
            "    <Hidden>false</Hidden>\n"
            "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
            "    <WakeToRun>false</WakeToRun>\n"
            "    <ExecutionTimeLimit>PT72H</ExecutionTimeLimit>\n"
            "    <Priority>7</Priority>\n"
            "  </Settings>\n"
            '  <Actions Context="Author">\n'
            "    <Exec>\n"
            f"      <Command>{esc(executable)}</Command>\n"
            f"      <Arguments>{esc(arguments)}</Arguments>\n"
            "    </Exec>\n"
            "  </Actions>\n"
            "</Task>\n"
        )

    def _register_windows_task(self, account_id, run_time, label=None):
        """
        Register a daily scheduled task via XML import.

        Why XML instead of `schtasks /SC DAILY /ST HH:MM` flags: the
        flag form doesn't expose StartWhenAvailable, so a trigger that
        fires while the machine is off is silently skipped forever.
        The XML form lets us flip StartWhenAvailable=true so a missed
        trigger catches up at next boot — same behavior as systemd's
        Persistent=true on the Linux side.
        """
        import tempfile

        xml_body = self._build_windows_task_xml(
            account_id, run_time, label or account_id
        )

        # schtasks /XML reads the task definition from disk; UTF-16 is
        # the encoding Task Scheduler expects (the XML decl says so and
        # schtasks refuses UTF-8 without a BOM on some Windows builds).
        fd, xml_path = tempfile.mkstemp(suffix=".xml", prefix="autorewarder-task-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(xml_body.encode("utf-16"))

            result = subprocess.run(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    self._windows_task_name(account_id),
                    "/XML",
                    xml_path,
                    "/F",
                ],
                capture_output=True,
                text=True,
                creationflags=0x08000000,
            )
            if result.returncode != 0:
                self.log(
                    f"[ERROR] schtasks create failed for {label or account_id}: "
                    f"{(result.stderr or result.stdout).strip()}"
                )
                return False
            self.log(
                f"Scheduled task registered: '{label or account_id}' at {run_time}"
            )
            return True
        except FileNotFoundError:
            self.log("[ERROR] schtasks not found — Task Scheduler unavailable.")
            return False
        except Exception as e:
            self.log(f"[ERROR] Failed to register Windows task: {e}")
            return False
        finally:
            try:
                os.remove(xml_path)
            except OSError:
                pass

    def _remove_windows_task(self, account_id):
        """schtasks /Delete an account's daily task (idempotent)."""
        try:
            subprocess.run(
                [
                    "schtasks",
                    "/Delete",
                    "/TN",
                    self._windows_task_name(account_id),
                    "/F",
                ],
                capture_output=True,
                creationflags=0x08000000,
            )
            return True
        except Exception:
            return False

    def _register_systemd_unit(self, account_id, run_time, label=None):
        """Write + enable a per-account systemd .service + .timer."""
        try:
            base = self._systemd_user_dir()
            unit_base = self._systemd_unit_base(account_id)
            service_path = os.path.join(base, f"{unit_base}.service")
            timer_path = os.path.join(base, f"{unit_base}.timer")
            timer_unit = f"{unit_base}.timer"

            os.makedirs(base, exist_ok=True)
            cmd = self._autostart_command(account_id)
            desc_label = label or account_id
            service_file = (
                "[Unit]\n"
                f"Description=AutoRewarder daily run ({desc_label})\n\n"
                "[Service]\n"
                "Type=oneshot\n"
                f"ExecStart={cmd}\n"
            )
            timer_file = (
                "[Unit]\n"
                f"Description=Run AutoRewarder daily ({desc_label})\n\n"
                "[Timer]\n"
                f"OnCalendar=*-*-* {run_time}:00\n"
                "Persistent=true\n"
                f"Unit={unit_base}.service\n\n"
                "[Install]\n"
                "WantedBy=timers.target\n"
            )
            with open(service_path, "w", encoding="utf-8") as fh:
                fh.write(service_file)
            with open(timer_path, "w", encoding="utf-8") as fh:
                fh.write(timer_file)

            subprocess.run(
                ["systemctl", "--user", "daemon-reload"], capture_output=True
            )
            result = subprocess.run(
                ["systemctl", "--user", "enable", "--now", timer_unit],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.log(
                    f"[ERROR] systemctl enable failed for {desc_label}: "
                    f"{(result.stderr or result.stdout).strip()}"
                )
                return False
            self.log(f"Scheduled timer registered: '{desc_label}' at {run_time}")
            return True
        except FileNotFoundError:
            self.log("[ERROR] systemctl not found — systemd unavailable.")
            return False
        except Exception as e:
            self.log(f"[ERROR] Failed to register systemd timer: {e}")
            return False

    def _remove_systemd_unit(self, account_id):
        """Disable + delete an account's systemd service + timer."""
        try:
            base = self._systemd_user_dir()
            unit_base = self._systemd_unit_base(account_id)
            service_path = os.path.join(base, f"{unit_base}.service")
            timer_path = os.path.join(base, f"{unit_base}.timer")
            timer_unit = f"{unit_base}.timer"

            subprocess.run(
                ["systemctl", "--user", "disable", "--now", timer_unit],
                capture_output=True,
            )
            for path in (service_path, timer_path):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"], capture_output=True
            )
            return True
        except Exception:
            return False

    def _remove_account_autostart(self, account_id):
        """Remove an account's OS-level scheduled task (platform-aware)."""
        system = platform.system()
        if system == "Windows":
            return self._remove_windows_task(account_id)
        if system == "Linux":
            return self._remove_systemd_unit(account_id)
        return False

    def _sync_account_autostart(self, account_id):
        """
        Bring one account's OS-level scheduled task in sync with its
        meta.json schedule. Called whenever set_schedule mutates an
        account, or the global Start-with-Windows toggle is flipped on.

        Semantics:
          * Global toggle OFF → always remove (regardless of schedule.enabled)
          * Account doesn't exist anymore → remove
          * schedule.enabled = False → remove
          * Otherwise → register at schedule.run_time
        """
        if not self.is_autostart_enabled():
            self._remove_account_autostart(account_id)
            return False

        if not self.account_manager.exists(account_id):
            self._remove_account_autostart(account_id)
            return False

        meta = AccountMetaManager(account_id)
        sched = meta.get_schedule()
        if not sched.get("enabled"):
            self._remove_account_autostart(account_id)
            return True

        run_time = _normalize_run_time(sched.get("run_time"))
        acc = self.account_manager.get(account_id)
        label = acc["label"] if acc else account_id

        system = platform.system()
        if system == "Windows":
            return self._register_windows_task(account_id, run_time, label)
        if system == "Linux":
            return self._register_systemd_unit(account_id, run_time, label)
        self.log("Autostart is only supported on Windows and Linux.")
        return False

    def _sync_all_autostart(self):
        """Iterate every account and re-sync its scheduled task."""
        for acc in self.account_manager.list():
            try:
                self._sync_account_autostart(acc["id"])
            except Exception as e:
                self.log(f"[WARNING] Sync failed for {acc.get('label')}: {e}")

    def _set_autostart_registry(self, enable):
        """
        Global autostart master toggle. Persists the user's intent in
        global settings (`autoStartUp`) and syncs every account's OS-level
        scheduled task to match.

          * enable=True  → autoStartUp=True; create a task for each
                           account whose schedule.enabled=True at its
                           own schedule.run_time.
          * enable=False → autoStartUp=False; remove every per-account
                           task that we might have registered.

        Legacy entries (HKCU Run, .desktop, single-task daily scheduler)
        are always cleaned up on either path.
        """
        system_name = platform.system()
        if system_name not in ("Windows", "Linux"):
            self.log("Autostart is only supported on Windows and Linux.")
            return False

        # Persist user intent FIRST so _sync_account_autostart reads the
        # new value when it queries is_autostart_enabled().
        settings = self.global_settings.get_settings()
        settings["autoStartUp"] = bool(enable)
        self.global_settings.save_settings(settings)

        # Always clean up legacy single-task / fire-on-login entries.
        self._cleanup_legacy_autostart()

        if not enable:
            # Remove every per-account task that might have been registered.
            for acc in self.account_manager.list():
                self._remove_account_autostart(acc["id"])
            self.log("Autostart disabled (all per-account tasks removed)")
            return True

        # Enable path: register tasks for every account with schedule.enabled.
        self._sync_all_autostart()
        self.log("Autostart enabled (per-account scheduled tasks registered)")
        return True

    def is_autostart_enabled(self):
        """Return True if the global 'Start with Windows/Linux' toggle is on.

        Per-account OS tasks are derived from this AND each account's
        schedule.enabled — the toggle here is the master switch.
        """
        try:
            return bool(self.global_settings.get_settings().get("autoStartUp", False))
        except Exception:
            return False

    def get_launch_on_startup(self):
        """Return OS support flag + current autostart state for the Settings UI."""
        system_name = platform.system()
        return {
            "supported": system_name in ("Windows", "Linux"),
            "enabled": self.is_autostart_enabled(),
        }

    def set_launch_on_startup(self, enabled):
        """
        Register or unregister the OS autostart entry. Called from JS.

        Args:
            enabled (bool): True to enable autostart, False to disable.

        Returns:
            bool: True if the operation succeeded, False otherwise.
        """
        ok = self._set_autostart_registry(bool(enabled))
        if ok:
            # Mirror the state into global settings.json for the UI.
            settings = self.global_settings.get_settings()
            settings["autoStartUp"] = bool(enabled)
            self.global_settings.save_settings(settings)
        return ok

    # ------------------------------------------------------------------
    # Exposed to JS: accounts
    # ------------------------------------------------------------------

    def list_accounts(self):
        """Return accounts for UI display."""
        return self.account_manager.list()

    def get_current_account(self):
        """Return the currently selected account, or None."""
        return self.account_manager.get_current()

    def create_account(self, label):
        """
        Create a new account, select it, and run First Setup against it.
        On setup failure (user closes browser without logging in), rolls back
        and restores the previously-selected account.

        Args:
            label (str): The user-friendly label for the new account.

        Returns:
            dict: {ok (bool), id (str), label (str)} on success, or {ok: False, error: str} on failure.
        """
        if self._run_lock.locked():
            self.log("[WARNING] Cannot add an account while the bot is running.")
            return {"ok": False, "error": "bot_running"}

        previous_id = self.account_manager.current_id()
        new_account = self.account_manager.create(label)
        new_id = new_account["id"]

        self.account_manager.select(new_id)
        self._rebuild_account_context()
        self._broadcast_account_ui()

        success = self._run_first_setup_for_current()

        if not success:
            # Rollback: drop the new account and restore previous.
            self.account_manager.delete(new_id)
            self.account_manager.select(previous_id)
            self._rebuild_account_context()
            self._broadcast_account_ui()
            return {"ok": False, "error": "setup_failed", "id": new_id}

        return {"ok": True, "id": new_id, "label": new_account["label"]}

    def switch_account(self, account_id):
        """
        Switch to the specified account if possible.

        Args:
            account_id (str): The ID of the account to switch to.

        Returns:
            bool: True if switching succeeded, False otherwise.
        """
        if self._run_lock.locked():
            self.log("[WARNING] Cannot switch account while the bot is running.")
            return False
        if not self.account_manager.exists(account_id):
            self.log(f"[ERROR] Unknown account: {account_id}")
            return False

        self.account_manager.select(account_id)
        self._rebuild_account_context()
        current = self.account_manager.get_current()
        if current:
            self.log(f"Switched to account '{current['label']}'.")
        self._broadcast_account_ui()
        return True

    def rename_account(self, account_id, new_label):
        """
        Rename an account label.

        Args:
            account_id (str): The ID of the account to rename.
            new_label (str): The new label for the account.

        Returns:
            bool: True if renaming succeeded, False otherwise.
        """
        try:
            self.account_manager.rename(account_id, new_label)
        except ValueError as e:
            self.log(f"[ERROR] {e}")
            return False
        self._broadcast_account_ui()
        return True

    def delete_account(self, account_id):
        """
        Delete an account and refresh the UI.

        Args:
            account_id (str): The ID of the account to delete.

        Returns:
            bool: True if deletion succeeded, False if the account is active or on error.
        """
        if self._run_lock.locked() and account_id == self.account_manager.current_id():
            self.log(
                "[WARNING] Cannot delete the active account while the bot is running."
            )
            return False

        # Tear down the account's OS-level scheduled task BEFORE deletion
        # so the task name (which embeds the account_id) is still
        # resolvable. Idempotent — no-op if no task was registered.
        try:
            self._remove_account_autostart(account_id)
        except Exception as e:
            self.log(f"[WARNING] Failed to remove scheduled task: {e}")

        try:
            self.account_manager.delete(account_id)
        except ValueError as e:
            self.log(f"[ERROR] {e}")
            return False

        self._rebuild_account_context()
        self._broadcast_account_ui()
        return True

    def rerun_setup(self, account_id):
        """
        Re-run First Setup for an existing account (e.g. profile got corrupted).
        Temporarily switches to it if not current, then restores previous.

        Args:
            account_id (str): The ID of the account to run setup for.

        Returns:
            bool: True if setup succeeded, False on failure or if the bot is running.
        """
        if self._run_lock.locked():
            self.log("[WARNING] Cannot re-run setup while the bot is running.")
            return False
        if not self.account_manager.exists(account_id):
            return False

        previous_id = self.account_manager.current_id()
        if account_id != previous_id:
            self.account_manager.select(account_id)
            self._rebuild_account_context()
            self._broadcast_account_ui()

        ok = self._run_first_setup_for_current()

        if account_id != previous_id:
            self.account_manager.select(previous_id)
            self._rebuild_account_context()
            self._broadcast_account_ui()

        return ok

    # ------------------------------------------------------------------
    # First setup flow (scoped to the currently-active account)
    # ------------------------------------------------------------------

    def _run_first_setup_for_current(self):
        """
        Open Bing in a visible Edge window for the user to log in manually.
        Returns True on success (browser closed after login attempt), False on error.

        On Windows, temporarily disables the browser-level Microsoft sign-in
        policy (BrowserSignin=0) so Edge does not silently authenticate using
        the Windows account identity. The previous policy value is restored
        when setup ends, regardless of outcome.
        """
        if self.driver_manager is None or self.account_meta is None:
            self.log("[ERROR] No account selected for setup.")
            return False

        current = self.account_manager.get_current()
        label = current["label"] if current else "account"
        self.log(
            f"Starting First Setup for '{label}'... Please log in to your Microsoft account."
        )

        # Capture current policy state so we can restore it afterwards.
        previous_policy = edge_policy.get_current_value()
        policy_applied = False
        if edge_policy.is_supported():
            policy_applied = edge_policy.set_browser_signin_disabled(True)
            if policy_applied:
                self.log("Edge: browser sign-in temporarily disabled for this setup.")

        setup_succeeded = False
        setup_driver = None

        try:
            setup_driver = self.driver_manager.setup_driver(
                headless=False, disable_identity=True
            )
        except Exception as e:
            self.log(f"[ERROR] Could not start the browser: {e}")
            if policy_applied:
                edge_policy.restore_value(previous_policy)
            return False

        try:
            # Windows WAM can silently push an MSA identity even on a fresh
            # profile. Before showing anything to the user, wipe every bit of
            # state that could carry an identity forward (cookies, cache,
            # storage) via the DevTools protocol.
            self.log("Clearing any cached Microsoft identity...")
            try:
                setup_driver.get("about:blank")
                time.sleep(0.5)
                setup_driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
                setup_driver.execute_cdp_cmd("Network.clearBrowserCache", {})
            except Exception:
                pass

            # Explicit logout at the Microsoft endpoint, then re-clear cookies
            # in case the logout page dropped new ones.
            try:
                setup_driver.get(
                    "https://login.live.com/logout.srf?wa=wsignout1.0&ct=0&rver=7.0"
                )
                time.sleep(3)
                try:
                    setup_driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
                except Exception:
                    pass
            except Exception:
                pass

            # Force the Microsoft sign-in form with prompt=login. This is an
            # OAuth2 parameter that forces re-authentication no matter what
            # cached/WAM session exists. The wreply sends the user back to
            # Bing after a successful sign-in.
            self.log("Opening the Microsoft sign-in page...")
            try:
                setup_driver.get(
                    "https://login.live.com/login.srf?"
                    "wa=wsignin1.0&"
                    "rpsnv=13&"
                    "ct=0&"
                    "rver=7.0&"
                    "wp=MBI_SSL&"
                    "wreply=https%3a%2f%2fwww.bing.com%2f&"
                    "lc=1033&"
                    "id=264960&"
                    "mkt=en-us&"
                    "prompt=login"
                )
            except Exception:
                # Fallback if the forced-prompt URL fails.
                setup_driver.get("https://login.live.com/")

            self.log("""Sign in with the Microsoft account for THIS profile.
- Enter the email and password yourself; don't pick a suggested account.
- If Microsoft still auto-connects another account, click the avatar
  (top-right on Bing) and choose 'Sign in with a different account'.
- Close the browser when you're done.""")

            while len(setup_driver.window_handles) > 0:
                time.sleep(1)

            setup_succeeded = True

        except Exception as e:
            error_msg = str(e).lower()
            if (
                "target window already closed" in error_msg
                or "disconnected" in error_msg
                or "not reachable" in error_msg
            ):
                setup_succeeded = True
            else:
                self.log(f"[ERROR] Error during setup: {e}")
                if self.history is not None:
                    self.history.add_to_history(
                        "First Setup Failed", "[ERROR] " + str(e)[:50]
                    )

        finally:
            try:
                setup_driver.quit()
            except Exception:
                pass

            # Always restore the Edge policy to its previous state.
            if policy_applied:
                edge_policy.restore_value(previous_policy)

            if setup_succeeded:
                self.log(
                    f"First Setup completed for '{label}'! You can now start the bot."
                )
                self.account_meta.mark_up_as_done()
                if self.history is not None:
                    self.history.add_to_history("First Setup Completed", "Success")

        return setup_succeeded

    # ------------------------------------------------------------------
    # History (scoped to current account)
    # ------------------------------------------------------------------

    def get_history(self):
        """Return the current account query history."""
        if self.history is None:
            return []
        return self.history.get_history()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, message):
        """
        Log to the GUI when attached; otherwise to stdout.

        Args:
            message (str): The message to log.
        """
        if self._webview_window:
            try:
                safe_message = json.dumps(message)
                self._webview_window.evaluate_js(f"update_log({safe_message})")
            except Exception as e:
                print(f"Log error: {e}")
        else:
            print(message)

    def _broadcast_account_ui(self):
        """Ask the GUI to refresh the account dropdown and setup state."""
        if self._webview_window:
            try:
                self._webview_window.evaluate_js("refresh_account_ui()")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def _sleep_with_stop(self, seconds):
        """
        Sleep up to `seconds`, but return early if Stop was requested.

        Args:
            seconds (float): The number of seconds to sleep.

        Returns:
            bool: True if stop was requested during the wait, else False.
        """
        try:
            return self._stop_event.wait(timeout=float(seconds))
        except Exception:
            time.sleep(seconds)
            return self._stop_event.is_set()

    def _run_advanced_schedule(
        self, pc_count, mobile_count, duration_hours, queries_per_hour
    ):
        """
        Drip-feed queries across a duration using the GUI run pipeline.

        Args:
            pc_count (int): total PC queries to run
            mobile_count (int): total Mobile queries to run
            duration_hours (float|int): how many hours to spread the queries across
            queries_per_hour (int): target queries per hour (overrides duration_hours if > 0)
        """
        try:
            pc = max(0, int(pc_count or 0))
        except (TypeError, ValueError):
            pc = 0
        try:
            mobile = max(0, int(mobile_count or 0))
        except (TypeError, ValueError):
            mobile = 0

        try:
            duration_hours = float(duration_hours)
        except (TypeError, ValueError):
            duration_hours = 3.0

        duration_hours = max(1.0, duration_hours)

        try:
            qph = int(queries_per_hour or 0)
        except (TypeError, ValueError):
            qph = 0

        if qph < 0:
            qph = 0

        total = pc + mobile
        self.log(
            f"Advanced scheduling: PC={pc}, Mobile={mobile} over {duration_hours}h (qph={qph})"
        )

        if total <= 0:
            self.log("[WARNING] Nothing to do (PC and Mobile counts are both 0).")
            return

        if qph > 0:
            raw_batch = qph // 6  # ~10-minute batches
        else:
            raw_batch = total // max(1, int(duration_hours * 2))
        per_batch = max(1, min(10, raw_batch))

        num_batches = math.ceil(total / per_batch)
        total_seconds = duration_hours * 3600
        interval = total_seconds / max(num_batches, 1)

        self.log(
            f"Planning {num_batches} batches of ~{per_batch} queries, interval ~{interval:.1f}s"
        )

        pc_left = pc
        mobile_left = mobile

        for i in range(num_batches):
            if self._stop_event.is_set():
                break

            if pc_left > 0:
                batch_pc = min(per_batch, pc_left)
                batch_mobile = 0
            else:
                batch_pc = 0
                batch_mobile = min(per_batch, mobile_left)

            if batch_pc == 0 and batch_mobile == 0:
                break

            self.log(
                f"Batch {i+1}/{num_batches}: PC={batch_pc}, Mobile={batch_mobile} "
                f"(PC left {pc_left}, Mobile left {mobile_left})"
            )

            if batch_pc > 0 and not self._stop_event.is_set():
                self._run_phase(mobile=False, count=batch_pc, do_daily_set=True)

            if batch_mobile > 0 and not self._stop_event.is_set():
                self._run_phase(mobile=True, count=batch_mobile, do_daily_set=False)

            pc_left -= batch_pc
            mobile_left -= batch_mobile

            if pc_left <= 0 and mobile_left <= 0:
                break
            if self._stop_event.is_set():
                break

            sleep_time = max(5.0, interval * random.uniform(0.75, 1.25))
            self.log(f"Sleeping {sleep_time:.1f}s until next batch")
            if self._sleep_with_stop(sleep_time):
                break

        if not self._stop_event.is_set() and pc_left <= 0 and mobile_left <= 0:
            self.log("Advanced schedule completed!")

    def main(self, pc_count, mobile_count=0, daily_only=False):
        """
        Run the bot against the currently-selected account.

        Default mode (daily_only=False): runs sequentially
          1. PC phase     — desktop UA, `pc_count` Bing searches, then Daily Set.
          2. Mobile phase — iPhone UA, `mobile_count` Bing searches only.
        Either count may be 0 to skip that phase.

        Daily-only mode (daily_only=True): skips searches entirely and only
        opens a desktop driver to run the Daily Set + More Activities. Both
        count arguments are ignored. Useful when the user just wants to
        collect today's daily-task points without churning searches.

        Args:
            pc_count (int): how many searches to do in the PC phase (ignored if daily_only)
            mobile_count (int): how many searches to do in the Mobile phase (ignored if daily_only)
            daily_only (bool): whether to skip searches and just run the Daily Set
        """
        if self.account_manager.current_id() is None:
            self.log("[ERROR] No account selected. Add one via the dropdown.")
            if self._webview_window:
                self._webview_window.evaluate_js("enable_start_button()")
            return

        if self.account_meta is None or not self.account_meta.is_first_setup_done():
            self.log("[ERROR] First Setup has not been completed for this account.")
            if self._webview_window:
                self._webview_window.evaluate_js("enable_start_button()")
            return

        daily_only = bool(daily_only)

        try:
            pc_count = max(0, int(pc_count or 0))
            mobile_count = max(0, int(mobile_count or 0))
        except (TypeError, ValueError):
            pc_count, mobile_count = 0, 0

        if not daily_only and pc_count == 0 and mobile_count == 0:
            self.log("[WARNING] Nothing to do (PC and Mobile counts are both 0).")
            if self._webview_window:
                self._webview_window.evaluate_js("enable_start_button()")
            return

        schedule = {}
        if not daily_only and self.account_meta is not None:
            try:
                schedule = self.account_meta.get_schedule() or {}
            except Exception:
                schedule = {}

        schedule_enabled = isinstance(schedule, dict) and bool(schedule.get("enabled"))
        use_advanced = (
            not daily_only
            and schedule_enabled
            and bool(schedule.get("advancedScheduling"))
        )

        if (
            not daily_only
            and isinstance(schedule, dict)
            and bool(schedule.get("advancedScheduling"))
            and not schedule_enabled
        ):
            self.log(
                "[WARNING] Advanced scheduling is enabled, but Schedule is off. Running normal pace."
            )

        if not self._run_lock.acquire(blocking=False):
            self.log("[WARNING] A run is already in progress.")
            return

        # Reset stop flag before each run so a previous Stop doesn't carry over.
        self._stop_event.clear()

        try:
            if daily_only:
                self.log("Starting AutoRewarder (Daily tasks only)...")
            else:
                self.log("Starting AutoRewarder (Edge Edition)...")
            if self._webview_window:
                try:
                    self._webview_window.evaluate_js(
                        "update_status_indicator && update_status_indicator('executing')"
                    )
                except Exception:
                    pass

            if daily_only:
                self._run_daily_only()
            else:
                if use_advanced:
                    duration = schedule.get("runDuration", 3)
                    qph = schedule.get("queriesPerHour", 10)
                    self.log("Advanced scheduling enabled. Using scheduled pacing.")
                    self._run_advanced_schedule(pc_count, mobile_count, duration, qph)
                else:
                    if pc_count > 0 and not self._stop_event.is_set():
                        self._run_phase(mobile=False, count=pc_count, do_daily_set=True)

                    if mobile_count > 0 and not self._stop_event.is_set():
                        self._run_phase(
                            mobile=True, count=mobile_count, do_daily_set=False
                        )

            if self._stop_event.is_set():
                self.log("Stopped.")
            else:
                self.log("Done!")

                if self.account_meta is not None:
                    try:
                        from datetime import date

                        current_schedule = self.account_meta.get_schedule()
                        if isinstance(current_schedule, dict):
                            current_schedule["last_triggered_date"] = (
                                date.today().isoformat()
                            )
                            self.account_meta.set_schedule(current_schedule)
                    except Exception as e:
                        self.log(f"[WARNING] Failed to update deduplication date: {e}")
        finally:
            try:
                if self._webview_window:
                    self._webview_window.evaluate_js("enable_start_button()")
            except Exception:
                pass
            self._run_lock.release()

    def _run_daily_only(self):
        """
        Open a PC driver, run only the Daily Set + More Activities, scrape
        the points balance, then quit. No Bing searches are performed.

        Unlike the normal flow, this path is user-initiated (explicit toggle)
        so it ignores `should_perform_daily_set()` — if the saved status says
        "done today" but the user clicked Start anyway, they want it to run.
        The card-level detection inside perform_daily_set will skip cards
        that are genuinely complete, so re-running on a real already-done day
        just confirms state without wasting clicks.
        """
        if self.daily_set is None:
            self.log("[ERROR] Daily tasks unavailable for this account.")
            return

        if not self.daily_set.should_perform_daily_set():
            self.log(
                "Note: today is already marked as done in status.json, "
                "but running anyway since you asked explicitly."
            )

        self.log("=== Daily tasks only — no searches ===")

        self._driver = self.driver_manager.setup_driver(mobile=False)
        try:
            human = HumanBehavior(self._driver, show_cursor=True, mobile=False)
            success = self.daily_set.perform_daily_set(
                self._driver, human, stop_event=self._stop_event
            )
            if self._stop_event.is_set():
                self.log("Daily tasks aborted by Stop.")
                return
            if success:
                self.daily_set.mark_as_completed()
                self.log("Daily tasks completed and marked as done for today.")
            else:
                self.log("Daily tasks failed. Not marked as done for today.")

        finally:
            try:
                self._driver.quit()
            except Exception as e:
                self.log(f"[WARNING] Error closing driver: {e}")
            self._driver = None
            time.sleep(0.5)

    def _run_phase(self, mobile, count, do_daily_set):
        """
        Open a driver for a single phase (PC or Mobile), do `count` searches,
        optionally run the Daily Set, then quit.

        Args:
            mobile (bool): whether this is the Mobile phase (True) or PC phase (False)
            count (int): how many searches to perform in this phase
            do_daily_set (bool): whether to run the Daily Set after searches (PC phase only)
        """
        label = "Mobile" if mobile else "PC"
        self.log(
            f"=== {label} phase — {count} {'queries' if count != 1 else 'query'} ==="
        )

        queries_to_search = self.search_engine.load_queries_from_json(
            JSON_FILE_PATH, num_needed=count
        )
        if not queries_to_search:
            self.log(f"[WARNING] {label}: no queries available. Skipping phase.")
            if self.history is not None:
                self.history.add_to_history(
                    "N/A", f"[ERROR] {label}: no queries available"
                )
            return

        self._driver = self.driver_manager.setup_driver(mobile=mobile)
        try:
            self.search_engine.perform_searches(
                self._driver,
                queries_to_search,
                mobile=mobile,
                stop_event=self._stop_event,
            )

            if (
                do_daily_set
                and not self._stop_event.is_set()
                and self.daily_set.should_perform_daily_set()
            ):
                self.log("Daily Set not completed today. Starting Daily Set tasks...")
                human = HumanBehavior(self._driver, show_cursor=True, mobile=mobile)
                success = self.daily_set.perform_daily_set(
                    self._driver, human, stop_event=self._stop_event
                )
                if not self._stop_event.is_set():
                    if success:
                        self.daily_set.mark_as_completed()
                        self.log(
                            "Daily Set tasks completed and marked as done for today."
                        )
                    else:
                        self.log("Daily Set failed. Not marked as done for today.")

        finally:
            try:
                self._driver.quit()
            except Exception as e:
                self.log(f"[WARNING] Error closing driver: {e}")
            self._driver = None
            time.sleep(0.5)
