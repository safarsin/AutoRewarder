import os
import time
import json
import threading
import webbrowser
import sys
import platform

from .config import GUI_DIR, REPO, CURRENT_VERSION, JSON_FILE_PATH, BASE_DIR
from .driver_manager import DriverManager
from .history import HistoryManager
from .search_engine import SearchEngine
from .utils import check_for_updates
from .settings_manager import SettingsManager
from .daily_set import DailySet
from .human_behavior import HumanBehavior


class AutoRewarderAPI:
    """
    Core API class for AutoRewarder.

    This class manages the main functionality of the AutoRewarder application, including:
    - Interacting with the webview GUI
    - Managing the Selenium WebDriver
    - Handling search queries and history
    - Performing the Daily Set tasks
    - Checking for updates
    - Managing user settings

    It serves as the bridge between the frontend (GUI) and the backend logic.
    """

    def __init__(self):
        """
        Initialize the AutoRewarderAPI with necessary managers and state variables.
        """

        self.driver_manager = DriverManager()
        self.history = HistoryManager(logger=self.log)
        self.search_engine = SearchEngine(logger=self.log, history=self.history)
        self.daily_set = DailySet(logger=self.log)
        self.settings_manager = SettingsManager()

        self._webview_window = None
        self._driver_loader_thread_started = False
        self._update_check_started = False
        self._driver = None

        # Load settings from file or create with default values if it doesn't exist
        settings = self.get_settings()
        # Default mode is visible browser or it will run in hidden mode (headless)
        self.hide_browser = settings.get("hide_browser", False)
        self.driver_manager.hide_browser = bool(self.hide_browser)

        self.is_driver_loading = False

    def set_window(self, window):
        """
        Save the window reference and start background tasks.

        Checks for updates and loads the driver in a separate thread
        so the UI doesn't freeze. This is important when Edge updates
        and the driver needs time to download.

        Args:
            window: The pywebview window instance for JS interaction.
        """

        # store reference to webview window so Python can call JS (evaluate_js)
        self._webview_window = window

        self.start_update_check()

        if not self._driver_loader_thread_started:
            self._driver_loader_thread_started = True
            threading.Thread(target=self.load_driver_in_background, daemon=True).start()

    def open_history_window(self):
        """
        Open a new window to display the search history.
        """
        try:
            import webview

        except Exception as e:
            short_error = str(e)[:50]
            self.log(f"[ERROR] Cannot open history window: {short_error}")
            return

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
        """
        Start the update check in a background thread to avoid blocking the UI.
        """

        if self._update_check_started:
            return

        self._update_check_started = True

        threading.Thread(target=self.run_update_check, daemon=True).start()

    def run_update_check(self):
        """
        Check for updates and notify the user if a new version is available.
        """

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

        # A clickable link in the log area (pywebview)
        link_html = f"<a href='#' onclick='window.pywebview.api.open_link(\"{url}\")'>Click here to download</a>"

        self.log(f"New version {latest_version} available: {link_html}")

        try:
            self._webview_window.evaluate_js(f"alert({json.dumps(msg)})")
        except Exception as e:
            self.log(f"[ERROR] Error displaying update alert: {e}")
            return

    def open_link(self, url):
        """
        Open a URL in the default web browser.

        Args:
            url: The URL to open.
        """

        webbrowser.open(url)

    def load_driver_in_background(self):
        """
        Load the Selenium WebDriver in a background thread to avoid freezing the UI.
        """

        self.is_driver_loading = True

        try:
            # Trigger Selenium Manager to download/prepare the driver
            warmup_driver = self.driver_manager.setup_driver(headless=True)
            warmup_driver.quit()
        except Exception as e:
            self.log(f"[ERROR] Error loading WebDriver: {e}")
        finally:
            self.is_driver_loading = False

            if hasattr(self, "_webview_window") and self._webview_window:
                self._webview_window.evaluate_js("stop_loader()")

    def check_driver_status(self):
        """
        Check if the WebDriver is still loading.
        Runs from JS.

        Returns:
            bool: True if the WebDriver is still loading, False otherwise.
        """

        return self.is_driver_loading

    def get_settings(self):
        """
        Retrieve user settings from the settings manager.
        Or create the settings file with default values if it doesn't exist.

        Returns:
            dict: A dictionary containing user settings.
        """

        return self.settings_manager.get_settings()

    def get_history(self):
        """
        Retrieve the search history from the history manager.

        Returns:
            list: A list of search history entries.
        """

        return self.history.get_history()

    # First setup function to let user log in to their Microsoft account and prepare the Edge profile for the bot
    def first_setup(self):
        """
        Perform the first-time setup for the bot.
        This function opens a browser window for the user to log in to their Microsoft account.
        After the user logs in and closes the browser, the setup is marked as completed.
        After successful setup, the start button is enabled and the setup button is hidden in the UI.
        """

        self.log("Starting First Setup... Please log in to your Microsoft account.")

        setup_driver = self.driver_manager.setup_driver(
            headless=False
        )  # Open browser in normal mode for login
        # Used to avoid false "completed" state when finally executes after a failure.
        setup_succeeded = False

        try:
            self.log("Opening Bing page...")
            self.log("""Log in directly on the Bing page.
            IMPORTANT: Do NOT sync the Edge profile!
            Just log in and close the browser when done.""")
            time.sleep(4)
            setup_driver.get("https://www.bing.com")
            self.log(
                "Waiting for you to log in...\nClose the browser window when done!"
            )

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
                # If unexpected error, log it and add to history
                self.log(f"[ERROR] Error during setup: {e}")
                self.history.add_to_history(
                    "First Setup Failed", "[ERROR] " + str(e)[:50]
                )

        finally:
            try:
                setup_driver.quit()
            except Exception:
                pass

            if setup_succeeded:
                self.log("First Setup completed! You can now start the bot.")

                self.settings_manager.mark_up_as_done()

                self.history.add_to_history("First Setup Completed", "Success")

                if self._webview_window:
                    self._webview_window.evaluate_js("enable_start_button()")
                    self._webview_window.evaluate_js("hide_setup_button()")
            else:
                if self._webview_window:
                    # Allow retry after a failed setup attempt.
                    self._webview_window.evaluate_js("enable_setup_button()")

    def set_hide_browser(self, is_hide):
        """
        Toggle the browser hidden(headless) mode and save the setting.

        Args:
            is_hide: A boolean indicating whether to hide the browser (True) or show it (False).
        """

        self.hide_browser = is_hide
        self.driver_manager.hide_browser = bool(is_hide)

        self.settings_manager.set_hide_browser(is_hide)

        self.log(f"Browser hidden mode: {'ON' if is_hide else 'OFF'}")

    def save_user_settings(self, settings_data):
        """
        Save user settings received from the GUI. This method validates and merges
        provided keys into the existing settings file and applies runtime effects
        where appropriate (e.g., hide_browser, autoStartUp etc.).

        Called from JS via `pywebview.api.save_user_settings({...})`.

        Args:
            settings_data (dict): A dictionary containing user settings to be saved.

        Returns:
            bool: True if the save operation was successful, False otherwise.
        """

        try:
            if not isinstance(settings_data, dict):
                self.log(
                    "[ERROR] Invalid settings payload: must be a JSON object/dictionary"
                )
                raise ValueError("Settings payload must be a JSON object/dictionary")

            current = self.settings_manager.get_settings()

            # Keep previous autostart state to decide whether to modify registry
            prev_autostart = bool(current.get("autoStartUp", False))

            # Merge and validate known keys (don't overwrite unrelated settings)
            if "hide_browser" in settings_data:
                current["hide_browser"] = bool(settings_data["hide_browser"])

            if "autoStartUp" in settings_data:
                current["autoStartUp"] = bool(settings_data["autoStartUp"])

            if "advancedScheduling" in settings_data:
                current["advancedScheduling"] = bool(
                    settings_data["advancedScheduling"]
                )

            if "runDuration" in settings_data:
                try:
                    rd = int(settings_data["runDuration"])
                except Exception:
                    raise ValueError("runDuration must be an integer")
                rd = max(1, min(24, rd))
                current["runDuration"] = rd

            if "totalQueries" in settings_data:
                try:
                    tq = int(settings_data["totalQueries"])
                except Exception:
                    raise ValueError("totalQueries must be an integer")
                tq = max(1, min(99, tq))
                current["totalQueries"] = tq

            if "queriesPerHour" in settings_data:
                try:
                    qph = int(settings_data["queriesPerHour"])
                except Exception:
                    raise ValueError("queriesPerHour must be an integer")
                qph = max(1, min(99, qph))
                current["queriesPerHour"] = qph

            # Handle autostart (Windows registry) if the flag changed
            try:
                new_autostart = bool(current.get("autoStartUp", False))
                if new_autostart != prev_autostart:
                    self._set_autostart_registry(new_autostart)
            except Exception as e:
                self.log(f"[WARNING] Failed to update autostart: {e}")
                raise Exception(f"Could not update Windows Registry: {e}")
            
            # Save merged settings
            self.settings_manager.save_settings(current)

            # Apply runtime effects where relevant
            try:
                if current.get("hide_browser") is not None:
                    self.set_hide_browser(bool(current.get("hide_browser")))
            except Exception:
                # Don't fail saving if runtime effect cannot be applied
                self.log("[WARNING] Failed to apply runtime hide_browser setting")

            self.log("Settings saved successfully")
            return True

        except Exception as e:
            short_error = str(e)[:50]
            self.log(f"[ERROR] Failed saving settings: {short_error}")
            return False

    def _autostart_command(self):
        """
        Return the command string to use for autostart registry entry.

        Returns:
            str: The command to execute AutoRewarder in headless mode.
        """

        # if .exe, just call itself with --headless
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --headless'

        # if script, call python with the AutoRewarder_CLI.py
        runner_py = os.path.join(BASE_DIR, "AutoRewarder_CLI.py")
        return f'"{sys.executable}" "{runner_py}"'

    def _linux_autostart_path(self):
        """
        Return the Linux autostart .desktop file path.

        Returns:
            str: The file path for the autostart .desktop entry.
        """

        autostart_dir = os.path.join(os.path.expanduser("~"), ".config", "autostart")
        return os.path.join(autostart_dir, "AutoRewarder.desktop")

    def _set_autostart_linux(self, enable):
        """
        Enable or disable autostart on Linux using a .desktop file.

        Args:
            enable (bool): True to enable autostart, False to disable.

        Returns:
            bool: True if the .desktop file was successfully updated, False otherwise.
        """

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

                with open(desktop_path, "w", encoding="utf-8") as file:
                    file.write(desktop_file)

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
        """
        Enable or disable autostart for the current platform.

        Uses HKCU on Windows and a .desktop file on Linux. Other platforms are not supported.

        Args:
            enable (bool): True to enable autostart, False to disable.

        Returns:
            bool: True if the registry was successfully updated, False otherwise.
        """

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
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE
            )

            try:
                name = "AutoRewarder"

                if enable:
                    cmd = self._autostart_command()
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, cmd)
                    self.log("Autostart enabled (HKCU Run)")
                else:
                    try:
                        winreg.DeleteValue(key, name)
                        self.log("Autostart disabled (HKCU Run)")

                    except FileNotFoundError:
                        self.log("Autostart entry not found; nothing to remove")

            finally:
                winreg.CloseKey(key)

            return True

        except Exception as e:
            self.log(f"[ERROR] Failed to update autostart registry: {e}")
            return False

    def is_autostart_enabled(self):
        """
        Return True if an autostart entry exists for the current platform.

        Returns:
            bool: True if autostart is enabled, False otherwise.
        """
        try:
            system_name = platform.system()

            if system_name == "Linux":
                return os.path.exists(self._linux_autostart_path())

            if system_name != "Windows":
                return False

            import winreg

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

    # Send message to UI log area
    def log(self, message):
        """
        Log a message to the UI log area.

        Args:
            message: The message string to log.
        """

        if self._webview_window:
            try:
                safe_message = json.dumps(message)
                self._webview_window.evaluate_js(f"update_log({safe_message})")
            except Exception as e:
                print(f"Log error: {e}")

    def main(self, count):
        """
        Main function to run the bot.

        Args:
            count: The number of queries to search.
        """

        self.log("Starting AutoRewarder (Edge Edition)...")

        # 1. Get queries to search from JSON file
        queries_to_search = self.search_engine.load_queries_from_json(
            JSON_FILE_PATH, num_needed=count
        )

        if not queries_to_search:
            self.log("No queries available for search. Exiting...")
            self.history.add_to_history(
                "N/A", "[ERROR] No queries available for search"
            )
            return

        # 2. Setup browser
        self._driver = self.driver_manager.setup_driver()
        try:
            # 3. Perform searches
            self.search_engine.perform_searches(self._driver, queries_to_search)

            # 4. Perform Daily Set tasks
            if self.daily_set.should_perform_daily_set():
                self.log("Daily Set not completed today. Starting Daily Set tasks...")

                human = HumanBehavior(self._driver, show_cursor=True)
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

            time.sleep(0.5)  # pause for clean shutdown

            self.log("Done!")
            # Re-enable button after finish
            if self._webview_window:
                self._webview_window.evaluate_js("enable_start_button()")
