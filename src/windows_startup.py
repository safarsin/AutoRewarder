"""
Windows "Start with Windows" integration.

Writes to HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run, which does
not require admin privileges. No-op on non-Windows platforms.
"""

import os
import platform
import sys

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_KEY = "AutoRewarder"


def is_supported():
    """True if running on Windows (the only platform where these calls do anything)."""
    return platform.system() == "Windows"


def _startup_command():
    """Return the command that should launch the app at login."""
    if getattr(sys, "frozen", False):
        # PyInstaller / Inno Setup build: launch the bundled exe directly.
        return f'"{sys.executable}"'

    # Dev mode: launch via python + path to the entry script.
    entry = os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.pardir, "AutoRewarder.py")
    )
    return f'"{sys.executable}" "{entry}"'


def is_launch_on_startup():
    """True if the Run key already has an AutoRewarder entry."""
    if not is_supported():
        return False
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_QUERY_VALUE
        ) as key:
            winreg.QueryValueEx(key, _APP_KEY)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_launch_on_startup(enabled):
    """
    Add or remove AutoRewarder from the HKCU Run key.

    Returns:
        bool: True on success, False if not supported or the registry call failed.
    """
    if not is_supported():
        return False

    try:
        import winreg
    except ImportError:
        return False

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _REG_PATH,
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, _APP_KEY, 0, winreg.REG_SZ, _startup_command())
            else:
                try:
                    winreg.DeleteValue(key, _APP_KEY)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
