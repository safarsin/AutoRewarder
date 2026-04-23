import os
import sys
import time
import json
import platform
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
from .driver_manager import DriverManager
from .history import HistoryManager
from .search_engine import SearchEngine
from .utils import check_for_updates
from .settings_manager import GlobalSettingsManager, AccountMetaManager
from .account_manager import AccountManager
from .daily_set import DailySet
from .human_behavior import HumanBehavior
from . import edge_policy


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
        self._webview_window = window
        self.start_update_check()

        if not self._driver_loader_thread_started:
            self._driver_loader_thread_started = True
            threading.Thread(target=self.load_driver_in_background, daemon=True).start()

    def _safe_log(self, message):
        """Log wrapper usable before the webview window is attached."""
        if self._webview_window:
            self.log(message)
        else:
            print(message)

    def open_history_window(self):
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
        if self._update_check_started:
            return
        self._update_check_started = True
        threading.Thread(target=self.run_update_check, daemon=True).start()

    def run_update_check(self):
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
        return self.is_driver_loading

    # ------------------------------------------------------------------
    # Exposed to JS: global settings
    # ------------------------------------------------------------------

    def get_settings(self):
        """Return global settings (hide_browser, current_account_id, schema_version)."""
        return self.global_settings.get_settings()

    def set_hide_browser(self, is_hide):
        self.hide_browser = bool(is_hide)
        if self.driver_manager is not None:
            self.driver_manager.hide_browser = bool(is_hide)
        self.global_settings.set_hide_browser(is_hide)
        self.log(f"Browser hidden mode: {'ON' if is_hide else 'OFF'}")

    # ------------------------------------------------------------------
    # Exposed to JS: per-account schedule + startup
    # ------------------------------------------------------------------

    def is_running(self):
        """True when the bot is mid-run. Used by the headless runner to avoid overlap."""
        return self._run_lock.locked()

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
        queriesPerHour (1..99), queries_pc (0..130), queries_mobile (0..99).
        Unknown keys are ignored.
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
            # Reset the daily-dedup marker so the edited schedule can still fire today.
            "last_triggered_date": None,
        }
        meta.set_schedule(new)

        label = self.account_manager.get(account_id)
        label = label["label"] if label else account_id
        if new["enabled"]:
            mode = "advanced" if new["advancedScheduling"] else "simple"
            self.log(
                f"Schedule '{label}' ({mode}): PC={new['queries_pc']}, "
                f"Mobile={new['queries_mobile']}, "
                f"{new['runDuration']}h @ {new['queriesPerHour']}/h"
            )
        else:
            self.log(f"Schedule '{label}' disabled.")
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

    # ---- Autostart (OS-level) — ported from v3.1 main -----------------

    def _autostart_command(self):
        """Command string registered for autostart."""
        # Frozen build: call the bundled exe with --headless.
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --headless'
        # Dev: call python on the entry script with --headless so the dispatch
        # in AutoRewarder.py forwards to AutoRewarder_CLI.main().
        entry = os.path.join(BASE_DIR, "AutoRewarder.py")
        return f'"{sys.executable}" "{entry}" --headless'

    def _linux_autostart_path(self):
        return os.path.join(
            os.path.expanduser("~"), ".config", "autostart", "AutoRewarder.desktop"
        )

    def _set_autostart_linux(self, enable):
        """Create or remove the Linux .desktop autostart entry."""
        try:
            desktop_path = self._linux_autostart_path()
            if enable:
                os.makedirs(os.path.dirname(desktop_path), exist_ok=True)
                cmd = self._autostart_command()
                desktop_file = (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=AutoRewarder\n"
                    f"Exec={cmd}\n"
                    "Terminal=false\n"
                    "X-GNOME-Autostart-enabled=true\n"
                )
                with open(desktop_path, "w", encoding="utf-8") as fh:
                    fh.write(desktop_file)
                self.log("Autostart enabled (.desktop)")
            else:
                if os.path.exists(desktop_path):
                    os.remove(desktop_path)
                    self.log("Autostart disabled (.desktop)")
                else:
                    self.log("Autostart entry not found; nothing to remove")
            return True
        except Exception as e:
            self.log(f"[ERROR] Failed to update Linux autostart: {e}")
            return False

    def _set_autostart_registry(self, enable):
        """Platform-agnostic entry point. Windows → HKCU Run, Linux → .desktop."""
        try:
            system_name = platform.system()
            if system_name == "Linux":
                return self._set_autostart_linux(enable)
            if system_name != "Windows":
                self.log("Autostart is only supported on Windows and Linux.")
                return False

            try:
                import winreg
            except Exception:
                self.log(
                    "[WARNING] winreg module not available; cannot modify registry."
                )
                return False

            run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE
            ) as key:
                name = "AutoRewarder"
                if enable:
                    winreg.SetValueEx(
                        key, name, 0, winreg.REG_SZ, self._autostart_command()
                    )
                    self.log("Autostart enabled (HKCU Run)")
                else:
                    try:
                        winreg.DeleteValue(key, name)
                        self.log("Autostart disabled (HKCU Run)")
                    except FileNotFoundError:
                        self.log("Autostart entry not found; nothing to remove")
            return True
        except Exception as e:
            self.log(f"[ERROR] Failed to update autostart registry: {e}")
            return False

    def is_autostart_enabled(self):
        """Return True if an autostart entry exists for the current platform."""
        try:
            system_name = platform.system()
            if system_name == "Linux":
                return os.path.exists(self._linux_autostart_path())
            if system_name != "Windows":
                return False
            try:
                import winreg
            except Exception:
                return False
            run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_READ
                ) as key:
                    val, _ = winreg.QueryValueEx(key, "AutoRewarder")
                    return bool(val)
            except OSError:
                return False
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
        """Register or unregister the OS autostart entry. Called from JS."""
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
        return self.account_manager.list()

    def get_current_account(self):
        return self.account_manager.get_current()

    def create_account(self, label):
        """
        Create a new account, select it, and run First Setup against it.
        On setup failure (user closes browser without logging in), rolls back
        and restores the previously-selected account.
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
        try:
            self.account_manager.rename(account_id, new_label)
        except ValueError as e:
            self.log(f"[ERROR] {e}")
            return False
        self._broadcast_account_ui()
        return True

    def delete_account(self, account_id):
        if self._run_lock.locked() and account_id == self.account_manager.current_id():
            self.log(
                "[WARNING] Cannot delete the active account while the bot is running."
            )
            return False
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
        if self.history is None:
            return []
        return self.history.get_history()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, message):
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

    def main(self, pc_count, mobile_count=0):
        """
        Run the bot against the currently-selected account.

        Executes sequentially:
          1. PC phase     — desktop UA, `pc_count` Bing searches, then Daily Set.
          2. Mobile phase — iPhone UA, `mobile_count` Bing searches only.
        Either count may be 0 to skip that phase.
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

        try:
            pc_count = max(0, int(pc_count or 0))
            mobile_count = max(0, int(mobile_count or 0))
        except (TypeError, ValueError):
            pc_count, mobile_count = 0, 0

        if pc_count == 0 and mobile_count == 0:
            self.log("[WARNING] Nothing to do (PC and Mobile counts are both 0).")
            if self._webview_window:
                self._webview_window.evaluate_js("enable_start_button()")
            return

        if not self._run_lock.acquire(blocking=False):
            self.log("[WARNING] A run is already in progress.")
            return

        try:
            self.log("Starting AutoRewarder (Edge Edition)...")
            if self._webview_window:
                try:
                    self._webview_window.evaluate_js(
                        "update_status_indicator && update_status_indicator('executing')"
                    )
                except Exception:
                    pass

            if pc_count > 0:
                self._run_phase(mobile=False, count=pc_count, do_daily_set=True)

            if mobile_count > 0:
                self._run_phase(mobile=True, count=mobile_count, do_daily_set=False)

            self.log("Done!")
        finally:
            try:
                if self._webview_window:
                    self._webview_window.evaluate_js("enable_start_button()")
            except Exception:
                pass
            self._run_lock.release()

    def _run_phase(self, mobile, count, do_daily_set):
        """
        Open a driver for a single phase (PC or Mobile), do `count` searches,
        optionally run the Daily Set, then quit.
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
                self._driver, queries_to_search, mobile=mobile
            )

            if do_daily_set and self.daily_set.should_perform_daily_set():
                self.log("Daily Set not completed today. Starting Daily Set tasks...")
                human = HumanBehavior(
                    self._driver, show_cursor=True, mobile=mobile
                )
                success = self.daily_set.perform_daily_set(self._driver, human)
                if success:
                    self.daily_set.mark_as_completed()
                    self.log("Daily Set tasks completed and marked as done for today.")
                else:
                    self.log("Daily Set failed. Not marked as done for today.")
        finally:
            try:
                self._driver.quit()
            except Exception as e:
                self.log(f"[WARNING] Error closing driver: {e}")
            self._driver = None
            time.sleep(0.5)
