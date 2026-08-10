"""Edge browser setup (nodriver) for per-account profiles."""

import glob
import os
import json
import shutil

from .nodriver_backend import NodriverDriver


def _clear_session_state(profile_path):
    """Remove Chromium/Edge session files to suppress crash-restore prompt."""
    if not profile_path or not os.path.isdir(profile_path):
        return
    default_dir = os.path.join(profile_path, 'Default')
    if os.path.isdir(default_dir):
        # Delete individual session files
        for fname in ('Last Session', 'Last Tabs', 'Current Session', 'Current Tabs'):
            fp = os.path.join(default_dir, fname)
            try:
                if os.path.isfile(fp):
                    os.remove(fp)
            except OSError:
                pass
        # Delete Sessions/ subdirectory (Edge stores session snapshots here)
        sessions_dir = os.path.join(default_dir, 'Sessions')
        if os.path.isdir(sessions_dir):
            try:
                shutil.rmtree(sessions_dir, ignore_errors=True)
            except OSError:
                pass
        # Patch Preferences: set exited_cleanly + suppress restore
        pref_path = os.path.join(default_dir, 'Preferences')
        if os.path.isfile(pref_path):
            try:
                with open(pref_path, 'r') as f:
                    prefs = json.load(f)
                changed = False
                # Chromium/Edge crash recovery: set clean exit
                if prefs.get('profile', {}).get('exited_cleanly') is not True:
                    prefs.setdefault('profile', {})['exited_cleanly'] = True
                    changed = True
                # Remove session restore preference
                if 'session' in prefs:
                    if 'restore_on_startup' in prefs['session']:
                        del prefs['session']['restore_on_startup']
                        changed = True
                if changed:
                    with open(pref_path, 'w') as f:
                        json.dump(prefs, f)
            except (OSError, json.JSONDecodeError):
                pass
    # Also clear Local State (Edge stores session crash state here too)
    local_state = os.path.join(profile_path, 'Local State')
    if os.path.isfile(local_state):
        try:
            with open(local_state, 'r') as f:
                state = json.load(f)
            changed = False
            if state.get('profile', {}).get('info_cache'):
                for profile_name in state['profile']['info_cache']:
                    pinfo = state['profile']['info_cache'][profile_name]
                    if pinfo.get('session_restore_enabled') is not None:
                        pinfo['session_restore_enabled'] = False
                        changed = True
            if changed:
                with open(local_state, 'w') as f:
                    json.dump(state, f)
        except (OSError, json.JSONDecodeError):
            pass


