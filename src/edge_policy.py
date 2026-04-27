"""
Temporarily neutralise Microsoft Edge's browser-level sign-in during First
Setup so the user can actually pick which Microsoft account to log in with.

On Windows, Edge pulls the Microsoft identity from the logged-in Windows
account (Web Account Manager). Even on a brand-new profile, this silently
authenticates the user and makes it impossible to sign out from within
Bing / Rewards (the site shows "there's a problem, close your browser").

Setting the HKCU policy `BrowserSignin = 0` disables the browser-level
sign-in for the current user; websites can still be logged into via their
regular sign-in forms. We capture the previous value and restore it after
First Setup completes.

No-op on non-Windows platforms.
"""

import platform

_POLICY_KEY = r"Software\Policies\Microsoft\Edge"
_VALUE_NAME = "BrowserSignin"


def is_supported():
    return platform.system() == "Windows"


def get_current_value():
    """Return the current BrowserSignin value (0/1/2) or None if unset / not supported."""
    if not is_supported():
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _POLICY_KEY, 0, winreg.KEY_QUERY_VALUE
        ) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return int(value)
    except FileNotFoundError:
        return None
    except OSError:
        return None


def set_browser_signin_disabled(disabled):
    """Set BrowserSignin=0 (disable) or delete the value (restore default behaviour)."""
    if not is_supported():
        return False
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _POLICY_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if disabled:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_DWORD, 0)
            else:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def restore_value(previous_value):
    """Restore a previously-captured value (or delete the entry if it was unset)."""
    if not is_supported():
        return False
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _POLICY_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if previous_value is None:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(
                    key, _VALUE_NAME, 0, winreg.REG_DWORD, int(previous_value)
                )
        return True
    except OSError:
        return False