def _edge_executable_path():
    """Locate a usable Chromium-based browser.

    Microsoft Edge is preferred (per-account profiles + First Setup are
    Edge-specific), but any Chromium build works over the same CDP, so on
    Linux we fall back to Chrome/Chromium and the Playwright-managed
    Chromium when Edge is not installed.
    """
    if os.name == "nt":
        candidates = [
            os.path.join(
                os.environ.get("LOCALAPPDATA", ""),
                "Microsoft",
                "Edge",
                "Application",
                "msedge.exe",
            ),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return None
    for name in (
        "microsoft-edge",
        "microsoft-edge-stable",
        "microsoft-edge-beta",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        path = shutil.which(name)
        if path:
            return path
    for candidate in (
        "/opt/microsoft/msedge/msedge",
        "/usr/bin/microsoft-edge",
        os.path.expanduser("~/edge/opt/microsoft/msedge/msedge"),
    ):
        if os.path.exists(candidate):
            return candidate
    for path in sorted(
        glob.glob(
            os.path.expanduser(
                "~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"
            )
        )
    ):
        if os.path.exists(path):
            return path
    return None


def _sandbox_helper_unavailable(browser_path):
    """True when the Chromium/Edge SUID sandbox helper missing or not setuid."""
    if not browser_path:
        return False
    dir_ = os.path.dirname(browser_path)
    candidates = ["chrome-sandbox", "msedge-sandbox"]
    for name in candidates:
        helper = os.path.join(dir_, name)
        if os.path.exists(helper):
            return not (os.stat(helper).st_mode & 0o4000)
    return True


class DriverManager:
    """
    Manages the browser automation session for MS Edge via nodriver.

    Each DriverManager instance is bound to a specific Edge --user-data-dir
    (i.e. one account). Switching account = rebuilding this manager with a
    different profile_path.
    """

    def __init__(self, profile_path=None, hide_browser=False):
        """
        Args:
            profile_path (str | None): Absolute path to the Edge profile
                directory. None when no account is selected (empty state). In
                that case setup_driver will raise, since there is nothing to
                launch.
            hide_browser (bool): Whether to run the browser in headless mode.
        """
        self.profile_path = profile_path
        self.hide_browser = hide_browser

    # Realistic iPhone UA so Microsoft Rewards credits the searches as mobile.
    MOBILE_USER_AGENT = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 "
        "Mobile/15E148 Safari/604.1"
    )
    MOBILE_WINDOW_SIZE = "412,915"
    DESKTOP_WINDOW_SIZE = "1920,1080"

    def setup_driver(self, headless=None, disable_identity=False, mobile=False):
        """
        Set up the nodriver session for MS Edge using this manager's profile.

        Args:
            headless: Headless override. Falls back to self.hide_browser.
            disable_identity: When True, add Edge/Chromium flags that disable
                the Windows-account-based auto sign-in. Used during First
                Setup so a second MSA can actually log in.
            mobile: When True, launch Edge with an iPhone user agent and a
                mobile-sized viewport so Rewards credits the searches as
                mobile. When False, use the desktop viewport.

        Returns:
            NodriverDriver: The configured driver facade (Selenium-like API).

        Raises:
            RuntimeError: If profile_path is None (no account selected).
        """
        if not self.profile_path:
            raise RuntimeError(
                "No account selected: cannot start the browser. "
                "Create or select an account first."
            )

        if headless is None:
            headless = self.hide_browser

        browser_args = [
            "--profile-directory=Default",
            "--no-default-browser-check",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
        ]
        # Clear session state files to prevent restore-pages prompt
        _clear_session_state(self.profile_path)

        if mobile:
            browser_args.append(f"--user-agent={self.MOBILE_USER_AGENT}")
            window_size = self.MOBILE_WINDOW_SIZE
        else:
            window_size = self.DESKTOP_WINDOW_SIZE
        browser_args.append(f"--window-size={window_size}")

        if disable_identity:
            # Kill the various Chromium/Edge paths that silently sign the user
            # in with the Windows-level Microsoft identity.
            browser_args.append(
                "--disable-features=msImplicitSignin,AadSsoUrlInterceptionEnabled,"
                "WebOtpBackendAuto,IdentityConsistency,msIdentityWebSignIn,"
                "msEdgeIdentitySyncInterception"
            )
            browser_args.append("--disable-sync")

        if headless:
            browser_args.append("--headless=new")
            browser_args.append("--disable-gpu")
            browser_args.append("--window-position=-32000,-32000")

        browser_path = _edge_executable_path()
        if os.name != "nt" and _sandbox_helper_unavailable(browser_path):
            # Extracted/user-local Chromium builds never get the setuid
            # chrome-sandbox helper, so Chromium refuses to start as a
            # non-root user without this flag.
            browser_args.append("--no-sandbox")

        driver = NodriverDriver(
            browser_executable_path=browser_path,
            user_data_dir=self.profile_path,
            headless=headless,
            browser_args=browser_args,
            mobile=mobile,
            mobile_user_agent=self.MOBILE_USER_AGENT if mobile else None,
            page_load_timeout=60,
        )
        try:
            driver.start()
        except Exception:
            # Browser may have crashed on launch (e.g. stale lock file).
            # Clear session state and retry once.
            _clear_session_state(self.profile_path)
            driver = NodriverDriver(
                browser_executable_path=browser_path,
                user_data_dir=self.profile_path,
                headless=headless,
                browser_args=browser_args,
                mobile=mobile,
                mobile_user_agent=self.MOBILE_USER_AGENT if mobile else None,
                page_load_timeout=60,
            )
            driver.start()
        return driver

    def close_running_edge(self):
        """
        Close running Edge processes to avoid conflicts with the profile.
        Kept as a no-op for backward compatibility; per-account profiles make
        this generally unnecessary.
        """
        return
